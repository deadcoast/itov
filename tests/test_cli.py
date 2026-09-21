import json
import subprocess
import sys

import pytest

from itov.cli import main
from itov.config import initialize
from itov.doctor import Check, diagnose


def test_module_entrypoint():
    result = subprocess.run(
        [sys.executable, "-m", "itov", "--version"], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "itov 0.1.0"


def test_cli_init_and_refused_overwrite(tmp_path, capsys):
    args = ["init", str(tmp_path / "work"), "--json"]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert main(args) == 2
    assert "already has a configuration" in json.loads(capsys.readouterr().out)["error"]


def test_live_validation_performs_only_metadata_get(tmp_path, graph, http_server, capsys):
    url, _routes, requests = http_server
    config = initialize(tmp_path / "work", tmp_path / "comfy", url=url)
    workflow = tmp_path / "workflow.json"
    workflow.write_text(json.dumps(graph))
    assert (
        main(
            [
                "workflow",
                "validate",
                str(workflow),
                "--live",
                "--config",
                str(config.file),
                "--json",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["scope"] == "node_schema" and result["valid"]
    assert requests == [("GET", "/object_info")]


def test_validation_exit_codes(tmp_path, capsys):
    workflow = tmp_path / "workflow.json"
    workflow.write_text('{"nodes": []}')
    args = ["workflow", "validate", str(workflow), "--json"]
    assert main(args) == 1
    assert not json.loads(capsys.readouterr().out)["valid"]
    workflow.write_text('{"broken"')
    assert main(args) == 2
    assert "error" in json.loads(capsys.readouterr().out)


@pytest.mark.parametrize("content", ["null", "[]", "{}"])
def test_explicit_invalid_registry_cannot_fall_back_to_structure(tmp_path, graph, capsys, content):
    workflow = tmp_path / "workflow.json"
    workflow.write_text(json.dumps(graph))
    registry = tmp_path / "registry.json"
    registry.write_text(content)
    assert (
        main(["workflow", "validate", str(workflow), "--object-info", str(registry), "--json"]) == 2
    )
    assert "node registry" in json.loads(capsys.readouterr().out)["error"]


@pytest.mark.parametrize("timeout", ["0", "-1", "nan", "inf", "61"])
def test_invalid_timeout_is_reported_before_io(timeout, capsys):
    assert main(["doctor", "--timeout", timeout, "--json"]) == 2
    assert "Timeout" in json.loads(capsys.readouterr().out)["error"]


def test_offline_diagnostics_keep_missing_runtime_visible(tmp_path, monkeypatch):
    config = initialize(tmp_path / "work", tmp_path / "absent")

    def no_http(*_a, **_k):
        raise AssertionError("Offline diagnosis attempted HTTP")

    monkeypatch.setattr("itov.doctor.ComfyUIClient", no_http)
    monkeypatch.setattr("itov.doctor._tool_check", lambda name, *_a: Check(name, "pass", "fixture"))
    report = diagnose(config, offline=True)
    assert not report["ok"]
    checks = {check["name"]: check for check in report["checks"]}
    assert checks["comfyui.installation"]["status"] == "fail"
    assert checks["comfyui.python"]["status"] == "fail"
    assert checks["comfyui.api"]["status"] == "skip"


def test_live_doctor_reports_cpu_server_without_claiming_cuda(tmp_path, http_server, monkeypatch):
    url, routes, requests = http_server
    config = initialize(tmp_path / "work", tmp_path / "comfy", url=url)
    routes["/system_stats"][1]["devices"] = [{"name": "fixture CPU", "type": "cpu"}]
    monkeypatch.setattr("itov.doctor._tool_check", lambda name, *_a: Check(name, "pass", "fixture"))
    report = diagnose(config)
    assert not report["ok"]
    assert (
        next(check for check in report["checks"] if check["name"] == "comfyui.cuda")["status"]
        == "fail"
    )
    assert requests == [("GET", "/system_stats"), ("GET", "/object_info")]


def test_server_failure_has_no_success_report(tmp_path, http_server, monkeypatch):
    url, routes, requests = http_server
    config = initialize(tmp_path / "work", tmp_path / "comfy", url=url)
    routes["/system_stats"] = 500, {}
    monkeypatch.setattr("itov.doctor._tool_check", lambda name, *_a: Check(name, "pass", "fixture"))
    report = diagnose(config)
    assert not report["ok"] and report["server"] is None
    assert requests == [("GET", "/system_stats")]
