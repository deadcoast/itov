"""Durable sequential-plan cancellation; terminal observation still owns recovery."""

import sqlite3
from contextlib import closing, contextmanager
from urllib.parse import quote

from itov.batch import load_plan
from itov.catalog import canonical_bytes, object_fields, require, sha256
from itov.comfyui import ComfyUIError, parse_json
from itov.execution_store import check_run
from itov.jobs import _now
from itov.locking import file_lock
from itov.qualification import _file, safe_path
from itov.runtime import launch_command, profile_main_argv
from itov.training_data import publish
from itov.vram_identity import MARKER

# Reviewed atomic prompt_queue.interrupt_if_running implementation. No global fallback.
RUNTIME_SOURCES = {
    "server.py": "ebed5d21252caf640030a5c1bd60301404e5ee795e448b241da947efb45638c3",
    "execution.py": "dbf84f520bdafbdec014cf595838ccbca4fb08888e2be4064b1d105816ab0d3b",
    "comfy_execution/jobs.py": "e57ac4235dd1f85807b7f443ce7667bb2c3310dcf8299082e6595afa01dab322",
}


def directory(config, plan):
    return safe_path(config.root, f"state/batches/cancellations/{plan['plan_id']}")


def guard(config, plan):
    root = directory(config, plan)
    root.mkdir(parents=True, exist_ok=True)
    return file_lock(root / "request.lock", timeout=5)


def requested(config, plan):
    path = safe_path(directory(config, plan), "request.json")
    if not path.exists():
        return None
    raw = path.read_bytes()
    value = parse_json(raw)
    object_fields(
        value,
        {"version", "plan_id", "plan_sha256", "server", "policy", "created_at"},
        "cancellation request",
    )
    require(
        type(value["version"]) is int
        and value["version"] == 1
        and value["plan_id"] == plan["plan_id"]
        and value["plan_sha256"] == sha256(canonical_bytes(plan))
        and value["server"] == config.url
        and value["policy"] in {"finish-accepted", "interrupt-running"}
        and isinstance(value["created_at"], str)
        and raw == canonical_bytes(value) + b"\n",
        "Cancellation request binding differs",
    )
    return value


@contextmanager
def _database(config):
    """Read one transaction snapshot without the controller's write lock or PRAGMAs."""
    path = safe_path(config.root, "state/batches/execution.sqlite3")
    marker = safe_path(config.root, "state/batches/initialized")
    require(path.is_file() and marker.is_file(), "Batch database is not initialized")
    require(marker.read_bytes() == b"itov-execution-v1\n", "Invalid execution marker")
    for suffix in ("-journal", "-wal", "-shm"):
        safe_path(config.root, "state/batches/execution.sqlite3" + suffix)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=3)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        require(
            db.execute("PRAGMA user_version").fetchone()[0] == 1, "Unsupported execution database"
        )
        require(
            db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            and not db.execute("PRAGMA foreign_key_check").fetchall(),
            "Execution database integrity differs",
        )
        yield db


def cancel(config, path, *, interrupt_running=False):
    plan = load_plan(path)
    # Independent lock: the controller may hold execution.lock while observing.
    with guard(config, plan), _database(config) as db:
        run, _ = check_run(db, config, plan)
        require(
            parse_json(run["qualification"]).get("scope") != "managed_two_worker_audio",
            "Use parallel recover for a managed parallel batch",
        )
        prior = requested(config, plan)
        policy = "interrupt-running" if interrupt_running else "finish-accepted"
        if prior is None:
            require(
                run["status"] not in {"succeeded", "failed", "abandoned"},
                "Batch is already terminal; cancellation has no active work to retire",
            )
            prior = {
                "version": 1,
                "plan_id": plan["plan_id"],
                "server": config.url,
                "plan_sha256": sha256(canonical_bytes(plan)),
                "policy": policy,
                "created_at": _now(),
            }
            publish(directory(config, plan) / "request.json", prior)
        else:
            require(prior["policy"] == policy, "Cancellation policy is immutable")
        return {
            "ok": True,
            "scope": "durable_cancellation_request",
            "status": "requested",
            "plan_id": plan["plan_id"],
            "cancellation": prior,
            "limits": (
                "Request saved; ownership remains until the controller observes terminal work. "
                "Resume the same batch if detached."
            ),
        }


def runtime_supported(config, client):
    argv = client.system_stats()["system"].get("argv")
    require(
        argv in (launch_command(config)[2:], profile_main_argv(config) + [MARKER]),
        "Targeted cancellation requires the exact managed runtime launch",
    )
    for name, expected in RUNTIME_SOURCES.items():
        require(
            _file(safe_path(config.comfyui_root, name))["sha256"] == expected,
            "Targeted cancellation runtime differs; no interrupt was sent",
        )


def poll(config, plan, client, record):
    request = requested(config, plan)
    if request is None or request["policy"] != "interrupt-running":
        return
    root = directory(config, plan)
    intent = safe_path(root, record["request_id"] + ".intent.json")
    if intent.exists():
        # An interrupted process or lost response never authorizes another POST.
        saved = parse_json(intent.read_bytes())
        require(
            saved.get("request_id") == record["request_id"]
            and saved.get("prompt_id") == record["prompt_id"]
            and saved.get("workflow_sha256") == record["workflow_sha256"],
            "Cancellation intent differs from owned work",
        )
        return
    match = client.find_submission(
        record["request_id"], record["workflow"], prompt_id=record["prompt_id"]
    )
    require(match == record["prompt_id"], "Cannot prove cancellation target ownership")
    queue = client.queue()
    if not any(item[1] == match for item in queue["queue_running"]):
        return  # Never dequeue pending work: it would lose terminal history.
    runtime_supported(config, client)
    publish(
        intent,
        {
            "version": 1,
            "request_id": record["request_id"],
            "prompt_id": match,
            "workflow_sha256": record["workflow_sha256"],
            "created_at": _now(),
        },
    )
    try:
        acknowledgement = client._json(f"/api/jobs/{quote(match, safe='')}/cancel", {})
        require(type(acknowledgement.get("cancelled")) is bool, "Invalid cancel acknowledgement")
        outcome = {"acknowledgement": acknowledgement}
    except (ComfyUIError, ValueError) as error:
        outcome = {"error": str(error), "acknowledgement_unknown": True}
    publish(
        root / (record["request_id"] + ".response.json"),
        {"version": 1, "request_id": record["request_id"], "prompt_id": match, **outcome},
    )
