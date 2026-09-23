"""Cross-family exclusion, native ownership and external-server recovery contracts."""

import json
import subprocess
import sys
import uuid
from dataclasses import replace
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import pytest
from quality_fixtures import curated_inputs as curated_inputs
from test_audio import audio_case as audio_case
from test_audio import encoded_audio as encoded_audio
from test_batch_execution import execute
from test_batch_execution import execution_case as execution_case
from test_evaluation_runtime import planned
from test_evaluation_runtime import runtime_case as runtime_case
from test_jobs import job_setup as job_setup
from test_parallel import protocol as parallel_protocol  # noqa: F401 - dynamic pytest fixture
from test_parallel import trial
from test_training import protocol as training_protocol  # noqa: F401 - dynamic pytest fixture
from test_training import training_inputs as training_inputs

from itov import device, evaluation_runtime, training, vram
from itov.batch_execution import _lock
from itov.client_ownership import ClientLease
from itov.client_ownership import target_gpu as actual_target_gpu
from itov.comfyui import ComfyUIClient, ComfyUIError
from itov.jobs import run_job, wait_job
from itov.owned_jobs import job_path
from itov.windows_process import Job, process_state

GPU = "GPU-19396af4-e5de-4d99-a258-803d73f4af12"


@pytest.fixture(params=["job", "batch", "evaluation", "training", "parallel"])
def entrypoint(request, http_server, monkeypatch):
    family = request.param
    routes = http_server[1]
    registry = device.registry_root()
    if family == "job":
        config, workflow, _, routes, _ = request.getfixturevalue("job_setup")
        run = partial(run_job, config, workflow)
    elif family == "batch":
        item = request.getfixturevalue("execution_case")
        config, routes = item[0], item[4]
        run = partial(execute, item)
    elif family == "evaluation":
        item = request.getfixturevalue("runtime_case")
        _, path = planned(item)
        config, routes = item.config, item.routes
        run = partial(evaluation_runtime.run, config, path, wait_timeout=0.1)
    elif family == "training":
        item = request.getfixturevalue("training_protocol")
        config, registry = item.config, item.registry
        run = partial(training.run, config, item.plan_path, GPU, registry=registry)
    else:
        item = request.getfixturevalue("parallel_protocol")
        config, build, routes, _, registry = item
        _, path = build()
        run = partial(trial, item, path)
    monkeypatch.setattr(device, "registry_root", lambda: registry)
    return SimpleNamespace(
        config=config, run=run, routes=routes, registry=registry, url=http_server[0], family=family
    )


def refused(item):
    try:
        result = item.run()
    except ValueError as error:
        message = str(error)
    else:
        assert result["status"] == "paused", result
        message = result["error"]
    assert any(word in message for word in ("ownership", "lease", "lock")), message
    assert not item.routes.get("_posted")


def test_all_families_share_the_workspace_dispatcher_lock(entrypoint):
    with _lock(entrypoint.config):
        refused(entrypoint)


def test_standalone_wait_cannot_bypass_a_plan_owner(execution_case):
    config, plan, _, _, routes, _ = execution_case
    assert execute(execution_case)["status"] == "succeeded"
    count = len(routes["_posted"])
    with pytest.raises(ValueError, match="plan-owned"):
        wait_job(config, job_path(config, plan["plan_id"], 0))
    assert len(routes["_posted"]) == count


def test_completed_observation_is_offline_while_another_device_owner_runs(job_setup, monkeypatch):
    config, workflow, _, _, _ = job_setup
    result = run_job(config, workflow)
    monkeypatch.setattr(
        ComfyUIClient, "history", lambda *_: pytest.fail("Offline replay used HTTP")
    )
    with device.Lease(GPU, config.root / "other", "native-owner") as lease:
        assert wait_job(config, Path(result["record_path"]))["status"] == "succeeded"
        lease.release()


@pytest.mark.parametrize("change", ["graph", "prompt", "archive_id"])
def test_saved_job_cannot_change_its_retired_device_binding(job_setup, change):
    config, workflow, _, _, _ = job_setup
    result = run_job(config, workflow)
    path = Path(result["record_path"])
    if change == "graph":
        result["workflow"]["2"]["inputs"]["filename_prefix"] = "changed"
    elif change == "prompt":
        result["prompt_id"] = "other"
    else:
        result["device_lease"]["lease_id"] = "../elsewhere"
    path.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(ValueError):
        wait_job(config, path)


def test_each_family_refuses_detached_external_request_in_another_workspace(entrypoint, graph):
    item = entrypoint
    other = replace(item.config, file=item.config.root.parent / "other/itov.toml", url=item.url)
    record = {"request_id": str(uuid.uuid4()), "workflow": graph}
    with ClientLease(other, record["request_id"]) as lease:
        assert lease.begin(record)
    before = device.status(GPU, root=item.registry)
    assert before["status"] == "held"
    refused(item)
    assert device.status(GPU, root=item.registry) == before


def test_each_family_refuses_live_native_owner_and_only_owned_child_stops(entrypoint, tmp_path):
    item = entrypoint
    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import time;time.sleep(60)"],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        with device.Lease(GPU, tmp_path / "other", "native-owner", root=item.registry) as lease:
            pool = Job(lease.value["job_name"])
            try:
                worker = pool.spawn(
                    [sys.executable, "-c", "import time;time.sleep(60)"], str(tmp_path)
                )
                lease.register(worker)
                pool.resume(worker)
                refused(item)
                assert process_state(worker) == "alive"
                assert unrelated.poll() is None
            finally:
                pool.stop()
            assert process_state(worker) == "dead"
            assert unrelated.poll() is None
            lease.release()
        assert device.status(GPU, root=item.registry)["status"] == "idle"
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=10)


@pytest.mark.parametrize("owner", ["standalone", "training"])
def test_each_family_refuses_unfinished_workspace_owner_before_gpu_work(entrypoint, owner):
    item = entrypoint
    if owner == "standalone":
        key = str(uuid.uuid4())
        path = item.config.root / f"state/jobs/{key}.json"
        record = {
            "version": 1,
            "request_id": key,
            "status": "submission_unknown",
            "server": item.url,
        }
    else:
        path = item.config.root / ("state/training/runs/" + "f" * 64 + "/run.json")
        record = {"version": 2, "plan_id": "f" * 64, "status": "validating"}
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(record).encode()
    path.write_bytes(raw)
    refused(item)
    assert path.read_bytes() == raw
    assert device.status(GPU, root=item.registry)["status"] == "uninitialized"


def test_standalone_lost_ack_is_reconciled_with_exact_proof_and_no_duplicate(
    job_setup, monkeypatch
):
    config, workflow, _, routes, requests = job_setup
    submit = ComfyUIClient.submit

    def lost(client, *args):
        submit(client, *args)
        raise ComfyUIError("acknowledgement lost")

    monkeypatch.setattr(ComfyUIClient, "submit", lost)
    first = run_job(config, workflow)
    assert first["status"] == "submission_unknown"
    assert device.status(GPU)["status"] == "held"
    second = wait_job(config, Path(first["record_path"]), prompt_id="fixture-prompt")
    assert second["status"] == "succeeded"
    assert device.status(GPU)["status"] == "idle"
    assert len(routes["_posted"]) == 1
    assert not any(path != "/prompt" for method, path in requests if method == "POST")


@pytest.mark.parametrize("proof", ["missing", "wrong_graph", "active", "offline"])
def test_external_recovery_requires_positive_terminal_proof(job_setup, monkeypatch, proof):
    config, workflow, history, routes, requests = job_setup
    routes["/history/fixture-prompt"] = (200, {})
    result = run_job(config, workflow, wait_timeout=0.01, poll_interval=0.005)
    lease = device.status(GPU)
    assert lease["status"] == "held"
    monkeypatch.setattr(device, "process_state", lambda _: "dead")
    routes["/history/fixture-prompt"] = (200, {"fixture-prompt": history})
    if proof == "missing":
        routes["/history/fixture-prompt"] = (200, {})
        routes["/history?max_items=200"] = (200, {})
    elif proof == "wrong_graph":
        history["prompt"][2] = {}
    elif proof == "active":
        history["status"] = {"completed": False, "status_str": "running"}
    else:
        routes["/queue"] = (503, {})
    before = Path(result["record_path"]).read_bytes()
    with pytest.raises((ValueError, ComfyUIError)):
        device.recover(GPU, lease["lease_id"])
    assert device.status(GPU)["status"] == "held"
    assert Path(result["record_path"]).read_bytes() == before
    assert requests.count(("POST", "/prompt")) == 1


@pytest.mark.parametrize("boundary", ["intent", "queued", "succeeded"])
def test_native_client_crash_retains_external_work_and_recovery_never_posts(job_setup, boundary):
    config, workflow, _, routes, requests = job_setup
    script = r"""
import os,sys
from pathlib import Path
from itov import jobs,device,client_ownership
from itov.config import load_config
device.registry_root=lambda:Path(sys.argv[3])
client_ownership.target_gpu=lambda _:'GPU-19396af4-e5de-4d99-a258-803d73f4af12'
save,write=jobs._save,device._write
def save_crash(path,record):
    result=save(path,record)
    if record['status']==sys.argv[4]: os._exit(71)
    return result
def intent_crash(path,record):
    result=write(path,record)
    if sys.argv[4]=='intent' and record.get('requests'): os._exit(71)
    return result
jobs._save=save_crash
device._write=intent_crash
jobs.run_job(load_config(Path(sys.argv[1])),Path(sys.argv[2]),wait_timeout=1)
"""
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(config.file),
            str(workflow),
            str(device.registry_root()),
            boundary,
        ],
        capture_output=True,
        text=True,
        timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert child.returncode == 71, child.stderr
    lease = device.status(GPU)
    assert lease["status"] == "held" and process_state(lease["owner"]) == "dead"
    with pytest.raises(ValueError, match="Unreleased"):
        with device.Lease(GPU, config.root / "other", "managed"):
            pytest.fail("Unresolved external request admitted native work")
    if boundary == "intent":
        with pytest.raises(ValueError, match="unknown"):
            device.recover(GPU, lease["lease_id"])
        assert not routes.get("_posted")
    else:
        assert device.recover(GPU, lease["lease_id"])["status"] == "idle"
        key = next(iter(lease["requests"]))
        assert wait_job(config, config.root / f"state/jobs/{key}.json")["status"] == "succeeded"
        assert requests.count(("POST", "/prompt")) == 1


@pytest.mark.parametrize("damage", [None, "name", "index", "type", "multiple", "remote"])
def test_single_local_gpu_binding_is_explicit(job_setup, monkeypatch, damage):
    config, _, _, routes, _ = job_setup
    monkeypatch.setattr(vram, "gpu_snapshot", lambda: {"uuid": GPU, "name": "Fixture NVIDIA"})
    devices = [{"name": "cuda:0 Fixture NVIDIA : default", "index": 0, "type": "cuda"}]
    routes["/system_stats"][1]["devices"] = devices
    if damage in {"name", "index", "type"}:
        devices[0][damage] = {"name": "unrelated", "index": 1, "type": "cpu"}[damage]
    elif damage == "multiple":
        devices.append(dict(devices[0]))
    elif damage == "remote":
        config = replace(config, url="http://example.invalid:8188")
    if damage:
        with pytest.raises(ValueError):
            actual_target_gpu(config)
    else:
        assert actual_target_gpu(config) == GPU
    assert device.status(GPU)["status"] == "uninitialized"
