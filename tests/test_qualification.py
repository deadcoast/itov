import json

import pytest
from test_batch_execution import execution_case as execution_case

from itov.batch import create_plan
from itov.catalog import sha256
from itov.catalog_store import CatalogStore
from itov.qualification import qualify


def replace_workflow(case, graph, *, seed=False):
    config, plan, _, _, _, _ = case
    store = CatalogStore(config.root)
    catalog = store.snapshot().to_dict()["catalog"]
    raw = json.dumps(graph).encode()
    (config.root / "workflows/copy.json").write_bytes(raw)
    preset = catalog["presets"][0]
    preset["workflow"]["sha256"] = sha256(raw)
    request = plan["request"]
    if seed:
        preset["seed"] = {"base": 11, "step": 1}
        preset["base_model"] = "fixture"
        catalog["loras"] = [
            {
                "id": "fixture-lora",
                "asset": {"path": "models_shared/lora.bin", "sha256": sha256(b"lora fixture")},
                "category": "style",
                "slot": "style",
                "base_models": ["fixture"],
                "strength_milli": {"min": 500, "recommended": 500, "max": 500},
                "rotation_weight_milli": 1000,
                "trigger_words": [],
                "status": "active",
            }
        ]
        (config.root / "models_shared/lora.bin").write_bytes(b"lora fixture")
        request["lora_policy"].update(
            ids=["fixture-lora"],
            slots=["style"],
            max_strength_milli=1000,
            loader_names={"fixture-lora": "nested/style.safetensors"},
        )
        request["bindings"]["copy"] = {
            "seed_inputs": [{"node": "6", "class_type": "KSampler", "input": "seed"}],
            "lora_slots": [{"slot": "style", "node": "2"}],
        }
    snapshot = store.import_catalog(catalog, expected_head=plan["catalog_head"])
    request["catalog_head"] = snapshot.head
    return create_plan(config.root, request)


@pytest.fixture
def model_case(execution_case):
    config, _, _, _, routes, _ = execution_case
    graph = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "fixture.safetensors"},
        },
        "2": {
            "class_type": "LoraLoader",
            "inputs": {
                "model": ["1", 0],
                "clip": ["1", 1],
                "lora_name": "nested/style.safetensors",
                "strength_model": 0.5,
                "strength_clip": 0.5,
            },
        },
        "3": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 1], "text": "neutral"}},
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 64, "height": 64, "batch_size": 1},
        },
        "6": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["2", 0],
                "seed": 11,
                "positive": ["3", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
            },
        },
        "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["1", 2]}},
        "8": {
            "class_type": "SaveImage",
            "inputs": {"images": ["7", 0], "filename_prefix": "fixture/model"},
        },
    }
    registry = routes["/object_info"][1]
    schemas = {
        "CheckpointLoaderSimple": (
            {"ckpt_name": [["fixture.safetensors"]]},
            ["MODEL", "CLIP", "VAE"],
        ),
        "LoraLoader": (
            {
                "model": ["MODEL"],
                "clip": ["CLIP"],
                "lora_name": [["nested/style.safetensors"]],
                "strength_model": ["FLOAT"],
                "strength_clip": ["FLOAT"],
            },
            ["MODEL", "CLIP"],
        ),
        "CLIPTextEncode": ({"clip": ["CLIP"], "text": ["STRING"]}, ["CONDITIONING"]),
        "EmptyLatentImage": (
            {"width": ["INT"], "height": ["INT"], "batch_size": ["INT"]},
            ["LATENT"],
        ),
        "KSampler": (
            {
                "model": ["MODEL"],
                "seed": ["INT"],
                "positive": ["CONDITIONING"],
                "negative": ["CONDITIONING"],
                "latent_image": ["LATENT"],
            },
            ["LATENT"],
        ),
        "VAEDecode": ({"samples": ["LATENT"], "vae": ["VAE"]}, ["IMAGE"]),
    }
    for kind, (inputs, outputs) in schemas.items():
        registry[kind] = {
            "input": {"required": inputs},
            "output": outputs,
            "output_node": False,
            "python_module": "nodes",
        }
    for name, raw in (
        ("checkpoints/fixture.safetensors", b"checkpoint fixture"),
        ("loras/nested/style.safetensors", b"lora fixture"),
    ):
        path = config.comfyui_root / "models" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    plan = replace_workflow(execution_case, graph, seed=True)
    return config, plan, routes


def test_stock_loader_paths_bind_exact_bytes_and_reserved_seeds(model_case):
    config, plan, _ = model_case
    receipt = qualify(config, plan)
    files = {item["sha256"] for item in receipt["files"]}
    assert {sha256(b"checkpoint fixture"), sha256(b"lora fixture")} <= files
    assert len({job["seed"] for job in plan["jobs"]}) == 3
    # This is a byte/registry fixture test; no checkpoint or LoRA is loaded.


@pytest.mark.parametrize("change", ["wrong_lora", "missing_checkpoint", "registry", "module"])
def test_loader_resolution_fails_closed(model_case, change):
    config, plan, routes = model_case
    if change == "wrong_lora":
        (config.comfyui_root / "models/loras/nested/style.safetensors").write_bytes(b"wrong bytes")
    elif change == "missing_checkpoint":
        (config.comfyui_root / "models/checkpoints/fixture.safetensors").unlink()
    elif change == "registry":
        routes["/object_info"][1]["LoraLoader"]["input"]["required"]["lora_name"] = [[]]
    else:
        routes["/object_info"][1]["LoraLoader"]["python_module"] = "custom"
    with pytest.raises((ValueError, OSError)):
        qualify(config, plan)


@pytest.mark.parametrize("prefix", ["../escape", "C:/absolute", "%date%/dynamic", "CON"])
def test_unsafe_output_prefix_is_not_qualified(execution_case, prefix):
    graph = json.loads(execution_case[1]["jobs"][0]["workflow_json"])
    graph["2"]["inputs"]["filename_prefix"] = prefix
    plan = replace_workflow(execution_case, graph)
    with pytest.raises(ValueError):
        qualify(execution_case[0], plan)


@pytest.mark.parametrize("annotation", [" [output]", "[output]"])
def test_annotated_input_is_not_resolved_as_workspace_input(execution_case, annotation):
    graph = json.loads(execution_case[1]["jobs"][0]["workflow_json"])
    graph["1"]["inputs"]["image"] = "example.png" + annotation
    registry = execution_case[4]["/object_info"][1]
    registry["LoadImage"]["input"]["required"]["image"] = [["example.png" + annotation]]
    plan = replace_workflow(execution_case, graph)
    with pytest.raises(ValueError, match="Annotated"):
        qualify(execution_case[0], plan)


@pytest.mark.parametrize("change", ["embedding", "unbound_seed"])
def test_implicit_assets_and_unreserved_sampler_seed_are_refused(model_case, change):
    config, plan, _ = model_case
    graph = json.loads((config.root / "workflows/copy.json").read_bytes())
    if change == "embedding":
        graph["3"]["inputs"]["text"] = "embedding:untracked"
    else:
        graph["9"] = json.loads(json.dumps(graph["6"]))
        graph["9"]["inputs"]["seed"] = 999
    raw = json.dumps(graph).encode()
    (config.root / "workflows/copy.json").write_bytes(raw)
    store = CatalogStore(config.root)
    catalog = store.snapshot().to_dict()["catalog"]
    catalog["presets"][0]["workflow"]["sha256"] = sha256(raw)
    snapshot = store.import_catalog(catalog, expected_head=plan["catalog_head"])
    plan["request"]["catalog_head"] = snapshot.head
    current = create_plan(config.root, plan["request"])
    with pytest.raises(ValueError, match="embeddings|seed reservation"):
        qualify(config, current)
