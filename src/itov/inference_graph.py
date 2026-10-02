"""Pure graph construction from validated capability and resolved adapter bindings."""

from itov.catalog import canonical_bytes, require, sha256
from itov.inference_capabilities import validate_spec
from itov.qualification import json_text

SCOPE = "capability_inference_plan"


def definition(spec, deployment):
    spec = validate_spec(spec)
    if spec["version"] == 3:
        from itov.flux_image import definition as flux_definition

        return flux_definition(spec, deployment)
    require(deployment["specification"] == spec, "Deployment specification differs")
    spec_id = sha256(canonical_bytes(spec))
    image = {key: spec[key] for key in ("width", "height")}
    adapters = deployment["adapters"]
    require(len(adapters) == len(spec["adapters"]), "Deployment adapter coverage differs")
    jobs = []
    for index in range(spec["count"]):
        graph = {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": spec["checkpoint"]["loader_name"]},
                "_meta": {"itov_asset_sha256": spec["checkpoint"]["sha256"]},
            },
            "3": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["1", 1], "text": spec["prompt"]},
            },
            "4": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["1", 1], "text": spec["negative_prompt"]},
            },
            "5": {"class_type": "EmptyLatentImage", "inputs": {**image, "batch_size": 1}},
            "6": {
                "class_type": "KSampler",
                "inputs": {
                    "model": [str(9 + len(adapters)), 0] if adapters else ["1", 0],
                    "seed": spec["seed"] + index,
                    "steps": spec["sampler"]["steps"],
                    "cfg": spec["sampler"]["cfg_milli"] / 1000,
                    "sampler_name": spec["sampler"]["sampler_name"],
                    "scheduler": spec["sampler"]["scheduler"],
                    "denoise": 1,
                    "positive": ["3", 0],
                    "negative": ["4", 0],
                    "latent_image": ["5", 0],
                },
            },
            "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["1", 2]}},
            "8": {
                "class_type": "SaveImage",
                "inputs": {
                    "images": ["7", 0],
                    "filename_prefix": f"itov/inference/{spec_id}/{index:03d}",
                },
                "_meta": {"itov_image": image},
            },
        }
        for position, (adapter, declared) in enumerate(
            zip(adapters, spec["adapters"], strict=True)
        ):
            require(
                adapter["kind"] == declared["kind"]
                and adapter["asset"]["sha256"] == declared["sha256"]
                and adapter["strength_milli"] == declared["strength_milli"],
                "Deployment adapter identity/strength differs",
            )
            graph[str(10 + position)] = {
                "class_type": "LoraLoaderModelOnly",
                "inputs": {
                    "model": [str(9 + position), 0] if position else ["1", 0],
                    "lora_name": adapter["loader_name"],
                    "strength_model": adapter["strength_milli"] / 1000,
                },
                "_meta": {"itov_asset_sha256": adapter["asset"]["sha256"]},
            }
        encoded = json_text(graph)
        jobs.append(
            {
                "index": index,
                "preset": "inference",
                "seed": spec["seed"] + index,
                "workflow_json": encoded,
                "workflow_sha256": sha256(encoded.encode()),
                "loras": [{"loader_name": a["loader_name"], "asset": a["asset"]} for a in adapters],
            }
        )
    return {
        "version": 2,
        "scope": SCOPE,
        "specification": spec,
        "deployment": deployment,
        "jobs": jobs,
        "request": {
            "bindings": {
                "inference": {
                    "seed_inputs": [{"node": "6", "class_type": "KSampler", "input": "seed"}]
                }
            }
        },
    }
