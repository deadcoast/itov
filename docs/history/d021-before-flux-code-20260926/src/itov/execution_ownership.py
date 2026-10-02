"""Cross-family workspace admission. Callers hold the stable dispatcher lock."""

import sqlite3
from contextlib import closing

from itov.catalog import require
from itov.comfyui import parse_json
from itov.qualification import safe_path

JOB_TERMINAL = {"succeeded", "failed", "rejected", "validation_failed", "collection_failed"}
JOB_PENDING = {
    "prepared",
    "validating",
    "submitting",
    "queued",
    "observing",
    "collecting",
    "submission_unknown",
    "timed_out",
    "detached",
    "observation_failed",
}


def workspace_available(config, *, plan_id=None, request_id=None):
    retired = set()
    database = safe_path(config.root, "state/batches/execution.sqlite3")
    require(
        database.exists() or not (database.parent / "initialized").exists(),
        "Existing execution database is missing",
    )
    if database.exists():
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
            active = db.execute(
                "SELECT plan_id FROM runs WHERE status NOT IN ('succeeded','failed','abandoned')"
            ).fetchall()
            require(
                all(row[0] == plan_id for row in active),
                "An unfinished batch or evaluation retains workspace ownership; resume it first",
            )
            retired = {
                row[0]
                for row in db.execute(
                    "SELECT plan_id FROM runs WHERE status IN ('failed','abandoned')"
                )
            }
    jobs = safe_path(config.root, "state/jobs")
    for path in sorted(jobs.glob("*.json")):
        record = parse_json(safe_path(jobs, path.name).read_bytes())
        require(isinstance(record, dict), "Invalid job ownership record; preserve and inspect")
        require(
            isinstance(record.get("status"), str)
            and record["status"] in JOB_PENDING | JOB_TERMINAL,
            "Unknown job execution state; preserve and inspect",
        )
        if record["status"] in JOB_TERMINAL:
            continue
        owner = record.get("owner", {})
        require(isinstance(owner, dict), "Invalid job owner")
        if owner.get("plan_id") in retired:
            continue
        require(
            (request_id is not None and record.get("request_id") == request_id)
            or (plan_id is not None and owner.get("plan_id") == plan_id),
            f"An unfinished job retains workspace ownership: {path.name}; resume its owner",
        )
    training = safe_path(config.root, "state/training/runs")
    for path in sorted(training.glob("*/run.json")):
        record = parse_json(safe_path(training, path.relative_to(training).as_posix()).read_bytes())
        require(isinstance(record, dict), "Invalid training ownership record")
        require(
            isinstance(record.get("status"), str)
            and record["status"]
            in {"running", "validating", "failed", "succeeded", "artifacts_validated"},
            "Unknown training execution state; preserve and inspect",
        )
        require(
            record["status"] not in {"running", "validating"},
            "An unfinished training attempt retains workspace ownership; use training recover",
        )
