import json
from pathlib import Path

import pytest

from itov.cli import main
from itov.config import initialize
from itov.image_request import create
from itov.inference import load_spec
from itov.inference_capabilities import CHECKPOINT
from itov.inference_graph import definition


def test_cli_draft_save_and_connected_base_graph_without_models_or_http(
    tmp_path, monkeypatch, capsys
):
    config = initialize(tmp_path / "image project", tmp_path / "missing runtime")

    def forbidden(*args, **kwargs):
        raise AssertionError("Describing an image must not contact a runtime")

    monkeypatch.setattr("socket.socket.connect", forbidden)
    args = [
        "inference",
        "spec",
        "--prompt",
        "One red teapot on a wooden table",
        "--negative-prompt",
        "text, watermark",
        "--seed",
        "9262026",
        "--count",
        "2",
        "--config",
        str(config.file),
        "--json",
    ]
    assert main(args) == 0
    draft = json.loads(capsys.readouterr().out)
    assert draft["saved_path"] is None
    assert not (config.root / "state/inference").exists()
    assert main([*args, "--save"]) == 0
    saved = json.loads(capsys.readouterr().out)
    path = Path(saved["saved_path"])
    raw = path.read_bytes()
    spec = load_spec(path)
    assert spec == draft["specification"] == saved["specification"]
    assert "_cli" not in spec and spec["version"] == 2 and spec["adapters"] == []
    assert spec["checkpoint"]["sha256"] == CHECKPOINT
    assert spec["width"] == spec["height"] == 1024
    assert saved["quality_acceptance"] == "not_established"
    assert saved["_cli"]["actions"][0]["argv"][1:4] == ["inference", "prepare", str(path)]
    graph_plan = definition(spec, {"specification": spec, "adapters": []})
    for index, job in enumerate(graph_plan["jobs"]):
        graph = json.loads(job["workflow_json"])
        assert graph["3"]["inputs"]["text"] == "One red teapot on a wooden table"
        assert graph["4"]["inputs"]["text"] == "text, watermark"
        assert graph["6"]["inputs"]["model"] == ["1", 0]
        assert graph["6"]["inputs"]["seed"] == 9262026 + index
        assert graph["5"]["inputs"] == {"width": 1024, "height": 1024, "batch_size": 1}
        assert graph["8"]["_meta"]["itov_image"] == {"width": 1024, "height": 1024}
    assert main([*args, "--save"]) == 0
    capsys.readouterr()
    assert path.read_bytes() == raw
    assert not (config.root / "state/batches").exists()
    assert not (config.root / "state/jobs").exists()
    assert not config.comfyui_root.exists()


def test_changed_specification_is_preserved_and_new_prompt_gets_new_file(tmp_path):
    config = initialize(tmp_path / "workspace", tmp_path / "comfy")
    first = create(config, save=True, prompt="A red teapot")
    path = Path(first["saved_path"])
    path.write_text("user edit", encoding="utf-8")
    with pytest.raises(ValueError, match="Existing prepared file differs"):
        create(config, save=True, prompt="A red teapot")
    second = create(config, save=True, prompt="A blue teapot")
    assert second["saved_path"] != str(path)
    assert path.read_text(encoding="utf-8") == "user edit"
    assert load_spec(Path(second["saved_path"]))["prompt"] == "A blue teapot"


@pytest.mark.parametrize(
    "overrides",
    [
        ["--prompt", ""],
        ["--prompt", "embedding:unreviewed"],
        ["--checkpoint", "../outside.safetensors"],
        ["--width", "513"],
        ["--steps", "0"],
        ["--seed", "18446744073709551615", "--count", "2"],
    ],
)
def test_invalid_request_refuses_before_publication(tmp_path, capsys, overrides):
    config = initialize(tmp_path / "workspace", tmp_path / "comfy")
    assert (
        main(
            [
                "inference",
                "spec",
                "--prompt",
                "A teapot",
                *overrides,
                "--save",
                "--config",
                str(config.file),
                "--json",
            ]
        )
        == 2
    )
    result = json.loads(capsys.readouterr().out)
    assert result["_cli"]["outcome"] == "error"
    assert not (config.root / "state/inference").exists()


def test_explicit_dimensions_and_sampler_are_not_overridden(tmp_path):
    config = initialize(tmp_path / "workspace", tmp_path / "comfy")
    result = create(config, prompt="A teapot", width=768, height=1024, steps=30, cfg_milli=5500)
    spec = result["specification"]
    assert (spec["width"], spec["height"]) == (768, 1024)
    assert spec["sampler"]["steps"] == 30 and spec["sampler"]["cfg_milli"] == 5500
