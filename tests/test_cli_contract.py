"""Public CLI outcomes and recovery; fixture media/GPUs do not qualify models."""

import copy
import json
import os
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest
from test_batch_execution import execution_case as execution_case
from test_jobs import job_setup as job_setup
from test_training import GPU
from test_training import protocol as protocol
from test_training import training_inputs as training_inputs

from itov import device, training
from itov.cli import main
from itov.cli_output import present


def invoke(capsys, arguments, code, outcome):
    assert main([*arguments, "--json"]) == code
    captured = capsys.readouterr()
    assert not captured.err
    value = json.loads(captured.out)
    assert value["_cli"]["exit_code"] == code
    assert value["_cli"]["outcome"] == outcome
    assert value["_cli"]["version"] == 1
    assert value["_cli"]["next_action"] and value["_cli"]["actions"]
    return value


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["missing"],
        ["job", "run"],
        ["doctor", "--timeout", "x"],
        ["workflow", "validate", "x", "--live", "--object-info", "x"],
        ["inference", "run", "x", "--unexpected"],
    ],
)
def test_argument_errors_have_one_json_document(arguments, capsys):
    result = invoke(capsys, arguments, 2, "error")
    assert result["error_type"] == "ArgumentError"
    assert result["_cli"]["causes"][0]["detail"] == result["error"]
    assert main(arguments) == 2
    captured = capsys.readouterr()
    assert not captured.out and "ERROR arguments (exit 2)" in captured.err


@pytest.mark.parametrize(
    "body,expected,code",
    [
        ({"status": "running"}, "incomplete", 1),
        ({"status": "validating"}, "incomplete", 1),
        ({"status": "abandoned", "ok": True}, "incomplete", 1),
        ({"status": "artifacts_validated"}, "ok", 0),
        ({"status": "observation_failed", "error": "Lost history"}, "failed", 1),
        ({"scope": "promotion_refused", "ok": False}, "refused", 1),
        ({"technical_pass": False}, "failed", 1),
    ],
)
def test_text_and_json_share_meanings_without_mutating_documents(body, expected, code, capsys):
    original = copy.deepcopy(body)
    args = Namespace(command="training", action="status", file=Path("plan.json"), json=True)
    assert present(args, body) == code
    result = json.loads(capsys.readouterr().out)
    meta = result.pop("_cli")
    assert meta["outcome"] == expected and result == original == body
    args.json = False
    assert present(args, body) == code
    text = capsys.readouterr().out
    assert f"{expected.upper()} training status (exit {code})" in text
    assert meta["next_action"] in text


@pytest.mark.parametrize("failure", ["timeout", "collection", "observation", "interrupt"])
def test_job_recovers_through_suggested_command_and_replays_offline(
    job_setup, capsys, monkeypatch, failure
):
    config, workflow, history, routes, requests = job_setup
    endpoint = "/history/fixture-prompt"
    output = "/view?filename=render.png&subfolder=run&type=output"
    if failure == "timeout":
        routes[endpoint] = 200, {}
    elif failure == "collection":
        routes[output] = 503, {"error": "Fixture output unavailable"}
    elif failure == "observation":
        routes[endpoint] = 503, {"error": "Fixture history unavailable"}
    else:
        from itov.comfyui import ComfyUIClient

        original = ComfyUIClient.history

        def interrupt(*_a):
            raise KeyboardInterrupt

        monkeypatch.setattr(ComfyUIClient, "history", interrupt)
    arguments = [
        "job",
        "run",
        str(workflow),
        "--config",
        str(config.file),
        "--wait-timeout",
        "0.1",
        "--poll-interval",
        "0.01",
    ]
    outcome = "incomplete" if failure in {"timeout", "interrupt"} else "failed"
    partial = invoke(capsys, arguments, 1, outcome)
    assert partial["_cli"]["causes"]
    record = Path(partial["record_path"])
    assert "_cli" not in json.loads(record.read_bytes())
    assert partial["_cli"]["artifacts"][0]["path"] == str(record)
    routes[endpoint] = 200, {"fixture-prompt": history}
    routes[output] = 200, b"fixture image bytes"
    if failure == "interrupt":
        monkeypatch.setattr(ComfyUIClient, "history", original)
    suggested = partial["_cli"]["actions"][0]["argv"][1:]
    complete = invoke(capsys, suggested, 0, "ok")
    assert complete["request_id"] == partial["request_id"]
    assert requests.count(("POST", "/prompt")) == 1
    observed = len(requests)
    before = record.read_bytes()
    assert main(suggested) == 0
    text = capsys.readouterr().out
    assert "OK job wait" in text and complete["artifacts"][0]["path"] in text
    assert len(requests) == observed and record.read_bytes() == before


@pytest.mark.parametrize("failure", ["rejected", "execution", "validation"])
def test_job_failure_exposes_server_or_validation_cause(job_setup, capsys, failure):
    config, workflow, history, routes, _requests = job_setup
    if failure == "rejected":
        routes["POST /prompt"] = (
            400,
            {"error": "fixture rejection", "node_errors": {"1": "bad input"}},
        )
    elif failure == "execution":
        history["status"] = {
            "status_str": "error",
            "completed": False,
            "messages": [["execution_error", {"exception_message": "fixture CUDA error"}]],
        }
    else:
        workflow.write_text('{"1":{"class_type":"AbsentNode","inputs":{}}}')
    result = invoke(
        capsys,
        ["job", "run", str(workflow), "--config", str(config.file)],
        1,
        "refused" if failure == "rejected" else "failed",
    )
    details = json.dumps(result["_cli"]["causes"])
    assert {"rejected": "bad input", "execution": "fixture CUDA error", "validation": "AbsentNode"}[
        failure
    ] in details


def test_batch_partial_progress_status_resume_and_abandon_are_consistent(execution_case, capsys):
    config, _plan, path, receipt, routes, requests = execution_case
    submit = routes["POST /prompt"][1]
    hidden = []

    def delayed(payload):
        ack = submit(payload)
        if ack["prompt_id"] == "prompt-1":
            hidden.append(routes["/history/prompt-1"])
            routes["/history/prompt-1"] = 200, {}
        return ack

    routes["POST /prompt"] = 200, delayed
    flags = [str(path), "--config", str(config.file)]
    partial = invoke(
        capsys,
        [
            "batch",
            "run",
            *flags,
            "--qualification",
            str(receipt),
            "--wait-timeout",
            "0.1",
            "--poll-interval",
            "0.01",
        ],
        1,
        "incomplete",
    )
    assert partial["succeeded"] == 1
    assert main(["batch", "status", *flags]) == 1
    assert "Progress: 1/3 completed" in capsys.readouterr().out
    invoke(capsys, ["batch", "status", *flags], 1, "incomplete")
    routes["/history/prompt-1"] = hidden[0]
    resume = next(a for a in partial["_cli"]["actions"] if "Resume" in a["label"])
    completed = invoke(capsys, resume["argv"][1:], 0, "ok")
    assert completed["succeeded"] == 3 and requests.count(("POST", "/prompt")) == 3
    before = len(requests)
    invoke(capsys, ["batch", "resume", *flags], 0, "ok")
    assert len(requests) == before


def test_device_defaults_to_text_and_json_is_explicit(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(device, "registry_root", lambda: tmp_path / "registry")
    value = invoke(capsys, ["device", "status", "--gpu", GPU], 0, "ok")
    assert value["status"] == "uninitialized"
    assert main(["device", "status", "--gpu", GPU]) == 0
    assert capsys.readouterr().out.startswith("OK device status")
    assert not (tmp_path / "registry").exists()


def test_unknown_submission_stays_incomplete_and_never_reposts(job_setup, capsys):
    config, workflow, _history, routes, requests = job_setup
    routes["POST /prompt"] = 500, {"error": "Acknowledgement lost"}
    partial = invoke(
        capsys, ["job", "run", str(workflow), "--config", str(config.file)], 1, "incomplete"
    )
    assert partial["status"] == "submission_unknown"
    assert "Acceptance is unknown" in partial["_cli"]["next_action"]
    invoke(capsys, partial["_cli"]["actions"][0]["argv"][1:], 2, "error")
    assert requests.count(("POST", "/prompt")) == 1


@pytest.mark.parametrize("kind", ["capture", "check", "parallel"])
def test_nested_resource_failures_keep_causes_and_progress_visible(kind, capsys):
    body = {
        "capture": {
            "ok": False,
            "result": {
                "status": "paused",
                "succeeded": 1,
                "jobs": [{"status": "succeeded"}, {"status": "timed_out"}],
            },
            "profile": {"issues": ["missing second observation"]},
        },
        "check": {"ok": False, "admitted": False, "reasons": ["missing_cold_evidence"]},
        "parallel": {"ok": False, "status": "succeeded", "document": {"qualified": False}},
    }[kind]
    args = Namespace(
        command="parallel" if kind == "parallel" else "vram",
        action="qualify" if kind == "parallel" else kind,
        file=Path("plan.json"),
        json=True,
    )
    assert present(args, body) == 1
    value = json.loads(capsys.readouterr().out)
    assert (
        value["_cli"]["outcome"]
        == {"capture": "incomplete", "check": "refused", "parallel": "failed"}[kind]
    )
    assert value["_cli"]["causes"]
    args.json = False
    assert present(args, body) == 1
    text = capsys.readouterr().out
    assert "Cause" in text
    if kind == "capture":
        assert "1/2 completed" in text


def test_unhandled_interrupt_reports_state_and_exit(monkeypatch, capsys):
    def interrupted(_args):
        raise KeyboardInterrupt

    monkeypatch.setattr("itov.cli._execute", interrupted)
    invoke(capsys, ["inference", "status", "plan.json"], 130, "interrupted")
    assert main(["inference", "status", "plan.json"]) == 130
    assert "execution may still be active" in capsys.readouterr().err


@pytest.mark.skipif(os.name != "nt", reason="Native Windows process ownership")
def test_training_cli_recovers_after_real_controller_exit_without_record_edits(
    protocol, monkeypatch, capsys
):
    item = protocol
    monkeypatch.setattr(device, "registry_root", lambda: item.registry)
    # The child writes every record through the public controller. Only the final
    # atomic publication is fault-injected; the actual controller exits naturally.
    program = """
import json,sys
from pathlib import Path
from types import SimpleNamespace
sys.path[:0]=json.loads(sys.argv[1])
import pytest
from test_training import fake_job,GPU
from itov import training,device
from itov.cli import main
patch=pytest.MonkeyPatch()
fake_job(patch,'success')
patch.setattr(device,'registry_root',lambda:Path(sys.argv[2]))
patch.setattr(training,'probe',lambda _: {'python':'fixture','packages':training.PINNED})
queue=lambda:{'queue_running':[],'queue_pending':[]}
patch.setattr(training,'ComfyUIClient',lambda _:SimpleNamespace(queue=queue))
patch.setattr(training,'gpu_snapshot',lambda:{'uuid':GPU,'free_bytes':32*1024**3})
patch.setattr(training,'host_memory',lambda:{'available_physical':32*1024**3,'available_commit':32*1024**3})
write=training._atomic_write
def fail_final(path,raw):
    if path.name=='run.json' and json.loads(raw)['status']=='artifacts_validated':
        raise OSError('A06 injected terminal publication interruption')
    return write(path,raw)
patch.setattr(training,'_atomic_write',fail_final)
raise SystemExit(main(['training','run',sys.argv[3],'--config',sys.argv[4],'--gpu',GPU,'--json']))
"""
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            program,
            json.dumps([str(Path(p).absolute()) for p in sys.path]),
            str(item.registry),
            str(item.plan_path),
            str(item.config.file),
        ],
        capture_output=True,
        text=True,
        timeout=90,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert child.returncode == 2, child.stdout + child.stderr
    value = json.loads(child.stdout)
    assert value["_cli"]["outcome"] == "error"
    flags = [str(item.plan_path), "--config", str(item.config.file)]
    observed = invoke(capsys, ["training", "status", *flags], 1, "incomplete")
    assert observed["status"] == "validating"
    result_path = training.run_folder(item.config, item.plan) / "result.json"
    original = result_path.read_bytes()
    recovery = next(a for a in observed["_cli"]["actions"] if "Recover" in a["label"])

    def no_worker(*_args):
        pytest.fail("Recovery started another worker")

    monkeypatch.setattr(training, "Job", no_worker)
    recovered = invoke(capsys, recovery["argv"][1:], 0, "ok")
    assert recovered["status"] == "artifacts_validated"
    assert recovered["worker"] == observed["worker"]
    assert result_path.read_bytes() == original
    assert device.status(GPU)["status"] == "idle"
    invoke(capsys, ["evaluation", "assess", *flags], 0, "ok")
