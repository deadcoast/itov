import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_audio import audio_case as audio_case
from test_audio import prepare_plan
from test_batch_execution import execution_case as execution_case

from itov import vram, vram_identity, vram_runtime
from itov.batch import save_plan
from itov.batch_execution import run_batch
from itov.catalog import canonical_bytes, sha256
from itov.comfyui import parse_json
from itov.execution_store import open_store
from itov.qualification import qualify, save_qualification
from itov.runtime import profile_launch_command, profile_main_argv
from itov.vram_identity import MARKER, workload_key

GIB = 1024**3
NOW = datetime(2026, 9, 21, 22, tzinfo=UTC)


@pytest.fixture
def measured(audio_case, monkeypatch):
    config, spec, routes, requests = audio_case
    plan = prepare_plan(audio_case)
    routes["/system_stats"][1]["system"]["argv"] = profile_main_argv(config) + [MARKER]
    for name in (
        "execution.py",
        "comfy/model_management.py",
        "comfy/model_patcher.py",
        "comfy/memory_management.py",
    ):
        path = config.comfyui_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"runtime source fixture")
    observer = {
        "version": 1,
        "session_id": "test-session",
        "pid": 123,
        "started_at": NOW.isoformat(),
        "bootstrap_sha256": sha256(Path(vram_runtime.__file__).read_bytes()),
        "identity_sha256": sha256(Path(vram_identity.__file__).read_bytes()),
        "device": {"index": 0, "uuid": "gpu-fixture", "name": "synthetic", "total_bytes": 32 * GIB},
        "allocator_backend": "native",
        "packages": {"torch": "fixture"},
    }
    live = {
        "identity": observer,
        "state": {"executions": 0, "active": None, "last_workload": None, "errors": []},
        "memory": {
            "global_total_bytes": 32 * GIB,
            "global_free_bytes": 30 * GIB,
            "allocated_bytes": 0,
            "reserved_bytes": 0,
        },
    }
    routes["/itov/vram"] = (200, live)
    gpu = {
        "uuid": "GPU-fixture",
        "name": "synthetic",
        "driver": "fixture",
        "total_bytes": 32 * GIB,
        "used_bytes": 2 * GIB,
        "free_bytes": 30 * GIB,
    }
    monkeypatch.setattr(vram, "gpu_snapshot", lambda: gpu)
    receipt = qualify(config, plan)
    key = workload_key(parse_json(plan["jobs"][0]["workflow_json"]))
    profiles = []
    for index in range(2):
        observations = []
        for sequence in range(2):
            metric = {
                "version": 1,
                "execution_success": True,
                "errors": [],
                "finished_at": NOW.isoformat(),
                "session_id": f"session-{index}",
                "sequence": sequence,
                "workload_key": key,
                "previous_workload": key if sequence else None,
                "duration_ns": 200_000_001,
                "peak_allocated_bytes": 3 * GIB,
                "peak_reserved_bytes": 4 * GIB,
                "samples": [
                    {
                        "elapsed_ns": t,
                        "global_total_bytes": 32 * GIB,
                        "global_free_bytes": free * GIB,
                        "allocated_bytes": allocated * GIB,
                        "reserved_bytes": reserved * GIB,
                    }
                    for t, free, allocated, reserved in [
                        (1, 30, 0, 0),
                        (100_000_000, 27, 3, 4),
                        (200_000_000, 29, 1, 4),
                    ]
                ],
            }
            observations.append(
                {
                    "cache_state": "cold_process" if sequence == 0 else "warm_exact",
                    "measurement": metric,
                }
            )
        body = {
            "version": 1,
            "scope": "exact_workload_vram_observations",
            "captured_at": NOW.isoformat(),
            "plan_id": plan["plan_id"],
            "qualification_id": receipt["qualification_id"],
            "gpu": gpu,
            "observer": observer,
            "limits": "Synthetic unit-test measurements, not GPU qualification.",
            "runtime_key": vram.fingerprint(receipt, gpu),
            "observations": observations,
            "issues": [],
        }
        profile, _ = vram._save(config, "profiles", body, "profile_id")
        profiles.append(profile)
    return config, plan, receipt, profiles, gpu, live, routes, requests


def assess(case, **kwargs):
    _, plan, receipt, profiles, gpu, live, _, _ = case
    return vram.assess(plan, receipt, profiles, gpu, live, now=NOW, **kwargs)


def test_repeated_exact_cold_warm_measurements_admit_one_worker(measured):
    result = assess(measured)
    assert result["admitted"] and not result["reasons"]
    assert result["estimates"][0]["additional_envelope_bytes"] == 4 * GIB
    assert result["policy"]["reserve_bytes"] == 2 * GIB
    assert assess(measured, workers=2)["reasons"] == ["parallel_execution_not_qualified"]


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "duplicate_session",
        "stale",
        "gap",
        "failed",
        "peak",
        "cache",
        "source",
        "prompt",
        "dimensions",
        "driver",
        "device",
        "headroom",
        "live_cache",
        "busy",
    ],
)
def test_unknown_stale_or_unsafe_capacity_is_refused(measured, damage):
    _, plan, receipt, profiles, gpu, live, _, _ = measured
    if damage == "missing":
        profiles.clear()
    elif damage == "duplicate_session":
        profiles[1] = copy.deepcopy(profiles[0])
    elif damage in {"stale", "gap", "failed", "peak", "cache"}:
        for profile in profiles:
            for obs in profile["observations"]:
                metric = obs["measurement"]
                if damage == "stale":
                    metric["finished_at"] = (NOW - timedelta(days=8)).isoformat()
                elif damage == "gap":
                    metric["samples"][-1]["elapsed_ns"] = 5_000_000_000
                elif damage == "failed":
                    metric["errors"] = ["OOM"]
                elif damage == "peak":
                    metric["peak_reserved_bytes"] = 0
                else:
                    obs["cache_state"] = "mixed"
    elif damage == "source":
        receipt["files"][0]["sha256"] = "a" * 64
    elif damage in {"prompt", "dimensions"}:
        for job in plan["jobs"]:
            graph = json.loads(job["workflow_json"])
            if damage == "prompt":
                graph["3"]["inputs"]["text"] += " changed"
            else:
                graph["6"]["inputs"]["seconds"] += 1
            job["workflow_json"] = json.dumps(graph)
    elif damage == "driver":
        gpu["driver"] = "changed"
    elif damage == "device":
        gpu["uuid"] = "GPU-other"
    elif damage == "headroom":
        gpu["used_bytes"] = 30 * GIB
    elif damage == "live_cache":
        live["state"].update(executions=2, last_workload="other")
    else:
        live["state"]["active"] = "other"
    if damage == "device":
        with pytest.raises(ValueError, match="identities"):
            assess(measured)
    else:
        assert not assess(measured)["admitted"]


def test_seed_output_name_and_lossless_float_conversion_share_footprint(measured):
    graph = json.loads(measured[1]["jobs"][0]["workflow_json"])
    key = workload_key(graph)
    graph["7"]["inputs"]["seed"] += 100
    graph["9"]["inputs"]["filename_prefix"] = "other/path"
    graph["5"]["inputs"]["seconds_start"] = 0.0
    assert workload_key(graph) == key
    graph["7"]["inputs"]["steps"] += 1
    assert workload_key(graph) != key


def test_observer_source_and_session_are_bound(measured):
    config, plan, original, _, gpu, live, _, _ = measured
    live["identity"]["session_id"] = "another-session"
    receipt = qualify(config, plan)
    assert receipt["qualification_id"] != original["qualification_id"]
    assert vram.fingerprint(receipt, gpu) == vram.fingerprint(original, gpu)
    live["identity"]["bootstrap_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="observer source"):
        qualify(config, plan)


def test_profile_hash_tampering_is_refused(measured):
    config, _, _, profiles, *_ = measured
    path = config.root / "state/vram/profiles" / (profiles[0]["profile_id"] + ".json")
    value = json.loads(path.read_bytes())
    value["observations"][0]["measurement"]["peak_reserved_bytes"] = 0
    path.write_bytes(canonical_bytes(value) + b"\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        vram.load_profile(path)


def test_guarded_refusal_precedes_seed_claim_or_submission(measured, monkeypatch):
    config, plan, receipt, profiles, _, _, routes, _ = measured
    path = save_plan(config.root, plan)
    qpath = save_qualification(config, receipt)
    ppath = config.root / "state/vram/profiles" / (profiles[0]["profile_id"] + ".json")
    monkeypatch.setattr(
        vram,
        "check",
        lambda *args, **kwargs: {"admitted": False, "reasons": ["insufficient_headroom"]},
    )
    with pytest.raises(ValueError, match="VRAM admission refused"):
        run_batch(config, path, qualification=qpath, vram_profiles=[ppath])
    assert not routes.get("_posted", [])
    with open_store(config, create=False) as db:
        assert db.execute("SELECT COUNT(*) FROM seeds").fetchone()[0] == 0


def test_guard_persists_on_resume_and_missing_binding_fails_closed(measured, monkeypatch):
    config, plan, receipt, profiles, _, _, routes, _ = measured
    path = save_plan(config.root, plan)
    qpath = save_qualification(config, receipt)
    paths = [config.root / "state/vram/profiles" / (p["profile_id"] + ".json") for p in profiles]
    calls = []

    def checked(*args, **kwargs):
        calls.append(1)
        return {
            "admitted": len(calls) == 1,
            "reasons": [] if len(calls) == 1 else ["insufficient_headroom"],
        }

    monkeypatch.setattr(vram, "check", checked)
    result = run_batch(config, path, qualification=qpath, vram_profiles=paths)
    assert result["status"] == "paused" and not routes.get("_posted", [])
    assert run_batch(config, path, resume=True)["status"] == "paused"
    assert len(calls) == 3 and not routes.get("_posted", [])
    guard = config.root / "state/vram/guards" / (plan["plan_id"] + ".json")
    raw = guard.read_bytes()
    guard.unlink()
    with pytest.raises(ValueError, match="guard is missing"):
        run_batch(config, path, resume=True)
    guard.write_bytes(raw)
    with pytest.raises(ValueError, match="Cannot replace"):
        run_batch(config, path, resume=True, vram_profiles=paths[:1])


def test_profile_launcher_is_explicit_and_does_not_modify_stock_command(measured):
    config = measured[0]
    command = profile_launch_command(config)
    assert Path(command[2]).name == "vram_runtime.py" and command[4] == "--"
    assert "--disable-all-custom-nodes" in command and "--database-url" in command


@pytest.mark.parametrize("counter", [None, True, -1, "10"])
def test_invalid_measurement_counters_fail_closed(measured, counter):
    for profile in measured[3]:
        profile["observations"][0]["measurement"]["samples"][0]["reserved_bytes"] = counter
    assert not assess(measured)["admitted"]


def test_busy_queue_refuses_even_when_memory_fits(measured, monkeypatch):
    config, plan, receipt, profiles, _, _, routes, _ = measured
    monkeypatch.setattr(
        vram, "assess", lambda *args, **kwargs: {"ok": True, "admitted": True, "reasons": []}
    )
    routes["/queue"] = (200, {"queue_running": [[1, "foreign-job"]], "queue_pending": []})
    result = vram.check(config, plan, profiles, receipt=receipt)
    assert not result["admitted"] and result["reasons"] == ["server_queue_busy"]


def test_claim_commits_guard_and_seeds_in_one_transaction(measured):
    from itov.execution_store import claim

    config, plan, receipt, *_ = measured
    with open_store(config, create=True) as db:
        claim(db, config, plan, receipt, vram_guard_id="a" * 64)
        assert db.execute("SELECT COUNT(*) FROM seeds").fetchone()[0] == 2
        assert (
            db.execute("SELECT status FROM events WHERE status LIKE 'vram_guard:%'").fetchone()[0]
            == "vram_guard:" + "a" * 64
        )


@pytest.mark.parametrize("fail", [False, True])
def test_observer_measures_worker_process_and_retains_failed_execution(tmp_path, monkeypatch, fail):
    import sys
    import time
    import types
    import uuid

    class Executor:
        success = True

        def execute(self, *args):
            time.sleep(0.08)
            if fail:
                raise RuntimeError("synthetic execution failure")
            return "completed"

    class Routes:
        def get(self, path):
            return lambda function: function

    class Server:
        def __init__(self):
            self.routes = Routes()

    counters = {"synchronize": 0, "reset": 0}

    def synchronize(device):
        counters["synchronize"] += 1

    def reset(device):
        counters["reset"] += 1

    cuda = types.SimpleNamespace(
        is_available=lambda: True,
        device_count=lambda: 1,
        current_device=lambda: 0,
        get_device_properties=lambda device: types.SimpleNamespace(
            name="fixture", uuid="fixture", total_memory=32 * GIB
        ),
        get_allocator_backend=lambda: "native",
        mem_get_info=lambda device: (30 * GIB, 32 * GIB),
        memory_allocated=lambda device: GIB,
        memory_reserved=lambda device: 2 * GIB,
        max_memory_allocated=lambda device: 3 * GIB,
        max_memory_reserved=lambda device: 4 * GIB,
        synchronize=synchronize,
        reset_peak_memory_stats=reset,
    )
    torch = types.SimpleNamespace(
        cuda=cuda,
        version=types.SimpleNamespace(cuda="fixture"),
        backends=types.SimpleNamespace(cudnn=types.SimpleNamespace(version=lambda: 1)),
    )
    for name, module in {
        "torch": torch,
        "execution": types.SimpleNamespace(PromptExecutor=Executor),
        "server": types.SimpleNamespace(PromptServer=Server),
        "aiohttp": types.SimpleNamespace(
            web=types.SimpleNamespace(json_response=lambda data: data)
        ),
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(vram_runtime.importlib.metadata, "version", lambda name: "fixture")
    vram_runtime.install(tmp_path, {"encoded": vram_identity.encoded, "workload_key": workload_key})
    executor = Executor()
    prompt_id = str(uuid.uuid4())
    graph = {"1": {"class_type": "KSampler", "inputs": {"seed": 123}}}
    if fail:
        with pytest.raises(RuntimeError, match="synthetic execution"):
            executor.execute(graph, prompt_id, {"itov_request_id": "owned"})
    else:
        assert executor.execute(graph, prompt_id, {"itov_request_id": "owned"}) == "completed"
    record = json.loads(next(tmp_path.glob("*/" + prompt_id + ".json")).read_bytes())
    assert record["request_id"] == "owned" and record["execution_success"] is not fail
    assert record["peak_allocated_bytes"] == 3 * GIB and record["peak_reserved_bytes"] == 4 * GIB
    assert len(record["samples"]) >= 3 and counters == {"synchronize": 2, "reset": 1}
    assert bool(record["errors"]) is fail
