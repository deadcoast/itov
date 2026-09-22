"""Catalog-backed trigger collision review; aliases identify rows, never replace prompts."""

from __future__ import annotations

from itertools import combinations
from pathlib import Path

from itov import linting
from itov.catalog import array, digest, integer, object_fields, relative_path, require, text
from itov.qualification import safe_path


def load_rules(path: Path):
    rules, source = linting.document(path)
    object_fields(rules, {"version", "origin", "near_distance", "vocabularies"}, "trigger rules")
    require(
        type(rules["version"]) is int and rules["version"] == 1, "Invalid trigger rules version"
    )
    linting.origin(rules["origin"])
    integer(rules["near_distance"], "near_distance")
    require(rules["near_distance"] <= 2, "near_distance must be 0, 1 or 2")
    refs = array(rules["vocabularies"], "vocabularies")
    require(len(refs) <= 16, "At most 16 vocabulary files")
    vocabularies, sources, names = [], [], set()
    for ref in refs:
        object_fields(ref, {"path", "sha256"}, "vocabulary reference")
        relative_path(ref["path"], "vocabulary path")
        digest(ref["sha256"], "vocabulary hash")
        name = ref["path"].casefold()
        require(name not in names, "Duplicate vocabulary reference")
        names.add(name)
        value, observed = linting.document(safe_path(path.resolve().parent, ref["path"]))
        require(observed["sha256"] == ref["sha256"], "Vocabulary SHA-256 mismatch")
        object_fields(value, {"version", "origin", "base_models", "kind", "terms"}, "vocabulary")
        require(
            type(value["version"]) is int and value["version"] == 1, "Invalid vocabulary version"
        )
        linting.origin(value["origin"])
        require(
            bool(linting.ids(value["base_models"], "vocabulary base_models")),
            "Empty vocabulary models",
        )
        require(value["kind"] in ("base", "reserved"), "Invalid vocabulary kind")
        linting.terms(value["terms"], "vocabulary terms", maximum=5000)
        vocabularies.append({**value, "path": ref["path"]})
        sources.append({**ref, "bytes": observed["bytes"], "origin": value["origin"]})
    return (
        rules,
        vocabularies,
        {"rules": {**source, "origin": rules["origin"]}, "vocabularies": sources},
    )


def near(a, b, limit):
    """Banded Levenshtein threshold, including bounded substring differences."""
    if abs(len(a) - len(b)) > limit:
        return False
    previous = {j: j for j in range(min(len(b), limit) + 1)}
    for i, ca in enumerate(a, 1):
        current = {}
        for j in range(max(0, i - limit), min(len(b), i + limit) + 1):
            current[j] = min(
                previous.get(j, limit + 1) + 1,
                current.get(j - 1, limit + 1) + 1,
                previous.get(j - 1, limit + 1) + (ca != b[j - 1]) if j else i,
            )
        if min(current.values()) > limit:
            return False
        previous = current
    return previous.get(len(b), limit + 1) <= limit


def index(catalog):
    require(len(catalog["loras"]) <= 256, "Trigger lint supports at most 256 LoRAs")
    rows, excluded, count = [], [], 0
    for lora in sorted(catalog["loras"], key=lambda item: item["id"]):
        if lora["status"] == "quarantined":
            excluded.append({"lora": lora["id"], "reason": "quarantined"})
            continue
        count += len(lora["trigger_words"])
        require(count <= 512, "Trigger lint supports at most 512 declarations")
        for position, token in enumerate(lora["trigger_words"]):
            text(token, "trigger")
            require(len(token) <= 128 and bool(linting.normalize(token)), "Invalid trigger length")
            normalized = linting.normalize(token)
            rows.append(
                {
                    "lora": lora["id"],
                    "position": position,
                    "text": token,
                    "normalized": normalized,
                    "base_models": sorted(lora["base_models"]),
                    "asset": lora["asset"],
                    "status": lora["status"],
                    "alias": lora["id"] + "::" + normalized,
                    "alias_use": "report_label_only",
                }
            )
    return rows, excluded


def findings_for(rows, vocabularies, distance, base=None):
    findings = []

    def add(code, severity, holders, **extra):
        findings.append(
            {
                "code": code,
                "severity": severity,
                "holders": [
                    {"lora": r["lora"], "trigger": r["text"], "position": r["position"]}
                    for r in holders
                ],
                **extra,
            }
        )
        require(len(findings) <= 10000, "Too many trigger findings; narrow the input scope")

    for a, b in combinations(rows, 2):
        models = sorted(set(a["base_models"]) & set(b["base_models"]))
        if not models or (base is not None and base not in models):
            continue
        if a["normalized"] == b["normalized"]:
            add(
                "C0_DUPLICATE" if a["lora"] == b["lora"] else "C1_EXACT",
                "error",
                [a, b],
                base_models=[base] if base else models,
            )
        elif (
            a["lora"] != b["lora"] and distance and near(a["normalized"], b["normalized"], distance)
        ):
            add("C2_NEAR", "warning", [a, b], base_models=[base] if base else models)
    for row in rows:
        covered = set()
        models = {base} if base else set(row["base_models"])
        for vocab in vocabularies:
            applicable = models & set(vocab["base_models"])
            if not applicable:
                continue
            covered.update(applicable)
            # Normalized sets are built once by lint(), not once per trigger.
            if row["normalized"] in vocab["normalized_terms"]:
                reserved = vocab["kind"] == "reserved"
                add(
                    "C4_RESERVED" if reserved else "C3_BASE",
                    "error" if reserved else "warning",
                    [row],
                    vocabulary=vocab["path"],
                    base_models=sorted(applicable),
                )
        if models - covered:
            add("VOCABULARY_UNCOVERED", "warning", [row], base_models=sorted(models - covered))
    return findings


def lint(config, rules_path: Path, *, plan_path=None, strict=False, save=False):
    rules, vocabularies, sources = load_rules(rules_path)
    for vocab in vocabularies:
        vocab["normalized_terms"] = {linting.normalize(t) for t in vocab["terms"]}
    store, snapshot, plan = linting.context(config, plan_path)
    catalog = snapshot.to_dict()["catalog"]
    rows, excluded = index(catalog)
    findings = []
    if plan is None:
        findings = findings_for(rows, vocabularies, rules["near_distance"])
        selected_rows = rows
    else:
        presets = {p["id"]: p for p in catalog["presets"]}
        selected = {lora["id"] for job in plan["jobs"] for lora in job["loras"]}
        selected_rows = [r for r in rows if r["lora"] in selected]
        cache = {}
        for job in plan["jobs"]:
            keys = sorted(lora["id"] for lora in job["loras"])
            base = presets[job["preset"]]["base_model"]
            key = (base, tuple(keys))
            if key not in cache:
                cache[key] = findings_for(
                    [r for r in selected_rows if r["lora"] in keys],
                    vocabularies,
                    rules["near_distance"],
                    base,
                )
            findings.extend(
                {**f, "job_index": job["index"], "preset": job["preset"]} for f in cache[key]
            )
            require(len(findings) <= 10000, "Too many trigger findings; narrow the input scope")
    details = {
        "index": selected_rows,
        "excluded": excluded,
        "declared_triggers_checked": len(selected_rows),
        "loras_without_declared_triggers": sorted(
            lora["id"]
            for lora in catalog["loras"]
            if not lora["trigger_words"]
            and lora["status"] != "quarantined"
            and (plan is None or lora["id"] in selected)
        ),
        "asset_scope": "replayed_plan_asset_bytes" if plan else "catalog_references_only",
        "collision_scope": "selected_job_stacks" if plan else "shared_base_catalog_metadata",
        "aliases_change_activation": False,
    }
    return linting.finish(
        store,
        snapshot,
        kind="triggers",
        inputs={
            **sources,
            "plan_id": plan["plan_id"] if plan else None,
            "near_distance": rules["near_distance"],
        },
        findings=findings,
        details=details,
        strict=strict,
        save=save,
    )
