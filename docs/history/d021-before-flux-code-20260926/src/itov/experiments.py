"""Preregistered bounded endpoint experiments; loss never selects a checkpoint."""

from __future__ import annotations

import copy

from itov import quality, training
from itov.assessment_context import assessment_context
from itov.catalog import array, canonical_bytes, identifier, integer, object_fields, require, sha256
from itov.catalog import text as checked_text
from itov.comfyui import parse_json
from itov.evidence_reads import EvidenceReads, read_document
from itov.locking import file_lock
from itov.qualification import safe_path
from itov.review_records import CASE_CRITERIA
from itov.training_data import check_seal, file_ref, publish, seal

RULE = "all_cases_all_repetitions_then_fewest_steps"
LIMITS = (
    "Independent final-checkpoint endpoints, each trained from its declared seed; repeated "
    "prefix work consumes the budget. Intermediate restart bundles are not evaluated. "
    "Selection is for further evaluation only, never production acceptance or promotion. "
    "Loss is diagnostic. Reviews inspect every frozen case, seed and all four conditions."
)


def _text(value, label):
    checked_text(value, label)
    require(len(value) <= 4096, label + " exceeds 4096 characters")


def _spec(value):
    require(isinstance(value, dict), "Invalid experiment specification")
    version = value.get("version")
    require(type(version) is int and version in (1, 2), "Unsupported experiment")
    object_fields(
        value,
        {"version", "id", "hypothesis", "endpoints", "repetitions", "budget", "protocol"}
        | ({"numerical_tolerances"} if version == 2 else set()),
        "experiment specification",
    )
    identifier(value["id"], "experiment id")
    _text(value["hypothesis"], "experiment hypothesis")
    integer(value["repetitions"], "repetitions", minimum=1)
    require(value["repetitions"] <= 3, "At most three repetitions")
    if version == 2:
        from itov.experiment_variance import validate_tolerances

        validate_tolerances(value["numerical_tolerances"])
        require(value["repetitions"] >= 2, "Numerical experiments require repeated endpoints")
    endpoints = array(value["endpoints"], "endpoints")
    require(1 <= len(endpoints) <= 4, "Declare one to four endpoints")
    seen = set()
    for row in endpoints:
        object_fields(row, {"id", "hypothesis", "training"}, "endpoint")
        identifier(row["id"], "endpoint id")
        require(len(row["id"]) <= 64 and row["id"] not in seen, "Duplicate/long endpoint id")
        seen.add(row["id"])
        _text(row["hypothesis"], "endpoint hypothesis")
    budget = value["budget"]
    object_fields(budget, {"max_attempts", "max_optimizer_steps", "max_worker_seconds"}, "budget")
    for key, maximum in (
        ("max_attempts", 8),
        ("max_optimizer_steps", 2048),
        ("max_worker_seconds", 28800),
    ):
        integer(budget[key], key, minimum=1)
        require(budget[key] <= maximum, "Experiment budget exceeds supported bounds")
    protocol = value["protocol"]
    object_fields(protocol, {"selection", "method", "limitations"}, "evaluation protocol")
    require(protocol["selection"] == RULE, "Unsupported checkpoint selection rule")
    for key in ("method", "limitations"):
        _text(protocol[key], "protocol " + key)


def _inputs(config, spec):
    _spec(spec)
    templates = []
    for endpoint in spec["endpoints"]:
        path, _ = file_ref(config.root, endpoint["training"], maximum=32 * 1024**2)
        template = parse_json(read_document(path))
        training.validate_spec(template)
        require(template["version"] == 4, "Experiments require v4 optimizer checkpoints")
        templates.append(template)
    fixed = ("dataset", "checkpoint", "model_config", "environment", "trigger", "qualification")
    require(
        all(all(t[k] == templates[0][k] for k in fixed) for t in templates),
        "Endpoints must share dataset, model, environment, trigger and frozen suite",
    )
    _, suite = quality.qualification(config.root, templates[0])
    allocated = {
        "max_attempts": len(templates) * spec["repetitions"],
        "max_optimizer_steps": sum(t["parameters"]["steps"] for t in templates)
        * spec["repetitions"],
        "max_worker_seconds": sum(t["parameters"]["timeout_seconds"] for t in templates)
        * spec["repetitions"],
    }
    require(
        all(v <= spec["budget"][k] for k, v in allocated.items()),
        "Declared endpoints and repetitions exceed the experiment budget",
    )
    return templates, suite, allocated


def _members(spec, templates):
    experiment_hash = sha256(canonical_bytes(spec))
    for endpoint, template in zip(spec["endpoints"], templates, strict=True):
        for repetition in range(1, spec["repetitions"] + 1):
            key = f"{endpoint['id']}-r{repetition}"
            copied = copy.deepcopy(template)
            copied["id"] = "experiment-" + sha256(canonical_bytes([experiment_hash, key]))
            yield key, endpoint["id"], repetition, copied


def _reference(config, path):
    return {"path": path.relative_to(config.root).as_posix(), "sha256": sha256(read_document(path))}


def _destination(config, category, identity):
    return safe_path(config.root, f"state/experiments/{category}/{identity}.json")


def plan(config, path, *, save=False):
    reads = EvidenceReads()
    with reads.capture():
        raw = read_document(path)
        spec = parse_json(raw)
        templates, suite, allocated = _inputs(config, spec)
        members, plans = [], []
        for key, endpoint, repetition, template in _members(spec, templates):
            planned = training.make_plan(config, template, sha256(canonical_bytes(template)))
            require(
                not training.run_folder(config, planned).exists(),
                "Experiment already attempted; replay its manifest or declare a new id",
            )
            plans.append(planned)
            members.append(
                {
                    "id": key,
                    "endpoint": endpoint,
                    "repetition": repetition,
                    "plan": {
                        "path": f"state/training/plans/{planned['plan_id']}.json",
                        "sha256": sha256(canonical_bytes(planned) + b"\n"),
                    },
                }
            )
        value = seal(
            {
                "version": 1,
                "scope": "experiment_plan",
                "specification": spec,
                "specification_sha256": sha256(raw),
                "suite": suite,
                "allocated": allocated,
                "members": members,
                "limits": LIMITS,
            },
            "experiment_id",
        )
        reads.verify()
    if save:
        root = safe_path(config.root, "state/training")
        root.mkdir(parents=True, exist_ok=True)
        with file_lock(root / "training.lock"):
            require(
                all(not training.run_folder(config, p).exists() for p in plans),
                "Experiment already attempted during registration",
            )
            for planned in plans:
                training.save_plan(config, planned)
            publish(_destination(config, "plans", value["experiment_id"]), value)
    return value


def _load(config, path):
    value = check_seal(parse_json(read_document(path)), "experiment_id")
    object_fields(
        value,
        {
            "version",
            "scope",
            "specification",
            "specification_sha256",
            "suite",
            "allocated",
            "members",
            "limits",
            "experiment_id",
        },
        "experiment plan",
    )
    require(
        type(value["version"]) is int
        and value["version"] == 1
        and value["scope"] == "experiment_plan"
        and value["limits"] == LIMITS,
        "Unsupported experiment plan",
    )
    from itov.catalog import digest

    digest(value["specification_sha256"], "specification hash")
    templates, suite, allocated = _inputs(config, value["specification"])
    require(suite == value["suite"] and allocated == value["allocated"], "Experiment inputs differ")
    expected = list(_members(value["specification"], templates))
    require(len(array(value["members"], "members")) == len(expected), "Member coverage differs")
    loaded = []
    for row, (key, endpoint, repetition, template) in zip(value["members"], expected, strict=True):
        object_fields(row, {"id", "endpoint", "repetition", "plan"}, "member")
        require(
            (row["id"], row["endpoint"], row["repetition"]) == (key, endpoint, repetition)
            and type(row["repetition"]) is int,
            "Experiment member binding differs",
        )
        source, _ = file_ref(config.root, row["plan"], maximum=32 * 1024**2)
        planned = training.load_plan(source)
        require(
            planned["specification"] == template
            and planned["restart"] is None
            and planned["specification_sha256"] == sha256(canonical_bytes(template)),
            "Member is not its declared independent checkpoint endpoint",
        )
        require(
            row["plan"]["path"] == f"state/training/plans/{planned['plan_id']}.json",
            "Noncanonical member plan location",
        )
        loaded.append((row, planned, source))
    require(
        all(
            p["worker_sources"] == loaded[0][1]["worker_sources"]
            and p["environment"] == loaded[0][1]["environment"]
            for _, p, _ in loaded
        ),
        "Member runtime environments differ",
    )
    return value, loaded


def run(config, path, member, gpu_uuid):
    reads = EvidenceReads()
    with reads.capture():
        value, members = _load(config, path)
        saved = _destination(config, "plans", value["experiment_id"])
        require(
            read_document(saved) == canonical_bytes(value) + b"\n",
            "Publish the experiment before execution",
        )
        matches = [source for row, _, source in members if row["id"] == member]
        require(len(matches) == 1, "Unknown experiment member")
        reads.verify()
    # The training controller owns the lock, shared GPU lease and immutable one-attempt folder.
    return training.run(config, matches[0], gpu_uuid)


def _observation(config, row, planned, path, *, images):
    folder = training.run_folder(config, planned)
    base = {
        **row,
        "plan_id": planned["plan_id"],
        "step": planned["specification"]["parameters"]["steps"],
    }
    if not folder.exists():
        return {**base, "status": "not_started"}
    if not (folder / "run.json").is_file():
        return {**base, "status": "incomplete", "error": "Attempt folder has no controller record"}
    observed = training.status(config, path)
    base.update(status=observed["status"], record=_reference(config, folder / "run.json"))
    if observed["status"] != "artifacts_validated":
        return {**base, "error": observed.get("error", observed.get("failure_boundary"))}
    if not images:
        return base
    with assessment_context(config, path) as context:
        result = context.validated.result.to_dict()
        base.update(
            result=_reference(config, folder / "result.json"),
            result_id=result["result_id"],
            weights={
                **result["weights"],
                "path": (folder / result["weights"]["path"]).relative_to(config.root).as_posix(),
            },
            checkpoint={
                **result["checkpoints"][-1],
                "path": (folder / result["checkpoints"][-1]["path"])
                .relative_to(config.root)
                .as_posix(),
            },
            diagnostics={
                "heldout_before": result["heldout_before"],
                "heldout_after": result["heldout_after"],
                "optimization": {
                    **result["optimization"],
                    "path": (folder / result["optimization"]["path"])
                    .relative_to(config.root)
                    .as_posix(),
                },
            },
            images=[
                {
                    **image,
                    "image": {
                        **image["image"],
                        "path": (folder / image["image"]["path"])
                        .relative_to(config.root)
                        .as_posix(),
                    },
                }
                for image in context.validated.evaluation.rows()
            ],
        )
    return base


def status(config, path):
    reads = EvidenceReads()
    with reads.capture():
        value, members = _load(config, path)
        rows = [_observation(config, *m, images=False) for m in members]
        reads.verify()
    return {
        "scope": "experiment_status",
        "experiment_id": value["experiment_id"],
        "status": "review_pending"
        if all(r["status"] in {"failed", "artifacts_validated"} for r in rows)
        else "incomplete",
        "budget": value["specification"]["budget"],
        "allocated": value["allocated"],
        "members": rows,
        "limits": LIMITS,
    }


def packet(config, path, *, save=False):
    reads = EvidenceReads()
    with reads.capture():
        value, members = _load(config, path)
        rows = [_observation(config, *m, images=True) for m in members]
        require(
            all(r["status"] in {"failed", "artifacts_validated"} for r in rows),
            "Every declared member must finish or fail before review; recover stopped attempts",
        )
        result = seal(
            {
                "version": 1,
                "scope": "experiment_review_pending",
                "experiment_id": value["experiment_id"],
                "suite": value["suite"],
                "protocol": value["specification"]["protocol"],
                "members": rows,
                "limits": LIMITS,
            },
            "packet_id",
        )
        reads.verify()
    if save:
        destination = _destination(config, "packets", result["packet_id"])
        publish(destination, result)
        from itov.catalog_store import _atomic_write

        lines = [
            "# Experiment checkpoint review",
            "",
            "Decision: PENDING.",
            "",
            LIMITS,
            "",
            "Protocol: " + value["specification"]["protocol"]["method"],
            "",
        ]
        for row in rows:
            lines += [f"## {row['id']} / step {row['step']} / {row['status']}", ""]
            for image in row.get("images", []):
                case = next(c for c in value["suite"]["cases"] if c["id"] == image["case_id"])
                lines += [
                    f"### {image['case_id']} / seed {image['seed']} / {image['role']}",
                    "",
                    case["prompt"],
                    "",
                    "Expected: " + case["expectation"],
                    "",
                    f"![image]({(config.root / image['image']['path']).as_uri()})",
                    "",
                ]
        markdown = ("\n".join(lines) + "\n").encode("utf-8")
        target = destination.with_suffix(".md")
        try:
            _atomic_write(target, markdown, exclusive=True)
        except FileExistsError:
            require(target.read_bytes() == markdown, "Existing experiment report differs")
        template = {
            "version": 1,
            "packet": _reference(config, destination),
            "reviewer": "",
            "reviewer_kind": "assistant",
            "method": "",
            "limitations": "",
            "members": [
                {
                    "id": row["id"],
                    "cases": [
                        {
                            "case_id": c["id"],
                            "seed": seed,
                            "verdicts": dict.fromkeys(sorted(CASE_CRITERIA), "pending"),
                            "notes": "",
                        }
                        for c in value["suite"]["cases"]
                        for seed in c["seeds"]
                    ]
                    if row["status"] == "artifacts_validated"
                    else [],
                    "notes": "",
                }
                for row in rows
            ],
        }
        target = destination.with_suffix(".review.json")
        if not target.exists():
            publish(target, template)
    return result


def decide(config, path, review_path, *, save=False):
    reads = EvidenceReads()
    with reads.capture():
        raw = read_document(review_path)
        value = _decide(config, path, parse_json(raw), sha256(raw))
        reads.verify()
    if save:
        publish(_destination(config, "decisions", value["decision_id"]), value)
    return value


def _decide(config, path, review, review_hash):
    reads = EvidenceReads()
    with reads.capture():
        current = packet(config, path)
        object_fields(
            review,
            {"version", "packet", "reviewer", "reviewer_kind", "method", "limitations", "members"},
            "experiment review",
        )
        require(
            type(review["version"]) is int and review["version"] == 1,
            "Unsupported experiment review",
        )
        require(review["reviewer_kind"] in {"human", "assistant"}, "Unsupported reviewer")
        for key in ("reviewer", "method", "limitations"):
            _text(review[key], key)
        saved, _ = file_ref(config.root, review["packet"], maximum=32 * 1024**2)
        require(parse_json(read_document(saved)) == current, "Experiment review is stale")
        rows = array(review["members"], "reviewed members")
        require(len(rows) == len(current["members"]), "Review every declared member")
        outcomes = []
        wanted = [(c["id"], seed) for c in current["suite"]["cases"] for seed in c["seeds"]]
        for row, member in zip(rows, current["members"], strict=True):
            object_fields(row, {"id", "cases", "notes"}, "member review")
            require(row["id"] == member["id"], "Review member coverage/order differs")
            _text(row["notes"], "member notes")
            cases = array(row["cases"], "case reviews")
            expected = wanted if member["status"] == "artifacts_validated" else []
            require(len(cases) == len(expected), "Review every frozen case and seed")
            verdicts = []
            for case, key in zip(cases, expected, strict=True):
                object_fields(case, {"case_id", "seed", "verdicts", "notes"}, "case review")
                require(
                    type(case["seed"]) is int and (case["case_id"], case["seed"]) == key,
                    "Case/seed coverage differs",
                )
                object_fields(case["verdicts"], CASE_CRITERIA, "case verdicts")
                require(
                    all(
                        isinstance(v, str) and v in {"pass", "fail", "uncertain"}
                        for v in case["verdicts"].values()
                    ),
                    "Unresolved case verdict",
                )
                _text(case["notes"], "case observations")
                verdicts.extend(case["verdicts"].values())
            disposition = (
                "failed"
                if member["status"] == "failed"
                else "rejected"
                if "fail" in verdicts
                else "inconclusive"
                if "uncertain" in verdicts
                else "eligible"
            )
            outcomes.append(
                {
                    "id": row["id"],
                    "endpoint": member["endpoint"],
                    "step": member["step"],
                    "disposition": disposition,
                    "plan_id": member["plan_id"],
                }
            )
        endpoint_rows = []
        for endpoint in dict.fromkeys(m["endpoint"] for m in outcomes):
            matching = [m for m in outcomes if m["endpoint"] == endpoint]
            verdicts = {m["disposition"] for m in matching}
            disposition = (
                "eligible"
                if verdicts == {"eligible"}
                else "rejected"
                if verdicts & {"failed", "rejected"}
                else "inconclusive"
            )
            endpoint_rows.append(
                {"id": endpoint, "step": matching[0]["step"], "disposition": disposition}
            )
        eligible = sorted(
            (m for m in endpoint_rows if m["disposition"] == "eligible"),
            key=lambda m: (m["step"], m["id"]),
        )
        selected = eligible[0]["id"] if eligible else None
        disposition = (
            "selected_for_evaluation"
            if selected
            else "inconclusive"
            if any(m["disposition"] == "inconclusive" for m in endpoint_rows)
            else "rejected"
        )
        value = seal(
            {
                "version": 1,
                "scope": "experiment_selection",
                "status": disposition,
                "experiment_id": current["experiment_id"],
                "packet_id": current["packet_id"],
                "review": review,
                "review_sha256": review_hash,
                "members": outcomes,
                "endpoints": endpoint_rows,
                "selected_endpoint": selected,
                "selected_members": [m["id"] for m in outcomes if m["endpoint"] == selected],
                "promotion_eligible": False,
                "limits": LIMITS,
            },
            "decision_id",
        )
        reads.verify()
    return value


def replay(config, path, decision_path):
    """Recheck a saved decision and every bound artifact without running the worker."""
    reads = EvidenceReads()
    with reads.capture():
        saved = check_seal(parse_json(read_document(decision_path)), "decision_id")
        from itov.catalog import digest

        digest(saved.get("review_sha256"), "review hash")
        current = _decide(config, path, saved.get("review"), saved["review_sha256"])
        require(saved == current, "Decision evidence or selection differs")
        reads.verify()
    return {
        "scope": "experiment_decision_replay",
        "decision_id": saved["decision_id"],
        "valid": True,
        "status": saved["status"],
        "selected_endpoint": saved["selected_endpoint"],
        "promotion_eligible": False,
        "limits": LIMITS,
    }
