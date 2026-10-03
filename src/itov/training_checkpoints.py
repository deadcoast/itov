"""Immutable optimizer checkpoints, explicit compatibility and continuation planning."""

from __future__ import annotations

import math
import re

from itov import checkpoint_tensors, training_config
from itov.catalog import canonical_bytes, integer, object_fields, require, sha256
from itov.comfyui import parse_json
from itov.evidence_reads import read_document
from itov.qualification import safe_path
from itov.training_data import check_seal, file_ref, seal

PROFILE = "sdxl-optimizer-checkpoint-v1"


def compatibility(plan):
    return sha256(
        canonical_bytes({k: v for k, v in plan.items() if k not in {"plan_id", "restart"}})
    )


def checkpoint_steps(plan):
    total = plan["specification"]["parameters"]["steps"]
    every = plan["specification"]["checkpoints"]["every_steps"]
    return sorted({*range(every, total, every), total})


def position(plan, step):
    effective = plan["optimization"]
    return {
        "completed_steps": step,
        "next_position": step * effective["config"]["effective_batch_size"],
        "next_learning_rate_trillionths": (
            effective["steps"][step]["learning_rate_trillionths"]
            if step < len(effective["steps"])
            else None
        ),
    }


def _rng(value):
    object_fields(value, {"python", "numpy"}, "checkpoint RNG state")
    py, np = value["python"], value["numpy"]
    object_fields(py, {"version", "keys", "gauss_hex"}, "Python RNG state")
    require(type(py["version"]) is int and py["version"] == 3, "Unsupported Python RNG")
    object_fields(
        np, {"algorithm", "keys", "position", "has_gauss", "gauss_hex"}, "NumPy RNG state"
    )
    require(np["algorithm"] == "MT19937", "Unsupported NumPy RNG")
    for row, length in ((py, 625), (np, 624)):
        require(
            isinstance(row["keys"], list)
            and len(row["keys"]) == length
            and all(type(n) is int and 0 <= n < 2**32 for n in row["keys"]),
            "Invalid RNG keys",
        )
    require(py["keys"][-1] <= 624, "Invalid Python RNG position")
    integer(np["position"], "NumPy RNG position")
    integer(np["has_gauss"], "NumPy Gaussian flag")
    require(np["position"] <= 624 and np["has_gauss"] in (0, 1), "Invalid NumPy RNG position/flag")
    for number in (py["gauss_hex"], np["gauss_hex"]):
        require(
            number is None
            or (
                isinstance(number, str)
                and len(number) <= 32
                and math.isfinite(float.fromhex(number))
            ),
            "Invalid Gaussian RNG cache",
        )
    require(np["gauss_hex"] is not None, "Missing NumPy Gaussian cache")


def validate_manifest(value, plan):
    check_seal(value, "checkpoint_id")
    object_fields(
        value,
        {
            "version",
            "profile",
            "plan_id",
            "compatibility_id",
            "position",
            "runtime",
            "parameters",
            "state",
            "rng",
            "trace",
            "checkpoint_id",
        },
        "checkpoint",
    )
    require(
        type(value["version"]) is int and value["version"] == 1 and value["profile"] == PROFILE,
        "Unsupported checkpoint profile",
    )
    require(plan["specification"]["version"] == 4, "Checkpoint requires training specification v4")
    require(
        value["plan_id"] == plan["plan_id"] and value["compatibility_id"] == compatibility(plan),
        "Checkpoint plan/compatibility differs",
    )
    where = value["position"]
    object_fields(
        where,
        {"completed_steps", "next_position", "next_learning_rate_trillionths"},
        "checkpoint schedule and position",
    )
    integer(where["completed_steps"], "checkpoint step", minimum=1)
    step = where["completed_steps"]
    require(step in checkpoint_steps(plan), "Checkpoint step is outside declared cadence")
    require(
        canonical_bytes(where) == canonical_bytes(position(plan, step)),
        "Checkpoint position/schedule differs",
    )
    runtime = value["runtime"]
    object_fields(
        runtime,
        {
            "device",
            "gpu_uuid",
            "gpu_name",
            "driver",
            "cuda_capability",
            "deterministic_algorithms",
            "cudnn_benchmark",
            "cudnn_deterministic",
        },
        "checkpoint runtime",
    )
    require(runtime["device"] in ("cpu", "cuda"), "Unsupported checkpoint device")
    for flag in ("deterministic_algorithms", "cudnn_benchmark", "cudnn_deterministic"):
        require(type(runtime[flag]) is bool, "Invalid backend flags")
    if runtime["device"] == "cuda":
        require(
            all(
                isinstance(runtime[k], str) and runtime[k]
                for k in ("gpu_uuid", "gpu_name", "driver")
            ),
            "Missing checkpoint GPU identity",
        )
        require(
            isinstance(runtime["cuda_capability"], list)
            and len(runtime["cuda_capability"]) == 2
            and all(type(n) is int and n >= 0 for n in runtime["cuda_capability"]),
            "Invalid CUDA capability",
        )
    else:
        require(
            all(runtime[k] is None for k in ("gpu_uuid", "gpu_name", "driver", "cuda_capability")),
            "CPU checkpoint declares CUDA identity",
        )
    parameters = value["parameters"]
    require(
        isinstance(parameters, list) and 1 <= len(parameters) <= 4096,
        "Invalid checkpoint parameters",
    )
    names = []
    elements = 0
    for parameter in parameters:
        object_fields(parameter, {"name", "shape"}, "checkpoint parameter")
        require(
            isinstance(parameter["name"], str) and 0 < len(parameter["name"]) <= 512,
            "Invalid checkpoint parameter name",
        )
        shape = parameter["shape"]
        require(
            isinstance(shape, list)
            and 1 <= len(shape) <= 4
            and all(type(n) is int and 1 <= n <= 65536 for n in shape),
            "Invalid parameter shape",
        )
        elements += math.prod(shape)
        names.append(parameter["name"])
    require(
        len(set(names)) == len(names) and elements <= 16 * 1024**2, "Duplicate/oversized parameters"
    )
    _rng(value["rng"])
    trace = value["trace"]
    effective = plan["optimization"]
    partial = {
        **effective,
        "steps": effective["steps"][:step],
        "validation_steps": [n for n in effective["validation_steps"] if n <= step],
    }
    require(
        isinstance(trace, dict)
        and isinstance(trace.get("validation"), list)
        and trace["validation"],
        "Missing checkpoint validation history",
    )
    require(isinstance(trace.get("steps"), list), "Missing checkpoint training history")
    observations = trace["steps"] + trace["validation"]
    training_config.validate_trace(
        trace,
        partial,
        {
            "plan_id": plan["plan_id"],
            "training_loss_billionths": [row["loss_billionths"] for row in trace["steps"]],
            "heldout_before": trace["validation"][0]["losses"],
            "heldout_after": trace["validation"][-1]["losses"],
            "max_memory_allocated": max(
                row["resources"]["cuda_peak_allocated_bytes"] for row in observations
            ),
            "max_memory_reserved": max(
                row["resources"]["cuda_peak_reserved_bytes"] for row in observations
            ),
        },
    )
    require(
        trace["precision"]["adapter_tensors"] == len(parameters), "Checkpoint adapter count differs"
    )
    require(value["state"]["path"] == "state.safetensors", "Unexpected checkpoint payload name")
    return value


def validate(path, plan, *, published=True):
    value = validate_manifest(parse_json(read_document(path)), plan)
    if published:
        require(
            path.parent.name == f"step-{value['position']['completed_steps']:06d}"
            and path.name == "checkpoint.json",
            "Partial or misnamed checkpoint is not resumable",
        )
    require(
        {p.name for p in path.parent.iterdir()} == {"checkpoint.json", "state.safetensors"},
        "Incomplete or undeclared checkpoint files",
    )
    tensors, _ = file_ref(path.parent, value["state"], maximum=256 * 1024**2)
    checkpoint_tensors.inspect(tensors, value["parameters"], value["runtime"]["device"] == "cuda")
    return value


def restart(config, plan, *, current=False):
    """Read and validate the exact parent; current execution checks are separate from replay."""
    from itov import training

    refs = plan["restart"]
    object_fields(refs, {"plan", "checkpoint"}, "restart references")
    parent_path, _ = file_ref(config.root, refs["plan"], maximum=32 * 1024**2)
    parent = training.load_plan(parent_path)
    require(
        parent["plan_id"] != plan["plan_id"] and compatibility(parent) == compatibility(plan),
        "Restart inputs, environment or source differ",
    )
    checkpoint_path, _ = file_ref(config.root, refs["checkpoint"], maximum=32 * 1024**2)
    value = validate(checkpoint_path, parent)
    expected = (
        training.run_folder(config, parent)
        / "checkpoints"
        / checkpoint_path.parent.name
        / "checkpoint.json"
    )
    require(checkpoint_path == expected, "Checkpoint is outside its source attempt")
    require(
        value["position"]["completed_steps"] < len(plan["optimization"]["steps"]),
        "Final checkpoint has no remaining optimizer updates",
    )
    if current:
        record = training.read_record(config, parent_path)
        require(
            record["status"] in ("failed", "artifacts_validated"),
            "Recover the stopped source attempt before creating/executing a continuation",
        )
        from itov.windows_process import job_active, process_state

        require(process_state(record["owner"]) == "dead", "Source controller is still alive")
        require(
            record["worker"] is None or process_state(record["worker"]) == "dead",
            "Source worker is still alive",
        )
        require(job_active(record["lease"]["job_name"]) == 0, "Source job still has processes")
    return checkpoint_path, value


def resume_plan(config, source, checkpoint):
    from itov import training

    parent = training.load_plan(source)
    require(parent["specification"]["version"] == 4, "Resume requires training specification v4")
    base = training.make_plan(config, parent["specification"], parent["specification_sha256"])
    require(
        compatibility(base) == compatibility(parent),
        "Restart inputs, environment or source changed",
    )
    refs = {}
    for name, path in (("plan", source), ("checkpoint", checkpoint)):
        relative = path.absolute().relative_to(config.root).as_posix()
        checked = safe_path(config.root, relative)
        refs[name] = {"path": relative, "sha256": sha256(read_document(checked))}
    value = seal({**{k: v for k, v in base.items() if k != "plan_id"}, "restart": refs}, "plan_id")
    restart(config, value, current=True)
    return value


def status(config, path):
    from itov import training

    plan = training.load_plan(path)
    require(plan["specification"]["version"] == 4, "Checkpoints require training specification v4")
    folder = training.run_folder(config, plan) / "checkpoints"
    entries = []
    if folder.exists():
        names = sorted(folder.iterdir())
        require(len(names) <= 1024, "Too many checkpoint entries to inspect")
        for entry in names:
            row = {"path": str(entry), "status": "partial", "resumable": False}
            if re.fullmatch(r"step-\d{6}", entry.name):
                try:
                    manifest = safe_path(folder, entry.name + "/checkpoint.json")
                    value = validate(manifest, plan)
                    step = value["position"]["completed_steps"]
                    row.update(
                        status="complete",
                        checkpoint_id=value["checkpoint_id"],
                        step=step,
                        resumable=step < len(plan["optimization"]["steps"]),
                        path=str(manifest),
                    )
                except (OSError, ValueError, KeyError, TypeError) as error:
                    row.update(status="invalid", error=str(error))
            entries.append(row)
    return {
        "scope": "training_checkpoint_observation",
        "plan_id": plan["plan_id"],
        "entries": entries,
        "limits": (
            "Complete checkpoints are evidence; resume-plan separately requires current "
            "compatible inputs and a stopped terminal source attempt."
        ),
    }


def validate_result(config, plan, folder, result, trace):
    start = 0
    runtime = parameters = None
    if plan["restart"]:
        _, source = restart(config, plan)
        start = source["position"]["completed_steps"]
        runtime, parameters = source["runtime"], source["parameters"]
        require(
            trace["steps"][:start] == source["trace"]["steps"]
            and trace["validation"][: len(source["trace"]["validation"])]
            == source["trace"]["validation"],
            "Restart optimization history differs from committed checkpoint",
        )
    expected = [n for n in checkpoint_steps(plan) if n > start]
    refs = result["checkpoints"]
    require(isinstance(refs, list) and len(refs) == len(expected), "Incomplete checkpoint coverage")
    for step, ref in zip(expected, refs, strict=True):
        require(
            ref["path"] == f"checkpoints/step-{step:06d}/checkpoint.json",
            "Checkpoint sequence differs",
        )
        path, _ = file_ref(folder, ref, maximum=32 * 1024**2)
        value = validate(path, plan)
        require(
            value["trace"]
            == {
                **trace,
                "steps": trace["steps"][:step],
                "validation": [row for row in trace["validation"] if row["step"] <= step],
            },
            "Checkpoint history differs from final trace",
        )
        if runtime is not None:
            require(
                value["runtime"] == runtime and value["parameters"] == parameters,
                "Checkpoint runtime/parameter identity changed",
            )
        runtime, parameters = value["runtime"], value["parameters"]
    if parameters is None:
        raise ValueError("Checkpoint parameter evidence is missing")
    require(
        sum(math.prod(p["shape"]) for p in parameters) == result["trainable_parameters"],
        "Checkpoint parameter total differs from result",
    )
