"""Transactional workspace batch ownership, permanent seed reservations and observations."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from itov.catalog import canonical_bytes, require
from itov.catalog_store import _atomic_write
from itov.config import Config
from itov.jobs import _now
from itov.owned_jobs import identity
from itov.qualification import safe_path

SCHEMA = """
CREATE TABLE runs (
    plan_id TEXT PRIMARY KEY, server TEXT NOT NULL, plan BLOB NOT NULL,
    qualification BLOB NOT NULL, status TEXT NOT NULL, error TEXT, created_at TEXT NOT NULL
);
CREATE TABLE jobs (
    plan_id TEXT NOT NULL REFERENCES runs(plan_id), job_index INTEGER NOT NULL,
    request_id TEXT NOT NULL UNIQUE, workflow_sha256 TEXT NOT NULL,
    status TEXT NOT NULL, prompt_id TEXT,
    PRIMARY KEY (plan_id, job_index)
);
CREATE TABLE seeds (
    seed TEXT PRIMARY KEY, plan_id TEXT NOT NULL, job_index INTEGER NOT NULL,
    FOREIGN KEY (plan_id, job_index) REFERENCES jobs(plan_id, job_index)
);
CREATE TABLE events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT, plan_id TEXT NOT NULL REFERENCES runs(plan_id),
    job_index INTEGER, status TEXT NOT NULL, prompt_id TEXT, observed_at TEXT NOT NULL
);
PRAGMA user_version = 1;
"""


@contextmanager
def transaction(db):
    db.execute("BEGIN IMMEDIATE")
    try:
        yield
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise


def open_store(config: Config, *, create: bool) -> sqlite3.Connection:
    """Caller holds the workspace execution lock for the entire connection lifetime."""
    path = safe_path(config.root, "state/batches/execution.sqlite3")
    marker = safe_path(config.root, "state/batches/initialized")
    for suffix in ("-journal", "-wal", "-shm"):
        safe_path(config.root, f"state/batches/execution.sqlite3{suffix}")
    if not path.exists():
        require(
            create and not marker.exists(),
            "Execution database is missing; preserve state and restore it before executing",
        )
        path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.exists()
    db = sqlite3.connect(path, isolation_level=None, timeout=0)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA synchronous = FULL")
        db.execute("PRAGMA journal_mode = DELETE")
        if not existing:
            db.executescript("BEGIN IMMEDIATE;\n" + SCHEMA + "\nCOMMIT;")
        require(
            db.execute("PRAGMA user_version").fetchone()[0] == 1,
            "Unsupported or incomplete execution database; preserve and inspect",
        )
        require(
            db.execute("PRAGMA quick_check").fetchone()[0] == "ok",
            "Execution database integrity check failed",
        )
        require(
            not db.execute("PRAGMA foreign_key_check").fetchall(),
            "Execution database references are inconsistent",
        )
        if marker.exists():
            require(marker.read_bytes() == b"itov-execution-v1\n", "Invalid execution marker")
        else:
            _atomic_write(marker, b"itov-execution-v1\n", exclusive=True)
    except BaseException:
        db.close()
        raise
    return db


def claim(db, config: Config, plan: dict, receipt: dict, *, vram_guard_id: str | None = None):
    with transaction(db):
        active = db.execute(
            "SELECT plan_id FROM runs WHERE status NOT IN ('succeeded', 'failed', 'abandoned')"
        ).fetchall()
        require(not active, "Another batch retains workspace execution ownership; resume it first")
        db.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, 'running', NULL, ?)",
            (plan["plan_id"], config.url, canonical_bytes(plan), canonical_bytes(receipt), _now()),
        )
        for job in plan["jobs"]:
            index = job["index"]
            db.execute(
                "INSERT INTO jobs VALUES (?, ?, ?, ?, 'reserved', NULL)",
                (plan["plan_id"], index, identity(plan["plan_id"], index), job["workflow_sha256"]),
            )
            if job["seed"] is not None:
                seed = str(job["seed"])
                previous = db.execute(
                    "SELECT plan_id FROM seeds WHERE seed = ?", (seed,)
                ).fetchone()
                require(previous is None, f"Seed {seed} is already reserved by another batch")
                db.execute("INSERT INTO seeds VALUES (?, ?, ?)", (seed, plan["plan_id"], index))
        db.execute(
            "INSERT INTO events(plan_id, status, observed_at) VALUES (?, 'reserved', ?)",
            (plan["plan_id"], _now()),
        )
        if vram_guard_id is not None:
            db.execute(
                "INSERT INTO events(plan_id, status, observed_at) VALUES (?, ?, ?)",
                (plan["plan_id"], "vram_guard:" + vram_guard_id, _now()),
            )


def check_run(db, config: Config, plan: dict):
    run = db.execute("SELECT * FROM runs WHERE plan_id = ?", (plan["plan_id"],)).fetchone()
    require(run is not None, "Batch has not been reserved; use batch run with a qualification")
    require(
        run["server"] == config.url and run["plan"] == canonical_bytes(plan),
        "Saved batch plan/server differs from execution ownership",
    )
    rows = db.execute(
        "SELECT * FROM jobs WHERE plan_id = ? ORDER BY job_index", (plan["plan_id"],)
    ).fetchall()
    require(len(rows) == len(plan["jobs"]), "Execution job ownership is incomplete")
    for row, job in zip(rows, plan["jobs"], strict=True):
        require(
            row["job_index"] == job["index"]
            and row["request_id"] == identity(plan["plan_id"], job["index"])
            and row["workflow_sha256"] == job["workflow_sha256"],
            "Execution job ownership differs from plan",
        )
    expected = {(str(job["seed"]), job["index"]) for job in plan["jobs"] if job["seed"] is not None}
    actual = {
        (row[0], row[1])
        for row in db.execute(
            "SELECT seed, job_index FROM seeds WHERE plan_id = ?", (plan["plan_id"],)
        )
    }
    require(actual == expected, "Batch seed reservations differ from plan")
    return run, rows


def record_job(db, plan_id: str, index: int, record: dict):
    with transaction(db):
        db.execute(
            "UPDATE jobs SET status = ?, prompt_id = ? WHERE plan_id = ? AND job_index = ?",
            (record["status"], record.get("prompt_id"), plan_id, index),
        )
        db.execute(
            "INSERT INTO events(plan_id, job_index, status, prompt_id, observed_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (plan_id, index, record["status"], record.get("prompt_id"), _now()),
        )


def record_run(db, plan_id: str, status: str, error: str | None = None):
    with transaction(db):
        db.execute(
            "UPDATE runs SET status = ?, error = ? WHERE plan_id = ?", (status, error, plan_id)
        )
        db.execute(
            "INSERT INTO events(plan_id, status, observed_at) VALUES (?, ?, ?)",
            (plan_id, status, _now()),
        )


def report(db, config: Config, plan: dict) -> dict:
    run, rows = check_run(db, config, plan)
    return {
        "ok": run["status"] == "succeeded",
        "plan_id": plan["plan_id"],
        "status": run["status"],
        "error": run["error"],
        "jobs": [dict(row) for row in rows],
        "succeeded": sum(row["status"] == "succeeded" for row in rows),
        "scope": "sequential_batch_observations",
    }
