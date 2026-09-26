"""Installed workflow navigation; protocol fixtures do not qualify trained models."""

import io
import json
import os
import sqlite3
import subprocess
from pathlib import Path

import pytest
from PIL import Image
from quality_fixtures import curated_inputs as curated_inputs
from test_batch_execution import execute, lost_ack, resume
from test_batch_execution import execution_case as execution_case
from test_candidate_lifecycle import candidate as candidate
from test_candidate_lifecycle import decide
from test_deployed_review import reviewed as reviewed
from test_evaluation import completed as completed
from test_evaluation_runtime import runtime_case as runtime_case
from test_inference_runtime import execute as execute_inference
from test_inference_runtime import inference_v2 as inference_v2
from test_inference_runtime import planned as inference_plan
from test_training import training_inputs as training_inputs

from itov import candidate_lifecycle, training_results
from itov import workspace_dependencies as dependencies
from itov import workspace_navigation as navigation
from itov import workspace_starter as starter
from itov.catalog import canonical_bytes
from itov.cli import main, parser
from itov.config import initialize
from itov.owned_jobs import job_path
from itov.training_data import publish, seal
from itov.workspace_guide import TOPICS, guide


@pytest.fixture
def config(tmp_path):
    return initialize(tmp_path / "fresh space", tmp_path / "explicit-runtime")


def invoke(capsys, config, *args, code=0):
    assert main([*map(str, args), "--config", str(config.file), "--json"]) == code
    captured = capsys.readouterr()
    assert not captured.err
    value = json.loads(captured.out)
    assert value["_cli"]["exit_code"] == code
    for action in value["_cli"]["actions"]:
        parser().parse_args(action["argv"][1:])
    return value


def files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("topic", TOPICS)
def test_guides_work_before_configuration_and_every_command_parses(tmp_path, capsys, topic):
    path = tmp_path / "absent space/itov.toml"
    value = guide(path, topic)
    assert isinstance(value["description"], str) and isinstance(value["limits"], str)
    for step in value["steps"]:
        parser().parse_args(step["argv"][1:])
        assert not any("examples/" in arg or "scripts/" in arg for arg in step["argv"])
        assert step["when"]
    assert main(["workspace", "guide", topic, "--config", str(path)]) == 0
    text = capsys.readouterr().out
    for step in value["steps"]:
        assert step["label"] in text
        for need in step["needs"]:
            assert need in text
    assert not path.parent.exists()


def test_starter_is_valid_idempotent_and_leaves_catalog_and_execution_absent(config, capsys):
    result = invoke(capsys, config, "workspace", "starter")
    with Image.open(io.BytesIO((config.root / "input/itov-starter.png").read_bytes())) as image:
        image.load()
        assert image.size == (64, 64) and image.mode == "RGB"
        assert image.getpixel((8, 0)) == (255, 0, 0)
    before = files(config.root)
    assert invoke(capsys, config, "workspace", "starter")["starter_id"] == result["starter_id"]
    assert files(config.root) == before
    assert not (config.root / "state/catalog").exists()
    assert not (config.root / "state/batches").exists()


def test_changed_starter_file_refuses_before_publishing_other_inputs(config):
    path = config.root / "workflows/itov-starter.api.json"
    path.write_bytes(b"operator change")
    with pytest.raises(ValueError, match="Preserve changed"):
        starter.starter(config)
    assert path.read_bytes() == b"operator change"
    assert not (config.root / "input/itov-starter.png").exists()
    assert not (config.root / "state/workspace/starters").exists()


def test_interrupted_starter_can_resume_without_overwriting(config, monkeypatch):
    original = starter._atomic_write

    def interrupted(path, *args, **kwargs):
        if path.suffix == ".json":
            raise OSError("fixture interruption")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(starter, "_atomic_write", interrupted)
    with pytest.raises(OSError, match="interruption"):
        starter.starter(config)
    image = (config.root / "input/itov-starter.png").read_bytes()
    assert not (config.root / "state/workspace/starters").exists()
    monkeypatch.setattr(starter, "_atomic_write", original)
    assert starter.starter(config)["ok"]
    assert (config.root / "input/itov-starter.png").read_bytes() == image


def test_fresh_catalog_request_plan_and_offline_inspection(config, capsys):
    invoke(capsys, config, "workspace", "starter")
    initial = invoke(capsys, config, "catalog", "init")
    invoke(
        capsys,
        config,
        "catalog",
        "import",
        config.root / "templates/itov-starter.catalog.json",
        "--expected-head",
        initial["head"],
    )
    request = invoke(capsys, config, "workspace", "request", "itov-starter", "--count", 2, "--save")
    raw = Path(request["saved_path"]).read_bytes()
    assert "_cli" not in json.loads(raw)
    plan = invoke(capsys, config, "batch", "plan", request["saved_path"], "--save")
    before = files(config.root)
    inspected = invoke(capsys, config, "workspace", "inspect", plan["path"])
    assert inspected["recorded_status"] == "not_started"
    status = invoke(capsys, config, "workspace", "status")
    assert status["total"] == 1 and status["entries"][0]["kind"] == "batch"
    assert files(config.root) == before
    (config.root / "workflows/itov-starter.api.json").write_bytes(b"changed")
    invoke(capsys, config, "workspace", "request", "itov-starter", "--save", code=2)
    assert Path(request["saved_path"]).read_bytes() == raw


def test_empty_inventory_is_read_only(config, capsys):
    before = files(config.root)
    value = invoke(capsys, config, "workspace", "status")
    assert value["total"] == 0 and value["catalog"]["status"] == "not_initialized"
    assert files(config.root) == before
    assert not list((config.root / "state").iterdir())


def test_owned_job_guidance_resumes_lost_ack_without_duplicate(execution_case, monkeypatch, capsys):
    config, plan, path, _, routes, requests = execution_case
    lost_ack(monkeypatch)
    assert execute(execution_case)["status"] == "paused"
    before, network = files(config.root), list(requests)
    inspected = invoke(capsys, config, "workspace", "inspect", job_path(config, plan["plan_id"], 0))
    assert inspected["related"]["owner"]["path"] == str(path)
    assert any(a["argv"][1:3] == ["batch", "resume"] for a in inspected["actions"])
    assert not any(a["argv"][1:3] == ["job", "wait"] for a in inspected["actions"])
    assert navigation.inspect(config, path)["recorded_status"] == "paused"
    assert files(config.root) == before and requests == network
    assert resume(execution_case)["succeeded"] == 3
    assert len(routes["_posted"]) == 3
    assert navigation.inspect(config, path)["recorded_status"] == "succeeded"
    assert resume(execution_case)["succeeded"] == 3 and len(routes["_posted"]) == 3


def test_missing_owner_never_suggests_standalone_wait(execution_case, capsys):
    config, plan, path, _, _, _ = execution_case
    assert execute(execution_case)["status"] == "succeeded"
    path.rename(path.with_suffix(".retained"))
    result = invoke(
        capsys, config, "workspace", "inspect", job_path(config, plan["plan_id"], 0), code=2
    )
    assert "owner plan is missing" in result["error"]
    assert not any(a["argv"][1:3] == ["job", "wait"] for a in result["_cli"]["actions"])


def test_version_two_inference_plan_and_job_keep_the_inference_owner(inference_v2, capsys):
    item = inference_v2
    plan, path = inference_plan(item)
    assert plan["version"] == 2
    pending = invoke(capsys, item.config, "workspace", "inspect", path)
    assert pending["recorded_status"] == "not_started"
    assert execute_inference(item, path)["status"] == "succeeded"
    before, network = files(item.config.root), list(item.requests)
    for artifact in (path, job_path(item.config, plan["plan_id"], 0)):
        value = invoke(capsys, item.config, "workspace", "inspect", artifact)
        assert any(a["argv"][1:3] == ["inference", "resume"] for a in value["actions"])
        assert not any(a["argv"][1:3] == ["job", "wait"] for a in value["actions"])
    assert files(item.config.root) == before and item.requests == network


def test_missing_execution_database_is_not_reported_as_unstarted(execution_case):
    config, _, path, _, _, _ = execution_case
    assert execute(execution_case)["status"] == "succeeded"
    db = config.root / "state/batches/execution.sqlite3"
    db.rename(db.with_suffix(".retained"))
    with pytest.raises(ValueError, match="database is missing"):
        navigation.inspect(config, path)
    assert not db.exists()


@pytest.mark.parametrize("state,action", [("succeeded", "resume"), ("paused", "recover")])
def test_managed_parallel_plan_routes_to_worker_owner(execution_case, state, action, capsys):
    config, plan, path, _, _, _ = execution_case
    assert execute(execution_case)["status"] == "succeeded"
    # A recorded owner fixture, not a real parallel runtime qualification.
    with sqlite3.connect(config.root / "state/batches/execution.sqlite3") as db:
        db.execute(
            "UPDATE runs SET status=?, qualification=? WHERE plan_id=?",
            (state, canonical_bytes({"scope": "managed_two_worker_audio"}), plan["plan_id"]),
        )
    value = invoke(capsys, config, "workspace", "inspect", path)
    actions = [a["argv"][1:3] for a in value["actions"]]
    assert ["parallel", action] in actions and ["batch", "resume"] not in actions


def test_parallel_job_uses_its_recorded_worker_server(execution_case, capsys):
    config, plan, _, _, _, _ = execution_case
    assert execute(execution_case)["status"] == "succeeded"
    with sqlite3.connect(config.root / "state/batches/execution.sqlite3") as db:
        db.execute(
            "UPDATE runs SET qualification=?",
            (
                canonical_bytes(
                    {
                        "scope": "managed_two_worker_audio",
                        "ports": [8191, 8192],
                        "mode": "calibrate",
                    }
                ),
            ),
        )
    path = job_path(config, plan["plan_id"], 0)
    value = json.loads(path.read_bytes())
    value["server"] = "http://127.0.0.1:8191"
    path.write_bytes(canonical_bytes(value))
    result = invoke(capsys, config, "workspace", "inspect", path)
    assert result["related"]["owner"]["executor"] == "parallel"
    assert any(a["argv"][1:3] == ["parallel", "resume"] for a in result["actions"])
    with sqlite3.connect(config.root / "state/batches/execution.sqlite3") as db:
        db.execute(
            "UPDATE runs SET qualification=?",
            (
                canonical_bytes(
                    {"scope": "managed_two_worker_audio", "ports": [8191, 8192], "mode": "corrupt"}
                ),
            ),
        )
    bad = invoke(capsys, config, "workspace", "inspect", path, code=2)
    assert "Invalid recorded parallel assignment" in bad["error"]
    with sqlite3.connect(config.root / "state/batches/execution.sqlite3") as db:
        db.execute(
            "UPDATE runs SET qualification=?",
            (
                canonical_bytes(
                    {
                        "scope": "managed_two_worker_audio",
                        "ports": [8191, 8192],
                        "mode": "calibrate",
                    }
                ),
            ),
        )
    value["server"] = "http://127.0.0.1:8999"
    path.write_bytes(canonical_bytes(value))
    invoke(capsys, config, "workspace", "inspect", path, code=2)


@pytest.mark.parametrize("damage", ["seal", "version", "family", "database"])
def test_corrupt_inventory_has_explicit_failures(execution_case, damage):
    config, _, path, _, _, _ = execution_case
    value = json.loads(path.read_bytes())
    if damage == "database":
        assert execute(execution_case)["status"] == "succeeded"
        with sqlite3.connect(config.root / "state/batches/execution.sqlite3") as db:
            db.execute("UPDATE runs SET plan=?", (b"{}",))
    else:
        if damage == "seal":
            value["limits"] = "changed without resealing"
        elif damage == "version":
            value = seal({**value, "version": 999}, "plan_id")
        else:
            value = seal(
                {"version": 1, "scope": "workspace_dependencies", "ok": True}, "diagnostic_id"
            )
        path.write_bytes(canonical_bytes(value))
    before = files(config.root)
    result = navigation.status(config, kind="batch")
    assert not result["ok"] and result["entries"][0]["recorded_status"] == "invalid"
    assert result["issues"] and files(config.root) == before


def test_inspection_rejects_paths_outside_workspace(config, tmp_path):
    path = tmp_path / "outside.json"
    path.write_bytes(b"{}")
    with pytest.raises(ValueError, match="inside this workspace"):
        navigation.inspect(config, path)


@pytest.mark.parametrize("folder", ["state/jobs", "input"])
def test_redirected_inventory_or_starter_path_is_refused(config, tmp_path, folder):
    target = tmp_path / "outside"
    target.mkdir()
    (target / "keep.txt").write_bytes(b"preserve")
    path = config.root / folder
    if path.exists():
        path.rmdir()
    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(path), str(target)], capture_output=True
        )
        assert result.returncode == 0, result.stderr
    else:
        path.symlink_to(target, target_is_directory=True)
    try:
        if folder == "input":
            with pytest.raises(ValueError, match="redirects"):
                starter.starter(config)
        else:
            value = navigation.status(config)
            assert not value["ok"] and "redirects" in value["issues"][0]["detail"]
        assert files(target) == {"keep.txt": b"preserve"}
    finally:
        path.rmdir() if os.name == "nt" else path.unlink()


def test_training_inspection_reports_record_only_and_routes_to_real_validation(
    completed, monkeypatch, capsys
):
    item = completed
    (item.folder / "weights.safetensors").write_bytes(b"damaged")

    def unexpected(*args, **kwargs):
        pytest.fail("Shallow inventory must not decode model evidence")

    monkeypatch.setattr(training_results, "validate", unexpected)
    before = files(item.config.root)
    result = invoke(capsys, item.config, "workspace", "inspect", item.plan_path)
    assert result["recorded_status"] == "succeeded"
    assert result["integrity"] == "content_seal" and "not revalidated" in result["limits"]
    assert [a["argv"][1:3] for a in result["actions"]] == [
        ["training", "status"],
        ["evaluation", "assess"],
        ["training", "candidate"],
    ]
    assert files(item.config.root) == before


def test_rejected_decision_and_refused_preview_never_suggest_apply(candidate, capsys):
    decide(candidate, "fail")
    config = candidate.config
    preview = candidate_lifecycle.preview(config, candidate.path, 500, save=True)
    before = candidate.store.snapshot().head
    for path in (candidate.path, Path(preview["saved_path"])):
        value = invoke(capsys, config, "workspace", "inspect", path)
        assert not any(a["argv"][1:3] == ["candidate", "apply"] for a in value["actions"])
    assert value["recorded_status"] == "refused_preview"
    assert candidate.store.snapshot().head == before


@pytest.mark.parametrize(
    "body",
    [
        [],
        {},
        {"version": True},
        {"version": 1, "scope": []},
        {"version": 1, "request_id": [], "workflow": {}},
    ],
)
def test_malformed_artifacts_return_diagnostics(config, capsys, body):
    path = config.root / "bad.json"
    path.write_bytes(canonical_bytes(body))
    invoke(capsys, config, "workspace", "inspect", path, code=2)


def test_inventory_preserves_corrupt_rows_and_paginates(config, capsys):
    folder = config.root / "state/workspace/diagnostics"
    for n in range(3):
        value = seal(
            {"version": 1, "scope": "workspace_dependencies", "ok": bool(n), "n": n},
            "diagnostic_id",
        )
        publish(folder / f"{n}.json", value)
    (folder / "1.json").write_bytes(b"broken JSON")
    before = files(config.root)
    result = invoke(
        capsys, config, "workspace", "status", "--kind", "diagnostics", "--limit", 2, code=1
    )
    assert result["total"] == 3 and result["more"]
    assert [r["recorded_status"] for r in result["entries"]] == ["failed_metadata", "invalid"]
    assert result["issues"] and result["actions"][-1]["label"] == "Next inventory page"
    result = invoke(
        capsys, config, "workspace", "status", "--kind", "diagnostics", "--limit", 2, "--offset", 2
    )
    assert len(result["entries"]) == 1 and not result["more"]
    assert files(config.root) == before


def test_inventory_directory_bound_is_reported_not_silently_truncated(config, monkeypatch):
    folder = config.root / "state/jobs"
    folder.mkdir()
    for n in range(3):
        (folder / f"{n}.json").write_bytes(b"{}")
    monkeypatch.setattr(navigation, "LIMIT", 2)
    result = navigation.status(config)
    assert not result["ok"] and "exceeds 2 entries" in result["issues"][0]["detail"]


def test_import_inventory_ignores_lock_files_and_sorts_full_paths(config):
    folder = config.root / "state/dataset-imports"
    folder.mkdir()
    (folder / "import.lock").write_bytes(b"")
    for name in ("z", "a"):
        value = seal({"version": 1, "declaration": {}, "name": name}, "import_id")
        publish(folder / name / "operation.json", value)
    result = navigation.status(config, kind="imports", limit=1)
    assert result["ok"] and result["total"] == 2
    assert Path(result["entries"][0]["path"]).parent.name == "a"


def test_missing_optional_interpreter_is_retained(config, capsys):
    result = invoke(
        capsys,
        config,
        "workspace",
        "dependencies",
        "training",
        "--python",
        config.root / "absent-python.exe",
        "--save",
        code=1,
    )
    raw = Path(result["saved_path"]).read_bytes()
    assert result["checks"][0]["name"] == "interpreter" and not result["ok"]
    assert "_cli" not in json.loads(raw)
    assert (
        navigation.inspect(config, Path(result["saved_path"]))["recorded_status"]
        == "failed_metadata"
    )
    assert Path(result["saved_path"]).read_bytes() == raw


@pytest.mark.parametrize("version,ok", [(None, False), ("0.0.0", False), ("12.3.0", True)])
def test_metadata_probe_is_isolated_and_checks_pins(config, monkeypatch, version, ok):
    def probe(argv, **kwargs):
        assert argv[1:3] == ["-I", "-c"]
        assert "import torch" not in argv[3] and "import PIL" not in argv[3]
        assert kwargs["timeout"] == 30
        return subprocess.CompletedProcess(
            argv, 0, canonical_bytes({"python": "fixture", "packages": {"Pillow": version}}), b""
        )

    monkeypatch.setattr(dependencies.subprocess, "run", probe)
    result = dependencies.diagnose(config, "dataset")
    assert result["ok"] is ok
    assert result["checks"][0]["status"] == ("pass" if ok else "fail")


def test_invalid_probe_output_is_a_saved_failure(config, monkeypatch):
    monkeypatch.setattr(
        dependencies.subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess([], 0, b"[]", b""),
    )
    result = dependencies.diagnose(config, "dataset", save=True)
    assert not result["ok"] and "invalid package metadata" in result["checks"][0]["detail"]
    assert Path(result["saved_path"]).is_file()
