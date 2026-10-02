"""Pinned FLUX.2 Klein 4B FP8 text-to-image contract; GPU quality remains unqualified."""

from itov.catalog import MAX_INTEGER, canonical_bytes, integer, object_fields, require, sha256, text
from itov.comfyui import parse_json
from itov.image_media import image_contract
from itov.inference_capabilities import asset
from itov.qualification import _file, json_text, model_path
from itov.training_data import seal

MODEL = "flux2-klein-4b-fp8"
CAPABILITY = "flux2-klein-4b-fp8-v1"
SAMPLER = {"steps": 4, "cfg_milli": 1000, "sampler_name": "euler", "scheduler": "flux2"}
ASSETS = {
    "diffusion": {
        "loader_name": "flux-2-klein-4b-fp8.safetensors",
        "sha256": "97ed34fe0567e436200f2faee3939b88f2b5d99f8af2a4dc16532c4245c0ccb6",
        "bytes": 4070624520,
        "repository": "black-forest-labs/FLUX.2-klein-4b-fp8",
        "revision": "5b4408e59397a4a37ccb46afe426d8ed86379441",
        "file": "flux-2-klein-4b-fp8.safetensors",
        "loader": "UNETLoader",
        "folder": "diffusion_models",
    },
    "text_encoder": {
        "loader_name": "qwen_3_4b.safetensors",
        "sha256": "6c671498573ac2f7a5501502ccce8d2b08ea6ca2f661c458e708f36b36edfc5a",
        "bytes": 8044982048,
        "repository": "Comfy-Org/z_image_turbo",
        "revision": "6fc90a3b1b653e935a0d175e260736de25b84df5",
        "file": "split_files/text_encoders/qwen_3_4b.safetensors",
        "loader": "CLIPLoader",
        "folder": "text_encoders",
    },
    "vae": {
        "loader_name": "flux2-vae.safetensors",
        "sha256": "d64f3a68e1cc4f9f4e29b6e0da38a0204fe9a49f2d4053f0ec1fa1ca02f9c4b5",
        "bytes": 336213556,
        "repository": "Comfy-Org/flux2-dev",
        "revision": "ed33133cd56476eac818c0943b6f9419b3e4a3a1",
        "file": "split_files/vae/flux2-vae.safetensors",
        "loader": "VAELoader",
        "folder": "vae",
    },
}
RUNTIME_SOURCES = (
    "execution.py",
    "comfy/sd.py",
    "comfy/model_base.py",
    "comfy/model_detection.py",
    "comfy/supported_models.py",
    "comfy/model_patcher.py",
    "comfy/samplers.py",
    "comfy/sample.py",
    "comfy/k_diffusion/sampling.py",
    "comfy/ldm/flux/model.py",
    "comfy/ldm/flux/layers.py",
    "comfy/ldm/flux/math.py",
    "comfy/ldm/models/autoencoder.py",
    "comfy/ldm/modules/diffusionmodules/model.py",
    "comfy/text_encoders/flux.py",
    "comfy/text_encoders/llama.py",
    "comfy/sd1_clip.py",
    "comfy/text_encoders/qwen25_tokenizer/tokenizer_config.json",
    "comfy/text_encoders/qwen25_tokenizer/vocab.json",
    "comfy/text_encoders/qwen25_tokenizer/merges.txt",
)


def capabilities():
    return parse_json(
        canonical_bytes(
            {
                "ok": True,
                "scope": "inference_capabilities",
                "capability": CAPABILITY,
                "specification_version": 3,
                "models": ASSETS,
                "sampler": SAMPLER,
                "adapters": [],
                "negative_prompt": "empty_only",
                "quality_acceptance": "not_established",
                "limits": "Experimental text-to-image integration. Pinned distilled 4B FP8 only; "
                "no adapter, reference-image editing or training support. Actual GPU execution "
                "and visual quality require separate qualification. No automatic downloads.",
            }
        )
    )


def validate_spec(value):
    object_fields(
        value,
        {
            "version",
            "capability",
            "models",
            "adapters",
            "sampler",
            "prompt",
            "negative_prompt",
            "width",
            "height",
            "seed",
            "count",
        },
        "inference v3 specification",
    )
    require(
        type(value["version"]) is int and value["version"] == 3, "Unsupported inference version"
    )
    require(value["capability"] == CAPABILITY, "Unsupported FLUX capability")
    object_fields(value["models"], set(ASSETS), "FLUX models")
    for key, declared in value["models"].items():
        asset(declared, key)
        require(declared["sha256"] == ASSETS[key]["sha256"], f"Pinned FLUX {key} hash differs")
    require(value["adapters"] == [], "FLUX adapters are not supported")
    require(
        value["sampler"] == SAMPLER,
        "FLUX distilled requires Euler, Flux2 scheduling, 4 steps and CFG 1",
    )
    require(value["negative_prompt"] == "", "FLUX distilled does not support a negative prompt")
    text(value["prompt"], "prompt")
    require(
        len(value["prompt"]) <= 4096 and "embedding:" not in value["prompt"].lower(),
        "Prompts must be at most 4096 characters without external embeddings",
    )
    image_contract({key: value[key] for key in ("width", "height")})
    integer(value["seed"], "seed")
    integer(value["count"], "count", minimum=1)
    require(
        value["count"] <= 16 and value["seed"] + value["count"] - 1 <= MAX_INTEGER,
        "Inference requires 1..16 consecutive uint64 seeds",
    )
    return parse_json(canonical_bytes(value))


def specification(
    prompt, *, negative_prompt="", width=1024, height=1024, seed=0, count=1, steps=4, cfg_milli=1000
):
    return validate_spec(
        {
            "version": 3,
            "capability": CAPABILITY,
            "models": {
                key: {field: row[field] for field in ("loader_name", "sha256")}
                for key, row in ASSETS.items()
            },
            "adapters": [],
            "sampler": {**SAMPLER, "steps": steps, "cfg_milli": cfg_milli},
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "seed": seed,
            "count": count,
        }
    )


def deployment(config, spec):
    spec = validate_spec(spec)
    for key, declared in spec["models"].items():
        path = model_path(config, ASSETS[key]["loader"], declared["loader_name"])
        require(_file(path)["sha256"] == declared["sha256"], f"Pinned FLUX {key} SHA-256 mismatch")
    return seal(
        {
            "version": 1,
            "scope": "inference_deployment",
            "specification": spec,
            "capabilities": capabilities(),
            "adapters": [],
            "quality_acceptance": "not_established",
            "catalog_activation": False,
        },
        "deployment_id",
    )


def graph(spec, index):
    spec = validate_spec(spec)
    integer(index, "image index")
    require(index < spec["count"], "Image index exceeds declared count")
    spec_id = sha256(canonical_bytes(spec))
    size = {key: spec[key] for key in ("width", "height")}
    result = {
        "1": {"class_type": "UNETLoader", "inputs": {"weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"type": "flux2", "device": "default"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": spec["prompt"]}},
        "4": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["3", 0]}},
        "5": {"class_type": "EmptyFlux2LatentImage", "inputs": {**size, "batch_size": 1}},
        "6": {"class_type": "RandomNoise", "inputs": {"noise_seed": spec["seed"] + index}},
        "7": {"class_type": "VAEDecode", "inputs": {"samples": ["13", 0], "vae": ["9", 0]}},
        "8": {
            "class_type": "SaveImage",
            "inputs": {
                "images": ["7", 0],
                "filename_prefix": f"itov/inference/{spec_id}/{index:03d}",
            },
            "_meta": {"itov_image": size},
        },
        "9": {"class_type": "VAELoader", "inputs": {}},
        "10": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "11": {"class_type": "Flux2Scheduler", "inputs": {"steps": 4, **size}},
        "12": {
            "class_type": "CFGGuider",
            "inputs": {"model": ["1", 0], "positive": ["3", 0], "negative": ["4", 0], "cfg": 1},
        },
        "13": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "noise": ["6", 0],
                "guider": ["12", 0],
                "sampler": ["10", 0],
                "sigmas": ["11", 0],
                "latent_image": ["5", 0],
            },
        },
    }
    for key, node, field in [
        ("diffusion", "1", "unet_name"),
        ("text_encoder", "2", "clip_name"),
        ("vae", "9", "vae_name"),
    ]:
        declared = spec["models"][key]
        result[node]["inputs"][field] = declared["loader_name"]
        result[node]["_meta"] = {"itov_asset_sha256": declared["sha256"]}
    return result


def definition(spec, deployed):
    spec = validate_spec(spec)
    require(
        deployed["specification"] == spec and deployed["adapters"] == [], "FLUX deployment differs"
    )
    jobs = []
    for index in range(spec["count"]):
        encoded = json_text(graph(spec, index))
        jobs.append(
            {
                "index": index,
                "preset": "inference",
                "seed": spec["seed"] + index,
                "workflow_json": encoded,
                "workflow_sha256": sha256(encoded.encode()),
                "loras": [],
            }
        )
    return {
        "version": 3,
        "scope": "capability_inference_plan",
        "specification": spec,
        "deployment": deployed,
        "jobs": jobs,
        "request": {
            "bindings": {
                "inference": {
                    "seed_inputs": [
                        {"node": "6", "class_type": "RandomNoise", "input": "noise_seed"}
                    ]
                }
            }
        },
    }


def qualify_definition(plan):
    """Keep new custom sampler nodes confined to this exact capability graph and seeds."""
    require(
        plan.get("version") == 3 and plan.get("scope") == "capability_inference_plan",
        "FLUX nodes require a version-three inference plan",
    )
    expected = definition(plan["specification"], plan["deployment"])
    require(
        all(plan.get(key) == value for key, value in expected.items()),
        "FLUX graph or seed bindings differ from the pinned capability",
    )
