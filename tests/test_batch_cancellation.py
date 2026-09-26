import json
from contextlib import closing

import pytest
from test_batch_execution import execute, resume
from test_batch_execution import execution_case as execution_case

from itov import batch_cancellation as cancellation
from itov.batch_execution import batch_status
from itov.catalog import sha256
from itov.comfyui import ComfyUIClient, ComfyUIError
from itov.execution_store import claim, open_store
from itov.owned_jobs import job_path
from itov.qualification import load_qualification


def reserve(case):
    config, plan, _, receipt, _, _ = case
    with closing(open_store(config, create=True)) as db:
        claim(db, config, plan, load_qualification(receipt))


def request_during_poll(monkeypatch, path, *, interrupt=False):
    original = cancellation.poll
    seen = False

    def poll(config, plan, client, record):
        nonlocal seen
        if not seen:
            cancellation.cancel(config, path, interrupt_running=interrupt)
            seen = True
        return original(config, plan, client, record)

    monkeypatch.setattr(cancellation, "poll", poll)


def test_cancel_registered_plan_before_submission_preserves_picks(execution_case):
    config, plan, path, _, routes, requests = execution_case
    reserve(execution_case)
    before = path.read_bytes()
    database = config.root / "state/batches/execution.sqlite3"
    database_before = database.read_bytes()
    value = cancellation.cancel(config, path)
    assert database.read_bytes() == database_before
    assert value == cancellation.cancel(config, path)
    assert not [r for r in requests if r[0] == "POST"]
    result = resume(execution_case)
    assert result["status"] == "abandoned"
    assert all(j["status"] == "reserved" for j in result["jobs"])
    assert not routes.get("_posted") and path.read_bytes() == before
    assert batch_status(config, path)["cancellation"] == value["cancellation"]
    assert not job_path(config, plan["plan_id"], 0).exists()


def test_cancel_only_remainder_collects_accepted_work(execution_case, monkeypatch):
    config, _, path, _, routes, requests = execution_case
    request_during_poll(monkeypatch, path)
    result = execute(execution_case)
    assert result["status"] == "abandoned" and result["succeeded"] == 1
    assert len(routes["_posted"]) == 1
    before = list(requests)
    assert resume(execution_case)["status"] == "abandoned"
    assert requests == before
    with pytest.raises(ValueError, match="immutable"):
        cancellation.cancel(config, path, interrupt_running=True)


def pending_runtime(case, monkeypatch):
    config, _, _, _, routes, _ = case
    files = {}
    for name in cancellation.RUNTIME_SOURCES:
        path = config.comfyui_root / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(("atomic runtime fixture " + name).encode())
        files[name] = sha256(path.read_bytes())
    monkeypatch.setattr(cancellation, "RUNTIME_SOURCES", files)
    accepted = {}

    def submit(payload):
        prompt = "owned-prompt"
        accepted.update(
            prompt=[0, prompt, payload["prompt"], payload["extra_data"], ["2"]],
            outputs={},
            status={"completed": False, "status_str": "running", "messages": []},
        )
        routes["/queue"][1]["queue_running"] = [accepted["prompt"]]
        routes["/history/owned-prompt"] = (200, {})
        return {"prompt_id": prompt}

    def terminal():
        accepted["status"] = {
            "completed": False,
            "status_str": "error",
            "messages": [["execution_interrupted", {"prompt_id": "owned-prompt"}]],
        }
        routes["/queue"][1]["queue_running"] = []
        routes["/queue"][1]["queue_pending"] = []
        routes["/history/owned-prompt"] = (200, {"owned-prompt": accepted})
        routes["/history?max_items=200"][1]["owned-prompt"] = accepted

    def cancel(payload):
        terminal()
        return {"cancelled": True}

    routes["POST /prompt"] = (200, submit)
    routes["POST /api/jobs/owned-prompt/cancel"] = (200, cancel)
    return accepted, terminal


def test_targeted_interrupt_observes_terminal_and_keeps_failed_record(execution_case, monkeypatch):
    config, plan, path, _, _, requests = execution_case
    pending_runtime(execution_case, monkeypatch)
    request_during_poll(monkeypatch, path, interrupt=True)
    result = execute(execution_case)
    assert result["status"] == "abandoned"
    record = json.loads(job_path(config, plan["plan_id"], 0).read_bytes())
    assert record["status"] == "failed" and record["execution"]["status"]["messages"]
    assert [r for r in requests if r[0] == "POST"] == [
        ("POST", "/prompt"),
        ("POST", "/api/jobs/owned-prompt/cancel"),
    ]
    intent = cancellation.directory(config, plan) / (record["request_id"] + ".intent.json")
    assert intent.exists() and intent.with_name(record["request_id"] + ".response.json").exists()


@pytest.mark.parametrize("crash", [False, True])
def test_lost_cancel_response_never_reposts_and_retains_ownership(
    execution_case, monkeypatch, crash
):
    config, plan, path, _, routes, requests = execution_case
    _, terminal = pending_runtime(execution_case, monkeypatch)
    request_during_poll(monkeypatch, path, interrupt=True)
    routes["POST /api/jobs/owned-prompt/cancel"] = (200, {"cancelled": True})
    original = ComfyUIClient._json

    def lost(self, endpoint, payload=None):
        result = original(self, endpoint, payload)
        if endpoint.endswith("/cancel"):
            if crash:
                raise KeyboardInterrupt()
            raise ComfyUIError("injected lost cancellation response")
        return result

    monkeypatch.setattr(ComfyUIClient, "_json", lost)
    result = execute(execution_case)
    assert result["status"] == "paused"
    record = json.loads(job_path(config, plan["plan_id"], 0).read_bytes())
    assert record["status"] in {"timed_out", "detached"}
    first_posts = [r for r in requests if r[0] == "POST"]
    assert len(first_posts) == 2
    terminal()
    assert resume(execution_case)["status"] == "abandoned"
    assert [r for r in requests if r[0] == "POST"] == first_posts
    response = cancellation.directory(config, plan) / (record["request_id"] + ".response.json")
    assert (
        (not response.exists())
        if crash
        else json.loads(response.read_bytes())["acknowledgement_unknown"]
    )


@pytest.mark.parametrize("change", ["pending", "provenance", "runtime"])
def test_cancel_never_interrupts_other_or_unproven_work(execution_case, monkeypatch, change):
    config, plan, path, _, routes, requests = execution_case
    accepted, terminal = pending_runtime(execution_case, monkeypatch)
    original = cancellation.poll
    changed = False

    def poll(config, plan, client, record):
        nonlocal changed
        if not changed:
            cancellation.cancel(config, path, interrupt_running=True)
            if change == "pending":
                routes["/queue"][1]["queue_pending"] = [accepted["prompt"]]
                routes["/queue"][1]["queue_running"] = [[1, "someone-else", {}, {}, []]]
            elif change == "provenance":
                accepted["prompt"][3]["itov_request_id"] = "someone-else"
            else:
                (config.comfyui_root / "server.py").write_bytes(b"unreviewed")
            changed = True
        original(config, plan, client, record)

    monkeypatch.setattr(cancellation, "poll", poll)
    result = execute(execution_case)
    assert result["status"] == "paused"
    assert [r for r in requests if r[0] == "POST"] == [("POST", "/prompt")]
    assert not list(cancellation.directory(config, plan).glob("*.intent.json"))


def test_cancel_requires_registered_nonterminal_plan(execution_case):
    config, _, path, _, _, _ = execution_case
    with pytest.raises((ValueError, FileNotFoundError)):
        cancellation.cancel(config, path)
    assert execute(execution_case)["status"] == "succeeded"
    with pytest.raises(ValueError, match="terminal"):
        cancellation.cancel(config, path)


def test_cancel_request_mutation_cannot_enable_new_submissions(execution_case):
    config, plan, path, _, routes, _ = execution_case
    reserve(execution_case)
    cancellation.cancel(config, path)
    marker = cancellation.directory(config, plan) / "request.json"
    marker.write_bytes(marker.read_bytes().replace(b"finish-accepted", b"ignore-accepted"))
    with pytest.raises(ValueError, match="binding differs"):
        resume(execution_case)
    assert not routes.get("_posted")


def test_request_during_final_qualification_prevents_post(execution_case, monkeypatch):
    import itov.batch_execution as execution

    config, _, path, _, routes, requests = execution_case
    original = execution.qualify
    calls = 0

    def qualify(*args, **kwargs):
        nonlocal calls
        value = original(*args, **kwargs)
        calls += 1
        if calls == 2:
            cancellation.cancel(config, path)
        return value

    monkeypatch.setattr(execution, "qualify", qualify)
    assert execute(execution_case)["status"] == "abandoned"
    assert not routes.get("_posted") and not [r for r in requests if r[0] == "POST"]
