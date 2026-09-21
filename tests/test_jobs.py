from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from itov.comfyui import ComfyUIClient
from itov.config import initialize
from itov.jobs import _guard, run_job, wait_job


@pytest.fixture
def job_setup(tmp_path, graph, http_server):
    url, routes, requests = http_server
    config = initialize(tmp_path / "work", tmp_path / "comfy", url=url)
    workflow = tmp_path / "workflow.json"
    workflow.write_text(json.dumps(graph))
    history = {
        "status": {"status_str": "success", "completed": True, "messages": []},
        "outputs": {
            "2": {"images": [{"filename": "render.png", "subfolder": "run", "type": "output"}]}
        },
    }
    routes["POST /prompt"] = 200, {"prompt_id": "fixture-prompt", "node_errors": {}}
    routes["/history/fixture-prompt"] = 200, {"fixture-prompt": history}
    routes["/view?filename=render.png&subfolder=run&type=output"] = 200, b"fixture image bytes"
    return config, workflow, history, routes, requests


def test_job_success_records_exact_output_provenance(job_setup):
    config, workflow, _history, routes, requests = job_setup
    result = run_job(config, workflow)
    assert result["status"] == "succeeded"
    assert result["workflow_sha256"] == hashlib.sha256(workflow.read_bytes()).hexdigest()
    assert routes["_posted"][0]["extra_data"]["itov_request_id"] == result["request_id"]
    artifact = result["artifacts"][0]
    assert Path(artifact["path"]).read_bytes() == b"fixture image bytes"
    assert artifact["sha256"] == hashlib.sha256(b"fixture image bytes").hexdigest()
    assert artifact["filename"] == "render.png" and artifact["node_id"] == "2"
    assert json.loads(Path(result["record_path"]).read_text())["status"] == "succeeded"
    assert requests.count(("POST", "/prompt")) == 1


def test_failed_validation_never_submits(job_setup):
    config, workflow, _history, _routes, requests = job_setup
    workflow.write_text('{"1": {"class_type": "NotInstalled", "inputs": {}}}')
    result = run_job(config, workflow)
    assert result["status"] == "validation_failed"
    assert not any(method == "POST" for method, _ in requests)


def test_server_validation_rejection_preserves_details(job_setup):
    config, workflow, _history, routes, requests = job_setup
    body = {
        "error": {"type": "prompt_outputs_failed_validation"},
        "node_errors": {"1": {"errors": ["missing input file"]}},
    }
    routes["POST /prompt"] = 400, body
    result = run_job(config, workflow)
    assert result["status"] == "rejected" and result["server_error"] == body
    assert requests.count(("POST", "/prompt")) == 1


@pytest.mark.parametrize(
    "status,body", [(500, {"error": "internal"}), (200, {}), (200, b"truncated JSON")]
)
def test_uncertain_submission_is_never_automatically_retried(job_setup, status, body):
    config, workflow, _history, routes, requests = job_setup
    routes["POST /prompt"] = status, body
    result = run_job(config, workflow)
    assert result["status"] == "submission_unknown"
    with pytest.raises(ValueError, match="acceptance is unknown"):
        wait_job(config, Path(result["record_path"]))
    assert requests.count(("POST", "/prompt")) == 1


def test_execution_error_is_reported_immediately(job_setup):
    config, workflow, history, _routes, requests = job_setup
    history["status"] = {
        "status_str": "error",
        "completed": False,
        "messages": [["execution_error", {"node_id": "1", "exception_message": "fixture failure"}]],
    }
    result = run_job(config, workflow)
    assert result["status"] == "failed"
    assert result["execution"]["status"]["messages"][0][1]["exception_message"] == "fixture failure"
    assert not any(path.startswith("/view") for _, path in requests)


def test_timeout_can_resume_without_resubmission(job_setup):
    config, workflow, history, routes, requests = job_setup
    routes["/history/fixture-prompt"] = 200, {}
    timed_out = run_job(config, workflow, wait_timeout=0.05, poll_interval=0.01)
    assert timed_out["status"] == "timed_out" and timed_out["prompt_id"] == "fixture-prompt"
    routes["/history/fixture-prompt"] = 200, {"fixture-prompt": history}
    resumed = wait_job(config, Path(timed_out["record_path"]))
    assert resumed["status"] == "succeeded"
    assert requests.count(("POST", "/prompt")) == 1


def test_ctrl_c_detaches_and_does_not_interrupt_server(job_setup, monkeypatch):
    config, workflow, _history, _routes, requests = job_setup

    def interrupted(*_args):
        raise KeyboardInterrupt

    monkeypatch.setattr(ComfyUIClient, "history", interrupted)
    result = run_job(config, workflow)
    assert result["status"] == "detached" and result["prompt_id"] == "fixture-prompt"
    assert ("POST", "/interrupt") not in requests


def test_artifact_failure_is_not_success_and_can_be_resumed(job_setup):
    config, workflow, _history, routes, requests = job_setup
    view = "/view?filename=render.png&subfolder=run&type=output"
    routes[view] = 503, {"error": "unavailable"}
    failed = run_job(config, workflow)
    assert failed["status"] == "collection_failed"
    routes[view] = 200, b"fixture image bytes"
    resumed = wait_job(config, Path(failed["record_path"]))
    assert resumed["status"] == "succeeded"
    assert requests.count(("POST", "/prompt")) == 1


@pytest.mark.parametrize(
    "filename,subfolder",
    [
        ("../../escape.png", ""),
        ("render.png", "../escape"),
        ("C:\\escape.png", ""),
        ("render.png", "/outside"),
    ],
)
def test_unsafe_history_artifacts_are_not_downloaded(job_setup, filename, subfolder):
    config, workflow, history, _routes, requests = job_setup
    descriptor = history["outputs"]["2"]["images"][0]
    descriptor.update(filename=filename, subfolder=subfolder)
    result = run_job(config, workflow)
    assert result["status"] == "collection_failed"
    assert not any(path.startswith("/view") for _, path in requests)


def test_no_persistent_outputs_cannot_claim_delivery(job_setup):
    config, workflow, history, _routes, _requests = job_setup
    history["outputs"] = {}
    assert run_job(config, workflow)["status"] == "collection_failed"


def test_resume_preserves_modified_output(job_setup):
    config, workflow, _history, _routes, requests = job_setup
    result = run_job(config, workflow)
    output = Path(result["artifacts"][0]["path"])
    output.write_bytes(b"operator replacement")
    resumed = wait_job(config, Path(result["record_path"]))
    assert resumed["status"] == "collection_failed"
    assert output.read_bytes() == b"operator replacement"
    assert requests.count(("POST", "/prompt")) == 1


def test_resume_redownloads_missing_output(job_setup):
    config, workflow, _history, _routes, requests = job_setup
    result = run_job(config, workflow)
    output = Path(result["artifacts"][0]["path"])
    output.unlink()
    resumed = wait_job(config, Path(result["record_path"]))
    assert resumed["status"] == "succeeded" and output.read_bytes() == b"fixture image bytes"
    assert requests.count(("POST", "/prompt")) == 1


def test_resume_rejects_different_server(job_setup):
    config, workflow, _history, _routes, _requests = job_setup
    result = run_job(config, workflow)
    path = Path(result["record_path"])
    result["server"] = "http://127.0.0.1:1"
    path.write_text(json.dumps(result))
    with pytest.raises(ValueError, match="does not match"):
        wait_job(config, path)


def test_invalid_saved_artifacts_fail_without_a_traceback(job_setup):
    config, workflow, _history, _routes, _requests = job_setup
    result = run_job(config, workflow)
    path = Path(result["record_path"])
    result["artifacts"] = [{}]
    path.write_text(json.dumps(result))
    with pytest.raises(ValueError, match="does not match"):
        wait_job(config, path)


def test_job_guard_releases_after_process_crash(tmp_path):
    path = tmp_path / "job.json"
    script = (
        "import os,sys; from pathlib import Path; from itov.jobs import _guard\n"
        "with _guard(Path(sys.argv[1])):\n"
        " print('locked',flush=True)\n"
        " sys.stdin.read(1)\n"
        " os._exit(0)\n"
    )
    with subprocess.Popen(
        [sys.executable, "-c", script, str(path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as child:
        assert child.stdout.readline().strip() == "locked"
        with pytest.raises(ValueError, match="Another process"):
            with _guard(path):
                pytest.fail("Acquired an owned job lock")
        child.communicate("x", timeout=5)
        assert child.returncode == 0
    with _guard(path):
        assert path.with_suffix(".lock").is_file()
