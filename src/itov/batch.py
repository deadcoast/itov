"""Plan and replay batches without submitting jobs or recording render history."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal, overload

from itov.batch_request import validate_bindings, validate_request
from itov.catalog import MAX_DOCUMENT_BYTES, canonical_bytes, digest, read_document, require, sha256
from itov.catalog_store import CatalogStore, _atomic_write
from itov.comfyui import parse_json_object
from itov.rotation import ALGORITHM, feasible_stacks, select_jobs
from itov.workflow import validate_workflow

PLAN_FIELDS = {
    "version",
    "algorithm",
    "scope",
    "catalog_head",
    "ledger_head",
    "request",
    "assets",
    "exclusions",
    "stack_counts",
    "jobs",
    "plan_id",
}


@overload
def _asset(root: Path, reference: dict, *, workflow: Literal[True]) -> bytes: ...


@overload
def _asset(root: Path, reference: dict, *, workflow: Literal[False] = False) -> None: ...


@overload
def _asset(root: Path, reference: dict, *, workflow: bool) -> bytes | None: ...


def _asset(root: Path, reference: dict, *, workflow: bool = False) -> bytes | None:
    path = root / reference["path"]
    require(path.resolve().is_relative_to(root), f"Asset escapes workspace: {reference['path']}")
    if workflow:
        raw = read_document(path)
        actual = sha256(raw)
    else:
        raw = None
        with path.open("rb") as source:
            actual = hashlib.file_digest(source, "sha256").hexdigest()
    require(actual == reference["sha256"], f"Asset SHA-256 mismatch: {reference['path']}")
    return raw


def _workflow_json(graph: dict) -> str:
    # Workflows contain float inputs. Store their serialized bytes as a string in
    # the integer-only canonical plan, rather than changing catalog/ledger encoding.
    return (
        json.dumps(
            graph, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        + "\n"
    )


def create_plan(workspace: Path, request) -> dict:
    store = CatalogStore(workspace)
    require(isinstance(request, dict), "Batch request must be an object")
    head = digest(request.get("catalog_head"), "catalog_head")
    snapshot = store.snapshot(expected_head=head, require_clean=True)
    catalog = snapshot.to_dict()["catalog"]
    request = validate_request(parse_json_object(canonical_bytes(request)), catalog)
    presets = {item["id"]: item for item in catalog["presets"]}
    loras = {item["id"]: item for item in catalog["loras"]}
    stacks, exclusions, eligible = feasible_stacks(catalog, request)
    assets, templates = [], {}
    for key in sorted(request["presets"]):
        preset = presets[key]
        raw = _asset(store.workspace, preset["workflow"], workflow=True)
        graph = parse_json_object(raw, message=f"Invalid API workflow: {key}")
        require(validate_workflow(graph).valid, f"Invalid API workflow: {key}")
        validate_bindings(preset, request["bindings"][key], graph)
        templates[key] = raw
        assets.append({"kind": "workflow", "id": key, **preset["workflow"]})
    for key in sorted(eligible):
        _asset(store.workspace, loras[key]["asset"])
        assets.append({"kind": "lora", "id": key, **loras[key]["asset"]})
    jobs = select_jobs(catalog, request, stacks)
    workflow_size = 0
    for job in jobs:
        graph = parse_json_object(templates[job["preset"]])
        binding = request["bindings"][job["preset"]]
        for seed in binding["seed_inputs"]:
            graph[seed["node"]]["inputs"][seed["input"]] = job["seed"]
        by_slot = {item["slot"]: item for item in job["loras"]}
        for slot in binding["lora_slots"]:
            lora = by_slot[slot["slot"]]
            node = graph[slot["node"]]
            node["inputs"]["lora_name"] = lora["loader_name"]
            node["inputs"]["strength_model"] = lora["strength_milli"] / 1000
            if node["class_type"] == "LoraLoader":
                node["inputs"]["strength_clip"] = lora["strength_milli"] / 1000
        require(
            validate_workflow(graph).valid, f"Expanded workflow is invalid at index {job['index']}"
        )
        job["workflow_json"] = _workflow_json(graph)
        job["workflow_sha256"] = sha256(job["workflow_json"].encode("utf-8"))
        workflow_size += len(job["workflow_json"].encode("utf-8"))
        require(workflow_size <= MAX_DOCUMENT_BYTES, "Expanded batch exceeds plan size limit")
    body = {
        "version": 1,
        "algorithm": ALGORITHM,
        "scope": "planning_only",
        "catalog_head": head,
        "ledger_head": snapshot.report()["ledger_head"],
        "request": request,
        "assets": assets,
        "exclusions": exclusions,
        "stack_counts": {key: len(value) for key, value in stacks.items()},
        "jobs": jobs,
    }
    plan = {**body, "plan_id": sha256(canonical_bytes(body))}
    require(len(canonical_bytes(plan)) + 1 <= MAX_DOCUMENT_BYTES, "Batch plan exceeds size limit")
    # Reject a catalog change or pending transaction observed during construction.
    store.snapshot(expected_head=head, require_clean=True)
    return plan


def load_request(path: Path) -> dict:
    return parse_json_object(read_document(path), message="Batch request must be an object")


def _check_plan(value):
    from itov.catalog import object_fields

    object_fields(value, PLAN_FIELDS, "batch plan")
    require(type(value["version"]) is int and value["version"] == 1, "Invalid plan version")
    require(
        value["algorithm"] == ALGORITHM and value["scope"] == "planning_only",
        "Unsupported plan algorithm or scope",
    )
    digest(value["plan_id"], "plan_id")
    digest(value["catalog_head"], "catalog_head")
    digest(value["ledger_head"], "ledger_head")
    require(
        isinstance(value["request"], dict)
        and value["request"].get("catalog_head") == value["catalog_head"],
        "Plan and request catalog heads differ",
    )
    body = {key: item for key, item in value.items() if key != "plan_id"}
    require(sha256(canonical_bytes(body)) == value["plan_id"], "Batch plan hash mismatch")


def save_plan(workspace: Path, plan: dict) -> Path:
    _check_plan(plan)
    CatalogStore(workspace).snapshot(expected_head=plan["catalog_head"], require_clean=True)
    raw = canonical_bytes(plan) + b"\n"
    require(len(raw) <= MAX_DOCUMENT_BYTES, "Batch plan exceeds size limit")
    root = workspace.resolve()
    directory = root / "state/plans"
    path = directory / f"{plan['plan_id']}.json"
    require(path.resolve() == path.absolute() and not path.is_symlink(), "Plan path redirects")
    directory.mkdir(parents=True, exist_ok=True)
    try:
        _atomic_write(path, raw, exclusive=True)
    except FileExistsError:
        require(read_document(path) == raw, "Existing plan differs; preserve and inspect")
    return path


def load_plan(path: Path) -> dict:
    raw = read_document(path)
    plan = parse_json_object(raw, message="batch plan: expected an object")
    _check_plan(plan)
    require(raw == canonical_bytes(plan) + b"\n", "Plan is not canonically encoded")
    return plan


def replay_plan(workspace: Path, plan: dict):
    rebuilt = create_plan(workspace, plan["request"])
    require(
        canonical_bytes(rebuilt) == canonical_bytes(plan), "Plan differs from deterministic replay"
    )


def verify_plan(workspace: Path, path: Path) -> dict:
    plan = load_plan(path)
    replay_plan(workspace, plan)
    return {
        "ok": True,
        "plan_id": plan["plan_id"],
        "catalog_head": plan["catalog_head"],
        "jobs": len(plan["jobs"]),
        "scope": "deterministic_replay_and_asset_bytes",
    }
