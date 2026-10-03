"""Measured exact-workload VRAM profiles and conservative sequential admission."""

import csv
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from itov.batch import load_plan
from itov.catalog import (
    canonical_bytes,
    digest,
    integer,
    object_fields,
    read_document,
    require,
    sha256,
)
from itov.catalog_store import _atomic_write
from itov.comfyui import ComfyUIClient, ComfyUIError, parse_json_object, submission_matches
from itov.config import Config
from itov.owned_jobs import job_path, read_owned
from itov.qualification import load_qualification, qualify, safe_path
from itov.vram_identity import workload_key

POLICY = {
    "version": 1,
    "max_age_seconds": 7 * 86400,
    "minimum_cold_sessions": 2,
    "minimum_warm_sessions": 2,
    "reserve_bytes": 2 * 1024**3,
    "uncertainty_percent": 20,
    "max_sample_gap_ns": 1_000_000_000,
    "minimum_samples": 3,
    "max_workers": 1,
}


def gpu_snapshot() -> dict:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=uuid,name,driver_version,memory.total,memory.used,memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError("NVIDIA memory telemetry is unavailable") from error
    require(result.returncode == 0, "NVIDIA memory telemetry failed: " + result.stderr[-1000:])
    rows = list(csv.reader(result.stdout.strip().splitlines()))
    require(len(rows) == 1 and len(rows[0]) == 6, "VRAM admission requires exactly one NVIDIA GPU")
    row = [value.strip() for value in rows[0]]
    try:
        total, used, free = [int(value) * 1024**2 for value in row[3:]]
    except ValueError as error:
        raise ValueError("GPU memory counters are unavailable") from error
    require(0 <= used <= total and 0 <= free <= total and total > 0, "Invalid GPU memory counters")
    return {
        "uuid": row[0],
        "name": row[1],
        "driver": row[2],
        "total_bytes": total,
        "used_bytes": used,
        "free_bytes": free,
    }


def fingerprint(receipt: dict, gpu: dict) -> str:
    observer = receipt.get("vram_observer")
    if not isinstance(observer, dict):
        raise ValueError("Qualification requires the instrumented VRAM runtime")
    body = {
        key: receipt[key]
        for key in ("profile", "runtime", "devices", "node_schema_sha256", "files")
    }
    body["observer"] = {
        key: value
        for key, value in observer.items()
        if key not in {"session_id", "pid", "started_at"}
    }
    body["gpu"] = {key: gpu[key] for key in ("uuid", "name", "driver", "total_bytes")}
    require(
        str(observer["device"]["uuid"]).lower().removeprefix("gpu-")
        == gpu["uuid"].lower().removeprefix("gpu-"),
        "CUDA and NVIDIA device identities differ",
    )
    return sha256(canonical_bytes(body))


def _save(config: Config, category: str, body: dict, id_field: str) -> tuple[dict, Path]:
    document = {**body, id_field: sha256(canonical_bytes(body))}
    path = safe_path(config.root, f"state/vram/{category}/{document[id_field]}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical_bytes(document) + b"\n"
    try:
        _atomic_write(path, raw, exclusive=True)
    except FileExistsError:
        require(path.read_bytes() == raw, "Existing VRAM record differs; preserve and inspect")
    return document, path


def load_profile(path: Path) -> dict:
    raw = read_document(path)
    value = parse_json_object(raw, message="VRAM profile: expected an object")
    object_fields(
        value,
        {
            "version",
            "scope",
            "captured_at",
            "plan_id",
            "qualification_id",
            "runtime_key",
            "gpu",
            "observer",
            "observations",
            "issues",
            "limits",
            "profile_id",
        },
        "VRAM profile",
    )
    require(
        type(value["version"]) is int
        and value["version"] == 1
        and value["scope"] == "exact_workload_vram_observations",
        "Invalid VRAM profile",
    )
    body = {key: item for key, item in value.items() if key != "profile_id"}
    require(value.get("profile_id") == sha256(canonical_bytes(body)), "VRAM profile hash mismatch")
    require(raw == canonical_bytes(value) + b"\n", "Noncanonical VRAM profile")
    require(isinstance(value.get("observations"), list), "Missing VRAM observations")
    for field in ("plan_id", "qualification_id", "runtime_key", "profile_id"):
        digest(value[field], field)
    require(
        isinstance(value["observer"], dict)
        and isinstance(value["gpu"], dict)
        and isinstance(value["issues"], list),
        "Invalid VRAM profile metadata",
    )
    for item in value["observations"]:
        require(
            isinstance(item, dict) and isinstance(item.get("measurement"), dict),
            "Invalid VRAM observation",
        )
        digest(item["measurement"].get("workload_key"), "workload key")
    return value


def collect_profile(config: Config, plan: dict, receipt: dict, gpu: dict) -> tuple[dict, Path]:
    """Collect durable owned observations; unsuccessful observations remain unusable evidence."""
    require(receipt["plan_id"] == plan["plan_id"], "Qualification belongs to another plan")
    runtime_key = fingerprint(receipt, gpu)
    observer = receipt["vram_observer"]
    observations, issues = [], []
    client = ComfyUIClient(config.url)
    for job in plan["jobs"]:
        try:
            record = read_owned(config, plan, job)
            require(record["status"] == "succeeded", "Only successful collected jobs qualify")
            history = client.history(record["prompt_id"])
            if history is None:
                raise ValueError("Missing matching terminal server ownership")
            require(
                history["status"].get("completed") is True
                and history["status"].get("status_str") == "success"
                and history["prompt"][3].get("itov_request_id") == record["request_id"]
                and submission_matches(record["workflow"], history["prompt"][2]),
                "Missing matching terminal server ownership",
            )
            telemetry = safe_path(
                config.runtime_root,
                f"state/vram/telemetry/{observer['session_id']}/{record['prompt_id']}.json",
            )
            raw = read_document(telemetry)
            metric = parse_json_object(raw, message="VRAM telemetry: expected an object")
            from itov.vram_identity import encoded

            require(
                metric.get("session_id") == observer["session_id"]
                and metric.get("prompt_id") == record["prompt_id"]
                and metric.get("request_id") == record["request_id"]
                and metric.get("workflow_sha256") == sha256(encoded(history["prompt"][2]))
                and metric.get("workload_key") == workload_key(record["workflow"]),
                "Telemetry does not match the owned executed graph",
            )
            cache = (
                "cold_process"
                if metric["sequence"] == 0
                else (
                    "warm_exact"
                    if metric["previous_workload"] == metric["workload_key"]
                    else "mixed"
                )
            )
            observations.append(
                {
                    "job_index": job["index"],
                    "cache_state": cache,
                    "job_record_sha256": sha256(
                        read_document(job_path(config, plan["plan_id"], job["index"]))
                    ),
                    "telemetry_sha256": sha256(raw),
                    "measurement": metric,
                }
            )
        except (OSError, ValueError, KeyError, TypeError, ComfyUIError) as error:
            issues.append({"job_index": job["index"], "error": str(error)})
    for item in observations:
        try:
            _observation(item, datetime.now(UTC))
        except (KeyError, ValueError, TypeError) as error:
            issues.append({"job_index": item["job_index"], "error": str(error)})
    body = {
        "version": 1,
        "scope": "exact_workload_vram_observations",
        "captured_at": datetime.now(UTC).isoformat(),
        "plan_id": plan["plan_id"],
        "qualification_id": receipt["qualification_id"],
        "runtime_key": runtime_key,
        "gpu": gpu,
        "observer": observer,
        "observations": observations,
        "issues": issues,
        "limits": (
            "Allocator peaks exclude non-PyTorch allocations. "
            "Device samples can miss peaks; no parallel capacity guarantee."
        ),
    }
    return _save(config, "profiles", body, "profile_id")


def capture(config: Config, path: Path, qualification: Path, *, wait_timeout=900) -> dict:
    from itov.batch_execution import run_batch

    plan = load_plan(path)
    receipt = load_qualification(qualification)
    require(receipt == qualify(config, plan), "Qualification changed before profiling")
    require("vram_observer" in receipt, "Start a vram server before capture")
    state = ComfyUIClient(config.url)._json("/itov/vram")["state"]
    require(
        state["executions"] == 0 and state["active"] is None and not state["errors"],
        "Capture requires a fresh observer process for an honest cold measurement",
    )
    require(2 <= len(plan["jobs"]) <= 4, "Capture requires 2..4 explicitly seeded jobs")
    keys = {workload_key(parse_json_object(job["workflow_json"])) for job in plan["jobs"]}
    require(
        len(keys) == 1 and all(job["seed"] is not None for job in plan["jobs"]),
        "Capture requires one exact workload with explicit varying seeds",
    )
    gpu = gpu_snapshot()
    fingerprint(receipt, gpu)
    result = run_batch(config, path, qualification=qualification, wait_timeout=wait_timeout)
    profile, saved = collect_profile(config, plan, receipt, gpu)
    return {
        "ok": result["status"] == "succeeded" and not profile["issues"],
        "result": result,
        "profile": profile,
        "path": str(saved),
    }


def _observation(item: dict, now: datetime) -> tuple[str, str, int, int]:
    metric = item["measurement"]
    require(metric["execution_success"] is True and not metric["errors"], "failed_measurement")
    age = (now - datetime.fromisoformat(metric["finished_at"])).total_seconds()
    require(0 <= age <= POLICY["max_age_seconds"], "stale_measurement")
    samples = metric["samples"]
    require(
        isinstance(samples, list) and len(samples) >= POLICY["minimum_samples"],
        "insufficient_samples",
    )
    for sample in samples:
        for field in (
            "elapsed_ns",
            "global_free_bytes",
            "global_total_bytes",
            "allocated_bytes",
            "reserved_bytes",
        ):
            integer(sample[field], field)
        require(
            0 <= sample["global_free_bytes"] <= sample["global_total_bytes"]
            and sample["global_total_bytes"] > 0,
            "invalid_device_memory",
        )
    require(
        len({sample["global_total_bytes"] for sample in samples}) == 1,
        "device_capacity_changed",
    )
    times = [sample["elapsed_ns"] for sample in samples]
    require(times == sorted(set(times)), "invalid_sample_timestamps")
    gaps = [b - a for a, b in zip(times, times[1:], strict=False)]
    require(max(gaps) <= POLICY["max_sample_gap_ns"], "sampling_gap")
    for field in ("peak_allocated_bytes", "peak_reserved_bytes", "sequence", "duration_ns"):
        integer(metric[field], field)
    require(
        metric["peak_reserved_bytes"] >= max(sample["reserved_bytes"] for sample in samples)
        and metric["peak_allocated_bytes"] >= max(sample["allocated_bytes"] for sample in samples),
        "invalid_allocator_peak",
    )
    require(
        times[-1] <= metric["duration_ns"]
        and metric["duration_ns"] - times[-1] <= POLICY["max_sample_gap_ns"]
        and times[0] <= POLICY["max_sample_gap_ns"],
        "incomplete_sampling_window",
    )
    used = [sample["global_total_bytes"] - sample["global_free_bytes"] for sample in samples]
    additional = max(
        max(used) - used[0], metric["peak_reserved_bytes"], metric["peak_allocated_bytes"]
    )
    cache = item["cache_state"]
    require(
        (cache == "cold_process" and metric["sequence"] == 0)
        or (
            cache == "warm_exact"
            and metric["sequence"] > 0
            and metric["previous_workload"] == metric["workload_key"]
        ),
        "unqualified_cache_state",
    )
    return cache, metric["session_id"], additional, max(used)


def assess(
    plan: dict,
    receipt: dict,
    profiles: list[dict],
    gpu: dict,
    live: dict,
    *,
    workers=1,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(UTC)
    integer(workers, "workers", minimum=1)
    reasons, estimates = [], []
    if workers != 1:
        reasons.append("parallel_execution_not_qualified")
    runtime_key = fingerprint(receipt, gpu)
    require(live.get("identity") == receipt["vram_observer"], "Live observer identity changed")
    memory, state = live["memory"], live["state"]
    for counters, fields in (
        (gpu, ("total_bytes", "used_bytes", "free_bytes")),
        (memory, ("global_total_bytes", "global_free_bytes", "allocated_bytes", "reserved_bytes")),
    ):
        for field in fields:
            integer(counters[field], field)
    require(
        gpu["total_bytes"] > 0
        and gpu["used_bytes"] <= gpu["total_bytes"]
        and gpu["free_bytes"] <= gpu["total_bytes"]
        and memory["global_total_bytes"] > 0
        and memory["global_free_bytes"] <= memory["global_total_bytes"],
        "Invalid live memory counters",
    )
    integer(state["executions"], "observer executions")
    if state["active"] is not None or state["errors"]:
        reasons.append("observer_busy_or_failed")
    current_used = max(
        gpu["used_bytes"], memory["global_total_bytes"] - memory["global_free_bytes"]
    )
    total = min(gpu["total_bytes"], memory["global_total_bytes"])
    keys = sorted({workload_key(parse_json_object(job["workflow_json"])) for job in plan["jobs"]})
    for key in keys:
        observations = []
        cold: set[str] = set()
        warm: set[str] = set()
        rejected = []
        for profile in profiles:
            if profile.get("runtime_key") != runtime_key:
                rejected.append("runtime_device_or_asset_mismatch")
                continue
            if profile.get("issues"):
                rejected.append("incomplete_profile")
                continue
            for item in profile["observations"]:
                if item["measurement"].get("workload_key") != key:
                    continue
                try:
                    cache, session, additional, peak = _observation(item, now)
                except (KeyError, ValueError, TypeError) as error:
                    rejected.append(str(error))
                    continue
                (cold if cache == "cold_process" else warm).add(session)
                observations.append((additional, peak))
        if (
            len(cold) < POLICY["minimum_cold_sessions"]
            or len(warm) < POLICY["minimum_warm_sessions"]
        ):
            reasons.append("missing_repeated_cold_warm_evidence")
            reasons.extend(rejected)
            estimates.append(
                {"workload_key": key, "cold_sessions": len(cold), "warm_sessions": len(warm)}
            )
            continue
        if state["executions"] > 0 and state["last_workload"] != key:
            reasons.append("unprofiled_live_cache_state")
        additional = max(value[0] for value in observations)
        # Deliberately do not subtract current cached/reserved allocations.
        margin = (additional * POLICY["uncertainty_percent"] + 99) // 100
        required = current_used + additional + margin + POLICY["reserve_bytes"]
        if required > total:
            reasons.append("insufficient_headroom")
        estimates.append(
            {
                "workload_key": key,
                "cold_sessions": len(cold),
                "warm_sessions": len(warm),
                "additional_envelope_bytes": additional,
                "uncertainty_bytes": margin,
                "observed_device_peak_bytes": max(value[1] for value in observations),
                "required_total_bytes": required,
                "headroom_bytes": total - required,
            }
        )
    return {
        "version": 1,
        "ok": not reasons,
        "admitted": not reasons,
        "scope": "conservative_exact_workload_sequential_admission",
        "plan_id": plan["plan_id"],
        "checked_at": now.isoformat(),
        "workers": workers,
        "policy": POLICY,
        "profile_ids": sorted({profile["profile_id"] for profile in profiles}),
        "runtime_key": runtime_key,
        "gpu": gpu,
        "current_used_bytes": current_used,
        "estimates": estimates,
        "reasons": sorted(set(reasons)),
        "limits": (
            "A measured envelope with policy margins is not a peak guarantee. "
            "External clients can race; parallel execution remains disabled."
        ),
    }


def check(config: Config, plan: dict, profiles: list[dict], *, workers=1, receipt=None) -> dict:
    receipt = receipt or qualify(config, plan)
    client = ComfyUIClient(config.url)
    live = client._json("/itov/vram")
    result = assess(plan, receipt, profiles, gpu_snapshot(), live, workers=workers)
    state = live["state"]
    if state["executions"] > 0 and state["active"] is None:
        try:
            session = live["identity"]["session_id"]
            directory = safe_path(config.runtime_root, f"state/vram/telemetry/{session}")
            latest = []
            for path in directory.glob("*.json"):
                metric = parse_json_object(
                    read_document(safe_path(directory, path.name)),
                    message="VRAM telemetry: expected an object",
                )
                if metric.get("sequence") == state["executions"] - 1:
                    latest.append(metric)
            require(len(latest) == 1, "Missing unique last-execution measurement")
            metric = latest[0]
            require(
                metric["session_id"] == session
                and metric["workload_key"] == state["last_workload"],
                "Last-execution measurement differs from observer state",
            )
            _observation(
                {
                    "measurement": metric,
                    "cache_state": "cold_process" if metric["sequence"] == 0 else "warm_exact",
                },
                datetime.now(UTC),
            )
        except (OSError, ValueError, KeyError, TypeError) as error:
            result["reasons"] = sorted(set(result["reasons"] + ["unqualified_live_cache_evidence"]))
            result.update(ok=False, admitted=False, cache_error=str(error))
    queue = client.queue()
    if queue["queue_running"] or queue["queue_pending"]:
        result["reasons"] = sorted(set(result["reasons"] + ["server_queue_busy"]))
        result.update(ok=False, admitted=False)
    return result


def guard(
    config: Config, plan: dict, paths: list[Path] | None, *, expected_id=None
) -> list[dict] | None:
    """Persist immutable profile bindings; omitting options on resume never drops the guard."""
    path = safe_path(config.root, f"state/vram/guards/{plan['plan_id']}.json")
    require(
        expected_id is None or path.is_file(),
        "Reserved VRAM guard is missing; restore it before execution",
    )
    supplied = [load_profile(item) for item in paths] if paths else None
    if path.exists():
        value = parse_json_object(read_document(path), message="VRAM guard: expected an object")
        body = {key: item for key, item in value.items() if key != "guard_id"}
        require(
            value.get("guard_id") == sha256(canonical_bytes(body))
            and value.get("plan_id") == plan["plan_id"]
            and value.get("policy") == POLICY,
            "VRAM guard integrity or policy differs",
        )
        require(
            expected_id is None or value["guard_id"] == expected_id, "Reserved VRAM guard differs"
        )
        profiles = value["profiles"]
        if supplied is not None:
            require(supplied == profiles, "Cannot replace a batch's reserved VRAM profiles")
        return profiles
    if supplied is not None:
        decision = check(config, plan, supplied)
        _save(config, "decisions", decision, "decision_id")
        require(decision["admitted"], "VRAM admission refused: " + ", ".join(decision["reasons"]))
        body = {"version": 1, "plan_id": plan["plan_id"], "policy": POLICY, "profiles": supplied}
        value = {**body, "guard_id": sha256(canonical_bytes(body))}
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(path, canonical_bytes(value) + b"\n", exclusive=True)
    return supplied


def enforce(config: Config, plan: dict, profiles: list[dict], receipt: dict):
    decision = check(config, plan, profiles, receipt=receipt)
    _save(config, "decisions", decision, "decision_id")
    require(decision["admitted"], "VRAM admission refused: " + ", ".join(decision["reasons"]))
