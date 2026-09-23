"""Transactional local dataset import, retained attempts and explicit rebuild recovery."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from itov import dataset_manifest as manifest
from itov import dataset_snapshot as snapshots
from itov.catalog import canonical_bytes, object_fields, require, sha256
from itov.catalog_store import _atomic_write
from itov.comfyui import parse_json
from itov.evidence_reads import read_document
from itov.locking import file_lock
from itov.qualification import safe_path
from itov.training_data import check_seal, publish, seal


def _worker(python, arguments):
    worker = Path(__file__).with_name("dataset_images.py")
    try:
        run = subprocess.run(
            [str(python), "-I", str(worker), *map(str, arguments)],
            capture_output=True,
            timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired as error:
        raise ValueError("Dataset image worker exceeded 60 seconds") from error
    try:
        result = parse_json(run.stdout)
    except ValueError as error:
        raise ValueError(
            "Dataset image worker failed: " + run.stderr.decode(errors="replace")[-2000:]
        ) from error
    require(
        run.returncode == 0 and result.get("ok") is True,
        "Dataset image worker: " + str(result.get("error", "No successful result")),
    )
    return result["value"]


def _folder(root, value):
    return safe_path(root, f"state/dataset-imports/{value['import_id']}")


def _read_operation(root, path):
    value = snapshots.operation(parse_json(read_document(path)))
    require(
        path.absolute() == _folder(root, value) / "operation.json",
        "Use the saved dataset import operation in this workspace",
    )
    return value


def _event(attempt, body):
    value = seal({**body, "updated_at": datetime.now(UTC).isoformat()}, "record_id")
    publish(safe_path(attempt, f"events/{value['record_id']}.json"), value)
    _atomic_write(safe_path(attempt, "attempt.json"), canonical_bytes(value) + b"\n")
    return value


def _latest(folder):
    marker = safe_path(folder, "current.json")
    if not marker.exists():
        return None, None
    current = parse_json(read_document(marker))
    object_fields(current, {"attempt_id"}, "current dataset attempt")
    require(
        isinstance(current["attempt_id"], str)
        and str(uuid.UUID(current["attempt_id"])) == current["attempt_id"],
        "Invalid attempt id",
    )
    path = safe_path(folder, f"attempts/{current['attempt_id']}")
    record = check_seal(parse_json(read_document(safe_path(path, "attempt.json"))), "record_id")
    require(record.get("attempt_id") == current["attempt_id"], "Attempt record differs")
    return path, record


def status(config, path):
    value = _read_operation(config.root, path)
    folder = _folder(config.root, value)
    final = safe_path(config.root, snapshots.prefix(value["import_id"]))
    attempt, record = _latest(folder)
    result = {
        "ok": False,
        "scope": "dataset_import_status",
        "import_id": value["import_id"],
        "status": "not_started"
        if record is None
        else "failed"
        if record["status"] == "failed"
        else "paused",
        "recorded_status": record["status"] if record else None,
        "error": record.get("error") if record else None,
        "failure_boundary": record.get("failure_boundary") if record else None,
        "completed_images": record.get("completed_images", 0) if record else 0,
        "total": len(value["definition"]["samples"]),
        "artifacts": {"operation": str(path.absolute()), "attempts": str(folder / "attempts")},
        "limits": snapshots.LIMITS,
    }
    if attempt:
        result["artifacts"]["attempt record"] = str(attempt / "attempt.json")
    if final.exists():
        try:
            prepared = snapshots.verify_bundle(final, value["import_id"])
            result.update(
                ok=True,
                status="committed",
                error=None,
                failure_boundary=None,
                dataset_id=prepared["dataset_id"],
                counts=prepared["counts"],
                recovery_required=bool(record and record["status"] != "committed"),
                completed_images=len(value["definition"]["samples"]),
            )
            result["artifacts"].update(
                dataset=str(final / "dataset.json"),
                prepared=str(final / "prepared.json"),
                preparation=str(final / "preparation.json"),
                commit=str(final / "READY.json"),
            )
            if value["definition"]["curation"]:
                result["artifacts"]["curation"] = str(final / "curation.json")
        except (OSError, ValueError) as error:
            result.update(status="artifact_invalid", error=str(error), failure_boundary="commit")
    return result


def begin(config, path, *, source_root=None, image_python=None):
    raw = read_document(path)
    require(len(raw) <= 4 * 1024**2, "Import declaration exceeds 4 MiB")
    definition = manifest.validate(parse_json(raw))
    python = Path(image_python or sys.executable).absolute()
    engine = _worker(python, ["--probe"])
    value = snapshots.operation(
        seal(
            {
                "version": 1,
                "definition": definition,
                "declaration": {
                    "sha256": sha256(raw),
                    "bytes": len(raw),
                    "utf8": raw.decode("utf-8"),
                },
                "engine": engine,
            },
            "import_id",
        )
    )
    folder = _folder(config.root, value)
    folder.mkdir(parents=True, exist_ok=True)
    operation_path = safe_path(folder, "operation.json")
    with file_lock(safe_path(folder, "import.lock")):
        if operation_path.exists():
            require(parse_json(read_document(operation_path)) == value, "Import operation differs")
            observed = status(config, operation_path)
            require(
                observed["ok"],
                "Dataset import already exists; inspect dataset status and use dataset recover",
            )
            return observed
        # Operation is durable before any copying or transforms. Recovery also handles
        # a crash between these publications or before the first attempt pointer.
        publish(operation_path, value)
        return _build(config, value, Path(source_root or path.absolute().parent).absolute(), python)


def recover(config, path, *, source_root=None, image_python=None):
    value = _read_operation(config.root, path)
    folder = _folder(config.root, value)
    with file_lock(safe_path(folder, "import.lock")):
        observed = status(config, path)
        if observed["ok"]:
            # Complete publication can precede the final journal replacement.
            attempt, record = _latest(folder)
            if record and record["status"] != "committed":
                _event(
                    attempt,
                    {
                        **{k: v for k, v in record.items() if k not in {"record_id", "updated_at"}},
                        "status": "committed",
                        "error": None,
                        "failure_boundary": None,
                        "completed_images": observed["total"],
                    },
                )
            return status(config, path)
        require(
            observed["status"] != "artifact_invalid",
            "Published dataset is invalid; preserve it and investigate",
        )
        _, record = _latest(folder)
        source = source_root or (record and record["source_root"])
        python = image_python or (record and record["image_python"])
        require(
            source and python,
            "Recovery before the first attempt requires --source-root and --image-python",
        )
        return _build(config, value, Path(source).absolute(), Path(python).absolute())


def _copy(source_root, payload, definition):
    total = 0
    for name, ref, maximum in manifest.inputs(definition):
        path = safe_path(source_root, ref["path"])
        with path.open("rb") as source:
            raw = source.read(maximum + 1)
        require(0 < len(raw) <= maximum, f"Source size outside supported bounds: {ref['path']}")
        require(sha256(raw) == ref["sha256"], f"Source SHA-256 mismatch: {ref['path']}")
        total += len(raw)
        require(total <= 1024**3, "Import inputs exceed 1 GiB")
        destination = safe_path(payload, name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(destination, raw, exclusive=True)


def _publish_bundle(payload, final, import_id):
    require(not final.exists(), "Dataset publication destination already exists")
    snapshots.verify_bundle(payload, import_id)
    final.parent.mkdir(parents=True, exist_ok=True)
    require(final.resolve() == final.absolute(), "Dataset publication path redirects")
    # Same-volume directory rename exposes the entire verified bundle at once.
    # Same-import writers hold one OS lock; no power-loss durability guarantee.
    payload.rename(final)


def _build(config, value, source_root, python):
    folder = _folder(config.root, value)
    operation_path = folder / "operation.json"
    attempt_id = str(uuid.uuid4())
    attempt = safe_path(folder, f"attempts/{attempt_id}")
    attempt.mkdir(parents=True)
    payload = safe_path(attempt, "payload")
    payload.mkdir()
    body = {
        "version": 1,
        "import_id": value["import_id"],
        "attempt_id": attempt_id,
        "status": "running",
        "source_root": str(source_root),
        "image_python": str(python),
        "completed_images": 0,
        "error": None,
        "failure_boundary": None,
    }
    _event(attempt, body)
    _atomic_write(
        safe_path(folder, "current.json"), canonical_bytes({"attempt_id": attempt_id}) + b"\n"
    )
    boundary = "engine"
    try:
        require(
            _worker(python, ["--probe"]) == value["engine"],
            "Dataset image engine changed; create a new import",
        )
        boundary = "source_copy"
        _copy(source_root, payload, value["definition"])
        boundary = "provenance"
        manifest.verify_provenance(payload, value["definition"])
        boundary = "decode_transform"
        (payload / "images").mkdir()
        images = []
        for sample in sorted(value["definition"]["samples"], key=lambda s: s["id"]):
            key = sample["id"]
            row = _worker(
                python,
                [
                    safe_path(payload, f"sources/{key}.image"),
                    safe_path(payload, f"images/{key}.png"),
                    sample["source"]["sha256"],
                ],
            )
            require(
                row["engine"] == value["engine"], "Dataset image engine changed during preparation"
            )
            images.append({"sample": key, **row})
            body["completed_images"] = len(images)
            _event(attempt, body)
        boundary = "bundle_validation"
        receipt = seal(
            {"version": 1, "import_id": value["import_id"], "images": images}, "preparation_id"
        )
        prepared = snapshots.snapshot(payload, value, receipt)
        publish(payload / "operation.json", value)
        raw = value["declaration"]["utf8"].encode("utf-8")
        _atomic_write(payload / "declaration.json", raw, exclusive=True)
        for name, document in (
            ("preparation.json", receipt),
            ("dataset.json", prepared["dataset"]),
            ("prepared.json", prepared),
        ):
            publish(payload / name, document)
        if value["definition"]["curation"]:
            publish(payload / "curation.json", snapshots.curation(value, prepared))
        require(
            _worker(python, ["--probe"]) == value["engine"],
            "Dataset image engine changed before publication",
        )
        publish(
            payload / "READY.json",
            seal(
                {
                    "version": 1,
                    "import_id": value["import_id"],
                    "files": snapshots.inventory(payload),
                },
                "commit_id",
            ),
        )
        boundary = "publication"
        _publish_bundle(
            payload,
            safe_path(config.root, snapshots.prefix(value["import_id"])),
            value["import_id"],
        )
        boundary = "final_journal"
        _event(attempt, {**body, "status": "committed"})
    except (OSError, ValueError, KeyboardInterrupt) as error:
        _event(
            attempt,
            {
                **body,
                "status": "paused" if isinstance(error, KeyboardInterrupt) else "failed",
                "error": str(error) or "Dataset preparation interrupted",
                "failure_boundary": boundary,
            },
        )
    return status(config, operation_path)
