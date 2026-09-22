"""Opt-in sequential execution of qualified immutable plans."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from itov.batch import load_plan
from itov.catalog import canonical_bytes, require
from itov.catalog_store import CatalogStore
from itov.comfyui import ComfyUIClient, ComfyUIError, parse_json
from itov.config import Config, validate_timeout
from itov.execution_store import (
    check_run,
    claim,
    open_store,
    record_job,
    record_run,
    report,
    transaction,
)
from itov.jobs import _timing
from itov.locking import file_lock
from itov.owned_jobs import job_path, observe_owned, prepare_owned, read_owned, submit_owned
from itov.qualification import load_qualification, qualify, safe_path


def _lock(config):
    path = safe_path(config.root, "state/batches/execution.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    return file_lock(path)


def batch_status(config: Config, path: Path) -> dict:
    plan = load_plan(path)
    with _lock(config), closing(open_store(config, create=False)) as db:
        return report(db, config, plan)


def abandon_batch(config: Config, path: Path) -> dict:
    """Retire remaining picks only when no owned job can still be executing."""
    plan = load_plan(path)
    with _lock(config), closing(open_store(config, create=False)) as db:
        run, rows = check_run(db, config, plan)
        require(
            parse_json(run["qualification"]).get("scope") != "managed_two_worker_audio",
            "Use parallel recover for a managed parallel batch",
        )
        if run["status"] in {"succeeded", "failed", "abandoned"}:
            return report(db, config, plan)
        for job, row in zip(plan["jobs"], rows, strict=True):
            path = job_path(config, plan["plan_id"], job["index"])
            if row["status"] == "reserved" and not path.exists():
                continue
            record = read_owned(config, plan, job)
            require(
                record["status"] != "prepared" or row["status"] in {"prepared", "reserved"},
                "Job record moved backwards to prepared; preserve and inspect",
            )
            if record["status"] == "collection_failed":
                client = ComfyUIClient(config.url)
                client.find_submission(
                    record["request_id"], record["workflow"], prompt_id=record["prompt_id"]
                )
                history = client.history(record["prompt_id"])
                require(
                    history is not None
                    and history["status"].get("completed") is True
                    and history["status"].get("status_str") == "success",
                    "Cannot abandon failed collection without owned terminal server evidence",
                )
                continue
            require(
                record["status"]
                in {"prepared", "succeeded", "failed", "rejected", "validation_failed"},
                "Cannot abandon active or uncertain work; resume and resolve its outcome first",
            )
        record_run(
            db, plan["plan_id"], "abandoned", "Remaining picks retired; seed reservations retained"
        )
        return report(db, config, plan)


def run_batch(
    config: Config,
    path: Path,
    *,
    qualification: Path | None = None,
    resume: bool = False,
    prompt_id: str | None = None,
    timeout: float = 3,
    wait_timeout: float = 120,
    poll_interval: float = 1,
    vram_profiles: list[Path] | None = None,
) -> dict:
    _timing(wait_timeout, poll_interval)
    validate_timeout(timeout)
    plan = load_plan(path)
    with _lock(config), closing(open_store(config, create=not resume)) as db:
        from itov.vram import enforce, guard

        guards = db.execute(
            "SELECT status FROM events WHERE plan_id = ? AND status LIKE 'vram_guard:%'",
            (plan["plan_id"],),
        ).fetchall()
        require(len(guards) <= 1, "Duplicate durable VRAM guard bindings")
        expected_guard = guards[0]["status"].split(":", 1)[1] if guards else None
        profiles = guard(config, plan, vram_profiles, expected_id=expected_guard)
        guard_id = None
        if profiles is not None:
            guard_file = safe_path(config.root, f"state/vram/guards/{plan['plan_id']}.json")
            guard_id = parse_json(guard_file.read_bytes())["guard_id"]
        existing = db.execute(
            "SELECT plan_id FROM runs WHERE plan_id = ?", (plan["plan_id"],)
        ).fetchone()
        if existing is None:
            require(
                not resume and qualification is not None,
                "A new batch requires --qualification from batch qualify --save",
            )
            receipt = load_qualification(qualification)
            require(
                receipt == qualify(config, plan, timeout=timeout),
                "Qualification changed; qualify and inspect the current bindings",
            )
            claim(db, config, plan, receipt, vram_guard_id=guard_id)
        elif profiles is not None and not guards:
            from itov.jobs import _now

            with transaction(db):
                db.execute(
                    "INSERT INTO events(plan_id, status, observed_at) VALUES (?, ?, ?)",
                    (plan["plan_id"], "vram_guard:" + guard_id, _now()),
                )
        run, rows = check_run(db, config, plan)
        require(
            parse_json(run["qualification"]).get("scope") != "managed_two_worker_audio",
            "Use parallel resume or recover for a managed parallel batch",
        )
        if run["status"] == "abandoned":
            return report(db, config, plan)
        other = db.execute(
            "SELECT plan_id FROM runs WHERE plan_id != ? "
            "AND status NOT IN ('succeeded', 'failed', 'abandoned')",
            (plan["plan_id"],),
        ).fetchone()
        require(
            other is None, "Another batch retains workspace execution ownership; resume it first"
        )
        receipt = parse_json(run["qualification"])
        if qualification is not None:
            require(
                load_qualification(qualification) == receipt,
                "Qualification differs from the reserved batch",
            )
        client = ComfyUIClient(config.url, timeout=timeout)
        try:
            record_run(db, plan["plan_id"], "running")
            for job, saved in zip(plan["jobs"], rows, strict=True):
                path = job_path(config, plan["plan_id"], job["index"])
                if saved["status"] == "reserved":
                    record = prepare_owned(config, plan, job)
                    # A job file is published before the database leaves reserved.
                    require(
                        record["status"] == "prepared",
                        "Reserved job has unexpected execution state",
                    )
                    record_job(db, plan["plan_id"], job["index"], record)
                else:
                    require(
                        path.is_file(),
                        "Owned job record is missing; automatic recreation is forbidden",
                    )
                    record = read_owned(config, plan, job)
                    require(
                        saved["prompt_id"] is None or saved["prompt_id"] == record.get("prompt_id"),
                        "Job prompt ID differs from durable execution history",
                    )
                    require(
                        record["status"] != "prepared" or saved["status"] == "prepared",
                        "Job record moved backwards to prepared; preserve and inspect",
                    )
                if record["status"] == "prepared":
                    require(
                        prompt_id is None, "Prompt ID can only reconcile a previously submitted job"
                    )
                    current = qualify(config, plan, timeout=timeout)
                    require(
                        canonical_bytes(current) == canonical_bytes(receipt),
                        "Qualification changed; no further jobs were submitted",
                    )
                    queue = client.queue()
                    require(
                        not queue["queue_running"] and not queue["queue_pending"],
                        "Server queue is busy; resume when it is idle",
                    )
                    if profiles is not None:
                        enforce(config, plan, profiles, current)
                    # Catalog writers cannot change HEAD between the final check and POST.
                    store = CatalogStore(config.root)
                    with file_lock(store._path("catalog.lock")):
                        store._clean()
                        require(
                            store._head() == plan["catalog_head"],
                            "Catalog changed before submission",
                        )
                        record = submit_owned(config, plan, job, client)
                    record_job(db, plan["plan_id"], job["index"], record)
                    if record["status"] == "submission_unknown":
                        record_run(db, plan["plan_id"], "paused", record.get("error"))
                        return report(db, config, plan)
                # A prior success is verified again, including every collected artifact.
                selected_prompt = (
                    prompt_id if record["status"] in {"submitting", "submission_unknown"} else None
                )
                record = observe_owned(
                    config,
                    plan,
                    job,
                    timeout=timeout,
                    wait_timeout=wait_timeout,
                    poll_interval=poll_interval,
                    prompt_id=selected_prompt,
                )
                if selected_prompt:
                    prompt_id = None
                record_job(db, plan["plan_id"], job["index"], record)
                if record["status"] != "succeeded":
                    state = (
                        "failed"
                        if record["status"] in {"failed", "rejected", "validation_failed"}
                        else "paused"
                    )
                    record_run(db, plan["plan_id"], state, record.get("error"))
                    return report(db, config, plan)
            require(prompt_id is None, "No uncertain submission accepts the supplied prompt ID")
            record_run(db, plan["plan_id"], "succeeded")
        except (OSError, ValueError, ComfyUIError, sqlite3.Error) as error:
            record_run(db, plan["plan_id"], "paused", str(error))
        except KeyboardInterrupt:
            record_run(db, plan["plan_id"], "paused", "Detached; resume to observe accepted work")
        return report(db, config, plan)
