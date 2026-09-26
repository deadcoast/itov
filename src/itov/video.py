"""Pinned Wan 2.2 TI2V 5B preparation and sequential video planning."""

from __future__ import annotations

from pathlib import Path

from itov import media_configuration
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
from itov.catalog_store import CatalogStore
from itov.comfyui import parse_json
from itov.config import Config
from itov.inference import _merge, _publish
from itov.media import video_contract
from itov.qualification import _file, model_path, safe_path

PROFILE = "wan22-ti2v-5b-v1"
LOADERS = {
    "diffusion": ("UNETLoader", "unet_name"),
    "text_encoder": ("CLIPLoader", "clip_name"),
    "vae": ("VAELoader", "vae_name"),
}


def load_spec(path: Path) -> dict:
    return validate_spec(parse_json(read_document(path)))


def validate_spec(value: dict) -> dict:
    object_fields(
        value,
        {
            "version",
            "profile",
            "diffusion",
            "text_encoder",
            "vae",
            "input_image",
            "prompt",
            "negative_prompt",
            "width",
            "height",
            "frames",
            "fps",
            "seed",
            "count",
        }
        | (
            {"sampler", "source"}
            if isinstance(value, dict) and value.get("version") == 2
            else set()
        ),
        "video specification",
    )
    require(type(value["version"]) is int and value["version"] in (1, 2), "Invalid video version")
    require(
        value["profile"] == (PROFILE if value["version"] == 1 else "wan22-ti2v-5b-v2"),
        "Unsupported video profile",
    )
    if value["version"] == 2:
        from itov.media_sources import binding

        media_configuration.sampler(value["sampler"], "video")
        if value["source"] is not None:
            binding(value["source"])
    for name in (*LOADERS, "input_image"):
        asset = value[name]
        field = "name" if name == "input_image" else "loader_name"
        object_fields(asset, {field, "sha256"}, name)
        relative_path(asset[field], name)
        suffix = ".png" if name == "input_image" else ".safetensors"
        require(asset[field].endswith(suffix), f"{name} must end in {suffix}")
        if name == "input_image":
            require(
                "/" not in asset[field], "Video input must be a top-level PNG for stock LoadImage"
            )
        digest(asset["sha256"], name + ".sha256")
    for name in ("prompt", "negative_prompt"):
        text(value[name], name, empty=name == "negative_prompt")
        require(
            len(value[name]) <= 4096 and "embedding:" not in value[name].lower(),
            "Prompts must be at most 4096 characters without external embeddings",
        )
    video_contract(media_configuration.video_contract(value))
    integer(value["seed"], "seed")
    integer(value["count"], "count", minimum=1)
    require(
        value["count"] <= 4 and value["seed"] + value["count"] - 1 <= MAX_INTEGER,
        "Video count must be 1..4 without seed overflow",
    )
    return parse_json(canonical_bytes(value))


def describe(spec: dict) -> dict:
    spec = validate_spec(spec)
    spec_id = sha256(canonical_bytes(spec))
    graph = {}
    for index, (name, (kind, field)) in enumerate(LOADERS.items(), 1):
        graph[str(index)] = {
            "class_type": kind,
            "inputs": {field: spec[name]["loader_name"]},
            "_meta": {"itov_asset_sha256": spec[name]["sha256"]},
        }
    graph["1"]["inputs"]["weight_dtype"] = "default"
    graph["2"]["inputs"].update(type="wan", device="default")
    graph.update(
        {
            "4": {
                "class_type": "LoadImage",
                "inputs": {"image": spec["input_image"]["name"]},
                "_meta": {"itov_asset_sha256": spec["input_image"]["sha256"]},
            },
            "5": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["2", 0], "text": spec["prompt"]},
            },
            "6": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["2", 0], "text": spec["negative_prompt"]},
            },
            "7": {
                "class_type": "Wan22ImageToVideoLatent",
                "inputs": {
                    "vae": ["3", 0],
                    "width": spec["width"],
                    "height": spec["height"],
                    "length": spec["frames"],
                    "batch_size": 1,
                    "start_image": ["4", 0],
                },
            },
            "8": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["1", 0], "shift": 8}},
            "9": {
                "class_type": "KSampler",
                "inputs": {
                    "model": ["8", 0],
                    "seed": spec["seed"],
                    "steps": 20,
                    "cfg": 5,
                    "sampler_name": "uni_pc",
                    "scheduler": "simple",
                    "denoise": 1,
                    "positive": ["5", 0],
                    "negative": ["6", 0],
                    "latent_image": ["7", 0],
                },
            },
            "10": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["3", 0]}},
            "11": {
                "class_type": "CreateVideo",
                "inputs": {"images": ["10", 0], "fps": spec["fps"]},
            },
            "12": {
                "class_type": "SaveVideo",
                "inputs": {
                    "video": ["11", 0],
                    "filename_prefix": "itov/video/" + spec_id,
                    "format": "mp4",
                    "format.codec": "h264",
                },
                "_meta": {"itov_video": media_configuration.video_contract(spec)},
            },
        }
    )
    if spec["version"] == 2:
        settings = spec["sampler"]
        graph["8"]["inputs"]["shift"] = settings["shift_milli"] / 1000
        graph["9"]["inputs"].update(steps=settings["steps"], cfg=settings["cfg_milli"] / 1000)
        if spec["source"] is not None:
            graph["4"]["_meta"]["itov_source"] = spec["source"]
    raw = _workflow_json(graph).encode("utf-8")
    preset = {
        "id": "video-" + spec_id,
        "category": "image-to-video",
        "tags": [spec["profile"]],
        "workflow": {"path": f"workflows/video/{spec_id}.api.json", "sha256": sha256(raw)},
        "base_model": "wan2.2-ti2v-5b",
        "rotation_weight_milli": 1000,
        "seed": {"base": spec["seed"], "step": 1},
    }
    return {"spec_id": spec_id, "preset": preset, "workflow": raw}


def _assets(config: Config, spec: dict):
    for name, (kind, _) in LOADERS.items():
        asset = spec[name]
        path = model_path(config, kind, asset["loader_name"])
        require(_file(path)["sha256"] == asset["sha256"], f"Pinned {name} SHA-256 mismatch")


def _input(config: Config, spec: dict) -> Path:
    if spec.get("source") is not None:
        from itov.media_sources import image_source

        image_source(config, spec["source"], spec["input_image"]["sha256"])
    path = safe_path(config.root / "input", spec["input_image"]["name"])
    require(
        _file(path)["sha256"] == spec["input_image"]["sha256"],
        "Pinned input image SHA-256 mismatch",
    )
    return path


def prepare_video(config: Config, spec: dict, *, image_source: Path | None = None) -> dict:
    spec = validate_spec(spec)
    definition = describe(spec)
    store = CatalogStore(config.root)
    snapshot = store.snapshot(require_clean=True)
    _assets(config, spec)
    catalog = snapshot.to_dict()["catalog"]
    _merge(catalog["presets"], definition["preset"])
    validate_catalog(catalog)
    if spec.get("source") is not None:
        from itov.media_sources import image_source as read_source

        source = read_source(config, spec["source"], spec["input_image"]["sha256"])
        _publish(safe_path(config.root / "input", spec["input_image"]["name"]), source.read_bytes())
    if image_source is not None:
        require(image_source.stat().st_size <= 16 * 1024**2, "Source PNG exceeds 16 MiB")
        raw = image_source.read_bytes()
        require(sha256(raw) == spec["input_image"]["sha256"], "Pinned input image SHA-256 mismatch")
        _publish(safe_path(config.root / "input", spec["input_image"]["name"]), raw)
    _input(config, spec)
    workflow = safe_path(config.root, definition["preset"]["workflow"]["path"])
    _publish(workflow, definition["workflow"])
    raw = canonical_bytes(catalog) + b"\n"
    candidate = safe_path(config.root, f"templates/video/{sha256(raw)}.catalog.json")
    _publish(candidate, raw)
    store.snapshot(expected_head=snapshot.head, require_clean=True)
    return {
        "ok": True,
        "scope": "prepared_video_candidates",
        "spec_id": definition["spec_id"],
        "catalog": str(candidate),
        "workflow": str(workflow),
        "expected_head": snapshot.head,
        "limits": "No catalog import, seed reservation, or runtime submission.",
    }


def plan_video(config: Config, spec: dict) -> dict:
    spec = validate_spec(spec)
    definition = describe(spec)
    _assets(config, spec)
    _input(config, spec)
    snapshot = CatalogStore(config.root).snapshot(require_clean=True)
    preset = definition["preset"]
    require(
        preset in snapshot.to_dict()["catalog"]["presets"],
        "Import the prepared video catalog before planning",
    )
    request = neutral_request(snapshot.head, preset["id"], count=spec["count"], seed=0)
    request["bindings"][preset["id"]]["seed_inputs"] = [
        {"node": "9", "class_type": "KSampler", "input": "seed"}
    ]
    return create_plan(config.root, request)
