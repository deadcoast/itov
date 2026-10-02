"""Versioned, conservative SDXL model/adapter compatibility contracts."""

from itov.catalog import (
    MAX_INTEGER,
    array,
    canonical_bytes,
    digest,
    integer,
    object_fields,
    relative_path,
    require,
    text,
)
from itov.comfyui import parse_json
from itov.image_media import image_contract

CAPABILITY = "sdxl-1.0-unet-v1"
CHECKPOINT = "31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b"
LCM = "a764e6859b6e04047cd761c08ff0cee96413a8e004c9f07707530cd776b19141"
RUNTIME_SOURCES = (
    "execution.py",
    "comfy/sd.py",
    "comfy/lora.py",
    "comfy/lora_convert.py",
    "comfy/model_patcher.py",
    "comfy/samplers.py",
    "comfy/sample.py",
    "comfy/k_diffusion/sampling.py",
)


def capabilities():
    return {
        "ok": True,
        "scope": "inference_capabilities",
        "capability": CAPABILITY,
        "checkpoint_sha256": CHECKPOINT,
        "lcm_sha256": LCM,
        "adapter_order": ["lcm (optional)", "trained_candidate (optional)"],
        "adapter_target": "UNet only; checkpoint CLIP and VAE remain bound",
        "candidate_strength_milli": {"min": 1, "max": 1000},
        "lcm_strength_milli": 1000,
        "samplers": {
            "without_lcm": {
                "sampler_name": "dpmpp_2m",
                "scheduler": "karras",
                "steps": [1, 50],
                "cfg_milli": [1, 15000],
            },
            "with_lcm": {
                "sampler_name": "lcm",
                "scheduler": "sgm_uniform",
                "steps": [4, 8],
                "cfg_milli": [1000, 1000],
            },
        },
        "limits": (
            "Pinned SDXL base and LCM bytes, plus technically validated ITOV UNet exports. "
            "Compatibility permits experiments; it does not establish stack quality, "
            "candidate acceptance, promotion or Diffusers/ComfyUI parity."
        ),
    }


def asset(value, label):
    object_fields(value, {"loader_name", "sha256"}, label)
    relative_path(value["loader_name"], label + ".loader_name")
    require(value["loader_name"].endswith(".safetensors"), "Expected safetensors loader name")
    digest(value["sha256"], label + ".sha256")


def validate_spec(value):
    if isinstance(value, dict) and value.get("version") == 3:
        from itov.flux_image import validate_spec as validate_flux

        return validate_flux(value)
    object_fields(
        value,
        {
            "version",
            "capability",
            "checkpoint",
            "adapters",
            "sampler",
            "prompt",
            "negative_prompt",
            "width",
            "height",
            "seed",
            "count",
        },
        "inference v2 specification",
    )
    require(
        type(value["version"]) is int and value["version"] == 2, "Unsupported inference version"
    )
    require(value["capability"] == CAPABILITY, "Unsupported model capability")
    asset(value["checkpoint"], "checkpoint")
    require(
        value["checkpoint"]["sha256"] == CHECKPOINT,
        "Checkpoint is outside the pinned SDXL capability",
    )
    image_contract({key: value[key] for key in ("width", "height")})
    for key in ("prompt", "negative_prompt"):
        text(value[key], key, empty=key == "negative_prompt")
        require(
            len(value[key]) <= 4096 and "embedding:" not in value[key].lower(),
            "Prompts must be at most 4096 characters without external embeddings",
        )
    integer(value["seed"], "seed")
    integer(value["count"], "count", minimum=1)
    require(
        value["count"] <= 16 and value["seed"] + value["count"] - 1 <= MAX_INTEGER,
        "Inference requires 1..16 consecutive uint64 seeds",
    )
    adapters = array(value["adapters"], "adapters")
    require(len(adapters) <= 2, "At most one LCM and one trained candidate are supported")
    kinds = []
    for adapter in adapters:
        require(isinstance(adapter, dict), "Adapter must be an object")
        kind = adapter.get("kind")
        require(kind in ("lcm", "trained_candidate"), "Unsupported adapter capability")
        kinds.append(kind)
        common = {"kind", "sha256", "strength_milli"}
        object_fields(
            adapter,
            common | ({"loader_name"} if kind == "lcm" else {"training_plan", "candidate_id"}),
            "adapter",
        )
        digest(adapter["sha256"], "adapter hash")
        integer(adapter["strength_milli"], "adapter strength", minimum=1)
        require(adapter["strength_milli"] <= 1000, "Adapter strength must be 1..1000 milli")
        if kind == "lcm":
            asset({key: adapter[key] for key in ("loader_name", "sha256")}, "LCM")
            require(
                adapter["sha256"] == LCM and adapter["strength_milli"] == 1000,
                "LCM capability requires the pinned SDXL adapter at strength 1000",
            )
        else:
            digest(adapter["candidate_id"], "candidate id")
            ref = adapter["training_plan"]
            object_fields(ref, {"path", "sha256"}, "training plan reference")
            relative_path(ref["path"], "training plan path")
            digest(ref["sha256"], "training plan hash")
    require(
        kinds in ([], ["lcm"], ["trained_candidate"], ["lcm", "trained_candidate"]),
        "Adapters must be unique and ordered LCM then trained candidate",
    )
    sampler = value["sampler"]
    object_fields(sampler, {"steps", "cfg_milli", "sampler_name", "scheduler"}, "sampler")
    contract = capabilities()["samplers"]["with_lcm" if "lcm" in kinds else "without_lcm"]
    for key in ("steps", "cfg_milli"):
        integer(sampler[key], key, minimum=contract[key][0])
        require(sampler[key] <= contract[key][1], "Sampler budget is incompatible with stack")
    require(
        all(sampler[key] == contract[key] for key in ("sampler_name", "scheduler")),
        "Sampler/scheduler is incompatible with adapter stack",
    )
    return parse_json(canonical_bytes(value))
