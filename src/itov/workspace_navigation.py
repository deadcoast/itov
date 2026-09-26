"""Bounded, offline navigation of saved artifacts, never an execution controller."""

import sqlite3
import uuid
from contextlib import closing
from pathlib import Path

from itov.catalog import canonical_bytes, digest, integer, require, sha256
from itov.catalog_store import CatalogStore
from itov.comfyui import parse_json
from itov.evidence_reads import read_document
from itov.qualification import safe_path
from itov.training_data import check_seal
from itov.workspace_guide import command

FOLDERS = {
    "jobs": "state/jobs",
    "batch": "state/plans",
    "training": "state/training/plans",
    "inference": "state/inference/plans",
    "evaluation": "state/evaluation/plans",
    "experiments": "state/experiments/plans",
    "candidates": "state/training/candidates",
    "decisions": "state/evaluation/decisions",
    "lifecycle": "state/candidates/previews",
    "diagnostics": "state/workspace/diagnostics",
    "imports": "state/dataset-imports",
}
SCOPES = {
    "planning_only": ("batch", "plan_id"),
    "training_plan_only": ("training", "plan_id"),
    "capability_inference_plan": ("inference", "plan_id"),
    "deployed_evaluation_plan": ("evaluation", "plan_id"),
    "experiment_plan": ("experiments", "experiment_id"),
    "deployed_candidate_decision": ("decisions", "decision_id"),
    "candidate_lifecycle_preview": ("lifecycle", "operation_id"),
    "workspace_dependencies": ("diagnostics", "diagnostic_id"),
}
LIMIT = 10000
LIMITS = (
    "Offline discovery and document seals/recorded state only. Inputs, artifacts, processes, "
    "runtime and model quality are not revalidated. Observations are point-in-time, not a "
    "cross-file snapshot. Follow the owning command for authoritative checks. No "
    "recursive asset scan."
)


def _document(config, path):
    path = Path(path).absolute()
    require(path.is_relative_to(config.root), "Inspect a saved artifact inside this workspace")
    path = safe_path(config.root, path.relative_to(config.root).as_posix())
    raw = read_document(path)
    value = parse_json(raw)
    require(isinstance(value, dict), "Expected an artifact object")
    require(type(value.get("version")) is int and value["version"] > 0, "Invalid artifact version")
    return path, raw, value


def _kind(value):
    if isinstance(value.get("scope"), str) and value["scope"] in SCOPES:
        return SCOPES[value["scope"]]
    if "request_id" in value and "workflow" in value:
        return "jobs", None
    if "candidate_id" in value and "entry" in value:
        return "candidates", "candidate_id"
    if "import_id" in value and "declaration" in value:
        return "imports", "import_id"
    raise ValueError("Unsupported artifact; use workspace guide or its domain command")


def _execution_state(config, value):
    path = safe_path(config.root, "state/batches/execution.sqlite3")
    if not path.exists():
        require(
            not safe_path(config.root, "state/batches/initialized").exists(),
            "Execution database is missing; preserve and restore it",
        )
        return "not_started", {}
    for suffix in ("-journal", "-wal", "-shm"):
        safe_path(config.root, "state/batches/execution.sqlite3" + suffix)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0)) as db:
        db.execute("PRAGMA query_only=ON")
        require(
            db.execute("PRAGMA user_version").fetchone()[0] == 1, "Unsupported execution database"
        )
        row = db.execute(
            "SELECT status, plan, qualification, server FROM runs WHERE plan_id = ?",
            (value["plan_id"],),
        ).fetchone()
        if row is None:
            return "not_started", {}
        require(
            canonical_bytes(parse_json(row[1])) == canonical_bytes(value),
            "Recorded execution plan differs",
        )
        require(isinstance(row[0], str), "Invalid recorded execution state")
        require(row[3] == config.url, "Execution belongs to another configured server")
        receipt = parse_json(row[2])
        require(isinstance(receipt, dict), "Invalid execution qualification")
        return row[0], receipt


def _owner(config, value):
    owner = value.get("owner")
    if owner is None:
        return None
    require(isinstance(owner, dict) and set(owner) == {"plan_id", "index"}, "Invalid job owner")
    identity = digest(owner["plan_id"], "owner plan")
    integer(owner["index"], "owner index")
    found = []
    for family in ("batch", "inference", "evaluation"):
        path = safe_path(config.root, f"{FOLDERS[family]}/{identity}.json")
        if path.exists():
            _, _, plan = _document(config, path)
            require(_kind(plan)[0] == family, "Owner family differs")
            require(
                plan["version"] == (2 if family == "inference" else 1),
                "Unsupported owner plan version",
            )
            check_seal(plan, "plan_id")
            jobs = plan.get("jobs")
            require(isinstance(jobs, list) and owner["index"] < len(jobs), "Owner job is missing")
            job = jobs[owner["index"]]
            require(
                isinstance(job, dict)
                and {"index", "workflow_json", "workflow_sha256"} <= job.keys()
                and job["index"] == owner["index"]
                and isinstance(job["workflow_json"], str),
                "Invalid owner job",
            )
            from itov.owned_jobs import read_owned

            state, receipt = _execution_state(config, plan)
            executor, job_config = family, config
            if receipt.get("scope") == "managed_two_worker_audio":
                from itov.parallel import assignments, worker_configs

                ports = receipt.get("ports")
                require(isinstance(ports, list), "Missing recorded worker ports")
                require(
                    receipt.get("mode") in ("calibrate", "qualify") and len(jobs) >= 2,
                    "Invalid recorded parallel assignment",
                )
                workers = worker_configs(config, ports)
                groups = assignments(plan, receipt.get("mode") == "calibrate")
                matches = [
                    worker for worker, group in zip(workers, groups, strict=True) if job in group
                ]
                require(len(matches) == 1, "Parallel assignment is missing or ambiguous")
                executor, job_config = "parallel", matches[0]
            require(read_owned(job_config, plan, job) == value, "Owner job differs")
            found.append(
                {
                    "family": family,
                    "executor": executor,
                    "status": state,
                    "path": str(path),
                    "plan_id": identity,
                }
            )
    require(len(found) == 1, "Job owner plan is missing or ambiguous; preserve the record")
    return found[0]


def inspect(config, path):
    path, raw, value = _document(config, path)
    kind, key = _kind(value)
    require(
        value["version"] == (2 if kind == "inference" else 1),
        "Unsupported navigation artifact version",
    )
    if key:
        check_seal(value, key)
    actions, related = [], {}

    def add(label, *argv, **kwargs):
        actions.append(command(config, label, *argv, **kwargs))

    recorded = value.get("status", value.get("disposition", "saved"))
    require(isinstance(recorded, str), "Invalid recorded status")
    if kind == "jobs":
        identity = value["request_id"]
        require(
            isinstance(identity, str) and str(uuid.UUID(identity)) == identity,
            "Invalid request identity",
        )
        require(
            path == safe_path(config.root, f"state/jobs/{identity}.json"),
            "Job belongs to another workspace/server",
        )
        digest(value.get("workflow_sha256"), "workflow hash")
        owner = _owner(config, value)
        if owner:
            related["owner"] = owner
            add("Inspect owning plan", "workspace", "inspect", owner["path"])
            add("Observe owning execution", owner["family"], "status", owner["path"])
            if owner["executor"] == "parallel":
                if owner["status"] != "abandoned":
                    add(
                        "Observe or retire the same workers",
                        "parallel",
                        "resume" if owner["status"] == "succeeded" else "recover",
                        owner["path"],
                        when="Recovery requires confirmed worker exit; no worker restart",
                    )
            else:
                add(
                    "Resume the same owner",
                    owner["family"],
                    "resume",
                    owner["path"],
                    when="Observe accepted jobs; only unsubmitted remainder may run",
                )
        else:
            require(value.get("server") == config.url, "Job belongs to another configured server")
            add(
                "Observe or verify this same job",
                "job",
                "wait",
                path,
                when="Never resubmit an uncertain accepted request",
            )
    else:
        identity = value[key]
    if kind in ("batch", "inference", "evaluation"):
        recorded, receipt = _execution_state(config, value)
        parallel = receipt.get("scope") == "managed_two_worker_audio"
        if parallel:
            related["execution_owner"] = "parallel"
        add("Observe recorded execution", kind, "status", path)
        if parallel:
            if recorded == "succeeded":
                add("Reverify completed worker artifacts", "parallel", "resume", path)
            elif recorded != "abandoned":
                add(
                    "Retire confirmed stopped workers",
                    "parallel",
                    "recover",
                    path,
                    when="Only after owned worker exit is confirmed; no worker restart",
                )
        elif recorded == "not_started":
            if kind == "batch":
                add("Qualify this batch", "batch", "qualify", path, "--save")
            else:
                add(
                    "Run this saved plan",
                    kind,
                    "run",
                    path,
                    when="After reviewing the plan and runtime readiness",
                )
        elif recorded not in ("failed", "abandoned"):
            add("Verify or resume the same plan", kind, "resume", path)
        if kind in ("inference", "evaluation") and recorded == "succeeded":
            add("Revalidate completed evidence", kind, "replay", path, "--save")
            if kind == "evaluation":
                add("Continue complete deployed review", "workspace", "guide", "evaluation")
    elif kind == "training":
        record_path = safe_path(config.root, f"state/training/runs/{identity}/run.json")
        if record_path.exists():
            _, _, record = _document(config, record_path)
            check_seal(record, "record_id")
            require(record.get("plan_id") == identity, "Training record belongs to another plan")
            recorded = record.get("status")
            require(isinstance(recorded, str), "Invalid training state")
            related["run"] = str(record_path)
            add("Revalidate training status", "training", "status", path)
            if recorded in ("succeeded", "artifacts_validated"):
                add("Assess technical artifacts", "evaluation", "assess", path, "--save")
                add("Export candidate", "training", "candidate", path, "--save")
            elif recorded in ("running", "validating"):
                add(
                    "Recover the stopped owner",
                    "training",
                    "recover",
                    path,
                    when="Only after its controller and worker are confirmed stopped",
                )
        else:
            recorded = "not_started"
            add(
                "Run declared training",
                "training",
                "run",
                path,
                "--gpu",
                "GPU_UUID",
                needs=["GPU_UUID"],
            )
    elif kind == "experiments":
        add("Inspect every member", "experiment", "status", path)
    elif kind == "candidates":
        related["training_plan"] = str(
            safe_path(
                config.root,
                f"state/training/plans/{digest(value.get('plan_id'), 'training plan')}.json",
            )
        )
        add("Inspect source training", "workspace", "inspect", related["training_plan"])
        add("Continue deployed comparison", "workspace", "guide", "evaluation")
    elif kind == "decisions":
        add("Revalidate disposition and deployment", "candidate", "summary", path)
        add("Inspect catalog lifecycle", "candidate", "status")
    elif kind == "lifecycle":
        from itov.candidate_lifecycle import load_preview

        load_preview(path)
        recorded = "eligible_preview" if value["eligible"] else "refused_preview"
        add("Inspect committed lifecycle", "candidate", "status")
        if value["eligible"]:
            add(
                "Apply this exact preview",
                "candidate",
                "apply",
                path,
                when="After reviewing the entry delta; fresh policy/head checks still apply",
            )
    elif kind == "imports":
        add("Inspect import and retained attempts", "dataset", "import-status", path)
    elif kind == "diagnostics":
        recorded = "passed_metadata" if value.get("ok") else "failed_metadata"
    return {
        "scope": "workspace_inspection",
        "ok": True,
        "path": str(path),
        "kind": kind,
        "identity": identity,
        "document_sha256": sha256(raw),
        "recorded_status": recorded,
        "integrity": "content_seal" if key else "job_identity_and_owner_binding",
        "related": related,
        "actions": actions,
        "limits": LIMITS,
    }


def _files(config, kind):
    folder = safe_path(config.root, FOLDERS[kind])
    if not folder.exists():
        return []
    paths = []
    for index, path in enumerate(folder.iterdir()):
        require(index < LIMIT, f"Inventory directory exceeds {LIMIT} entries: {folder}")
        if kind == "imports":
            safe_path(config.root, path.relative_to(config.root).as_posix())
            if path.is_dir():
                paths.append(path / "operation.json")
        elif path.suffix == ".json":
            paths.append(path)
    return paths


def status(config, *, kind="all", offset=0, limit=25):
    integer(offset, "offset")
    integer(limit, "limit", minimum=1)
    require(limit <= 200 and (kind == "all" or kind in FOLDERS), "Invalid inventory limit or kind")
    catalog, errors, paths = {}, [], []
    store = CatalogStore(config.root)
    try:
        if store._path("HEAD").exists():
            catalog = store._load(store._head()).report()
        else:
            catalog = {"status": "not_initialized"}
        catalog["recovery_required"] = store.recovery_required
    except (OSError, ValueError) as error:
        errors.append({"location": "catalog", "detail": str(error)})
    for group in FOLDERS if kind == "all" else (kind,):
        try:
            paths.extend((group, path) for path in _files(config, group))
        except (OSError, ValueError) as error:
            errors.append({"location": group, "detail": str(error)})
    paths.sort(key=lambda row: (row[0], row[1].as_posix()))
    rows = []
    for group, path in paths[offset : offset + limit]:
        try:
            item = inspect(config, path)
            require(item["kind"] == group, "Artifact family differs from inventory directory")
            rows.append(
                {k: item[k] for k in ("path", "kind", "identity", "recorded_status", "integrity")}
            )
        except (OSError, ValueError, sqlite3.Error) as error:
            errors.append({"location": str(path), "detail": str(error)})
            rows.append(
                {
                    "path": str(path),
                    "kind": group,
                    "recorded_status": "invalid",
                    "error": str(error),
                }
            )
    more = offset + limit < len(paths)
    actions = [
        command(config, "Inspect this artifact", "workspace", "inspect", row["path"])
        for row in rows
        if "error" not in row
    ]
    if more:
        actions.append(
            command(
                config,
                "Next inventory page",
                "workspace",
                "status",
                "--kind",
                kind,
                "--offset",
                offset + limit,
                "--limit",
                limit,
            )
        )
    return {
        "scope": "workspace_inventory",
        "ok": not errors,
        "config": str(config.file),
        "catalog": catalog,
        "entries": rows,
        "issues": errors,
        "total": len(paths),
        "offset": offset,
        "limit": limit,
        "more": more,
        "actions": actions,
        "limits": LIMITS,
    }
