"""CPU/HTTP protocol fixtures, not FLUX runtime or model-quality acceptance."""

import copy
import json
import sqlite3
from pathlib import Path

import pytest
from quality_fixtures import curated_inputs as curated_inputs  # noqa: F401
from test_evaluation_runtime import runtime_case as runtime_case  # noqa: F401
from test_training import document
from test_training import training_inputs as training_inputs  # noqa: F401

from itov import flux_image as flux
from itov import inference_runtime as runtime
from itov.catalog import canonical_bytes, sha256
from itov.catalog_store import CatalogStore
from itov.cli import main
from itov.comfyui import ComfyUIClient, ComfyUIError
from itov.image_request import create, specification
from itov.inference import load_spec
from itov.owned_jobs import job_path
from itov.qualification import FLUX_MODULES, qualify_graphs
from itov.training_data import seal


@pytest.fixture
def flux_case(runtime_case, monkeypatch):
    item = runtime_case
    assets = copy.deepcopy(flux.ASSETS)
    for key, asset in assets.items():
        raw = (key + " protocol fixture; not model weights").encode()
        asset.update(sha256=sha256(raw), bytes=len(raw))
        path = item.config.comfyui_root / "models" / asset["folder"] / asset["loader_name"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    monkeypatch.setattr(flux, "ASSETS", assets)
    for name in (
        *flux.RUNTIME_SOURCES,
        "comfy_extras/nodes_flux.py",
        "comfy_extras/nodes_custom_sampler.py",
    ):
        path = item.config.comfyui_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(b"Runtime protocol fixture")
    schemas = {
        "UNETLoader": (
            {"unet_name": [[assets["diffusion"]["loader_name"]]], "weight_dtype": [["default"]]},
            ["MODEL"],
        ),
        "CLIPLoader": (
            {
                "clip_name": [[assets["text_encoder"]["loader_name"]]],
                "type": [["flux2"]],
                "device": [["default"]],
            },
            ["CLIP"],
        ),
        "VAELoader": ({"vae_name": [[assets["vae"]["loader_name"]]]}, ["VAE"]),
        "ConditioningZeroOut": ({"conditioning": ["CONDITIONING"]}, ["CONDITIONING"]),
        "EmptyFlux2LatentImage": (
            {"width": ["INT"], "height": ["INT"], "batch_size": ["INT"]},
            ["LATENT"],
        ),
        "RandomNoise": ({"noise_seed": ["INT"]}, ["NOISE"]),
        "Flux2Scheduler": ({"steps": ["INT"], "width": ["INT"], "height": ["INT"]}, ["SIGMAS"]),
        "KSamplerSelect": ({"sampler_name": [["euler"]]}, ["SAMPLER"]),
        "CFGGuider": (
            {
                "model": ["MODEL"],
                "positive": ["CONDITIONING"],
                "negative": ["CONDITIONING"],
                "cfg": ["FLOAT"],
            },
            ["GUIDER"],
        ),
        "SamplerCustomAdvanced": (
            {
                "noise": ["NOISE"],
                "guider": ["GUIDER"],
                "sampler": ["SAMPLER"],
                "sigmas": ["SIGMAS"],
                "latent_image": ["LATENT"],
            },
            ["LATENT", "LATENT"],
        ),
    }
    item.routes["/object_info"][1].update(
        {
            kind: {
                "input": {"required": fields},
                "output": outputs,
                "python_module": FLUX_MODULES.get(kind, "nodes"),
                "output_node": False,
            }
            for kind, (fields, outputs) in schemas.items()
        }
    )
    item.flux = flux.specification(
        "One red cube beside one white cone", width=512, height=512, seed=926100, count=2
    )
    return item


def planned(item):
    runtime.prepare(item.config, item.flux)
    value = runtime.plan(item.config, item.flux, save=True)
    return value, item.config.root / f"state/inference/plans/{value['plan_id']}.json"


def execute(item, path, **kwargs):
    return runtime.run(item.config, path, wait_timeout=0.05, poll_interval=0.005, **kwargs)


def test_flux_draft_save_is_offline_and_preserves_sdxl_defaults(tmp_path, monkeypatch, capsys):
    from itov.config import initialize

    config = initialize(tmp_path / "images", tmp_path / "no models")

    def no_network(*args, **kwargs):
        raise AssertionError("Request drafting must remain offline")

    monkeypatch.setattr("socket.socket.connect", no_network)
    args = [
        "inference",
        "spec",
        "--model",
        flux.MODEL,
        "--prompt",
        "One red cube",
        "--config",
        str(config.file),
        "--json",
    ]
    assert main(args) == 0
    draft = json.loads(capsys.readouterr().out)
    assert not (config.root / "state/inference").exists()
    assert main([*args, "--save"]) == 0
    saved = json.loads(capsys.readouterr().out)
    assert saved["specification"] == draft["specification"] == load_spec(Path(saved["saved_path"]))
    assert saved["specification"]["version"] == 3
    assert saved["specification"]["sampler"] == flux.SAMPLER
    assert (
        create(config, save=True, prompt="One red cube", model=flux.MODEL)["spec_id"]
        == saved["spec_id"]
    )
    assert saved["_cli"]["actions"][0]["argv"][1:3] == ["inference", "prepare"]
    old = specification("One red cube")
    assert (
        old["version"] == 2
        and old["sampler"]["steps"] == 20
        and old["sampler"]["cfg_milli"] == 7000
    )
    assert "models" not in old and old["adapters"] == []
    assert main(["inference", "capabilities", "--model", flux.MODEL, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["capability"] == flux.CAPABILITY
    copy_caps = flux.capabilities()
    copy_caps["models"]["vae"]["sha256"] = "a" * 64
    assert flux.capabilities()["models"]["vae"]["sha256"] != "a" * 64


@pytest.mark.parametrize(
    "settings",
    [
        {"negative_prompt": "watermark"},
        {"steps": 20},
        {"cfg_milli": 7000},
        {"checkpoint": "anything.safetensors"},
        {"width": 513},
        {"seed": 2**64 - 1, "count": 2},
        {"prompt": "embedding:external"},
        {"prompt": ""},
        {"count": 0},
        {"model": "arbitrary"},
    ],
)
def test_unsupported_request_is_refused_before_saving(tmp_path, settings):
    from itov.config import initialize

    config = initialize(tmp_path / "images", tmp_path / "no models")
    with pytest.raises(ValueError):
        create(config, save=True, **{"model": flux.MODEL, "prompt": "A cube", **settings})
    assert not (config.root / "state/inference").exists()


def test_public_flux_pipeline_and_owned_navigation(flux_case, monkeypatch, capsys):
    item = flux_case
    catalog = CatalogStore(item.config.root).snapshot().raw
    spec = document(item.config.root / "flux.json", item.flux)
    args = [str(spec), "--config", str(item.config.file), "--json"]
    before = list(item.requests)
    assert main(["inference", "prepare", *args]) == 0
    prepared = json.loads(capsys.readouterr().out)
    assert (
        prepared["deployment"]["adapters"] == []
        and not prepared["deployment"]["catalog_activation"]
    )
    assert item.requests == before
    assert main(["inference", "plan", *args, "--save"]) == 0
    result = json.loads(capsys.readouterr().out)
    value, path = result["plan"], Path(result["saved_path"])
    assert value["version"] == 3 and value["runtime"]["profile"] == "stock-flux2-klein-inference-v3"
    assert result["_cli"]["actions"][0]["argv"][1:3] == ["inference", "run"]
    assert not item.routes.get("_posted")
    assert execute(item, path)["succeeded"] == 2
    for index, posted in enumerate(item.routes["_posted"]):
        graph = posted["prompt"]
        assert graph["6"]["inputs"]["noise_seed"] == item.flux["seed"] + index
        assert graph["11"]["inputs"] == {"steps": 4, "width": 512, "height": 512}
        assert graph["13"]["inputs"]["noise"] == ["6", 0]
        assert graph["12"]["inputs"]["negative"] == ["4", 0]
        assert graph["4"]["inputs"]["conditioning"] == ["3", 0]
        assert graph["2"]["inputs"]["type"] == "flux2"
    before = list(item.requests)

    def offline(*args, **kwargs):
        raise AssertionError("Completed replay must stay offline")

    monkeypatch.setattr("socket.socket.connect", offline)
    assert execute(item, path, resume=True)["ok"]
    report = runtime.replay(item.config, path, save=True)
    assert report["technical_pass"] and report["quality_acceptance"] == "not_established"
    for artifact in [path, job_path(item.config, value["plan_id"], 0)]:
        assert (
            main(
                ["workspace", "inspect", str(artifact), "--config", str(item.config.file), "--json"]
            )
            == 0
        )
        assert json.loads(capsys.readouterr().out)["ok"]
    assert item.requests == before and CatalogStore(item.config.root).snapshot().raw == catalog
    with sqlite3.connect(item.config.root / "state/batches/execution.sqlite3") as db:
        assert {r[0] for r in db.execute("SELECT seed FROM seeds")} == {"926100", "926101"}


@pytest.mark.parametrize("asset", ["diffusion", "text_encoder", "vae"])
def test_changed_model_refuses_prepare_without_network_or_staging(flux_case, asset):
    item = flux_case
    declared = flux.ASSETS[asset]
    (
        item.config.comfyui_root / "models" / declared["folder"] / declared["loader_name"]
    ).write_bytes(b"changed")
    before = list(item.requests)
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        runtime.prepare(item.config, item.flux)
    assert item.requests == before and not (item.config.root / "state/inference").exists()


@pytest.mark.parametrize("change", ["model", "tokenizer", "module", "schema", "ambiguous_path"])
def test_changed_runtime_or_asset_refuses_submission(flux_case, change):
    item = flux_case
    _, path = planned(item)
    root = item.config.comfyui_root
    if change in ("module", "schema"):
        item.routes["/object_info"][1]["RandomNoise"][
            "python_module" if change == "module" else "description"
        ] = "custom.changed"
    elif change == "ambiguous_path":
        asset = flux.ASSETS["text_encoder"]
        duplicate = root / "models/clip" / asset["loader_name"]
        duplicate.parent.mkdir()
        duplicate.write_bytes((root / "models/text_encoders" / asset["loader_name"]).read_bytes())
    else:
        target = root / (
            "comfy/text_encoders/qwen25_tokenizer/vocab.json"
            if change == "tokenizer"
            else "models/vae/flux2-vae.safetensors"
        )
        target.write_bytes(b"changed")
    with pytest.raises(ValueError):
        execute(item, path)
    assert not item.routes.get("_posted")


@pytest.mark.parametrize("change", ["noise", "scheduler", "decode", "extra_node", "bindings"])
def test_resealed_graph_tampering_refused_by_load_and_qualification(flux_case, change):
    item = flux_case
    value, path = planned(item)
    body = {k: copy.deepcopy(v) for k, v in value.items() if k != "plan_id"}
    if change == "bindings":
        body["request"]["bindings"]["inference"]["seed_inputs"] = []
    else:
        graph = json.loads(body["jobs"][0]["workflow_json"])
        if change == "noise":
            graph["6"]["inputs"]["noise_seed"] += 1
        elif change == "scheduler":
            graph["11"]["inputs"]["width"] = 1024
        elif change == "decode":
            graph["7"]["inputs"]["samples"] = ["5", 0]
        else:
            graph["extra"] = copy.deepcopy(graph["6"])
        encoded = json.dumps(graph)
        body["jobs"][0].update(workflow_json=encoded, workflow_sha256=sha256(encoded.encode()))
    changed = seal(body, "plan_id")
    document(path, changed)
    with pytest.raises(ValueError):
        runtime.load_plan(path)
    with pytest.raises(ValueError):
        qualify_graphs(item.config, changed)
    assert not item.routes.get("_posted")


@pytest.mark.parametrize("proof", ["present", "missing"])
def test_lost_ack_reconciles_without_duplicate_flux_generation(flux_case, monkeypatch, proof):
    item = flux_case
    _, path = planned(item)
    original = ComfyUIClient.submit

    def lose(client, *args):
        original(client, *args)
        raise ComfyUIError("Lost acknowledgement fixture")

    monkeypatch.setattr(ComfyUIClient, "submit", lose)
    assert execute(item, path)["status"] == "paused"
    monkeypatch.setattr(ComfyUIClient, "submit", original)
    if proof == "missing":
        item.routes["/history?max_items=200"][1].clear()
    result = execute(item, path, resume=True)
    assert result["ok"] == (proof == "present")
    assert len(item.routes["_posted"]) == (2 if proof == "present" else 1)


def test_flux_specs_require_exact_assets_and_version():
    spec = flux.specification("A cube")
    for key, bad in [
        ("version", 2),
        ("capability", "other"),
        ("adapters", [{}]),
        ("models", {}),
        ("sampler", {**flux.SAMPLER, "steps": 4.0}),
    ]:
        with pytest.raises(ValueError):
            flux.validate_spec({**spec, key: bad})
    for key in flux.ASSETS:
        wrong = copy.deepcopy(spec)
        wrong["models"][key]["sha256"] = "a" * 64
        with pytest.raises(ValueError):
            flux.validate_spec(wrong)
        wrong["models"][key] = {**spec["models"][key], "loader_name": "../escape.safetensors"}
        with pytest.raises(ValueError):
            flux.validate_spec(wrong)
    assert sha256(canonical_bytes(spec)) != sha256(canonical_bytes(specification("A cube")))
