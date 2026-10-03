"""Identity-bound, replayable tensor-to-target evidence from the installed loader."""

import os
import struct
import subprocess
import uuid
from pathlib import Path

from itov import evaluation_runtime
from itov.catalog import canonical_bytes, object_fields, require, sha256
from itov.comfyui import parse_json, parse_json_object
from itov.evidence_reads import EvidenceReads, observe, read_document
from itov.qualification import _file, safe_path
from itov.training_data import check_seal, file_ref, publish, seal

SOURCES = (
    "comfy/utils.py",
    "comfy/model_base.py",
    "comfy/model_detection.py",
    "comfy/supported_models.py",
    "comfy/weight_adapter/__init__.py",
    "comfy/weight_adapter/base.py",
    "comfy/weight_adapter/lora.py",
)
LIMITS = (
    "CPU checkpoint load and stock loader patch registration, with exact target/shape/tensor "
    "coverage at every declared strength. Rendering separately exercises GPU execution. "
    "No attestation of all dependencies, in-memory server state, numerical parity or quality."
)


def reference(config, path):
    path = Path(path).absolute()
    relative = path.relative_to(config.root).as_posix()
    require(safe_path(config.root, relative) == path, "Reference path redirects")
    return {
        "path": relative,
        "sha256": sha256(read_document(path)),
    }


def _inputs(config, plan):
    evaluation_runtime._fresh_inputs(config, plan)
    files = plan["runtime"]["files"]
    require(
        all(_file(Path(item["path"])) == item for item in files),
        "Evaluation runtime or model bytes changed",
    )
    files = files + [_file(config.comfyui_root / name) for name in SOURCES]
    for item in files:
        observe(item["path"], item["sha256"], item["bytes"])
    return files


def validate_result(result: object, header, strengths) -> dict:
    if not isinstance(result, dict):
        raise ValueError("loader result: expected an object")
    object_fields(
        result,
        {
            "version",
            "device",
            "cuda_initialized",
            "visible_cuda_devices",
            "torch_version",
            "model_class",
            "rows",
            "accepted",
            "unconsumed",
        },
        "loader result",
    )
    require(
        type(result["version"]) is int
        and result["version"] == 1
        and result["device"] == "cpu"
        and type(result["cuda_initialized"]) is bool
        and type(result["visible_cuda_devices"]) is int
        and result["visible_cuda_devices"] == 0
        and result["unconsumed"] == [],
        "Invalid loader probe",
    )
    require(
        isinstance(result["torch_version"], str)
        and result["torch_version"]
        and result["model_class"] == "SDXL",
        "Unsupported loader model/runtime",
    )
    require(isinstance(result["rows"], list) and result["rows"], "Missing loader mappings")
    consumed: set[str] = set()
    targets = []
    for row in result["rows"]:
        object_fields(
            row,
            {
                "target",
                "tensors",
                "base_shape",
                "up_shape",
                "down_shape",
                "patch_type",
                "alpha_scale_milli",
            },
            "loader mapping",
        )
        target = row["target"]
        require(
            isinstance(target, str)
            and target.startswith("diffusion_model.")
            and target.endswith(".weight")
            and target not in targets,
            "Invalid target",
        )
        targets.append(target)
        keys = row["tensors"]
        require(
            isinstance(keys, list)
            and len(keys) == 2
            and all(isinstance(key, str) and key in header for key in keys)
            and len(set(keys)) == 2
            and not consumed.intersection(keys),
            "Tensor coverage differs",
        )
        consumed.update(keys)
        down, up = sorted(keys)
        require(
            down.endswith(".lora_down.weight") and up == down.replace(".lora_down.", ".lora_up."),
            "Expected paired exported tensors",
        )
        for shape in (row["base_shape"], row["up_shape"], row["down_shape"]):
            require(
                isinstance(shape, list)
                and len(shape) == 2
                and all(type(n) is int and n > 0 for n in shape),
                "Invalid loader shape",
            )
        require(
            row["up_shape"] == header[up]["shape"]
            and row["down_shape"] == header[down]["shape"]
            and row["up_shape"][1] == row["down_shape"][0]
            and row["base_shape"] == [row["up_shape"][0], row["down_shape"][1]],
            "Loader shape mismatch",
        )
        require(
            row["patch_type"] == "lora"
            and type(row["alpha_scale_milli"]) is int
            and row["alpha_scale_milli"] == 1000,
            "Unexpected patch scaling/type",
        )
    require(consumed == set(header) - {"__metadata__"}, "Incomplete loader tensor coverage")
    require(targets == sorted(targets), "Loader targets out of order")
    require(
        canonical_bytes(result["accepted"])
        == canonical_bytes([{"strength_milli": s, "targets": targets} for s in strengths]),
        "Patch registration differs",
    )
    return result


def _header(path):
    with path.open("rb") as stream:
        size = struct.unpack("<Q", stream.read(8))[0]
        require(size <= 16 * 1024**2, "Adapter header too large")
        return parse_json_object(stream.read(size), message="Adapter header must be an object")


def _request(config, plan):
    graph = parse_json_object(plan["jobs"][0]["workflow_json"])
    checkpoint = config.comfyui_root / "models/checkpoints" / graph["1"]["inputs"]["ckpt_name"]
    adapter = safe_path(config.comfyui_root / "models/loras", plan["deployment"]["loader_name"])
    strengths = sorted(
        {
            job.get("strength_milli", plan["specification"].get("strength_milli"))
            for job in plan["jobs"]
            if job["role"].startswith("adapter_")
        }
    )
    require(strengths, "Loader mapping requires adapter comparison conditions")
    return {
        "comfyui_root": str(config.comfyui_root),
        "checkpoint": str(checkpoint),
        "adapter": str(adapter),
        "strengths_milli": strengths,
    }


def mapping(config, path, *, save=False):
    with EvidenceReads().capture() as reads:
        plan = evaluation_runtime.load_plan(path)
        files = _inputs(config, plan)
        request = _request(config, plan)
        directory = safe_path(config.root, f"state/evaluation/loader-attempts/{uuid.uuid4()}")
        directory.mkdir(parents=True)
        request_path = publish(directory / "request.json", request)
        output = directory / "result.json"
        worker = _file(Path(__file__).with_name("deployed_loader_worker.py"))
        observe(worker["path"], worker["sha256"], worker["bytes"])
        command = [str(config.python), "-I", worker["path"], str(request_path), str(output)]
        with (directory / "worker.log").open("x", encoding="utf-8") as log:
            log.write("CPU loader probe; CUDA_VISIBLE_DEVICES=-1; isolated Python\n")
            log.flush()
            result = subprocess.run(
                command,
                cwd=config.comfyui_root,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=600,
                env={**os.environ, "CUDA_VISIBLE_DEVICES": "-1"},
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        require(result.returncode == 0, f"Loader probe failed; preserve {directory}")
        measured = validate_result(
            parse_json(read_document(output)),
            _header(Path(request["adapter"])),
            request["strengths_milli"],
        )
        require(
            measured["torch_version"] == plan["runtime"]["runtime"]["pytorch_version"],
            "Loader Torch version differs from planned runtime",
        )
        require(files == _inputs(config, plan), "Loader inputs changed during probe")
        value = seal(
            {
                "version": 1,
                "scope": "deployed_loader_mapping",
                "evaluation_plan": reference(config, path),
                "plan_id": plan["plan_id"],
                "candidate_id": plan["candidate"]["candidate_id"],
                "deployment": plan["deployment"],
                "files": files,
                "request": reference(config, request_path),
                "result": reference(config, output),
                "log": reference(config, directory / "worker.log"),
                "command": command,
                "environment": {"CUDA_VISIBLE_DEVICES": "-1"},
                "worker": worker,
                "mapping": measured,
                "limits": LIMITS,
            },
            "mapping_id",
        )
    reads.verify()
    if save:
        publish(config.root / f"state/evaluation/mappings/{value['mapping_id']}.json", value)
    return value


def inspect(config, path):
    with EvidenceReads().capture() as reads:
        value = check_seal(parse_json(read_document(path)), "mapping_id")
        object_fields(
            value,
            {
                "version",
                "scope",
                "evaluation_plan",
                "plan_id",
                "candidate_id",
                "deployment",
                "files",
                "request",
                "result",
                "log",
                "command",
                "environment",
                "mapping",
                "limits",
                "worker",
                "mapping_id",
            },
            "loader certificate",
        )
        require(
            type(value["version"]) is int
            and value["version"] == 1
            and value["scope"] == "deployed_loader_mapping"
            and value["limits"] == LIMITS,
            "Invalid loader certificate",
        )
        plan = evaluation_runtime.load_plan(file_ref(config.root, value["evaluation_plan"])[0])
        require(
            value["plan_id"] == plan["plan_id"]
            and value["candidate_id"] == plan["candidate"]["candidate_id"]
            and value["deployment"] == plan["deployment"]
            and value["files"] == _inputs(config, plan),
            "Loader binding or implementation changed",
        )
        request_path = file_ref(config.root, value["request"])[0]
        request = parse_json_object(read_document(request_path), message="Loader request differs")
        require(request == _request(config, plan), "Loader request differs")
        output = file_ref(config.root, value["result"])[0]
        file_ref(config.root, value["log"])
        worker = _file(Path(__file__).with_name("deployed_loader_worker.py"))
        observe(worker["path"], worker["sha256"], worker["bytes"])
        observe(value["worker"]["path"], value["worker"]["sha256"], value["worker"]["bytes"])
        require(
            _file(Path(value["worker"]["path"])) == value["worker"]
            and all(worker[k] == value["worker"][k] for k in ("sha256", "bytes")),
            "Loader worker changed",
        )
        require(
            value["command"]
            == [str(config.python), "-I", value["worker"]["path"], str(request_path), str(output)],
            "Loader command differs",
        )
        require(
            value["environment"] == {"CUDA_VISIBLE_DEVICES": "-1"}, "Loader environment differs"
        )
        result = validate_result(
            parse_json(read_document(output)),
            _header(Path(request["adapter"])),
            request["strengths_milli"],
        )
        require(
            result["torch_version"] == plan["runtime"]["runtime"]["pytorch_version"],
            "Loader Torch version differs from planned runtime",
        )
        require(
            canonical_bytes(value["mapping"]) == canonical_bytes(result), "Loader result differs"
        )
    reads.verify()
    return value
