import copy
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_batch_execution import execution_case as execution_case
from test_qualification import model_case as model_case

from itov.catalog import MAX_INTEGER, canonical_bytes, load_catalog, sha256
from itov.catalog_store import CatalogStore
from itov.cli import main
from itov.comfyui import submission_matches
from itov.config import initialize
from itov.inference import describe, plan_inference, prepare_inference, validate_spec
from itov.qualification import qualify


@pytest.fixture
def inference_case(tmp_path):
    config = initialize(tmp_path / "workspace", tmp_path / "comfy")
    for folder, name, data in (
        ("checkpoints", "model.safetensors", b"checkpoint fixture"),
        ("loras", "lcm.safetensors", b"lora fixture"),
    ):
        path = config.comfyui_root / "models" / folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    CatalogStore(config.root).initialize()
    spec = {
        "version": 1,
        "profile": "sdxl-base-v1",
        "checkpoint": {"loader_name": "model.safetensors", "sha256": sha256(b"checkpoint fixture")},
        "lora": None,
        "prompt": "A ceramic teapot",
        "negative_prompt": "",
        "width": 1024,
        "height": 1024,
        "seed": 777,
        "count": 2,
    }
    return config, spec


@pytest.mark.parametrize("lcm", [False, True])
def test_prepare_import_plan_is_repeatable_and_does_not_submit(inference_case, lcm, monkeypatch):
    config, spec = inference_case
    if lcm:
        spec.update(
            profile="sdxl-lcm-v1",
            lora={"loader_name": "lcm.safetensors", "sha256": sha256(b"lora fixture")},
        )

    def no_http(*args, **kwargs):
        raise AssertionError("Inference preparation attempted runtime access")

    monkeypatch.setattr("itov.comfyui.ComfyUIClient.__init__", no_http)
    store = CatalogStore(config.root)
    original = store.snapshot()
    result = prepare_inference(config, spec)
    assert store.snapshot().raw == original.raw
    assert prepare_inference(config, spec) == result
    assert not (config.root / "state/jobs").exists()
    assert not (config.root / "state/batches").exists()
    with pytest.raises(ValueError, match="Import"):
        plan_inference(config, spec)
    snapshot = store.import_catalog(
        load_catalog(Path(result["catalog"])), expected_head=result["expected_head"]
    )
    plan = plan_inference(config, spec)
    assert [job["seed"] for job in plan["jobs"]] == [777, 778]
    assert plan == plan_inference(config, spec)
    assert store.snapshot().head == snapshot.head
    for job in plan["jobs"]:
        graph = json.loads(job["workflow_json"])
        assert graph["1"]["_meta"]["itov_asset_sha256"] == spec["checkpoint"]["sha256"]
        assert graph["6"]["inputs"]["seed"] == job["seed"]
        assert graph["5"]["inputs"]["batch_size"] == 1
        if lcm:
            assert graph["2"]["class_type"] == "LoraLoaderModelOnly"
            assert graph["6"]["inputs"]["steps"] == 4
            assert graph["6"]["inputs"]["sampler_name"] == "lcm"
            assert graph["6"]["inputs"]["scheduler"] == "sgm_uniform"
            assert graph["2"]["inputs"]["strength_model"] == 1.0
            assert (config.root / job["loras"][0]["asset"]["path"]).read_bytes() == b"lora fixture"
        else:
            assert not job["loras"] and "2" not in graph
            assert graph["6"]["inputs"]["steps"] == 20


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", True),
        ("profile", "unknown"),
        ("profile", []),
        ("checkpoint", None),
        ("seed", MAX_INTEGER),
        ("seed", True),
        ("count", 0),
        ("count", 17),
        ("count", 1.5),
        ("width", 511),
        ("height", 1088),
        ("height", 1000),
        ("prompt", ""),
        ("prompt", "embedding:untracked"),
        ("negative_prompt", "x" * 4097),
    ],
)
def test_invalid_specification_fails_before_writes(inference_case, field, value):
    config, spec = inference_case
    spec[field] = value
    with pytest.raises(ValueError):
        prepare_inference(config, spec)
    assert not (config.root / "workflows/inference").exists()


@pytest.mark.parametrize("name", ["../outside.safetensors", "C:/x.safetensors", "model.ckpt"])
def test_unsafe_or_unsupported_model_names(inference_case, name):
    _, spec = inference_case
    spec["checkpoint"]["loader_name"] = name
    with pytest.raises(ValueError):
        validate_spec(spec)


def test_pinned_assets_and_prepared_files_cannot_be_silently_replaced(inference_case):
    config, spec = inference_case
    result = prepare_inference(config, spec)
    Path(result["workflow"]).write_bytes(b"preserve conflicting workflow")
    with pytest.raises(ValueError, match="differs"):
        prepare_inference(config, spec)
    assert Path(result["workflow"]).read_bytes() == b"preserve conflicting workflow"
    (config.comfyui_root / "models/checkpoints/model.safetensors").write_bytes(b"different")
    with pytest.raises(ValueError, match="Pinned checkpoint"):
        prepare_inference(config, spec)


def test_existing_catalog_entries_are_preserved(inference_case):
    config, spec = inference_case
    first = prepare_inference(config, spec)
    store = CatalogStore(config.root)
    before = store.import_catalog(
        load_catalog(Path(first["catalog"])), expected_head=first["expected_head"]
    )
    other = copy.deepcopy(spec)
    other["seed"] += 20
    candidate = prepare_inference(config, other)
    assert store.snapshot().raw == before.raw
    assert len(load_catalog(Path(candidate["catalog"]))["presets"]) == 2
    assert (
        before.to_dict()["catalog"]["presets"][0]
        in load_catalog(Path(candidate["catalog"]))["presets"]
    )


def test_checkpoint_pin_is_enforced_during_live_qualification(model_case):
    config, plan, _ = model_case
    store = CatalogStore(config.root)
    catalog = store.snapshot().to_dict()["catalog"]
    path = config.root / "workflows/copy.json"
    graph = json.loads(path.read_bytes())
    graph["1"]["_meta"] = {"itov_asset_sha256": sha256(b"incorrect expected bytes")}
    raw = json.dumps(graph).encode()
    path.write_bytes(raw)
    catalog["presets"][0]["workflow"]["sha256"] = sha256(raw)
    current = store.import_catalog(catalog, expected_head=plan["catalog_head"])
    from itov.batch import create_plan

    plan["request"]["catalog_head"] = current.head
    pinned = create_plan(config.root, plan["request"])
    with pytest.raises(ValueError, match="Pinned checkpoint"):
        qualify(config, pinned)


def test_inference_cli(inference_case, capsys):
    config, spec = inference_case
    source = config.root / "inference.json"
    source.write_bytes(canonical_bytes(spec))
    args = [str(source), "--config", str(config.file), "--json"]
    assert main(["inference", "prepare", *args]) == 0
    prepared = json.loads(capsys.readouterr().out)
    CatalogStore(config.root).import_catalog(
        load_catalog(Path(prepared["catalog"])), expected_head=prepared["expected_head"]
    )
    assert main(["inference", "plan", *args, "--save"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert Path(result["path"]).is_file() and len(result["plan"]["jobs"]) == 2


def test_example_specs_are_valid_and_have_disjoint_seeds():
    from itov.inference import load_spec

    specs = [
        load_spec(Path("examples") / name)
        for name in ("sdxl-base.inference.json", "sdxl-lcm.inference.json")
    ]
    assert len({spec["seed"] + i for spec in specs for i in range(spec["count"])}) == 4
    assert all(describe(spec)["workflow"] for spec in specs)


@pytest.mark.parametrize(
    ("before", "after", "matches"),
    [
        (7, 7.0, True),
        (1, 1.0, True),
        (7.0, 7, True),
        (7, 7.01, False),
        (1, True, False),
        (0, False, False),
        (2**64 - 1, float(2**64 - 1), False),
        (["1", 0], ["1", 0.0], False),
        ("1", 1, False),
    ],
)
def test_submission_numeric_normalization_is_lossless_and_scalar(before, after, matches):
    expected = {"1": {"class_type": "KSampler", "inputs": {"cfg": before}}}
    actual = {"1": {"class_type": "KSampler", "inputs": {"cfg": after}}}
    assert submission_matches(expected, actual) is matches


def test_submission_normalization_keeps_identity_and_metadata_exact():
    expected = {"1": {"class_type": "KSampler", "inputs": {"cfg": 7}, "_meta": {"x": 1}}}
    actual = copy.deepcopy(expected)
    actual["1"]["_meta"]["x"] = 1.0
    assert not submission_matches(expected, actual)
    actual = copy.deepcopy(expected)
    actual["1"]["class_type"] = "OtherSampler"
    assert not submission_matches(expected, actual)


@pytest.fixture
def downloader():
    path = Path("scripts/fetch_inference_baseline.py")
    spec = importlib.util.spec_from_file_location("fetch_baseline", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "data,free_bytes",
    [
        (b"expected", 1024**3 + 8),
        (b"wrong", 1024**3 + 8),
        (b"too much content", 1024**3 + 8),
        (b"expected", 1024**3 + 7),
    ],
)
def test_download_publishes_only_exact_hash_and_length(
    tmp_path, downloader, monkeypatch, data, free_bytes
):
    asset = {
        "id": "fixture",
        "destination": "models/checkpoints/fixture.safetensors",
        "repository": "example/fixture",
        "revision": "a" * 40,
        "source_file": "fixture.safetensors",
        "bytes": 8,
        "sha256": sha256(b"expected"),
    }
    monkeypatch.setattr(downloader.shutil, "disk_usage", lambda _: SimpleNamespace(free=free_bytes))
    requests = []

    class Opener:
        def open(self, url, timeout):
            requests.append(url)
            assert "/resolve/" + "a" * 40 in url and timeout == 30
            return io.BytesIO(data)

    target = tmp_path / asset["destination"]
    if free_bytes < 1024**3 + asset["bytes"]:
        with pytest.raises(ValueError, match="Insufficient disk space"):
            downloader.fetch(tmp_path, asset, opener=Opener())
        assert not requests
        assert not target.exists()
        assert not list(target.parent.glob("*.partial"))
    elif data == b"expected":
        assert (
            downloader.fetch(tmp_path, asset, opener=Opener())["status"]
            == "downloaded_and_verified"
        )
        assert target.read_bytes() == data
        assert downloader.fetch(tmp_path, asset, opener=Opener())["status"] == "verified_existing"
        target.write_bytes(b"preserve")
        with pytest.raises(ValueError, match="refusing overwrite"):
            downloader.fetch(tmp_path, asset, opener=Opener())
        assert target.read_bytes() == b"preserve"
    else:
        with pytest.raises(ValueError):
            downloader.fetch(tmp_path, asset, opener=Opener())
        assert not target.exists()
        assert list(target.parent.glob("*.partial"))
