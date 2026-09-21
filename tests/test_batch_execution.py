import copy
import json
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

import pytest

from itov.batch import create_plan, save_plan
from itov.batch_execution import abandon_batch, batch_status, run_batch
from itov.batch_request import neutral_request
from itov.catalog import empty_catalog, sha256
from itov.catalog_store import CatalogStore
from itov.cli import main
from itov.comfyui import ComfyUIClient, ComfyUIError
from itov.config import initialize
from itov.execution_store import claim, open_store, record_run
from itov.owned_jobs import job_path
from itov.qualification import qualify, save_qualification
from itov.runtime import launch_command


@pytest.fixture
def execution_case(tmp_path, http_server, graph, registry):
    url, routes, requests = http_server
    comfy = tmp_path / "comfy"
    comfy.mkdir()
    for name in ("main.py", "nodes.py", "folder_paths.py", "python.exe"):
        (comfy / name).write_bytes(b"runtime protocol fixture, not an executable model")
    config = initialize(tmp_path / "workspace", comfy, python=comfy / "python.exe", url=url)
    (config.root / "input/example.png").write_bytes(b"input fixture")
    for value in registry.values():
        value["python_module"] = "nodes"
    routes["/system_stats"][1]["system"].update(
        argv=launch_command(config)[2:], comfyui_version="fixture"
    )
    raw = json.dumps(graph).encode()
    (config.root / "workflows/copy.json").write_bytes(raw)
    catalog = empty_catalog()
    catalog["presets"] = [
        {
            "id": "copy",
            "category": "neutral",
            "tags": [],
            "workflow": {"path": "workflows/copy.json", "sha256": sha256(raw)},
            "base_model": None,
            "rotation_weight_milli": 1000,
            "seed": None,
        }
    ]
    store = CatalogStore(config.root)
    snapshot = store.import_catalog(catalog, expected_head=store.initialize().head)
    plan = create_plan(config.root, neutral_request(snapshot.head, "copy", count=3))
    path = save_plan(config.root, plan)
    receipt = save_qualification(config, qualify(config, plan))
    history = {}
    routes["/queue"] = (200, {"queue_running": [], "queue_pending": []})
    routes["/history?max_items=200"] = (200, history)

    def submit(payload):
        index = len(routes["_posted"]) - 1
        if index:
            previous = job_path(config, plan["plan_id"], index - 1)
            # Every prior artifact must be durable before the next POST.
            record = json.loads(previous.read_bytes())
            assert record["status"] == "succeeded"
            assert Path(record["artifacts"][0]["path"]).read_bytes() == b"output fixture"
        prompt = f"prompt-{index}"
        record = {
            "prompt": [index, prompt, payload["prompt"], payload["extra_data"], ["2"]],
            "outputs": {
                "2": {
                    "images": [
                        {"filename": f"result-{index}.png", "subfolder": "", "type": "output"}
                    ]
                }
            },
            "status": {"completed": True, "status_str": "success", "messages": []},
        }
        history[prompt] = record
        routes[f"/history/{prompt}"] = (200, {prompt: record})
        routes[f"/view?filename=result-{index}.png&subfolder=&type=output"] = (
            200,
            b"output fixture",
        )
        return {"prompt_id": prompt}

    routes["POST /prompt"] = (200, submit)
    return config, plan, path, receipt, routes, requests


def execute(case, **kwargs):
    config, _, path, receipt, _, _ = case
    return run_batch(
        config, path, qualification=receipt, wait_timeout=0.2, poll_interval=0.01, **kwargs
    )


def resume(case, **kwargs):
    config, _, path, _, _, _ = case
    return run_batch(config, path, resume=True, wait_timeout=0.2, poll_interval=0.01, **kwargs)


def test_sequential_execution_is_owned_and_repeat_is_idempotent(execution_case):
    config, plan, path, _, routes, requests = execution_case
    result = execute(execution_case)
    assert result["status"] == "succeeded" and result["succeeded"] == 3
    assert len(routes["_posted"]) == 3
    assert len({job["request_id"] for job in result["jobs"]}) == 3
    assert len({job["prompt_id"] for job in result["jobs"]}) == 3
    first = [json.loads(job_path(config, plan["plan_id"], i).read_bytes()) for i in range(3)]
    assert all(
        record["owner"] == {"plan_id": plan["plan_id"], "index": i}
        for i, record in enumerate(first)
    )
    before = list(requests)
    assert resume(execution_case)["status"] == "succeeded"
    assert requests == before  # Intact completed outputs need no runtime request.
    assert batch_status(config, path)["succeeded"] == 3


def test_qualification_cli_and_run_status_resume(execution_case, capsys):
    config, _, path, _, _, _ = execution_case
    flags = [str(path), "--config", str(config.file), "--json"]
    assert main(["batch", "qualify", *flags, "--save"]) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert main(["batch", "run", *flags, "--qualification", receipt["path"]]) == 0
    assert json.loads(capsys.readouterr().out)["succeeded"] == 3
    for action in ("status", "resume"):
        assert main(["batch", action, *flags]) == 0
        assert json.loads(capsys.readouterr().out)["status"] == "succeeded"


@pytest.mark.parametrize("change", ["input", "runtime", "argv", "schema", "extra_paths"])
def test_changed_qualification_blocks_submission(execution_case, change):
    config, _, _, _, routes, _ = execution_case
    if change == "input":
        (config.root / "input/example.png").write_bytes(b"changed")
    elif change == "runtime":
        (config.comfyui_root / "nodes.py").write_bytes(b"changed")
    elif change == "argv":
        routes["/system_stats"][1]["system"]["argv"].append("--custom-nodes")
    elif change == "schema":
        routes["/object_info"][1]["SaveImage"]["output"] = ["IMAGE"]
    else:
        (config.comfyui_root / "extra_model_paths.yaml").write_text("{}")
    with pytest.raises(ValueError):
        execute(execution_case)
    assert not routes.get("_posted")


def lost_ack(monkeypatch):
    original = ComfyUIClient.submit

    def submit(client, *args):
        result = original(client, *args)
        if result["prompt_id"] == "prompt-0":
            raise ComfyUIError("Simulated lost acknowledgement after server acceptance")
        return result

    monkeypatch.setattr(ComfyUIClient, "submit", submit)


def test_lost_ack_reconciles_exact_owner_without_duplicate(execution_case, monkeypatch):
    lost_ack(monkeypatch)
    first = execute(execution_case)
    assert first["status"] == "paused" and first["jobs"][0]["status"] == "submission_unknown"
    assert len(execution_case[4]["_posted"]) == 1
    assert resume(execution_case)["succeeded"] == 3
    assert len(execution_case[4]["_posted"]) == 3


@pytest.mark.parametrize("mismatch", ["missing", "graph", "duplicate", "owner"])
def test_uncertain_acceptance_never_retries(execution_case, monkeypatch, mismatch):
    lost_ack(monkeypatch)
    execute(execution_case)
    routes = execution_case[4]
    history = routes["/history?max_items=200"][1]
    if mismatch == "missing":
        history.clear()
    elif mismatch == "graph":
        history["prompt-0"]["prompt"][2]["1"]["inputs"]["image"] = "different.png"
    elif mismatch == "owner":
        history["prompt-0"]["prompt"][3]["itov_request_id"] = "different-owner"
    else:
        history["duplicate"] = copy.deepcopy(history["prompt-0"])
        history["duplicate"]["prompt"][1] = "duplicate"
    assert resume(execution_case)["status"] == "paused"
    assert len(routes["_posted"]) == 1


def test_explicit_prompt_requires_matching_server_proof(execution_case, monkeypatch):
    lost_ack(monkeypatch)
    execute(execution_case)
    execution_case[4]["/history?max_items=200"] = (200, {})
    assert resume(execution_case, prompt_id="wrong")["status"] == "paused"
    assert resume(execution_case, prompt_id="prompt-0")["succeeded"] == 3
    assert len(execution_case[4]["_posted"]) == 3


def test_timeout_resume_observes_accepted_job_then_stops_on_stale_catalog(execution_case):
    config, plan, _, _, routes, _ = execution_case
    original = routes["POST /prompt"][1]

    def submit(payload):
        result = original(payload)
        routes["/history/prompt-0"][1]["prompt-0"]["status"]["completed"] = False
        return result

    routes["POST /prompt"] = (200, submit)
    assert execute(execution_case)["jobs"][0]["status"] == "timed_out"
    store = CatalogStore(config.root)
    catalog = store.snapshot().to_dict()["catalog"]
    catalog["presets"][0]["tags"] = ["changed"]
    store.import_catalog(catalog, expected_head=plan["catalog_head"])
    routes["/history/prompt-0"][1]["prompt-0"]["status"]["completed"] = True
    result = resume(execution_case)
    assert result["status"] == "paused" and result["succeeded"] == 1
    assert "head" in result["error"].lower()
    assert len(routes["_posted"]) == 1


def test_asset_change_between_jobs_stops_next_post(execution_case):
    config, _, _, _, routes, _ = execution_case
    original = routes["POST /prompt"][1]

    def submit(payload):
        result = original(payload)
        (config.root / "input/example.png").write_bytes(b"changed after acceptance")
        return result

    routes["POST /prompt"] = (200, submit)
    result = execute(execution_case)
    assert result["status"] == "paused" and result["succeeded"] == 1
    assert "Qualification changed" in result["error"]
    assert len(routes["_posted"]) == 1


def test_busy_queue_retains_ownership_and_later_resumes(execution_case):
    config, plan, _, _, routes, _ = execution_case
    routes["/queue"][1]["queue_pending"] = [[0, "external", {}, {}]]
    assert execute(execution_case)["status"] == "paused"
    assert not routes.get("_posted")
    request = copy.deepcopy(plan["request"])
    request["count"] = 1
    other = create_plan(config.root, request)
    other_path = save_plan(config.root, other)
    other_receipt = save_qualification(config, qualify(config, other))
    with pytest.raises(ValueError, match="ownership"):
        run_batch(config, other_path, qualification=other_receipt)
    routes["/queue"][1]["queue_pending"] = []
    assert resume(execution_case)["succeeded"] == 3


@pytest.mark.parametrize("damage", ["missing", "owner", "workflow", "prepared", "artifact"])
def test_damaged_job_or_artifact_never_resubmits(execution_case, damage):
    config, plan, _, _, routes, _ = execution_case
    execute(execution_case)
    path = job_path(config, plan["plan_id"], 0)
    record = json.loads(path.read_bytes())
    if damage == "missing":
        path.unlink()
    elif damage == "artifact":
        Path(record["artifacts"][0]["path"]).write_bytes(b"preserve these changed bytes")
    else:
        if damage == "owner":
            record["owner"]["index"] = 1
        elif damage == "workflow":
            record["workflow"]["1"]["inputs"]["image"] = "other"
        else:
            record["status"] = "prepared"
        path.write_text(json.dumps(record), encoding="utf-8")
    result = resume(execution_case)
    assert result["status"] == "paused"
    assert len(routes["_posted"]) == 3
    if damage == "artifact":
        assert Path(record["artifacts"][0]["path"]).read_bytes() == b"preserve these changed bytes"


@pytest.mark.parametrize("kind", ["rejected", "failed"])
def test_terminal_failure_stops_remaining_jobs(execution_case, kind):
    routes = execution_case[4]
    if kind == "rejected":
        routes["POST /prompt"] = (400, {"error": "invalid prompt"})
    else:
        original = routes["POST /prompt"][1]

        def submit(payload):
            result = original(payload)
            routes["/history/prompt-0"][1]["prompt-0"]["status"]["status_str"] = "error"
            return result

        routes["POST /prompt"] = (200, submit)
    result = execute(execution_case)
    assert result["status"] == "failed" and result["jobs"][0]["status"] == kind
    assert resume(execution_case)["status"] == "failed"
    assert len(routes["_posted"]) == 1


def test_seed_reservations_are_atomic_permanent_and_uint64(execution_case):
    config, plan, _, _, _, _ = execution_case
    # Storage contract fixture; no server submission or inference claim.
    plan = copy.deepcopy(plan)
    for index, job in enumerate(plan["jobs"]):
        job["seed"] = 2**64 - 1 - index
    (config.root / "state/batches").mkdir()
    with closing(open_store(config, create=True)) as db:
        claim(db, config, plan, {})
        record_run(db, plan["plan_id"], "failed")
        other = copy.deepcopy(plan)
        other["plan_id"] = "a" * 64
        other["jobs"][0]["seed"] = 99  # Must roll back when a later seed collides.
        with pytest.raises(ValueError, match="already reserved"):
            claim(db, config, other, {})
        assert db.execute("SELECT count(*) FROM runs").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 3
        assert db.execute("SELECT count(*) FROM seeds").fetchone()[0] == 3
        assert db.execute("SELECT count(*) FROM seeds WHERE seed = '99'").fetchone()[0] == 0


def test_missing_execution_database_is_not_recreated(execution_case):
    config = execution_case[0]
    execute(execution_case)
    (config.root / "state/batches/execution.sqlite3").unlink()
    with pytest.raises(ValueError, match="database is missing"):
        execute(execution_case)


@pytest.mark.parametrize("boundary", ["prepared", "submitting", "queued"])
def test_process_crash_preserves_no_duplicate_boundary(execution_case, boundary):
    config, _, path, receipt, routes, _ = execution_case
    script = """
import os, sys
from pathlib import Path
import itov.owned_jobs as owned
from itov.batch_execution import run_batch
from itov.config import load_config
original = owned._save
def save(path, record):
    result = original(path, record)
    if record['status'] == sys.argv[4]:
        os._exit(71)
    return result
owned._save = save
run_batch(load_config(Path(sys.argv[1])), Path(sys.argv[2]), qualification=Path(sys.argv[3]))
"""
    child = subprocess.run(
        [sys.executable, "-c", script, str(config.file), str(path), str(receipt), boundary],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert child.returncode == 71, child.stderr
    result = resume(execution_case)
    if boundary == "submitting":
        # Intent was durable but POST never happened. Absence cannot prove that after a crash.
        assert result["status"] == "paused"
        assert not routes.get("_posted")
    else:
        assert result["status"] == "succeeded"
        assert len(routes["_posted"]) == 3


def test_process_crash_rolls_back_batch_claim(execution_case):
    config, _, path, receipt, _, _ = execution_case
    script = """
import os, sys
from contextlib import contextmanager
from pathlib import Path
import itov.execution_store as store
from itov.batch_execution import run_batch
from itov.config import load_config
original = store.transaction
@contextmanager
def transaction(db):
    with original(db):
        yield
        os._exit(72)
store.transaction = transaction
run_batch(load_config(Path(sys.argv[1])), Path(sys.argv[2]), qualification=Path(sys.argv[3]))
"""
    child = subprocess.run(
        [sys.executable, "-c", script, str(config.file), str(path), str(receipt)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert child.returncode == 72, child.stderr
    with closing(open_store(config, create=False)) as db:
        for table in ("runs", "jobs", "seeds", "events"):
            assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    assert execute(execution_case)["succeeded"] == 3


def test_abandon_retires_only_unsubmitted_remainder(execution_case):
    config, _, path, _, routes, _ = execution_case
    routes["/queue"][1]["queue_pending"] = [[0, "external", {}, {}]]
    assert execute(execution_case)["status"] == "paused"
    assert abandon_batch(config, path)["status"] == "abandoned"
    assert resume(execution_case)["status"] == "abandoned"
    assert not routes.get("_posted")


def test_abandon_refuses_uncertain_submission(execution_case, monkeypatch):
    lost_ack(monkeypatch)
    execute(execution_case)
    config, _, path, _, routes, _ = execution_case
    with pytest.raises(ValueError, match="Cannot abandon"):
        abandon_batch(config, path)
    assert len(routes["_posted"]) == 1


def test_history_requires_exact_batch_job_provenance(execution_case):
    routes = execution_case[4]
    original = routes["POST /prompt"][1]

    def submit(payload):
        result = original(payload)
        routes["/history/prompt-0"][1]["prompt-0"]["prompt"][3]["itov_request_id"] = "other"
        return result

    routes["POST /prompt"] = (200, submit)
    result = execute(execution_case)
    assert result["status"] == "paused"
    assert "does not belong" in result["error"]
    assert len(routes["_posted"]) == 1


def test_acceptance_can_be_reconciled_from_queue(execution_case, monkeypatch):
    lost_ack(monkeypatch)
    first = execute(execution_case)
    config, plan, _, _, routes, _ = execution_case
    prompt = routes["/history?max_items=200"][1]["prompt-0"]["prompt"]
    routes["/history?max_items=200"] = (200, {})
    routes["/queue"][1]["queue_running"] = [prompt]
    match = ComfyUIClient(config.url).find_submission(
        first["jobs"][0]["request_id"], json.loads(plan["jobs"][0]["workflow_json"])
    )
    assert match == "prompt-0" and len(routes["_posted"]) == 1


def test_process_lock_excludes_competing_dispatcher(execution_case):
    config, _, _, _, routes, _ = execution_case
    directory = config.root / "state/batches"
    directory.mkdir()
    ready, release = directory / "ready", directory / "release"
    script = """
import sys, time
from pathlib import Path
from itov.locking import file_lock
root = Path(sys.argv[1])
with file_lock(root / 'execution.lock'):
    (root / 'ready').write_text('owned')
    deadline = time.monotonic() + 15
    while not (root / 'release').exists() and time.monotonic() < deadline:
        time.sleep(0.01)
"""
    child = subprocess.Popen(
        [sys.executable, "-c", script, str(directory)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists()
        with pytest.raises(ValueError, match="Another process"):
            execute(execution_case)
        assert not routes.get("_posted")
    finally:
        release.write_text("release")
        child.communicate(timeout=20)
    assert child.returncode == 0
    assert execute(execution_case)["succeeded"] == 3
