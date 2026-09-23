"""Bounded two-worker audio trials with one workspace claim and one device lease."""

from __future__ import annotations

import platform
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from itov import device, vram
from itov.batch import load_plan
from itov.batch_execution import _lock
from itov.catalog import canonical_bytes, integer, object_fields, read_document, require, sha256
from itov.catalog_store import CatalogStore, _atomic_write
from itov.comfyui import ComfyUIClient, parse_json
from itov.config import Config
from itov.execution_store import check_run, claim, open_store, record_job, record_run, report
from itov.jobs import _now
from itov.locking import file_lock
from itov.owned_jobs import observe_owned, prepare_owned, read_owned, submit_owned
from itov.qualification import qualify, safe_path
from itov.runtime import profile_launch_command
from itov.vram_identity import workload_key
from itov.windows_process import Job, host_memory, job_active, process_memory, process_state

POLICY = {
    "version": 1,
    "workers": 2,
    "host_reserve_bytes": 4 * 1024**3,
    "uncertainty_percent": 20,
    "minimum_overlap_ns": 100_000_000,
}
AUDIO_NODES = {
    "CheckpointLoaderSimple",
    "CLIPLoader",
    "CLIPTextEncode",
    "EmptyLatentAudio",
    "ConditioningStableAudio",
    "KSampler",
    "VAEDecodeAudio",
    "SaveAudioAdvanced",
}


def save_document(config: Config, category: str, body: dict, field="record_id"):
    value = {**body, field: sha256(canonical_bytes(body))}
    path = safe_path(config.root, f"state/parallel/{category}/{value[field]}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical_bytes(value) + b"\n"
    if path.exists():
        require(path.read_bytes() == raw, "Parallel evidence differs; preserve and inspect")
    else:
        _atomic_write(path, raw, exclusive=True)
    return value, path


def load_calibration(path: Path) -> dict:
    raw = read_document(path)
    value = parse_json(raw)
    object_fields(
        value,
        {
            "version",
            "scope",
            "plan_id",
            "captured_at",
            "host_identity",
            "policy",
            "workers",
            "lease",
            "admission",
            "calibration_id",
        },
        "Parallel calibration",
    )
    body = {k: v for k, v in value.items() if k != "calibration_id"}
    require(
        value.get("calibration_id") == sha256(canonical_bytes(body))
        and raw == canonical_bytes(value) + b"\n",
        "Parallel calibration integrity differs",
    )
    require(
        type(value["version"]) is int
        and value["version"] == 1
        and value.get("scope") == "two_worker_audio_calibration"
        and value.get("policy") == POLICY
        and isinstance(value["workers"], list)
        and len(value.get("workers", [])) == 2,
        "Unsupported parallel calibration",
    )
    require(host_matches(value["host_identity"], host_identity()), "Host platform identity differs")
    for index, entry in enumerate(value["workers"]):
        object_fields(
            entry,
            {"index", "profile", "profile_path", "process", "host_memory"},
            "Calibration worker",
        )
        require(
            type(entry["index"]) is int and entry["index"] == index,
            "Calibration worker order differs",
        )
        object_fields(entry["process"], {"pid", "created"}, "Calibration process")
        for key in ("pid", "created"):
            integer(entry["process"][key], key, minimum=1)
        object_fields(
            entry["host_memory"],
            {"peak_working", "working", "peak_commit", "private"},
            "Calibration host memory",
        )
        for key, amount in entry["host_memory"].items():
            integer(amount, key, minimum=1)
        require(
            entry["host_memory"]["peak_working"] >= entry["host_memory"]["working"]
            and entry["host_memory"]["peak_commit"] >= entry["host_memory"]["private"],
            "Invalid host memory peaks",
        )
        require(isinstance(entry["profile"], dict), "Invalid calibration VRAM profile")
        profile = entry["profile"]
        require(
            profile.get("profile_id")
            == sha256(canonical_bytes({k: v for k, v in profile.items() if k != "profile_id"})),
            "Embedded VRAM profile integrity differs",
        )
    return value


def host_identity():
    return {
        "node": platform.node(),
        "machine": platform.machine(),
        "windows": list(platform.win32_ver()),
    }


def host_matches(observed, current):
    """Python 3.11 calls the same Windows 11 kernel '10'; keep the actual build bound."""
    if observed == current:
        return True
    if not isinstance(observed, dict) or set(observed) != set(current):
        return False
    windows = observed.get("windows")
    live = current["windows"]
    return (
        isinstance(windows, list)
        and len(windows) == len(live) == 4
        and windows[0] in {"10", "11"}
        and live[0] in {"10", "11"}
        and windows[1:] == live[1:]
        and live[1].startswith("10.0.")
        and observed["node"] == current["node"]
        and observed["machine"] == current["machine"]
    )


def worker_configs(config: Config, ports: list[int]) -> list[Config]:
    require(
        len(ports) == 2 and len(set(ports)) == 2, "Exactly two distinct worker ports are required"
    )
    result = []
    for index, port in enumerate(ports):
        integer(port, "port", minimum=1024)
        require(port <= 65535, "Invalid worker port")
        root = safe_path(config.root, f"state/parallel/workers/{index}")
        result.append(replace(config, url=f"http://127.0.0.1:{port}", worker_root=root))
    require(
        all(item.url != config.url for item in result), "Worker ports overlap the configured server"
    )
    return result


def validate_plan(plan: dict, *, calibrate: bool):
    require(
        len(plan["jobs"]) == (4 if calibrate else 2),
        "Calibration needs four jobs; a parallel trial needs two",
    )
    keys = set()
    for job in plan["jobs"]:
        graph = parse_json(job["workflow_json"])
        kinds = [node["class_type"] for node in graph.values()]
        require(
            set(kinds) <= AUDIO_NODES
            and kinds.count("KSampler") == 1
            and kinds.count("SaveAudioAdvanced") == 1
            and job["seed"] is not None,
            "This gate supports one explicit, stock audio sampler/output per job",
        )
        keys.add(workload_key(graph))
    require(len(keys) == 1, "All workers must run the same exact audio workload")


def assignments(plan: dict, calibrate: bool):
    return (
        [plan["jobs"][:2], plan["jobs"][2:]]
        if calibrate
        else [[plan["jobs"][0]], [plan["jobs"][1]]]
    )


def admission(configs, plan, receipts, calibrations, *, memory=None) -> dict:
    require(len(calibrations) >= 2, "Two independent calibration sessions are required")
    memory = memory or host_memory()
    checks, host_peaks = [], []
    for index, config in enumerate(configs):
        entries = [cal["workers"][index] for cal in calibrations]
        profiles = [entry["profile"] for entry in entries]
        checks.append(vram.check(config, plan, profiles, receipt=receipts[index]))
        peaks = []
        for entry in entries:
            require(
                entry["process"]["pid"] == entry["profile"]["observer"]["pid"],
                "Host measurement owner differs",
            )
            for key in ("peak_working", "peak_commit"):
                integer(entry["host_memory"][key], "host " + key, minimum=1)
            peaks.append(
                max(entry["host_memory"]["peak_working"], entry["host_memory"]["peak_commit"])
            )
        host_peaks.append(max(peaks))
    reasons = [reason for check in checks for reason in check["reasons"]]
    envelopes = [check["estimates"][0].get("additional_envelope_bytes", 0) for check in checks]
    additional = sum(envelopes)
    current = max(check["current_used_bytes"] for check in checks)
    capacity = min(check["gpu"]["total_bytes"] for check in checks)
    # Include the CUDA total (which can differ from NVIDIA's accounting).
    for check in checks:
        estimate = check["estimates"][0]
        if "headroom_bytes" in estimate:
            capacity = min(capacity, estimate["headroom_bytes"] + estimate["required_total_bytes"])
    required_gpu = (
        current + additional + (additional * 20 + 99) // 100 + vram.POLICY["reserve_bytes"]
    )
    required_host = (
        sum(host_peaks) + (sum(host_peaks) * 20 + 99) // 100 + POLICY["host_reserve_bytes"]
    )
    if required_gpu > capacity:
        reasons.append("aggregate_device_headroom")
    for name in ("available_physical", "available_commit"):
        integer(memory[name], name)
        if memory[name] < required_host:
            reasons.append("host_" + name)
    return {
        "version": 1,
        "scope": "bounded_two_worker_audio_admission",
        "admitted": not reasons,
        "checked_at": _now(),
        "policy": POLICY,
        "workers": checks,
        "host": memory,
        "host_peak_envelopes": host_peaks,
        "required_host_bytes": required_host,
        "required_gpu_bytes": required_gpu,
        "gpu_capacity_bytes": capacity,
        "reasons": sorted(set(reasons)),
        "limits": "Policy margins are not guarantees; unmanaged clients can race.",
    }


def _idle(url):
    queue = ComfyUIClient(url).queue()
    require(not queue["queue_running"] and not queue["queue_pending"], "Runtime queue is busy")


def _start(config, index, lease, job, log_root):
    for name in ("input", "output"):
        safe_path(config.runtime_root, name).mkdir(parents=True, exist_ok=True)
    port = int(config.url.rsplit(":", 1)[1])
    with socket.socket() as probe:
        probe.settimeout(0.2)
        require(probe.connect_ex(("127.0.0.1", port)) != 0, "Worker port is already occupied")
    command = profile_launch_command(config)
    log = log_root / f"worker-{index}.log"
    command = (
        command[:2] + [str(Path(__file__).with_name("worker_bootstrap.py")), str(log)] + command[2:]
    )
    process = job.spawn(command, str(config.comfyui_root))
    lease.register(process)  # Persist the suspended child's identity before any Python/CUDA work.
    job.resume(process)
    client = ComfyUIClient(config.url, timeout=1)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        require(
            process_state(process) == "alive", f"Owned worker exited during startup; inspect {log}"
        )
        try:
            live = client._json("/itov/vram")
        except OSError:
            live = None
        except Exception as error:
            from itov.comfyui import ComfyUIError

            if not isinstance(error, ComfyUIError):
                raise
            live = None
        if live is not None:
            require(
                live["identity"]["pid"] == process["pid"],
                "Worker endpoint is not the owned process",
            )
            require(
                live["state"]["executions"] == 0 and live["state"]["active"] is None,
                "Worker is not fresh",
            )
            return process
        time.sleep(0.1)
    raise ValueError(f"Worker startup timed out; inspect {log}")


def _fresh(config, plan, receipt):
    require(qualify(config, plan) == receipt, "Worker qualification changed before submission")
    _idle(config.url)


def _observe(config, plan, job, wait_timeout):
    return observe_owned(config, plan, job, timeout=5, wait_timeout=wait_timeout, poll_interval=0.1)


def run(
    config: Config,
    path: Path,
    *,
    calibrate=False,
    calibration_paths=None,
    ports=None,
    wait_timeout=900,
    registry=None,
) -> dict:
    from itov.execution_ownership import workspace_available
    from itov.jobs import _timing

    _timing(wait_timeout, 0.1)
    plan = load_plan(path)
    validate_plan(plan, calibrate=calibrate)
    configs = worker_configs(config, ports or [8191, 8192])
    groups = assignments(plan, calibrate)
    calibrations = [load_calibration(p) for p in (calibration_paths or [])]
    require(calibrate or len(calibrations) >= 2, "Qualify requires two calibration documents")
    require(
        not calibrate or not calibrations, "Calibration does not accept prior calibration documents"
    )
    with _lock(config), closing(open_store(config, create=True)) as db:
        workspace_available(config)
        require(
            db.execute("SELECT 1 FROM runs WHERE plan_id=?", (plan["plan_id"],)).fetchone() is None,
            "Plan already has an execution; use parallel resume or recover",
        )
        require(
            db.execute(
                "SELECT 1 FROM runs WHERE status NOT IN ('succeeded','failed','abandoned')"
            ).fetchone()
            is None,
            "Another batch retains workspace ownership",
        )
        _idle(config.url)
        gpu = vram.gpu_snapshot()
        with device.Lease(gpu["uuid"], config.root, plan["plan_id"], root=registry) as lease:
            pool = Job(lease.value["job_name"])
            claimed = False
            result = None
            try:
                log_root = safe_path(config.root, f"state/parallel/logs/{lease.value['lease_id']}")
                log_root.mkdir(parents=True)
                processes = [
                    _start(worker, i, lease, pool, log_root) for i, worker in enumerate(configs)
                ]
                receipts = [qualify(worker, plan) for worker in configs]
                require(
                    all(r["profile"] == "stock-stable-audio-v1" for r in receipts),
                    "Only the stock audio profile is qualified",
                )
                if calibrate:
                    memory = host_memory()
                    weights = sum(
                        f["bytes"]
                        for f in receipts[0]["files"]
                        if f["path"].endswith(".safetensors")
                    )
                    minimum = 2 * weights + POLICY["host_reserve_bytes"]
                    require(
                        min(memory["available_physical"], memory["available_commit"]) >= minimum,
                        "Insufficient host memory for serial calibration with two workers",
                    )
                    require(
                        vram.gpu_snapshot()["free_bytes"] >= vram.POLICY["reserve_bytes"],
                        "Insufficient device reserve for calibration",
                    )
                    decision = {
                        "scope": "explicit_serial_calibration_trial",
                        "host": memory,
                        "minimum_host_bytes": minimum,
                        "not_capacity_qualified": True,
                    }
                else:
                    decision = admission(configs, plan, receipts, calibrations)
                    save_document(config, "decisions", decision)
                    require(
                        decision["admitted"],
                        "Parallel admission refused: " + ", ".join(decision["reasons"]),
                    )
                receipt = {
                    "version": 1,
                    "scope": "managed_two_worker_audio",
                    "mode": "calibrate" if calibrate else "qualify",
                    "plan_id": plan["plan_id"],
                    "lease": lease.value,
                    "ports": ports or [8191, 8192],
                    "workers": receipts,
                    "processes": processes,
                    "policy": POLICY,
                    "calibrations": calibrations,
                    "admission": decision,
                }
                claim(db, config, plan, receipt)
                claimed = True
                for worker, jobs in zip(configs, groups, strict=True):
                    for item in jobs:
                        prepared = prepare_owned(worker, plan, item)
                        # Build shared parents under the dispatcher lock before collectors race.
                        safe_path(config.root, f"output/jobs/{prepared['request_id']}").mkdir(
                            parents=True, exist_ok=True
                        )
                        record_job(db, plan["plan_id"], item["index"], prepared)
                if calibrate:
                    for worker, jobs, qualification in zip(configs, groups, receipts, strict=True):
                        for item in jobs:
                            _fresh(worker, plan, qualification)
                            store = CatalogStore(config.root)
                            with file_lock(store._path("catalog.lock")):
                                store._clean()
                                require(
                                    store._head() == plan["catalog_head"],
                                    "Catalog changed before submission",
                                )
                                record = submit_owned(worker, plan, item, ComfyUIClient(worker.url))
                            record_job(db, plan["plan_id"], item["index"], record)
                            record = _observe(worker, plan, item, wait_timeout)
                            record_job(db, plan["plan_id"], item["index"], record)
                            require(
                                record["status"] == "succeeded",
                                "Calibration job did not complete; preserve and recover",
                            )
                else:
                    for worker, qualification in zip(configs, receipts, strict=True):
                        _fresh(worker, plan, qualification)
                    _idle(config.url)
                    final = admission(configs, plan, receipts, calibrations)
                    save_document(config, "decisions", final)
                    require(final["admitted"], "Parallel admission changed; reservations retained")
                    decision = final
                    barrier = threading.Barrier(2)

                    def post(index):
                        barrier.wait(timeout=10)
                        worker = configs[index]
                        return submit_owned(
                            worker, plan, groups[index][0], ComfyUIClient(worker.url)
                        )

                    store = CatalogStore(config.root)
                    with file_lock(store._path("catalog.lock")):
                        store._clean()
                        require(
                            store._head() == plan["catalog_head"],
                            "Catalog changed before submission",
                        )
                        with ThreadPoolExecutor(max_workers=2) as threads:
                            submitted = list(threads.map(post, range(2)))
                    for item, record in zip(plan["jobs"], submitted, strict=True):
                        record_job(db, plan["plan_id"], item["index"], record)
                    with ThreadPoolExecutor(max_workers=2) as threads:
                        futures = [
                            threads.submit(_observe, worker, plan, group[0], wait_timeout)
                            for worker, group in zip(configs, groups, strict=True)
                        ]
                        for item, future in zip(plan["jobs"], futures, strict=True):
                            record_job(db, plan["plan_id"], item["index"], future.result())
                    require(
                        all(
                            read_owned(w, plan, g[0])["status"] == "succeeded"
                            for w, g in zip(configs, groups, strict=True)
                        ),
                        "A parallel job did not complete; preserve and recover",
                    )
                observations = []
                for index, (worker, group, qualification, process) in enumerate(
                    zip(configs, groups, receipts, processes, strict=True)
                ):
                    profile, saved = vram.collect_profile(
                        worker, {**plan, "jobs": group}, qualification, gpu
                    )
                    require(not profile["issues"], "Worker measurement is incomplete")
                    observations.append(
                        {
                            "index": index,
                            "profile": profile,
                            "profile_path": str(saved),
                            "process": process,
                            "host_memory": process_memory(process),
                        }
                    )
                body = {
                    "version": 1,
                    "scope": "two_worker_audio_calibration"
                    if calibrate
                    else "bounded_audio_parallel_qualification",
                    "plan_id": plan["plan_id"],
                    "captured_at": _now(),
                    "host_identity": host_identity(),
                    "policy": POLICY,
                    "workers": observations,
                    "lease": lease.value,
                    "admission": decision,
                }
                if not calibrate:
                    metrics = [o["profile"]["observations"][0]["measurement"] for o in observations]
                    start = max(datetime.fromisoformat(m["started_at"]) for m in metrics)
                    end = min(datetime.fromisoformat(m["finished_at"]) for m in metrics)
                    overlap = max(0, int((end - start).total_seconds() * 1_000_000_000))
                    body["overlap_ns"] = overlap
                    body["qualified"] = overlap >= POLICY["minimum_overlap_ns"]
                    body["limits"] = (
                        "Prompt execution overlap; GPU kernel overlap and speedup unverified."
                    )
                document, saved = save_document(
                    config,
                    "calibrations" if calibrate else "qualifications",
                    body,
                    "calibration_id" if calibrate else "qualification_id",
                )
                record_run(db, plan["plan_id"], "succeeded")
                result = {
                    **report(db, config, plan),
                    "ok": calibrate or body["qualified"],
                    "scope": body["scope"],
                    "evidence": str(saved),
                    "document": document,
                }
            except BaseException as error:
                if claimed:
                    record_run(db, plan["plan_id"], "paused", str(error))
                raise
            finally:
                pool.stop()
                lease.release()
            return result


def resume(config: Config, path: Path) -> dict:
    plan = load_plan(path)
    with _lock(config), closing(open_store(config, create=False)) as db:
        saved, _ = check_run(db, config, plan)
        receipt = parse_json(saved["qualification"])
        require(receipt.get("scope") == "managed_two_worker_audio", "Not a managed parallel plan")
        require(
            saved["status"] == "succeeded",
            "Interrupted workers are not restarted; use parallel recover",
        )
        configs = worker_configs(config, receipt["ports"])
        groups = assignments(plan, receipt["mode"] == "calibrate")
        for worker, group in zip(configs, groups, strict=True):
            for item in group:
                require(
                    read_owned(worker, plan, item)["status"] == "succeeded",
                    "Completed ownership record differs",
                )
                result = _observe(worker, plan, item, 1)
                require(result["status"] == "succeeded", "Completed artifact verification failed")
        return {**report(db, config, plan), "scope": "completed_parallel_artifact_reverification"}


def recover(config: Config, path: Path, *, registry=None) -> dict:
    plan = load_plan(path)
    with _lock(config), closing(open_store(config, create=False)) as db:
        saved, _ = check_run(db, config, plan)
        receipt = parse_json(saved["qualification"])
        require(receipt.get("scope") == "managed_two_worker_audio", "Not a managed parallel plan")
        require(
            saved["status"] not in {"succeeded", "abandoned"},
            "No interrupted parallel run to retire",
        )
        lease = receipt["lease"]
        require(
            job_active(lease["job_name"]) == 0
            and all(process_state(p) == "dead" for p in receipt["processes"]),
            "Worker termination is not confirmed; do not release reservations",
        )
        current = device.status(lease["gpu_uuid"], root=registry)
        if current.get("lease_id") == lease["lease_id"] and current.get("status") == "held":
            device.recover(lease["gpu_uuid"], lease["lease_id"], root=registry)
        record_run(
            db,
            plan["plan_id"],
            "abandoned",
            "Workers confirmed dead; uncertain outcomes and seeds retained; no resubmission",
        )
        return {**report(db, config, plan), "scope": "confirmed_worker_exit_retirement", "ok": True}
