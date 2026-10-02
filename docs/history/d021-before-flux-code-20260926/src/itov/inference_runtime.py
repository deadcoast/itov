"""Candidate deployment, live qualification and owned inference execution."""

import sqlite3
from contextlib import closing, nullcontext
from pathlib import Path

from itov import evaluation, training
from itov.batch_execution import _lock, abandon_reserved_plan, run_reserved_plan
from itov.catalog import object_fields, read_document, require, sha256
from itov.comfyui import parse_json
from itov.execution_store import report as execution_report
from itov.image_media import image_tools, verify_image
from itov.inference import _copy_lora
from itov.inference_capabilities import RUNTIME_SOURCES, capabilities, validate_spec
from itov.inference_graph import definition
from itov.owned_jobs import job_path, read_owned
from itov.qualification import _file, qualify_graphs, safe_path
from itov.training_data import check_seal, file_ref, publish, seal
from itov.training_results import boundary


def _deployment(config, spec, *, stage=False):
    spec = validate_spec(spec)
    checkpoint = safe_path(
        config.comfyui_root / "models/checkpoints", spec["checkpoint"]["loader_name"]
    )
    require(
        _file(checkpoint)["sha256"] == spec["checkpoint"]["sha256"],
        "Pinned checkpoint SHA-256 mismatch",
    )
    adapters = []
    for declared in spec["adapters"]:
        candidate = None
        if declared["kind"] == "trained_candidate":
            path, _ = file_ref(config.root, declared["training_plan"])
            trained = training.load_plan(path)
            require(
                trained["specification"]["checkpoint"]["sha256"] == spec["checkpoint"]["sha256"],
                "Candidate was trained against a different checkpoint",
            )
            candidate = evaluation.candidate(config, path)
            require(
                candidate["candidate_id"] == declared["candidate_id"]
                and candidate["export"]["sha256"] == declared["sha256"]
                and candidate["export"]["format"] == "comfy-unet-lora-v1"
                and candidate["export"]["alpha_scale_milli"] == 1000,
                "Candidate identity/export differs from specification",
            )
            asset = candidate["entry"]["asset"]
            loader = f"itov_candidate_{asset['sha256']}.safetensors"
        else:
            asset = {
                "path": f"models_shared/inference/{declared['sha256']}.safetensors",
                "sha256": declared["sha256"],
            }
            loader = declared["loader_name"]
            source = safe_path(config.comfyui_root / "models/loras", loader)
            require(_file(source)["sha256"] == declared["sha256"], "Pinned LCM bytes differ")
        adapters.append(
            {
                "kind": declared["kind"],
                "loader_name": loader,
                "asset": asset,
                "strength_milli": declared["strength_milli"],
                "candidate": candidate,
            }
        )
    # Finish semantic/identity checks before staging any new assets.
    for adapter, declared in zip(adapters, spec["adapters"], strict=True):
        destination = safe_path(config.comfyui_root / "models/loras", adapter["loader_name"])
        if stage:
            if adapter["candidate"] is not None:
                path, _ = file_ref(config.root, declared["training_plan"])
                require(
                    evaluation.candidate(config, path, save=True) == adapter["candidate"],
                    "Candidate changed during staging",
                )
                source, _ = file_ref(config.root, adapter["asset"])
                _copy_lora(source, destination, adapter["asset"]["sha256"])
            else:
                _copy_lora(
                    destination,
                    safe_path(config.root, adapter["asset"]["path"]),
                    adapter["asset"]["sha256"],
                )
        require(destination.is_file(), "Adapter is not deployed; use inference prepare first")
        require(
            _file(destination)["sha256"] == adapter["asset"]["sha256"],
            "Deployed adapter bytes differ",
        )
        file_ref(config.root, adapter["asset"])
    return seal(
        {
            "version": 1,
            "scope": "inference_deployment",
            "specification": spec,
            "capabilities": capabilities(),
            "adapters": adapters,
            "quality_acceptance": "not_established",
            "catalog_activation": False,
        },
        "deployment_id",
    )


def prepare(config, spec):
    value = _deployment(config, spec, stage=True)
    path = safe_path(config.root, f"state/inference/deployments/{value['deployment_id']}.json")
    publish(path, value)
    return {
        "ok": True,
        "scope": "prepared_inference_deployment",
        "deployment": value,
        "saved_path": str(path),
        "next_action": "Start the stock server; inference plan --save.",
        "limits": "Assets staged only; no catalog activation, qualification or submission.",
    }


def _runtime(config, value, *, timeout):
    receipt = qualify_graphs(config, value, timeout=timeout, extra_sources=RUNTIME_SOURCES)
    receipt.pop("qualification_id")
    receipt.pop("plan_id")
    return {**receipt, "image_decoder": image_tools(), "profile": "stock-sdxl-inference-v2"}


def plan(config, spec, *, save=False, timeout=3):
    deployment = _deployment(config, spec)
    body = definition(spec, deployment)
    value = seal(
        {**body, "runtime": _runtime(config, seal(body, "plan_id"), timeout=timeout)}, "plan_id"
    )
    if save:
        publish(safe_path(config.root, f"state/inference/plans/{value['plan_id']}.json"), value)
    return value


def load_plan(path):
    with boundary("inference_plan"):
        value = check_seal(parse_json(read_document(path)), "plan_id")
        object_fields(
            value,
            {
                "version",
                "scope",
                "specification",
                "deployment",
                "jobs",
                "request",
                "runtime",
                "plan_id",
            },
            "inference plan",
        )
        check_seal(value["deployment"], "deployment_id")
        require(
            {k: v for k, v in value.items() if k not in {"runtime", "plan_id"}}
            == definition(value["specification"], value["deployment"]),
            "Inference graph/adapter/strength bindings differ",
        )
        return value


def _fresh(config, value):
    require(
        _deployment(config, value["specification"]) == value["deployment"],
        "Inference candidate or deployment inputs changed",
    )


def _receipt(value):
    return seal({**value["runtime"], "plan_id": value["plan_id"]}, "qualification_id")


def _qualify(config, value, *, timeout):
    _fresh(config, value)
    require(
        _runtime(config, value, timeout=timeout) == value["runtime"],
        "Inference runtime, schema or model identity changed; no new submission",
    )
    return _receipt(value)


def run(
    config, path, *, resume=False, prompt_id=None, timeout=3, wait_timeout=300, poll_interval=1
):
    value = load_plan(path)
    run_reserved_plan(
        config,
        value,
        qualification=None if resume else _receipt(value),
        resume=resume,
        prompt_id=prompt_id,
        timeout=timeout,
        wait_timeout=wait_timeout,
        poll_interval=poll_interval,
        qualify_plan=_qualify,
        submission_guard=lambda config, plan: nullcontext(),
    )
    return status(config, path)


def abandon(config, path):
    abandon_reserved_plan(config, load_plan(path))
    return status(config, path)


def status(config, path):
    value = load_plan(path)
    database = safe_path(config.root, "state/batches/execution.sqlite3")
    with _lock(config):
        observed = {"status": "not_started", "ok": False, "jobs": [], "error": None}
        if not database.is_file():
            require(not (database.parent / "initialized").exists(), "Execution database missing")
        else:
            with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
                db.row_factory = sqlite3.Row
                if db.execute(
                    "SELECT 1 FROM runs WHERE plan_id = ?", (value["plan_id"],)
                ).fetchone():
                    observed = execution_report(db, config, value)
        images = []
        for job in value["jobs"]:
            row = {
                "index": job["index"],
                "seed": job["seed"],
                "status": "reserved" if observed["jobs"] else "not_started",
            }
            path = job_path(config, value["plan_id"], job["index"])
            row["record_path"] = str(path)
            if observed["jobs"]:
                durable = observed["jobs"][job["index"]]
                if durable["status"] != "reserved" or path.exists():
                    record = read_owned(config, value, job)
                    require(
                        durable["prompt_id"] is None
                        or durable["prompt_id"] == record.get("prompt_id"),
                        "Inference prompt differs from durable ownership",
                    )
                    require(
                        record["status"] != "prepared"
                        or durable["status"] in {"prepared", "reserved"},
                        "Inference job moved backwards; preserve and inspect",
                    )
                    row.update(
                        status=record["status"],
                        request_id=record["request_id"],
                        prompt_id=record.get("prompt_id"),
                        error=record.get("error"),
                        record_sha256=sha256(path.read_bytes()),
                    )
                    if record["status"] == "succeeded":
                        try:
                            require(
                                isinstance(record.get("artifacts"), list)
                                and len(record["artifacts"]) == 1,
                                "Expected exactly one inference artifact",
                            )
                            artifact = record["artifacts"][0]
                            require(
                                isinstance(artifact, dict)
                                and isinstance(artifact.get("path"), str),
                                "Invalid inference artifact record",
                            )
                            output = Path(artifact["path"])
                            require(
                                output.parent == config.root / f"output/jobs/{record['request_id']}"
                                and artifact.get("node_id") == "8",
                                "Inference artifact ownership differs",
                            )
                            reference = {
                                "path": output.relative_to(config.root).as_posix(),
                                "sha256": artifact.get("sha256"),
                            }
                            file_ref(config.root, reference)
                            decoded = verify_image(
                                output, {k: value["specification"][k] for k in ("width", "height")}
                            )
                            require(
                                decoded["decoder_sha256"]
                                == value["runtime"]["image_decoder"]["sha256"],
                                "Image decoder changed",
                            )
                            row.update(image=reference, decoded=decoded)
                        except (OSError, ValueError) as error:
                            row.update(status="artifact_invalid", error=str(error))
            images.append(row)
    invalid = any(row["status"] == "artifact_invalid" for row in images)
    complete = observed["status"] == "succeeded" and all(r["status"] == "succeeded" for r in images)
    return {
        "scope": "inference_status",
        "plan_id": value["plan_id"],
        "ok": complete,
        "recorded_status": observed["status"],
        "status": "artifact_invalid" if invalid else observed["status"],
        "error": observed["error"],
        "images": images,
        "succeeded": sum(r["status"] == "succeeded" for r in images),
        "total": len(images),
        "quality_acceptance": "not_established",
        "next_action": (
            "Run inference replay --save and inspect image quality."
            if complete
            else "Inspect records; use inference run for a new plan, resume for "
            "accepted work, or abandon only after terminal outcomes are known."
        ),
    }


def replay(config, path, *, save=False):
    value = load_plan(path)
    observed = status(config, path)
    require(observed["ok"], "Inference is incomplete or invalid; inspect inference status")
    _fresh(config, value)
    for item in value["runtime"]["files"]:
        require(_file(Path(item["path"])) == item, "Inference runtime or model bytes changed")
    require(image_tools() == value["runtime"]["image_decoder"], "Image decoder changed")
    result = seal(
        {
            "version": 1,
            "scope": "inference_technical_report",
            "plan_id": value["plan_id"],
            "deployment": value["deployment"],
            "runtime": value["runtime"],
            "images": observed["images"],
            "technical_pass": True,
            "quality_acceptance": "not_established",
            "catalog_activation": False,
            "limits": "Exact owned graph, asset and decoded image evidence; no quality "
            "acceptance, adapter target coverage or cross-runtime parity claim.",
        },
        "report_id",
    )
    if save:
        publish(
            safe_path(config.root, f"state/inference/reports/{result['report_id']}.json"), result
        )
    return result
