import ctypes
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from itov import device, windows_process
from itov.windows_process import Job, host_memory, process_identity, process_memory, process_state

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Native Windows qualification")
GPU = "GPU-19396af4-e5de-4d99-a258-803d73f4af12"


def test_process_identity_is_observational_and_handles_pid_reuse():
    identity = process_identity(os.getpid())
    assert process_state(identity) == "alive"
    assert process_state({**identity, "created": identity["created"] - 1}) == "dead"
    assert process_state(identity) == "alive"
    memory = process_memory(identity)
    assert memory["peak_commit"] >= memory["private"] > 0
    assert memory["peak_working"] >= memory["working"] > 0
    host = host_memory()
    assert 0 < host["available_physical"] <= host["total_physical"]
    assert 0 < host["available_commit"] <= host["total_commit"]


def test_access_denied_is_unknown_not_dead(monkeypatch):
    class Denied:
        def OpenProcess(self, *args):
            ctypes.set_last_error(5)
            return 0

    monkeypatch.setattr(windows_process, "api", lambda: Denied())
    with pytest.raises(OSError):
        process_state({"pid": 123, "created": 456})


def test_suspended_creation_registration_and_confirmed_shutdown(tmp_path):
    registry = tmp_path / "registry"
    touched = tmp_path / "worker-ran"
    with device.Lease(GPU, tmp_path / "workspace-a", "plan", root=registry) as lease:
        pool = Job(lease.value["job_name"])
        try:
            command = [
                sys.executable,
                "-c",
                "import sys,time;from pathlib import Path;"
                "Path(sys.argv[1]).write_text('ran');time.sleep(30)",
                str(touched),
            ]
            child = pool.spawn(command, str(tmp_path))
            time.sleep(0.1)
            assert not touched.exists()
            lease.register(child)
            pool.resume(child)
            deadline = time.monotonic() + 10
            while not touched.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert touched.read_text() == "ran"
            with pytest.raises(ValueError, match="not stopped"):
                lease.release()
        finally:
            pool.stop()
        assert process_state(child) == "dead"
        lease.release()
    assert device.status(GPU, root=registry)["status"] == "idle"


def test_cross_workspace_process_contention_and_release(tmp_path):
    registry = tmp_path / "registry"
    code = (
        "from pathlib import Path;import sys;from itov.device import Lease;\n"
        "with Lease(sys.argv[1],Path(sys.argv[2]),'other',root=Path(sys.argv[3])) as lease: "
        "lease.release()"
    )
    command = [sys.executable, "-c", code, GPU, str(tmp_path / "workspace-b"), str(registry)]
    with device.Lease(GPU, tmp_path / "workspace-a", "first", root=registry) as lease:
        assert device.status(GPU, root=registry)["owner"]["pid"] == os.getpid()
        refused = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        assert refused.returncode != 0 and "holds the lock" in refused.stderr
        lease.release()
    admitted = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert admitted.returncode == 0, admitted.stderr


@pytest.mark.parametrize("register", [False, True])
def test_controller_crash_kills_job_and_requires_explicit_recovery(tmp_path, register):
    registry, ready = tmp_path / "registry", tmp_path / "ready.json"
    code = """
import json,os,sys
from pathlib import Path
from itov.device import Lease
from itov.windows_process import Job
with Lease(sys.argv[1],Path(sys.argv[2]),'crashed',root=Path(sys.argv[3])) as lease:
    pool=Job(lease.value['job_name'])
    child=pool.spawn([sys.executable,'-c','import time;time.sleep(30)'],sys.argv[2])
    if sys.argv[5]=='True': lease.register(child)
    pool.resume(child)
    Path(sys.argv[4]).write_text(json.dumps({'child':child,'lease':lease.value}))
    os._exit(23)
"""
    result = subprocess.run(
        [sys.executable, "-c", code, GPU, str(tmp_path), str(registry), str(ready), str(register)],
        capture_output=True,
        text=True,
        timeout=20,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert result.returncode == 23, result.stderr
    evidence = json.loads(ready.read_bytes())
    deadline = time.monotonic() + 10
    while process_state(evidence["child"]) != "dead" and time.monotonic() < deadline:
        time.sleep(0.02)
    assert process_state(evidence["child"]) == "dead"
    assert device.status(GPU, root=registry)["status"] == "held"
    with pytest.raises(ValueError, match="Unreleased"):
        with device.Lease(GPU, tmp_path / "other", "new", root=registry):
            pytest.fail("Abandoned ownership admitted a new controller")
    with pytest.raises(ValueError, match="changed"):
        device.recover(GPU, str(uuid.uuid4()), root=registry)
    assert device.recover(GPU, evidence["lease"]["lease_id"], root=registry)["status"] == "idle"
    assert (device.directory(GPU, registry) / (evidence["lease"]["lease_id"] + ".json")).is_file()
    with device.Lease(GPU, tmp_path / "other", "new", root=registry) as lease:
        lease.release()


def test_live_or_unknown_owner_cannot_be_recovered(tmp_path, monkeypatch):
    with device.Lease(GPU, tmp_path, "unfinished", root=tmp_path / "registry") as lease:
        token = lease.value["lease_id"]
    with pytest.raises(ValueError, match="still alive"):
        device.recover(GPU, token, root=tmp_path / "registry")
    monkeypatch.setattr(
        device, "process_state", lambda identity: (_ for _ in ()).throw(PermissionError("unknown"))
    )
    with pytest.raises(PermissionError):
        device.recover(GPU, token, root=tmp_path / "registry")
    assert device.status(GPU, root=tmp_path / "registry")["status"] == "held"


def test_missing_initialized_journal_does_not_reset_ownership(tmp_path):
    registry = tmp_path / "registry"
    with device.Lease(GPU, tmp_path, "done", root=registry) as lease:
        lease.release()
    (device.directory(GPU, registry) / "current.json").unlink()
    with pytest.raises(ValueError, match="incomplete"):
        with device.Lease(GPU, tmp_path, "new", root=registry):
            pytest.fail("Missing journal reset ownership")


def test_hidden_worker_keeps_streams_alive_when_comfy_style_logging_wraps_them(tmp_path):
    from itov import worker_bootstrap

    script = tmp_path / "wrapped.py"
    script.write_text(
        "import sys,io,gc\n"
        "sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')\n"
        "sys.stderr=io.TextIOWrapper(sys.stderr.buffer,encoding='utf-8')\n"
        "gc.collect()\nprint('progress survived');sys.stdout.flush()\n",
        encoding="utf-8",
    )
    log = tmp_path / "worker.log"
    pool = Job("Global\\ITOV-log-test-" + str(uuid.uuid4()))
    try:
        child = pool.spawn(
            [sys.executable, str(Path(worker_bootstrap.__file__)), str(log), str(script)],
            str(tmp_path),
        )
        pool.resume(child)
        deadline = time.monotonic() + 10
        while process_state(child) == "alive" and time.monotonic() < deadline:
            time.sleep(0.02)
        assert "progress survived" in log.read_text(encoding="utf-8")
        assert "closed file" not in log.read_text(encoding="utf-8")
    finally:
        pool.stop()
