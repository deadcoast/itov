"""Pinned stock Stable Audio Open preparation and sequential planning."""

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
from itov.catalog_store import CatalogStore
from itov.comfyui import parse_json_object
from itov.config import Config
from itov.inference import _merge, _publish
from itov.qualification import _file, model_path, safe_path

PROFILE = "stable-audio-open-v1"


def load_spec(path: Path) -> dict:
    return validate_spec(
        parse_json_object(read_document(path), message="audio specification: expected an object")
    )


def validate_spec(value: dict) -> dict:
    object_fields(
        value,
        {
            "version",
            "profile",
            "checkpoint",
            "text_encoder",
            "prompt",
            "negative_prompt",
            "seconds",
            "seed",
            "count",
        }
        | ({"sampler"} if isinstance(value, dict) and value.get("version") == 2 else set()),
        "audio specification",
    )
    require(type(value["version"]) is int and value["version"] in (1, 2), "Invalid audio version")
    require(
        value["profile"] == (PROFILE if value["version"] == 1 else "stable-audio-open-v2"),
        "Unsupported audio profile",
    )
    if value["version"] == 2:
        from itov.media_configuration import sampler

        sampler(value["sampler"], "audio")
    for name in ("checkpoint", "text_encoder"):
        asset = value[name]
        object_fields(asset, {"loader_name", "sha256"}, name)
        relative_path(asset["loader_name"], name)
        require(asset["loader_name"].endswith(".safetensors"), "Audio models must be safetensors")
        digest(asset["sha256"], name + ".sha256")
    for name in ("prompt", "negative_prompt"):
        text(value[name], name, empty=name == "negative_prompt")
        require(
            len(value[name]) <= 4096 and "embedding:" not in value[name].lower(),
            "Prompts must be at most 4096 characters without external embeddings",
        )
    integer(value["seconds"], "seconds", minimum=1)
    require(
        value["seconds"] <= (47 if value["version"] == 2 else 10),
        "Audio duration must be an integer in 1..10 (v1) or 1..47 (v2) seconds",
    )
    integer(value["seed"], "seed")
    integer(value["count"], "count", minimum=1)
    require(
        value["count"] <= 4 and value["seed"] + value["count"] - 1 <= MAX_INTEGER,
        "Audio count must be 1..4 without seed overflow",
    )
    return parse_json_object(canonical_bytes(value))


def output_contract(spec: dict) -> dict:
    spec = validate_spec(spec)
    # Stock EmptyLatentAudio rounds to an even latent length, decoded at stride 2048.
    return {
        **({"version": 2} if spec["version"] == 2 else {}),
        "sample_rate": 44100,
        "channels": 2,
        "samples": round(spec["seconds"] * 44100 / 4096) * 4096,
    }


def describe(spec: dict) -> dict:
    spec = validate_spec(spec)
    spec_id = sha256(canonical_bytes(spec))
    graph: dict[str, dict] = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": spec["checkpoint"]["loader_name"]},
            "_meta": {"itov_asset_sha256": spec["checkpoint"]["sha256"]},
        },
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": spec["text_encoder"]["loader_name"],
                "type": "stable_audio",
                "device": "default",
            },
            "_meta": {"itov_asset_sha256": spec["text_encoder"]["sha256"]},
        },
        "3": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": spec["prompt"]}},
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["2", 0], "text": spec["negative_prompt"]},
        },
        "5": {
            "class_type": "ConditioningStableAudio",
            "inputs": {
                "positive": ["3", 0],
                "negative": ["4", 0],
                "seconds_start": 0,
                "seconds_total": spec["seconds"],
            },
        },
        "6": {
            "class_type": "EmptyLatentAudio",
            "inputs": {"seconds": spec["seconds"], "batch_size": 1},
        },
        "7": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "seed": spec["seed"],
                "steps": 50,
                "cfg": 4.98,
                "sampler_name": "dpmpp_3m_sde_gpu",
                "scheduler": "exponential",
                "denoise": 1,
                "positive": ["5", 0],
                "negative": ["5", 1],
                "latent_image": ["6", 0],
            },
        },
        "8": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["7", 0], "vae": ["1", 2]}},
        "9": {
            "class_type": "SaveAudioAdvanced",
            "inputs": {
                "audio": ["8", 0],
                "filename_prefix": "itov/audio/" + spec_id,
                "format": "flac",
            },
            "_meta": {"itov_audio": output_contract(spec)},
        },
    }
    if spec["version"] == 2:
        graph["7"]["inputs"].update(
            steps=spec["sampler"]["steps"], cfg=spec["sampler"]["cfg_milli"] / 1000
        )
    raw = _workflow_json(graph).encode("utf-8")
    preset = {
        "id": "audio-" + spec_id,
        "category": "text-to-audio",
        "tags": [spec["profile"]],
        "workflow": {"path": f"workflows/audio/{spec_id}.api.json", "sha256": sha256(raw)},
        "base_model": "stable-audio-open-1.0",
        "rotation_weight_milli": 1000,
        "seed": {"base": spec["seed"], "step": 1},
    }
    return {"spec_id": spec_id, "preset": preset, "workflow": raw}


def _assets(config: Config, spec: dict):
    for name, kind in (("checkpoint", "CheckpointLoaderSimple"), ("text_encoder", "CLIPLoader")):
        asset = spec[name]
        path = model_path(config, kind, asset["loader_name"])
        require(_file(path)["sha256"] == asset["sha256"], f"Pinned {name} SHA-256 mismatch")


def prepare_audio(config: Config, spec: dict) -> dict:
    spec = validate_spec(spec)
    definition = describe(spec)
    store = CatalogStore(config.root)
    snapshot = store.snapshot(require_clean=True)
    _assets(config, spec)
    catalog = snapshot.to_dict()["catalog"]
    _merge(catalog["presets"], definition["preset"])
    validate_catalog(catalog)
    workflow = safe_path(config.root, definition["preset"]["workflow"]["path"])
    _publish(workflow, definition["workflow"])
    raw = canonical_bytes(catalog) + b"\n"
    candidate = safe_path(config.root, f"templates/audio/{sha256(raw)}.catalog.json")
    _publish(candidate, raw)
    store.snapshot(expected_head=snapshot.head, require_clean=True)
    return {
        "ok": True,
        "scope": "prepared_audio_candidates",
        "spec_id": definition["spec_id"],
        "catalog": str(candidate),
        "workflow": str(workflow),
        "expected_head": snapshot.head,
        "limits": "No catalog import, seed reservation, or runtime submission.",
    }


def plan_audio(config: Config, spec: dict) -> dict:
    spec = validate_spec(spec)
    definition = describe(spec)
    _assets(config, spec)
    snapshot = CatalogStore(config.root).snapshot(require_clean=True)
    preset = definition["preset"]
    require(
        preset in snapshot.to_dict()["catalog"]["presets"],
        "Import the prepared audio catalog before planning",
    )
    request = neutral_request(snapshot.head, preset["id"], count=spec["count"], seed=0)
    request["bindings"][preset["id"]]["seed_inputs"] = [
        {"node": "7", "class_type": "KSampler", "input": "seed"}
    ]
    return create_plan(config.root, request)
