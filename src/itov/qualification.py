"""Fail-closed preflight for the supported local, stock-node execution profile."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from itov.batch import replay_plan
from itov.catalog import canonical_bytes, read_document, relative_path, require, sha256
from itov.catalog_store import _atomic_write
from itov.comfyui import ComfyUIClient, parse_json
from itov.config import Config
from itov.runtime import launch_command
from itov.workflow import validate_workflow

PROFILE = "stock-local-v1"
SUPPORTED = {
    "LoadImage",
    "SaveImage",
    "CheckpointLoaderSimple",
    "LoraLoader",
    "LoraLoaderModelOnly",
    "CLIPTextEncode",
    "EmptyLatentImage",
    "KSampler",
    "VAEDecode",
    "VAEEncode",
}


def json_text(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def safe_path(root: Path, name: str) -> Path:
    relative_path(name, "runtime file")
    path = root / name
    require(
        path.resolve() == path.absolute() and not path.is_symlink(),
        f"Runtime path redirects: {path}",
    )
    return path


def _file(path: Path) -> dict:
    with path.open("rb") as source:
        before = path.stat()
        digest = hashlib.file_digest(source, "sha256").hexdigest()
        after = path.stat()
    require(
        (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns),
        f"File changed while hashing: {path}",
    )
    return {"path": str(path), "bytes": after.st_size, "sha256": digest}


def qualify(config: Config, plan: dict, *, timeout: float = 3) -> dict:
    """Rebuild the plan and bind stock loader names to actual local file bytes.

    This receipt establishes preflight observations, not model efficacy or a render.
    Runtime and assets must remain under operator control while execution is active.
    """
    replay_plan(config.root, plan)
    expected_argv = launch_command(config)[2:]
    client = ComfyUIClient(config.url, timeout=timeout)
    stats, registry = client.system_stats(), client.object_info()
    require(
        stats["system"].get("argv") == expected_argv,
        "Qualification requires the exact stock runtime launched by itov server start",
    )
    require(
        not (config.comfyui_root / "extra_model_paths.yaml").exists(),
        "Extra model search paths are not supported by this qualification profile",
    )
    used, files = set(), {}

    def bind(root, name):
        path = safe_path(root, name)
        key = str(path)
        if key not in files:
            files[key] = _file(path)
        return files[key]

    for name in ("main.py", "nodes.py", "folder_paths.py"):
        bind(config.comfyui_root, name)
    for job in plan["jobs"]:
        graph = parse_json(job["workflow_json"])
        validation = validate_workflow(graph, registry).to_dict()
        require(
            validation["valid"],
            f"Live workflow validation failed at job {job['index']}: {validation['issues']}",
        )
        planned_loras = {}
        for item in job["loras"]:
            name, digest = item["loader_name"], item["asset"]["sha256"]
            require(
                name not in planned_loras or planned_loras[name] == digest,
                f"One loader name refers to different planned LoRA assets: {name}",
            )
            planned_loras[name] = digest
        seed_nodes = {
            binding["node"]
            for binding in plan["request"]["bindings"][job["preset"]]["seed_inputs"]
            if binding["class_type"] == "KSampler" and binding["input"] == "seed"
        }
        for node_id, node in graph.items():
            kind, inputs = node["class_type"], node["inputs"]
            require(kind in SUPPORTED, f"Node is outside the {PROFILE} profile: {kind}")
            require(
                registry[kind].get("python_module") == "nodes",
                f"Node is not the stock implementation: {kind}",
            )
            used.add(kind)
            if kind == "LoadImage":
                require(
                    not inputs["image"].endswith(("[input]", "[output]", "[temp]")),
                    "Annotated LoadImage paths are outside this qualification profile",
                )
                bind(config.root / "input", inputs["image"])
            elif kind == "CLIPTextEncode":
                require(
                    isinstance(inputs["text"], str) and "embedding:" not in inputs["text"].lower(),
                    "External text embeddings are outside this qualification profile",
                )
            elif kind == "CheckpointLoaderSimple":
                bind(config.comfyui_root / "models/checkpoints", inputs["ckpt_name"])
            elif kind in {"LoraLoader", "LoraLoaderModelOnly"}:
                name = inputs["lora_name"]
                asset = bind(config.comfyui_root / "models/loras", name)
                require(
                    asset["sha256"] == planned_loras.get(name),
                    f"Loader name does not resolve to the planned LoRA bytes: {name}",
                )
            elif kind == "SaveImage":
                prefix = inputs["filename_prefix"]
                require(
                    isinstance(prefix, str) and "%" not in prefix,
                    "SaveImage requires a literal relative filename prefix",
                )
                safe_path(config.root / "output", prefix)
            elif kind == "KSampler":
                require(
                    node_id in seed_nodes
                    and job["seed"] is not None
                    and inputs["seed"] == job["seed"],
                    "Every KSampler seed must be covered by the plan's seed reservation",
                )
    system = stats["system"]
    body = {
        "version": 1,
        "profile": PROFILE,
        "scope": "runtime_schema_and_asset_binding",
        "plan_id": plan["plan_id"],
        "server": config.url,
        "runtime": {
            key: system.get(key)
            for key in ("argv", "comfyui_version", "python_version", "pytorch_version")
        },
        "devices": [
            {key: item.get(key) for key in ("name", "type", "index")} for item in stats["devices"]
        ],
        "node_schema_sha256": sha256(
            json_text({key: registry[key] for key in sorted(used)}).encode()
        ),
        "files": [files[key] for key in sorted(files)],
        "jobs": len(plan["jobs"]),
    }
    return {**body, "qualification_id": sha256(canonical_bytes(body))}


def save_qualification(config: Config, receipt: dict) -> Path:
    path = safe_path(config.root, f"state/qualifications/{receipt['qualification_id']}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical_bytes(receipt) + b"\n"
    try:
        _atomic_write(path, raw, exclusive=True)
    except FileExistsError:
        require(path.read_bytes() == raw, "Existing qualification differs; preserve and inspect")
    return path


def load_qualification(path: Path) -> dict:
    raw = read_document(path)
    receipt = parse_json(raw)
    require(isinstance(receipt, dict), "Qualification must be an object")
    body = {key: value for key, value in receipt.items() if key != "qualification_id"}
    require(
        receipt.get("qualification_id") == sha256(canonical_bytes(body)),
        "Qualification hash mismatch",
    )
    require(raw == canonical_bytes(receipt) + b"\n", "Noncanonical qualification")
    return receipt
