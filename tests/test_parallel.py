import copy
import json
import os
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_audio import audio_case as audio_case
from test_audio import encoded_audio as encoded_audio
from test_audio import prepare_plan
from test_batch_execution import execution_case as execution_case
from test_vram import measured as measured

from itov import parallel, vram
from itov.batch import save_plan
from itov.batch_execution import abandon_batch, run_batch
from itov.catalog import canonical_bytes, sha256
from itov.comfyui import ComfyUIClient, ComfyUIError
from itov.execution_store import open_store
from itov.owned_jobs import job_path
from itov.runtime import profile_launch_command

GIB = 1024**3
GPU = "GPU-19396af4-e5de-4d99-a258-803d73f4af12"


@pytest.mark.parametrize("damage", [None, "node", "machine", "build", "edition", "release"])
def test_windows_marketing_name_alias_keeps_actual_host_and_build_bound(damage):
    observed = {
        "node": "host",
        "machine": "AMD64",
        "windows": ["11", "10.0.26200", "SP0", "Multiprocessor Free"],
    }
    current = copy.deepcopy(observed)
    current["windows"][0] = "10"  # Actual Python 3.11 result on this Windows 11 host.
    if damage in {"node", "machine"}:
        current[damage] += "-changed"
    elif damage == "build":
        current["windows"][1] = "10.0.26100"
    elif damage == "edition":
        current["windows"][3] = "Other"
    elif damage == "release":
        current["windows"][0] = "8.1"
    assert parallel.host_matches(observed, current) is (damage is None)
    assert parallel.host_matches(current, observed) is (damage is None)


def test_worker_runtime_isolation_preserves_shared_catalog_and_job_root(audio_case):
    config = audio_case[0]
    workers = parallel.worker_configs(config, [8191, 8192])
    paths = set()
    for worker in workers:
        for name in ("input", "output"):
            (worker.runtime_root / name).mkdir(parents=True)
        command = profile_launch_command(worker)
        assert worker.root == config.root and worker.file == config.file
        for name in (
            "--input-directory",
            "--output-directory",
            "--user-directory",
            "--temp-directory",
            "--database-url",
        ):
            value = command[command.index(name) + 1]
            assert value not in paths
            paths.add(value)
    assert len(paths) == 10 and len({worker.url for worker in workers}) == 2


@pytest.mark.parametrize("ports", [[8191], [8191, 8191], [80, 8192], [8191, 99999]])
def test_invalid_worker_ports_refused(audio_case, ports):
    with pytest.raises(ValueError):
        parallel.worker_configs(audio_case[0], ports)


@pytest.mark.parametrize("damage", ["count", "prompt", "seed", "video"])
def test_parallel_plan_is_exact_bounded_audio(audio_case, damage):
    plan = prepare_plan(audio_case)
    parallel.validate_plan(plan, calibrate=False)
    if damage == "count":
        plan["jobs"] *= 2
    else:
        job = plan["jobs"][0]
        graph = json.loads(job["workflow_json"])
        if damage == "prompt":
            graph["3"]["inputs"]["text"] += " changed"
        elif damage == "seed":
            job["seed"] = None
        else:
            graph["9"]["class_type"] = "SaveVideo"
        job["workflow_json"] = json.dumps(graph)
    with pytest.raises(ValueError):
        parallel.validate_plan(plan, calibrate=False)


@pytest.fixture
def admission_case(measured, monkeypatch):
    config, plan, receipt, profiles, gpu, live, *_ = measured
    for profile in profiles:
        for observation in profile["observations"]:
            observation["measurement"]["finished_at"] = datetime.now(UTC).isoformat()
    cals = [
        {
            "workers": [
                {
                    "profile": profile,
                    "process": {"pid": profile["observer"]["pid"]},
                    "host_memory": {"peak_working": 3 * GIB, "peak_commit": 4 * GIB},
                }
                for _ in range(2)
            ]
        }
        for profile in profiles
    ]
    # Use the actual evidence evaluator with synthetic counters; HTTP ownership is tested below.
    monkeypatch.setattr(
        vram,
        "check",
        lambda config, plan, profiles, receipt: vram.assess(plan, receipt, profiles, gpu, live),
    )
    return config, plan, receipt, cals, gpu, live


@pytest.mark.parametrize(
    "damage", [None, "device_sum", "physical", "commit", "repetition", "stale", "identity"]
)
def test_aggregate_gpu_and_measured_host_admission(admission_case, damage):
    config, plan, receipt, cals, gpu, _ = admission_case
    memory = {"available_physical": 24 * GIB, "available_commit": 24 * GIB}
    if damage == "device_sum":
        gpu["used_bytes"] = 24 * GIB  # Each 4 GiB envelope fits singly; their sum does not.
    elif damage in {"physical", "commit"}:
        memory["available_" + damage] = 8 * GIB
    elif damage == "repetition":
        cals[1] = copy.deepcopy(cals[0])
    elif damage == "stale":
        for cal in cals:
            for worker in cal["workers"]:
                for obs in worker["profile"]["observations"]:
                    obs["measurement"]["finished_at"] = (
                        datetime.now(UTC) - timedelta(days=8)
                    ).isoformat()
    elif damage == "identity":
        cals[0]["workers"][0]["process"]["pid"] += 1
    if damage == "identity":
        with pytest.raises(ValueError, match="owner differs"):
            parallel.admission([config] * 2, plan, [receipt] * 2, cals, memory=memory)
    else:
        result = parallel.admission([config] * 2, plan, [receipt] * 2, cals, memory=memory)
        assert result["admitted"] is (damage is None)
        if damage == "device_sum":
            assert result["reasons"] == ["aggregate_device_headroom"]


@pytest.fixture
def protocol(audio_case, encoded_audio, monkeypatch, tmp_path):
    config, spec, routes, requests = audio_case
    original_init = ComfyUIClient.__init__

    def initialize(client, url, **kwargs):
        original_init(client, config.url, **kwargs)

    monkeypatch.setattr(ComfyUIClient, "__init__", initialize)
    monkeypatch.setattr(parallel, "_start", lambda *args: {"pid": os.getpid(), "created": 1})
    monkeypatch.setattr(
        parallel,
        "qualify",
        lambda worker, plan: {
            "profile": "stock-stable-audio-v1",
            "worker": worker.url,
            "files": [],
        },
    )
    monkeypatch.setattr(
        parallel, "process_memory", lambda process: {"peak_working": GIB, "peak_commit": GIB}
    )
    monkeypatch.setattr(
        parallel,
        "host_memory",
        lambda: {"available_physical": 32 * GIB, "available_commit": 32 * GIB},
    )
    monkeypatch.setattr(vram, "gpu_snapshot", lambda: {"uuid": GPU, "free_bytes": 30 * GIB})
    monkeypatch.setattr(parallel, "load_calibration", lambda path: {"fixture": str(path)})
    monkeypatch.setattr(
        parallel, "admission", lambda *args, **kwargs: {"admitted": True, "reasons": []}
    )
    start = datetime.now(UTC)

    def collect(worker, plan, receipt, gpu):
        return {
            "issues": [],
            "observations": [
                {
                    "measurement": {
                        "started_at": start.isoformat(),
                        "finished_at": (start + timedelta(seconds=1)).isoformat(),
                    }
                }
            ],
        }, tmp_path / "fixture-profile"

    monkeypatch.setattr(vram, "collect_profile", collect)
    gate = threading.Barrier(2)
    history = routes["/history?max_items=200"][1]

    def submit(payload):
        prompt = str(uuid.uuid4())
        filename = prompt + ".flac"
        entry = {
            "prompt": [0, prompt, payload["prompt"], payload["extra_data"], ["9"]],
            "status": {"completed": True, "status_str": "success", "messages": []},
            "outputs": {
                "9": {"audio": [{"filename": filename, "subfolder": "", "type": "output"}]}
            },
        }
        history[prompt] = entry
        routes["/history/" + prompt] = (200, {prompt: entry})
        routes[f"/view?filename={filename}&subfolder=&type=output"] = (
            200,
            encoded_audio[0].read_bytes(),
        )
        if spec["count"] == 2:
            gate.wait(timeout=5)  # Proves both POST requests are in flight together.
        return {"prompt_id": prompt}

    routes["POST /prompt"] = (200, submit)

    def build(count=2):
        spec["count"] = count
        plan = prepare_plan(audio_case)
        return plan, save_plan(config.root, plan)

    return config, build, routes, requests, tmp_path / "registry"


def trial(case, path, **kwargs):
    config, _, _, _, registry = case
    return parallel.run(
        config,
        path,
        calibration_paths=[Path("one"), Path("two")],
        registry=registry,
        wait_timeout=1,
        **kwargs,
    )


def test_parallel_posts_owned_outputs_and_offline_completed_resume(protocol):
    config, build, routes, requests, _ = protocol
    plan, path = build()
    result = trial(protocol, path)
    assert result["ok"] and result["succeeded"] == 2
    assert len(routes["_posted"]) == 2
    records = [json.loads(job_path(config, plan["plan_id"], i).read_bytes()) for i in range(2)]
    assert len({r["request_id"] for r in records}) == 2
    assert len({r["prompt_id"] for r in records}) == 2
    assert len({r["artifacts"][0]["path"] for r in records}) == 2
    before = list(requests)
    assert parallel.resume(config, path)["succeeded"] == 2
    assert requests == before
    for function in (run_batch, abandon_batch):
        with pytest.raises(ValueError, match="Use parallel"):
            function(config, path)
    with pytest.raises(ValueError, match="already"):
        trial(protocol, path)
    assert len(routes["_posted"]) == 2


def test_lost_acknowledgement_reconciles_without_another_post(protocol, monkeypatch):
    _, build, routes, _, _ = protocol
    _, path = build()
    original = ComfyUIClient.submit

    def lost(client, *args):
        original(client, *args)
        raise ComfyUIError("Injected lost acknowledgement after acceptance")

    monkeypatch.setattr(ComfyUIClient, "submit", lost)
    assert trial(protocol, path)["succeeded"] == 2
    assert len(routes["_posted"]) == 2


@pytest.mark.parametrize("when", [1, 2])
def test_refusal_preserves_preclaim_or_reserved_boundary(protocol, monkeypatch, when):
    config, build, routes, _, _ = protocol
    _, path = build()
    calls = []

    def decide(*args, **kwargs):
        calls.append(1)
        return {"admitted": len(calls) != when, "reasons": ["host_available_commit"]}

    monkeypatch.setattr(parallel, "admission", decide)
    with pytest.raises(ValueError, match="admission"):
        trial(protocol, path)
    assert not routes.get("_posted")
    with open_store(config, create=False) as db:
        assert db.execute("SELECT COUNT(*) FROM seeds").fetchone()[0] == (0 if when == 1 else 2)


def test_worker_failure_requires_confirmed_exit_and_keeps_uncertain_evidence(protocol, monkeypatch):
    config, build, routes, _, registry = protocol
    plan, path = build()
    monkeypatch.setattr(
        parallel, "_observe", lambda *args: (_ for _ in ()).throw(ComfyUIError("worker exited"))
    )
    with pytest.raises(ComfyUIError):
        trial(protocol, path)
    records = [job_path(config, plan["plan_id"], i).read_bytes() for i in range(2)]
    with pytest.raises(ValueError, match="not restarted"):
        parallel.resume(config, path)
    monkeypatch.setattr(parallel, "process_state", lambda p: "alive")
    with pytest.raises(ValueError, match="termination"):
        parallel.recover(config, path, registry=registry)
    monkeypatch.setattr(parallel, "process_state", lambda p: "dead")
    assert parallel.recover(config, path, registry=registry)["status"] == "abandoned"
    assert records == [job_path(config, plan["plan_id"], i).read_bytes() for i in range(2)]
    with open_store(config, create=False) as db:
        assert db.execute("SELECT COUNT(*) FROM seeds").fetchone()[0] == 2
    assert len(routes["_posted"]) == 2


def test_calibration_remains_serial_and_records_both_workers(protocol):
    config, build, routes, _, registry = protocol
    _, path = build(4)
    result = parallel.run(config, path, calibrate=True, registry=registry, wait_timeout=1)
    assert result["ok"] and result["succeeded"] == 4
    assert result["scope"] == "two_worker_audio_calibration"
    assert len(result["document"]["workers"]) == 2 and len(routes["_posted"]) == 4


@pytest.mark.parametrize("damage", [None, "host", "order", "peak", "profile", "missing", "hash"])
def test_calibration_integrity_and_host_measurement_binding(audio_case, damage):
    config = audio_case[0]
    profile = {"profile_id": sha256(canonical_bytes({}))}
    body = {
        "version": 1,
        "scope": "two_worker_audio_calibration",
        "plan_id": "a" * 64,
        "captured_at": datetime.now(UTC).isoformat(),
        "host_identity": parallel.host_identity(),
        "policy": parallel.POLICY,
        "lease": {},
        "admission": {},
        "workers": [
            {
                "index": i,
                "profile": profile,
                "profile_path": "unused",
                "process": {"pid": 10 + i, "created": 100},
                "host_memory": {
                    "peak_working": 4 * GIB,
                    "working": GIB,
                    "peak_commit": 5 * GIB,
                    "private": 2 * GIB,
                },
            }
            for i in range(2)
        ],
    }
    if damage == "host":
        body["host_identity"]["node"] += "-different"
    elif damage == "order":
        body["workers"].reverse()
    elif damage == "peak":
        body["workers"][0]["host_memory"]["peak_commit"] = GIB
    elif damage == "profile":
        profile["changed"] = True
    elif damage == "missing":
        del body["host_identity"]
    value, path = parallel.save_document(config, "calibrations", body, "calibration_id")
    if damage == "hash":
        value["workers"][0]["host_memory"]["peak_commit"] += 1
        path.write_bytes(canonical_bytes(value) + b"\n")
    if damage is None:
        assert parallel.load_calibration(path) == value
    else:
        with pytest.raises(ValueError):
            parallel.load_calibration(path)


def test_nonoverlapping_success_does_not_qualify_and_retains_final_admission(protocol, monkeypatch):
    _, build, _, _, _ = protocol
    _, path = build()
    original = vram.collect_profile
    calls = []

    def collect(*args):
        profile, saved = original(*args)
        if calls:
            metric = profile["observations"][0]["measurement"]
            start = datetime.fromisoformat(metric["finished_at"]) + timedelta(seconds=1)
            metric.update(started_at=start.isoformat(), finished_at=start.isoformat())
        calls.append(1)
        return profile, saved

    decisions = iter(
        [
            {"admitted": True, "reasons": [], "sequence": 1},
            {"admitted": True, "reasons": [], "sequence": 2},
        ]
    )
    monkeypatch.setattr(parallel, "admission", lambda *args: next(decisions))
    monkeypatch.setattr(vram, "collect_profile", collect)
    result = trial(protocol, path)
    assert result["succeeded"] == 2 and not result["ok"]
    assert result["document"]["overlap_ns"] == 0
    assert result["document"]["admission"]["sequence"] == 2
