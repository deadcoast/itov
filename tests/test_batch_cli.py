import json
import subprocess
import sys

import pytest
from test_batch import planning_case as planning_case

from itov.batch import create_plan
from itov.batch_request import neutral_request
from itov.catalog import canonical_bytes, empty_catalog, sha256
from itov.catalog_store import CatalogStore
from itov.cli import main
from itov.config import initialize


def test_batch_cli_preview_save_verify_and_no_queue(planning_case, capsys, monkeypatch):
    config, _, request, _ = planning_case

    def no_http(*_args, **_kwargs):
        raise AssertionError("Planner attempted HTTP")

    monkeypatch.setattr("itov.comfyui.ComfyUIClient.__init__", no_http)
    source = config.root / "request.json"
    source.write_bytes(canonical_bytes(request))
    flags = ["--config", str(config.file), "--json"]
    assert main(["batch", "plan", str(source), *flags]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["path"] is None and preview["plan"]["scope"] == "planning_only"
    assert main(["batch", "plan", str(source), "--save", *flags]) == 0
    saved = json.loads(capsys.readouterr().out)
    assert preview["plan"] == saved["plan"]
    assert main(["batch", "verify", saved["path"], *flags]) == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified["jobs"] == 8 and verified["plan_id"] == saved["plan"]["plan_id"]
    assert main(["batch", "plan", str(source), "--config", str(config.file)]) == 0
    assert "Planning only" in capsys.readouterr().out
    request["no_repeat_within"] = 2
    source.write_bytes(canonical_bytes(request))
    assert main(["batch", "plan", str(source), "--save", *flags]) == 2
    failure = json.loads(capsys.readouterr().out)
    assert failure["code"] == "rotation_exhausted" and failure["index"] == 2
    assert len(list((config.root / "state/plans").glob("*.json"))) == 1
    assert not (config.root / "state/jobs").exists()


def test_neutral_planning_zero_cooldowns_and_example_helper(tmp_path, capsys):
    config = initialize(tmp_path / "workspace", tmp_path / "comfy")
    graph = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "example.png"}},
        "2": {
            "class_type": "SaveImage",
            "inputs": {"images": ["1", 0], "filename_prefix": "neutral"},
        },
    }
    raw = json.dumps(graph).encode()
    (config.root / "workflows/copy.json").write_bytes(raw)
    catalog = empty_catalog()
    catalog["presets"] = [
        {
            "id": "neutral-copy",
            "category": "neutral",
            "tags": [],
            "workflow": {"path": "workflows/copy.json", "sha256": sha256(raw)},
            "base_model": None,
            "rotation_weight_milli": 1000,
            "seed": None,
        }
    ]
    store = CatalogStore(config.root)
    initial = store.initialize()
    snapshot = store.import_catalog(catalog, expected_head=initial.head)
    result = subprocess.run(
        [sys.executable, "scripts/create_batch_example.py", "--config", str(config.file)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    request = neutral_request(snapshot.head, "neutral-copy")
    assert json.loads((config.root / "templates/neutral.batch.json").read_bytes()) == request
    plan = create_plan(config.root, request)
    assert len(plan["jobs"]) == 4 and all(
        job["seed"] is None and not job["loras"] for job in plan["jobs"]
    )
    assert len({job["workflow_sha256"] for job in plan["jobs"]}) == 1
    assert (
        main(
            [
                "batch",
                "plan",
                str(config.root / "templates/neutral.batch.json"),
                "--config",
                str(config.file),
                "--save",
            ]
        )
        == 0
    )
    assert "Planned 4 jobs" in capsys.readouterr().out
    request["no_repeat_within"] = 1
    with pytest.raises(ValueError, match="No next pick"):
        create_plan(config.root, request)
