"""Pinned SDXL LoRA plans and a single native-owned Windows training process."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import subprocess
import time
from contextlib import closing
from pathlib import Path

from itov import device, training_results
from itov.batch_execution import _lock as execution_lock
from itov.catalog import (
    array,
    canonical_bytes,
    digest,
    identifier,
    integer,
    object_fields,
    relative_path,
    require,
    sha256,
    text,
)
from itov.catalog_store import _atomic_write
from itov.comfyui import ComfyUIClient, parse_json
from itov.evidence_reads import read_document
from itov.jobs import _now
from itov.locking import file_lock
from itov.qualification import model_path, safe_path
from itov.training_data import check_seal, file_ref, load_dataset, publish, seal
from itov.vram import gpu_snapshot
from itov.windows_process import Job, host_memory, job_active, process_identity, process_state

PROFILE = "sdxl-unet-lora-v1"
PACKAGES = (
    "torch",
    "torchvision",
    "transformers",
    "huggingface-hub",
    "tokenizers",
    "diffusers",
    "peft",
    "accelerate",
    "numpy",
    "safetensors",
    "Pillow",
)
PINNED = {
    "diffusers": "0.38.0",
    "peft": "0.21.0",
    "accelerate": "1.15.0",
    "transformers": "4.57.6",
    "huggingface-hub": "0.36.0",
    "tokenizers": "0.22.2",
}
CONFIG_FILES = {
    "model_index.json",
    "scheduler/scheduler_config.json",
    "text_encoder/config.json",
    "text_encoder_2/config.json",
    "unet/config.json",
    "vae/config.json",
    *(
        f"{folder}/{name}"
        for folder in ("tokenizer", "tokenizer_2")
        for name in ("merges.txt", "special_tokens_map.json", "tokenizer_config.json", "vocab.json")
    ),
}


def probe(python: Path):
    code = (
        "import sys,json,importlib.metadata as m; "
        "print(json.dumps({'python':sys.version,'packages':{n:m.version(n) for n in "
        + repr(PACKAGES)
        + "}}))"
    )
    try:
        result = subprocess.run(
            [str(python), "-I", "-c", code], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError("Training environment probe failed") from error
    require(result.returncode == 0, "Training dependencies unavailable: " + result.stderr[-2000:])
    value = parse_json(result.stdout)
    require(
        all(value["packages"].get(k) == v for k, v in PINNED.items()),
        "Unsupported trainer package versions",
    )
    return value


def worker_sources():
    names = (
        "training_worker.py",
        "training.py",
        "training_data.py",
        "training_results.py",
        "curation.py",
        "quality.py",
        "records.py",
        "training_records.py",
        "evaluation_cases.py",
        "review_records.py",
        "evidence_reads.py",
        "dataset_snapshot.py",
        "dataset_manifest.py",
    )
    return {name: sha256(Path(__file__).with_name(name).read_bytes()) for name in names}


def plan(config, spec_path: Path):
    raw = read_document(spec_path)
    return make_plan(config, parse_json(raw), sha256(raw))


def validate_spec(spec):
    require(isinstance(spec, dict), "Expected training specification")
    object_fields(
        spec,
        {
            "version",
            "id",
            "profile",
            "dataset",
            "checkpoint",
            "model_config",
            "environment",
            "trigger",
            "parameters",
        }
        | ({"qualification"} if spec.get("version") == 2 else set()),
        "training specification",
    )
    require(
        type(spec["version"]) is int and spec["version"] in (1, 2) and spec["profile"] == PROFILE,
        "Unsupported training profile",
    )
    identifier(spec["id"], "training id")
    text(spec["trigger"], "trigger")
    require(
        len(spec["trigger"]) <= 64 and len(spec["trigger"].split()) == 1,
        "Use one bounded explicit trigger",
    )
    for key in ("dataset", "environment"):
        object_fields(spec[key], {"path", "sha256"}, key)
        relative_path(spec[key]["path"], key)
        digest(spec[key]["sha256"], key)
    object_fields(spec["checkpoint"], {"loader_name", "sha256"}, "checkpoint")
    text(spec["checkpoint"]["loader_name"], "checkpoint loader")
    digest(spec["checkpoint"]["sha256"], "checkpoint hash")
    object_fields(
        spec["model_config"],
        {"directory", "repository", "revision", "files"},
        "model configuration",
    )
    params = spec["parameters"]
    object_fields(
        params,
        {"seed", "steps", "rank", "learning_rate_millionths", "resolution", "timeout_seconds"},
        "training parameters",
    )
    for key, value in params.items():
        integer(value, key)
    require(params["seed"] < 2**32 and 1 <= params["steps"] <= 256, "Invalid seed/step bound")
    require(
        params["rank"] in (4, 8) and params["resolution"] == 512,
        "Only rank 4/8 at 512px is supported",
    )
    require(
        1 <= params["learning_rate_millionths"] <= 1000 and 60 <= params["timeout_seconds"] <= 3600,
        "Invalid learning rate/time bound",
    )


def make_plan(config, spec, source_hash):
    validate_spec(spec)
    digest(source_hash, "specification hash")
    dataset_path, _ = file_ref(config.root, spec["dataset"], maximum=32 * 1024 * 1024)
    dataset = load_dataset(config.root, dataset_path)
    if spec["version"] == 2:
        from itov.quality import qualification

        qualification(config.root, spec)
    for sample in dataset["dataset"]["samples"]:
        from itov.linting import contains

        require(
            contains(
                (config.root / sample["caption"]["path"]).read_text(encoding="utf-8"),
                spec["trigger"],
            ),
            "Every caption must explicitly include the declared trigger",
        )
    object_fields(spec["checkpoint"], {"loader_name", "sha256"}, "checkpoint")
    digest(spec["checkpoint"]["sha256"], "checkpoint hash")
    checkpoint = model_path(config, "CheckpointLoaderSimple", spec["checkpoint"]["loader_name"])
    with checkpoint.open("rb") as source:
        require(
            hashlib.file_digest(source, "sha256").hexdigest() == spec["checkpoint"]["sha256"],
            "Checkpoint hash mismatch",
        )
    object_fields(
        spec["model_config"],
        {"directory", "repository", "revision", "files"},
        "model configuration",
    )
    model = spec["model_config"]
    require(
        model["repository"] == "stabilityai/stable-diffusion-xl-base-1.0",
        "Unsupported model configuration repository",
    )
    require(
        model["revision"] == "462165984030d82259a11f4367a4eed129e94a7b",
        "Unsupported model configuration revision",
    )
    relative_path(model["directory"], "model config directory")
    directory = safe_path(config.root, model["directory"])
    refs = array(model["files"], "model config files")
    require(len(refs) == len(CONFIG_FILES), "Incomplete model configuration")
    for ref in refs:
        file_ref(directory, ref, maximum=8 * 1024 * 1024)
    require(
        {r["path"] for r in refs} == CONFIG_FILES,
        "Unexpected model configuration files",
    )
    # Refuse extra model/config files that could silently change loader behavior.
    actual = set()
    expected_top = {p.split("/")[0] for p in CONFIG_FILES}
    for entry in directory.iterdir():
        require(entry.name in expected_top, "Model configuration has undeclared entries")
        safe_path(directory, entry.name)
        if entry.is_dir():
            for child in entry.iterdir():
                relative = child.relative_to(directory).as_posix()
                require(relative in CONFIG_FILES, "Model configuration has undeclared entries")
                safe_path(directory, relative)
                actual.add(relative)
        else:
            actual.add(entry.name)
    require(actual == CONFIG_FILES, "Model configuration directory has undeclared files")
    python, _ = file_ref(config.root, spec["environment"])
    environment = probe(python)
    params = spec["parameters"]
    require(
        all(s["width"] == params["resolution"] for s in dataset["samples"]),
        "Prepared image resolution differs from training",
    )
    return seal(
        {
            "version": 1,
            "scope": "training_plan_only",
            "specification": spec,
            "specification_sha256": source_hash,
            "dataset_id": dataset["dataset_id"],
            "purpose": dataset["dataset"]["purpose"],
            "environment": environment,
            "worker_sources": worker_sources(),
            "policy": {
                "free_gpu_bytes": 16 * 1024**3,
                "available_physical_bytes": 16 * 1024**3,
                "available_commit_bytes": 24 * 1024**3,
                "scope": "experimental_start_floor_not_measured_capacity_guarantee",
            },
            "limits": (
                "Bounded SDXL UNet LoRA training only; no text-encoder training, network "
                "downloads, execution resume, model quality acceptance or automatic promotion."
            ),
        },
        "plan_id",
    )


def save_plan(config, value):
    check_seal(value, "plan_id")
    return publish(safe_path(config.root, f"state/training/plans/{value['plan_id']}.json"), value)


def load_plan(path):
    value = check_seal(parse_json(read_document(path)), "plan_id")
    object_fields(
        value,
        {
            "version",
            "scope",
            "specification",
            "specification_sha256",
            "dataset_id",
            "purpose",
            "environment",
            "worker_sources",
            "policy",
            "limits",
            "plan_id",
        },
        "training plan",
    )
    require(
        type(value["version"]) is int
        and value["version"] == 1
        and value["scope"] == "training_plan_only",
        "Unsupported training plan",
    )
    validate_spec(value["specification"])
    digest(value["specification_sha256"], "specification hash")
    digest(value["dataset_id"], "dataset id")
    require(value["purpose"] in ("smoke", "training"), "Invalid plan purpose")
    return value


def revalidate(config, value):
    rebuilt = make_plan(config, value["specification"], value["specification_sha256"])
    require(rebuilt == value, "Training plan inputs or environment changed")


def run_folder(config, value):
    return safe_path(config.root, f"state/training/runs/{value['plan_id']}")


def read_record(config, path):
    value = load_plan(path)
    folder = run_folder(config, value)
    record = folder / "run.json"
    require(record.is_file(), "Training has not been started")
    result = check_seal(parse_json(read_document(record)), "record_id")
    require(
        type(result.get("version")) is int
        and result["version"] in (1, 2)
        and result.get("status")
        in ("running", "validating", "artifacts_validated", "succeeded", "failed"),
        "Invalid training status",
    )
    require(result.get("plan_id") == value["plan_id"], "Training record belongs to another plan")
    return result


def status(config, path):
    """Current read-only observation; record_id identifies the unchanged saved record."""
    value = load_plan(path)
    record = read_record(config, path)
    folder = run_folder(config, value)
    observed = {
        **record,
        "scope": "training_status_observation",
        "recorded_status": record["status"],
        "worker_completion": record.get("worker_completion", "unknown"),
        "artifact_validation": record.get("artifact_validation", "not_run"),
        "failure_boundary": record.get("failure_boundary"),
        "candidate_assessment": "not_performed_by_training",
        "artifacts": {key: str(folder / key) for key in ("run.json", "result.json", "worker.log")},
    }
    if record["status"] in ("succeeded", "artifacts_validated"):
        observed["worker_completion"] = "completed"
        try:
            with training_results.boundary("result_binding"):
                require(record.get("result_id"), "Training record has no bound result")
            training_results.validate(config, value, folder, expected_result_id=record["result_id"])
            observed.update(status="artifacts_validated", artifact_validation="passed")
        except training_results.ResultValidationError as error:
            observed.update(
                status="failed",
                artifact_validation="failed",
                failure_boundary=error.boundary,
                error=str(error),
            )
    observed["next_action"] = (
        "Run evaluation assess; technical validation does not accept a candidate."
        if observed["status"] == "artifacts_validated"
        else "Observe the owner; after confirmed exit use training recover."
        if observed["status"] in ("running", "validating")
        else "Inspect result.json and worker.log; preserve this attempt and create a new plan."
    )
    return observed


def _record(folder, body):
    value = seal(body, "record_id")
    # Retain each transition before replacing the current record, including recovery.
    publish(folder / "records" / f"{value['record_id']}.json", value)
    _atomic_write(folder / "run.json", canonical_bytes(value) + b"\n")
    return value


def run(config, path, gpu_uuid, *, registry=None):
    from itov.execution_ownership import workspace_available

    require(os.name == "nt", "Training execution currently requires native Windows ownership")
    value = load_plan(path)
    revalidate(config, value)
    root = safe_path(config.root, "state/training")
    root.mkdir(parents=True, exist_ok=True)
    with file_lock(root / "training.lock"), execution_lock(config):
        workspace_available(config)
        folder = run_folder(config, value)
        require(
            not folder.exists(),
            "Training attempt already exists; inspect it. No automatic retraining or overwrite",
        )
        database = safe_path(config.root, "state/batches/execution.sqlite3")
        require(
            database.exists() or not (database.parent / "initialized").exists(),
            "Existing execution database is missing",
        )
        if database.exists():
            with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
                require(
                    not db.execute(
                        "SELECT plan_id FROM runs "
                        "WHERE status NOT IN ('succeeded','failed','abandoned')"
                    ).fetchall(),
                    "An unfinished batch retains workspace ownership",
                )
        queue = ComfyUIClient(config.url).queue()
        require(
            not queue["queue_running"] and not queue["queue_pending"],
            "ComfyUI queue must be idle before training",
        )
        gpu, host = gpu_snapshot(), host_memory()
        require(gpu["uuid"].lower() == gpu_uuid.lower(), "Training GPU UUID differs")
        require(
            gpu["free_bytes"] >= value["policy"]["free_gpu_bytes"],
            "Insufficient free GPU memory for experimental training floor",
        )
        require(
            all(
                host[k] >= value["policy"][k + "_bytes"]
                for k in ("available_physical", "available_commit")
            ),
            "Insufficient host memory for experimental training floor",
        )
        with device.Lease(gpu_uuid, config.root, value["plan_id"], root=registry) as lease:
            owner = Job(lease.value["job_name"])
            failed_boundary = "worker_execution"
            try:
                folder.mkdir(parents=True)
                body = {
                    "version": 2,
                    "plan_id": value["plan_id"],
                    "status": "running",
                    "started_at": _now(),
                    "owner": process_identity(os.getpid()),
                    "lease": lease.value,
                    "gpu": gpu,
                    "host": host,
                    "worker": None,
                    "error": None,
                    "worker_completion": "pending",
                    "artifact_validation": "not_run",
                    "failure_boundary": None,
                    "candidate_assessment": "not_performed_by_training",
                }
                _record(folder, body)
                request = {
                    "version": 1,
                    "plan": value,
                    "workspace": str(config.root),
                    "checkpoint": str(
                        model_path(
                            config,
                            "CheckpointLoaderSimple",
                            value["specification"]["checkpoint"]["loader_name"],
                        )
                    ),
                    "output": str(folder),
                    "gpu_uuid": gpu_uuid,
                }
                publish(folder / "request.json", request)
                python = safe_path(config.root, value["specification"]["environment"]["path"])
                worker = owner.spawn(
                    [
                        str(python),
                        "-I",
                        str(Path(__file__).with_name("training_worker.py")),
                        str(folder / "request.json"),
                    ],
                    str(config.root),
                )
                lease.register(worker)
                body["worker"] = worker
                body["lease"] = lease.value
                _record(folder, body)
                owner.resume(worker)
                body["worker_completion"] = "running"
                deadline = (
                    time.monotonic() + value["specification"]["parameters"]["timeout_seconds"]
                )
                while process_state(worker) == "alive":
                    require(
                        time.monotonic() < deadline,
                        "Training exceeded its time bound; retain partial evidence",
                    )
                    require(
                        host_memory()["available_commit"] >= 1024**3,
                        "Host commit pressure during training",
                    )
                    time.sleep(0.5)
                require(
                    process_state(worker) == "dead",
                    "Training worker exit is uncertain; retain ownership evidence",
                )
                body.update(
                    status="validating",
                    worker_completion="completed",
                    artifact_validation="pending",
                )
                failed_boundary = "record_publication"
                _record(folder, body)
                result = training_results.read_result(folder, value)
                body.update(result_id=result["result_id"], artifact_validation="validating")
                _record(folder, body)
                training_results.validate(
                    config, value, folder, expected_result_id=result["result_id"]
                )
                failed_boundary = "input_freshness"
                revalidate(config, value)
                body.update(
                    status="artifacts_validated", artifact_validation="passed", finished_at=_now()
                )
            except (OSError, ValueError, KeyboardInterrupt) as error:
                if folder.exists() and (folder / "run.json").exists():
                    body.update(
                        status="failed",
                        error=str(error) or "Interrupted",
                        finished_at=_now(),
                        failure_boundary=getattr(error, "boundary", failed_boundary),
                    )
                    if body["artifact_validation"] in ("pending", "validating"):
                        body["artifact_validation"] = "failed"
                    if body["worker_completion"] != "completed":
                        body["worker_completion"] = "interrupted"
                else:
                    raise
            finally:
                owner.stop()
                lease.release()
            with training_results.boundary("record_publication"):
                _record(folder, body)
            return status(config, path)


def recover(config, path, *, registry=None):
    value = load_plan(path)
    root = safe_path(config.root, "state/training")
    with file_lock(root / "training.lock"), execution_lock(config):
        result = read_record(config, path)
        require(
            result["status"] in ("running", "validating"),
            "Only an interrupted running or validating attempt needs recovery",
        )
        require(
            process_state(result["owner"]) == "dead",
            "Training controller is still alive or its exit is uncertain",
        )
        lease = result["lease"]
        require(job_active(lease["job_name"]) == 0, "Training job still has live processes")
        if result["worker"]:
            require(
                process_state(result["worker"]) == "dead", "Training worker exit is not confirmed"
            )
        current = device.status(lease["gpu_uuid"], root=registry)
        if current["status"] == "held":
            require(current["lease_id"] == lease["lease_id"], "Device lease changed")
            device.recover(lease["gpu_uuid"], lease["lease_id"], root=registry)
        body = {k: v for k, v in result.items() if k != "record_id"}
        folder = run_folder(config, value)
        publish(folder / "records" / f"{result['record_id']}.json", result)
        body.update(
            version=2,
            status="failed",
            error="Explicit recovery after confirmed controller/worker exit; no retraining",
            finished_at=_now(),
            worker_completion=result.get("worker_completion", "interrupted"),
            artifact_validation="not_run",
            failure_boundary="worker_execution",
            candidate_assessment="not_performed_by_training",
        )
        if result["version"] == 2 and result["status"] == "validating":
            try:
                validated = training_results.validate(
                    config, value, folder, expected_result_id=result.get("result_id")
                )
                with training_results.boundary("input_freshness"):
                    revalidate(config, value)
                body.update(
                    status="artifacts_validated",
                    worker_completion="completed",
                    artifact_validation="passed",
                    failure_boundary=None,
                    error=None,
                    result_id=validated["result"]["result_id"],
                    recovery="Validated published artifacts after confirmed exit; no retraining",
                )
            except training_results.ResultValidationError as error:
                body.update(
                    artifact_validation="failed", failure_boundary=error.boundary, error=str(error)
                )
        with training_results.boundary("record_publication"):
            _record(folder, body)
        return status(config, path)
