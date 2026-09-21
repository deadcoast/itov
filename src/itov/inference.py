"""Prepare pinned stock SDXL workflows and reproducible seeded batch requests."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from itov.batch import _workflow_json, create_plan
from itov.batch_request import neutral_request
from itov.catalog import (
    MAX_INTEGER,
    canonical_bytes,
    digest,
    integer,
    object_fields,
    read_document,
    relative_path,
    require,
    sha256,
    text,
    validate_catalog,
)
from itov.catalog_store import CatalogStore, _atomic_write
from itov.comfyui import parse_json
from itov.config import Config
from itov.qualification import _file, safe_path

PROFILES = {
    "sdxl-base-v1": {"steps": 20, "cfg": 7, "sampler_name": "dpmpp_2m", "scheduler": "karras"},
    "sdxl-lcm-v1": {"steps": 4, "cfg": 1, "sampler_name": "lcm", "scheduler": "sgm_uniform"},
}


def load_spec(path: Path) -> dict:
    return validate_spec(parse_json(read_document(path)))


def validate_spec(value) -> dict:
    object_fields(
        value,
        {
            "version",
            "profile",
            "checkpoint",
            "lora",
            "prompt",
            "negative_prompt",
            "width",
            "height",
            "seed",
            "count",
        },
        "inference specification",
    )
    require(type(value["version"]) is int and value["version"] == 1, "Invalid inference version")
    require(
        isinstance(value["profile"], str) and value["profile"] in PROFILES,
        "Unsupported inference profile",
    )
    require(
        (value["lora"] is not None) == (value["profile"] == "sdxl-lcm-v1"),
        "sdxl-lcm-v1 requires one LCM LoRA; sdxl-base-v1 requires none",
    )
    for name in ("checkpoint", "lora"):
        asset = value[name]
        if asset is None:
            continue
        object_fields(asset, {"loader_name", "sha256"}, name)
        relative_path(asset["loader_name"], name + ".loader_name")
        require(
            asset["loader_name"].endswith(".safetensors"), "Inference assets must be safetensors"
        )
        digest(asset["sha256"], name + ".sha256")
    require(value["checkpoint"] is not None, "A checkpoint is required")
    for name in ("prompt", "negative_prompt"):
        text(value[name], name, empty=name == "negative_prompt")
        require(
            len(value[name]) <= 4096 and "embedding:" not in value[name].lower(),
            "Prompts must be at most 4096 characters and cannot use external embeddings",
        )
    for name in ("width", "height"):
        integer(value[name], name, minimum=512)
        require(
            value[name] <= 1024 and value[name] % 64 == 0,
            "Inference dimensions must be multiples of 64 within 512..1024",
        )
    integer(value["count"], "count", minimum=1)
    require(value["count"] <= 16, "An inference qualification batch supports at most 16 jobs")
    integer(value["seed"], "seed")
    require(value["seed"] + value["count"] - 1 <= MAX_INTEGER, "Inference seeds overflow uint64")
    return parse_json(canonical_bytes(value))


def describe(spec: dict) -> dict:
    spec = validate_spec(spec)
    spec_id = sha256(canonical_bytes(spec))
    preset_id = "inference-" + spec_id
    lcm = spec["lora"] is not None
    graph = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": spec["checkpoint"]["loader_name"]},
            "_meta": {"itov_asset_sha256": spec["checkpoint"]["sha256"]},
        },
        "3": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": spec["prompt"]}},
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": spec["negative_prompt"]},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": spec["width"], "height": spec["height"], "batch_size": 1},
        },
        "6": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["2" if lcm else "1", 0],
                "seed": spec["seed"],
                **PROFILES[spec["profile"]],
                "positive": ["3", 0],
                "negative": ["4", 0],
                "latent_image": ["5", 0],
                "denoise": 1,
            },
        },
        "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["1", 2]}},
        "8": {
            "class_type": "SaveImage",
            "inputs": {"images": ["7", 0], "filename_prefix": "itov/inference/" + spec_id},
        },
    }
    lora = None
    if lcm:
        # LCM modifies the diffusion model; it does not need a CLIP adapter.
        graph["2"] = {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {
                "model": ["1", 0],
                "lora_name": spec["lora"]["loader_name"],
                "strength_model": 1,
            },
        }
        lora = {
            "id": "inference-lcm-" + spec["lora"]["sha256"],
            "asset": {
                "path": "models_shared/inference/" + spec["lora"]["sha256"] + ".safetensors",
                "sha256": spec["lora"]["sha256"],
            },
            "category": "acceleration",
            "slot": "lcm",
            "base_models": ["sdxl-1.0"],
            "strength_milli": {"min": 1000, "recommended": 1000, "max": 1000},
            "rotation_weight_milli": 1000,
            "trigger_words": [],
            "status": "active",
        }
    raw = _workflow_json(graph).encode("utf-8")
    preset = {
        "id": preset_id,
        "category": "image-inference",
        "tags": [spec["profile"]],
        "workflow": {"path": f"workflows/inference/{spec_id}.api.json", "sha256": sha256(raw)},
        "base_model": "sdxl-1.0",
        "rotation_weight_milli": 1000,
        "seed": {"base": spec["seed"], "step": 1},
    }
    return {"spec_id": spec_id, "preset": preset, "lora": lora, "workflow": raw}


def _checked_assets(config: Config, spec: dict) -> dict:
    paths = {}
    for key, folder in (("checkpoint", "checkpoints"), ("lora", "loras")):
        asset = spec[key]
        if asset is not None:
            path = safe_path(config.comfyui_root / "models" / folder, asset["loader_name"])
            require(_file(path)["sha256"] == asset["sha256"], f"Pinned {key} SHA-256 mismatch")
            paths[key] = path
    return paths


def _publish(path: Path, raw: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _atomic_write(path, raw, exclusive=True)
    except FileExistsError:
        require(path.read_bytes() == raw, f"Existing prepared file differs: {path}")


def _copy_lora(source: Path, target: Path, expected: str):
    if target.exists():
        require(
            _file(target)["sha256"] == expected, "Prepared LoRA copy differs; preserve and inspect"
        )
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with (
            source.open("rb") as original,
            tempfile.NamedTemporaryFile(
                dir=target.parent, prefix=".inference-", delete=False
            ) as output,
        ):
            temporary = Path(output.name)
            observed = hashlib.sha256()
            while chunk := original.read(1024 * 1024):
                output.write(chunk)
                observed.update(chunk)
            output.flush()
            os.fsync(output.fileno())
        require(observed.hexdigest() == expected, "LoRA changed during copy")
        try:
            os.link(temporary, target)
        except FileExistsError:
            require(_file(target)["sha256"] == expected, "Prepared LoRA copy differs")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _merge(items: list, value: dict):
    existing = next((item for item in items if item["id"] == value["id"]), None)
    if existing is None:
        items.append(value)
    else:
        require(existing == value, "Existing inference catalog entry differs; preserve and inspect")


def prepare_inference(config: Config, spec: dict) -> dict:
    """Write immutable candidates without importing a catalog or submitting work."""
    spec = validate_spec(spec)
    definition = describe(spec)
    store = CatalogStore(config.root)
    snapshot = store.snapshot(require_clean=True)
    assets = _checked_assets(config, spec)
    catalog = snapshot.to_dict()["catalog"]
    _merge(catalog["presets"], definition["preset"])
    if definition["lora"] is not None:
        _merge(catalog["loras"], definition["lora"])
    validate_catalog(catalog)
    workflow = safe_path(config.root, definition["preset"]["workflow"]["path"])
    _publish(workflow, definition["workflow"])
    if definition["lora"] is not None:
        reference = definition["lora"]["asset"]
        _copy_lora(assets["lora"], safe_path(config.root, reference["path"]), reference["sha256"])
    raw = canonical_bytes(catalog) + b"\n"
    candidate = safe_path(config.root, f"templates/inference/{sha256(raw)}.catalog.json")
    _publish(candidate, raw)
    store.snapshot(expected_head=snapshot.head, require_clean=True)
    return {
        "ok": True,
        "scope": "prepared_inference_candidates",
        "spec_id": definition["spec_id"],
        "preset_id": definition["preset"]["id"],
        "catalog": str(candidate),
        "workflow": str(workflow),
        "expected_head": snapshot.head,
        "limits": "No catalog import, runtime validation, seed reservation, or submission.",
    }


def plan_inference(config: Config, spec: dict) -> dict:
    spec = validate_spec(spec)
    definition = describe(spec)
    _checked_assets(config, spec)
    snapshot = CatalogStore(config.root).snapshot(require_clean=True)
    catalog = snapshot.to_dict()["catalog"]
    preset = definition["preset"]
    require(preset in catalog["presets"], "Import the prepared inference catalog before planning")
    if definition["lora"] is not None:
        require(definition["lora"] in catalog["loras"], "Prepared LoRA is missing or changed")
    request = neutral_request(snapshot.head, preset["id"], count=spec["count"], seed=0)
    request["bindings"][preset["id"]]["seed_inputs"] = [
        {"node": "6", "class_type": "KSampler", "input": "seed"}
    ]
    if definition["lora"] is not None:
        key = definition["lora"]["id"]
        request["lora_policy"].update(
            ids=[key],
            slots=["lcm"],
            max_strength_milli=1000,
            loader_names={key: spec["lora"]["loader_name"]},
        )
        request["bindings"][preset["id"]]["lora_slots"] = [{"slot": "lcm", "node": "2"}]
    return create_plan(config.root, request)
