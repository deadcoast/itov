"""Reviewed, one-entry catalog transitions with atomic lineage and explicit recovery."""

from copy import deepcopy

from itov import deployed_loader, deployed_review
from itov.catalog import (
    _asset,
    canonical_bytes,
    digest,
    identifier,
    integer,
    object_fields,
    require,
    sha256,
    text,
    validate_catalog,
)
from itov.catalog_store import CatalogStore, _snapshot
from itov.comfyui import parse_json
from itov.evidence_reads import EvidenceReads, read_document
from itov.locking import file_lock
from itov.qualification import safe_path
from itov.training_data import check_seal, file_ref, publish, seal

POLICY = {
    "version": 1,
    "activation": "Current complete accepted_for_matrix decision, non-smoke candidate, "
    "verified deployment/mapping and one explicitly reviewed nonzero strength.",
    "retirement": "Set only this entry to quarantined; retain assets and all evidence.",
    "rollback": "Undo only the latest managed change to this exact entry value. Restoring "
    "active status requires the original deployed authorization to pass again.",
}
LIMITS = (
    "Local explicit catalog policy, not new model-quality evidence or authenticated review. "
    "No automatic promotion. Historical transaction replay does not requalify a model. "
    "Manual catalog import is a separate explicit operator interface. Process-crash recovery "
    "uses the existing journal; power-loss durability and hostile concurrent writes "
    "are unqualified."
)
FIELDS = {
    "version",
    "scope",
    "action",
    "entry_id",
    "expected_head",
    "before",
    "after",
    "authorization",
    "previous_authorization",
    "source_operation",
    "reason",
    "policy",
    "eligible",
    "blockers",
    "limits",
    "operation_id",
}


def _path(config, folder, identity):
    digest(identity, "lifecycle identity")
    return safe_path(config.root, f"state/candidates/{folder}/{identity}.json")


def _lock(config):
    path = safe_path(config.root, "state/candidates/lifecycle.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    return file_lock(path)


def _reference(config, path):
    return deployed_loader.reference(config, path)


def _evidence(config, path):
    decision = deployed_review.replay(config, path)
    packet = check_seal(
        parse_json(read_document(file_ref(config.root, decision["packet"])[0])), "packet_id"
    )
    report = packet["evaluation"]
    require(report["candidate"]["candidate_id"] == decision["candidate_id"], "Candidate differs")
    return decision, report


def _blockers(decision, report, strength=None):
    result = []
    if decision["disposition"] != "accepted_for_matrix":
        result.append("Deployed candidate decision is " + decision["disposition"])
    if report["candidate"]["purpose"] != "training":
        result.append("Smoke-test candidates cannot be activated")
    if strength is not None and strength not in report["strengths_milli"]:
        result.append("Selected strength was not reviewed in the complete deployed matrix")
    return result


def summary(config, path, *, deployment=False, save=False):
    with EvidenceReads().capture() as reads:
        decision, report = _evidence(config, path)
        value = seal(
            {
                "version": 1,
                "scope": "candidate_deployment_validation" if deployment else "candidate_summary",
                "decision": _reference(config, path),
                "decision_id": decision["decision_id"],
                "candidate": report["candidate"],
                "evaluation_plan_id": report["plan_id"],
                "mapping_id": decision["mapping_id"],
                "deployment": report["deployment"],
                "runtime": report["runtime"],
                "technical_pass": True,
                "disposition": decision["disposition"],
                "required_judgments": decision["required_judgments"],
                "by_case": decision["by_case"],
                "review_metadata": decision["review_metadata"],
                "reviewed_strengths_milli": report["strengths_milli"],
                "activation_eligible": not _blockers(decision, report),
                "blockers": _blockers(decision, report),
                "limits": LIMITS,
            },
            "summary_id",
        )
    reads.verify()
    if save:
        path = _path(config, "summaries", value["summary_id"])
        publish(path, value)
        return {**value, "saved_path": str(path)}
    return value


def _entry(catalog, key):
    return next((e for e in catalog["loras"] if e["id"] == key), None)


def load_preview(path):
    value = check_seal(parse_json(read_document(path)), "operation_id")
    object_fields(value, FIELDS, "lifecycle preview")
    require(type(value["version"]) is int and value["version"] == 1, "Invalid preview version")
    require(value["scope"] == "candidate_lifecycle_preview", "Expected lifecycle preview")
    require(value["action"] in ("activate", "retire", "rollback"), "Invalid lifecycle action")
    identifier(value["entry_id"], "entry_id")
    digest(value["expected_head"], "expected head")
    require(
        type(value["eligible"]) is bool and isinstance(value["blockers"], list), "Invalid policy"
    )
    require(value["eligible"] == (not value["blockers"]), "Policy eligibility differs")
    for blocker in value["blockers"]:
        text(blocker, "policy blocker")
    require(value["policy"] == POLICY and value["limits"] == LIMITS, "Lifecycle policy differs")
    text(value["reason"], "lifecycle reason")
    require(len(value["reason"]) <= 4096, "Lifecycle reason exceeds limit")
    for entry in (value["before"], value["after"]):
        require(
            entry is None or isinstance(entry, dict) and entry.get("id") == value["entry_id"],
            "Entry identity differs",
        )
    for authorization in (value["authorization"], value["previous_authorization"]):
        if authorization is not None:
            object_fields(authorization, {"decision", "strength_milli"}, "activation authorization")
            _asset(authorization["decision"], "activation decision")
            integer(authorization["strength_milli"], "strength_milli", minimum=1)
    if value["action"] == "activate":
        require(value["authorization"] is not None, "Activation authorization is missing")
    if value["action"] == "rollback":
        digest(value["source_operation"], "source operation")
    else:
        require(value["source_operation"] is None, "Unexpected source operation")
    require(value["before"] != value["after"], "Lifecycle change is a no-op")
    return value


def transition_catalog(catalog, operation):
    """An exact target precondition; unrelated entries/order/compatibility stay intact."""
    value = deepcopy(catalog)
    key = operation["entry_id"]
    require(_entry(value, key) == operation["before"], "Target entry changed; preview is stale")
    if operation["before"] is None:
        require(operation["after"] is not None, "Empty transition")
        value["loras"].append(deepcopy(operation["after"]))
    else:
        index = next(i for i, row in enumerate(value["loras"]) if row["id"] == key)
        if operation["after"] is None:
            value["loras"].pop(index)
        else:
            value["loras"][index] = deepcopy(operation["after"])
    return validate_catalog(value)


def _history(config, snapshot):
    store = CatalogStore(config.root)
    ledger = snapshot.to_dict()["ledger"]
    result, seen = [], set()
    for index, row in enumerate(ledger):
        if row["version"] != 2:
            continue
        operation = load_preview(file_ref(config.root, row["operation"])[0])
        require(operation["eligible"], "Committed lifecycle operation was refused")
        identity = operation["operation_id"]
        require(identity not in seen, "Duplicate lifecycle operation")
        seen.add(identity)
        before = store._load(operation["expected_head"]).to_dict()
        require(before["ledger"] == ledger[:index], "Lifecycle history predecessor differs")
        require(row["action"] == "candidate_" + operation["action"], "Lifecycle action differs")
        after = transition_catalog(before["catalog"], operation)
        require(sha256(canonical_bytes(after)) == row["catalog_sha256"], "Lifecycle delta differs")
        result.append({"sequence": row["sequence"], "operation": operation})
    return result


def _previous_authorization(config, snapshot, entry):
    if entry is None or entry["status"] != "active":
        return None
    for row in reversed(_history(config, snapshot)):
        operation = row["operation"]
        if operation["entry_id"] == entry["id"]:
            return operation["authorization"] if operation["after"] == entry else None
    return None


def _build(snapshot, *, action, before, after, authorization, previous, source, reason, blockers):
    text(reason, "lifecycle reason")
    require(len(reason) <= 4096, "Lifecycle reason exceeds limit")
    require(before != after, "Lifecycle change is a no-op")
    value = seal(
        {
            "version": 1,
            "scope": "candidate_lifecycle_preview",
            "action": action,
            "entry_id": (after or before)["id"],
            "expected_head": snapshot.head,
            "before": before,
            "after": after,
            "authorization": authorization,
            "previous_authorization": previous,
            "source_operation": source,
            "reason": reason,
            "policy": POLICY,
            "eligible": not blockers,
            "blockers": blockers,
            "limits": LIMITS,
        },
        "operation_id",
    )
    transition_catalog(snapshot.to_dict()["catalog"], value)
    return value


def _activation(config, path, strength, snapshot):
    integer(strength, "strength_milli", minimum=1)
    decision, report = _evidence(config, path)
    candidate = report["candidate"]
    after = deepcopy(candidate["entry"])
    after.update(
        status="active", strength_milli=dict.fromkeys(("min", "max", "recommended"), strength)
    )
    before = _entry(snapshot.to_dict()["catalog"], after["id"])
    if before:
        require(
            {k: v for k, v in before.items() if k not in {"status", "strength_milli"}}
            == {k: v for k, v in after.items() if k not in {"status", "strength_milli"}},
            "Existing candidate metadata differs; preserve it",
        )
    return _build(
        snapshot,
        action="activate",
        before=before,
        after=after,
        authorization={"decision": _reference(config, path), "strength_milli": strength},
        previous=_previous_authorization(config, snapshot, before),
        source=None,
        reason="Explicit activation of the reviewed candidate at the selected strength",
        blockers=_blockers(decision, report, strength),
    )


def _retirement(config, key, reason, snapshot):
    identifier(key, "entry_id")
    before = _entry(snapshot.to_dict()["catalog"], key)
    require(before is not None, "Catalog entry is missing")
    return _build(
        snapshot,
        action="retire",
        before=before,
        after={**before, "status": "quarantined"},
        authorization=None,
        previous=_previous_authorization(config, snapshot, before),
        source=None,
        reason=reason,
        blockers=[],
    )


def _check_authorization(config, authorization, entry):
    require(authorization is not None, "Restoring active status requires deployed authorization")
    object_fields(authorization, {"decision", "strength_milli"}, "activation authorization")
    decision, report = _evidence(config, file_ref(config.root, authorization["decision"])[0])
    strength = integer(authorization["strength_milli"], "strength_milli", minimum=1)
    blockers = _blockers(decision, report, strength)
    require(not blockers, "; ".join(blockers))
    wanted = {
        **report["candidate"]["entry"],
        "status": "active",
        "strength_milli": dict.fromkeys(("min", "max", "recommended"), strength),
    }
    require(entry == wanted, "Restored entry differs from deployed authorization")


def _rollback(config, identity, reason, snapshot):
    digest(identity, "operation_id")
    history = _history(config, snapshot)
    original = next(
        (r["operation"] for r in history if r["operation"]["operation_id"] == identity), None
    )
    require(original is not None, "Lifecycle operation is not committed in this catalog")
    latest = next(
        r["operation"]
        for r in reversed(history)
        if r["operation"]["entry_id"] == original["entry_id"]
    )
    require(latest["operation_id"] == identity, "A later lifecycle operation changed this entry")
    before = _entry(snapshot.to_dict()["catalog"], original["entry_id"])
    require(before == original["after"], "Rollback target entry changed")
    after = original["before"]
    authorization = original["previous_authorization"]
    if after is not None and after["status"] == "active":
        _check_authorization(config, authorization, after)
    else:
        authorization = None
    return _build(
        snapshot,
        action="rollback",
        before=before,
        after=after,
        authorization=authorization,
        previous=_previous_authorization(config, snapshot, before),
        source=identity,
        reason=reason,
        blockers=[],
    )


def _save(config, value, save):
    if save:
        path = _path(config, "previews", value["operation_id"])
        publish(path, value)
        return {**value, "ok": value["eligible"], "saved_path": str(path)}
    return {**value, "ok": value["eligible"]}


def preview(config, path, strength, *, save=False):
    with EvidenceReads().capture() as reads:
        snapshot = CatalogStore(config.root).snapshot(require_clean=True)
        value = _activation(config, path, strength, snapshot)
    reads.verify()
    return _save(config, value, save)


def retirement(config, key, reason, *, save=False):
    with EvidenceReads().capture() as reads:
        value = _retirement(
            config, key, reason, CatalogStore(config.root).snapshot(require_clean=True)
        )
    reads.verify()
    return _save(config, value, save)


def rollback(config, identity, reason, *, save=False):
    with EvidenceReads().capture() as reads:
        value = _rollback(
            config, identity, reason, CatalogStore(config.root).snapshot(require_clean=True)
        )
    reads.verify()
    return _save(config, value, save)


def _refresh(config, value, snapshot):
    require(snapshot.head == value["expected_head"], "Stale catalog head")
    if value["action"] == "activate":
        authorization = value["authorization"]
        expected = _activation(
            config,
            file_ref(config.root, authorization["decision"])[0],
            authorization["strength_milli"],
            snapshot,
        )
    elif value["action"] == "retire":
        expected = _retirement(config, value["entry_id"], value["reason"], snapshot)
    else:
        expected = _rollback(config, value["source_operation"], value["reason"], snapshot)
    require(expected == value, "Lifecycle preview or evidence changed; create a new preview")
    require(expected["eligible"], "; ".join(expected["blockers"]))


def apply(config, path):
    with _lock(config), EvidenceReads().capture() as reads:
        value = load_preview(path)
        store = CatalogStore(config.root)
        snapshot = store.snapshot(require_clean=True)
        _history(config, snapshot)
        _refresh(config, value, snapshot)
        destination = _path(config, "previews", value["operation_id"])
        publish(destination, value)
        operation = _reference(config, destination)
        committed = store.apply_lifecycle(operation, guard=reads.verify)
    return {
        "scope": "candidate_lifecycle_commit",
        "ok": True,
        "action": value["action"],
        "operation_id": value["operation_id"],
        "entry_id": value["entry_id"],
        "catalog_head": committed.head,
        "previous_head": snapshot.head,
        "limits": LIMITS,
    }


def status(config):
    store = CatalogStore(config.root)
    with EvidenceReads().capture() as reads:
        snapshot = store.snapshot()
        history = _history(config, snapshot)
    reads.verify()
    return {
        "scope": "candidate_lifecycle_status",
        "ok": True,
        "catalog_head": snapshot.head,
        "recovery_required": store.recovery_required,
        "entries": snapshot.to_dict()["catalog"]["loras"],
        "operations": [
            {
                "sequence": r["sequence"],
                **{
                    k: r["operation"][k]
                    for k in (
                        "operation_id",
                        "action",
                        "entry_id",
                        "expected_head",
                        "source_operation",
                    )
                },
            }
            for r in history
        ],
        "quality": "Not revalidated; use candidate summary for current deployed evidence",
        "limits": LIMITS,
    }


def replay(config, identity):
    digest(identity, "operation_id")
    with EvidenceReads().capture() as reads:
        snapshot = CatalogStore(config.root).snapshot()
        match = next(
            (r for r in _history(config, snapshot) if r["operation"]["operation_id"] == identity),
            None,
        )
        require(match is not None, "Lifecycle operation is not committed in this catalog")
    reads.verify()
    return {
        "scope": "candidate_lifecycle_replay",
        "valid": True,
        **match,
        "catalog_head": snapshot.head,
        "limits": LIMITS,
    }


def recover(config, *, abandon=False):
    with _lock(config), EvidenceReads().capture() as reads:
        store = CatalogStore(config.root)
        snapshot = store.snapshot()
        if not store.recovery_required:
            return {
                "scope": "candidate_lifecycle_recovery",
                "ok": True,
                "recovery": "not_needed",
                "catalog_head": snapshot.head,
            }
        raw = read_document(store._path("pending.json"))
        intent = parse_json(raw)
        object_fields(intent, {"version", "before", "after", "snapshot"}, "pending transaction")
        target = _snapshot(canonical_bytes(intent["snapshot"]) + b"\n", intent["after"])
        event = target.to_dict()["ledger"][-1]
        require(event["version"] == 2, "Non-lifecycle transaction requires catalog recover")
        if not abandon:
            # Validate the committed delta even if evidence changed after HEAD publication.
            _history(config, target)
            if snapshot.head == intent["before"]:
                value = load_preview(file_ref(config.root, event["operation"])[0])
                _refresh(config, value, snapshot)
            else:
                require(snapshot.head == intent["after"], "HEAD diverged from lifecycle intent")
        result = store.recover(
            lifecycle_guard=reads.verify, expected_pending=sha256(raw), abandon=abandon
        )
    return {"scope": "candidate_lifecycle_recovery", **result, "limits": LIMITS}
