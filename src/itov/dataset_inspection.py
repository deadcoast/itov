"""Reproducible duplicate, identity and caption observations; no automatic approval."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from itertools import combinations
from pathlib import Path

from itov import curation
from itov import dataset_identity as identity
from itov.catalog import (
    array,
    canonical_bytes,
    digest,
    identifier,
    object_fields,
    require,
    sha256,
    text,
)
from itov.catalog_store import _atomic_write
from itov.comfyui import parse_json
from itov.evidence_reads import EvidenceReads, read_document
from itov.qualification import safe_path
from itov.training_data import check_seal, file_ref, load_dataset, publish, seal

PROFILE = "oriented-rgb-dhash64-ahash64-v1"
POLICY = {
    "profile": PROFILE,
    "dhash_distance_max": 6,
    "ahash_distance_max": 6,
    "low_luma_range": 16,
    "pair_coverage": "all unordered source pairs",
}
LIMITS = (
    "Similarity hashes are review candidates, not duplicate/independence verdicts. "
    "Source RGB is EXIF-oriented without prepared padding. Identifiers/rights are attributed. "
    "No crop/rotation invariance, universal creator resolution, pretraining exclusion or "
    "model-quality acceptance. Saved replay rechecks bytes and derivation, not image decoding."
)


def ref(root, path):
    path = path.absolute()
    name = path.relative_to(root).as_posix()
    raw = read_document(safe_path(root, name))
    return {"path": name, "sha256": sha256(raw)}


def retained(raw):
    require(0 < len(raw) <= 8 * 1024**2, "Review declaration must be at most 8 MiB")
    return {"utf8": raw.decode("utf-8"), "sha256": sha256(raw), "bytes": len(raw)}


def unretain(value):
    object_fields(value, {"utf8", "sha256", "bytes"}, "retained declaration")
    require(isinstance(value["utf8"], str), "Retained declaration must be UTF-8")
    raw = value["utf8"].encode("utf-8")
    require(retained(raw) == value, "Retained declaration differs")
    return parse_json(raw)


def inputs(root, value):
    object_fields(
        value,
        {"version", "dataset", "curation", "target", "trigger", "local_identities", "exclusions"},
        "dataset inspection specification",
    )
    require(type(value["version"]) is int and value["version"] == 1, "Invalid inspection version")
    identifier(value["trigger"], "caption trigger")
    target = value["target"]
    object_fields(target, {"id", "description", "include", "exclude"}, "visual target")
    identifier(target["id"], "target id")
    text(target["description"], "visual target")
    for field in ("include", "exclude"):
        require(1 <= len(array(target[field], "target criteria")) <= 32, "Invalid target criteria")
        for row in target[field]:
            text(row, "target criterion")
    dataset_path, _ = file_ref(root, value["dataset"], maximum=32 * 1024**2)
    dataset = load_dataset(root, dataset_path)
    declared = {s["id"] for s in dataset["dataset"]["samples"]}
    local = array(value["local_identities"], "local identities")
    curated = None
    if value["curation"] is not None:
        path, _ = file_ref(root, value["curation"], maximum=32 * 1024**2)
        base_curation = parse_json(read_document(path))
        require(
            isinstance(base_curation, dict) and base_curation.get("version") == 1,
            "Inspection uses base version-one provenance; reviewed lineage is verified separately",
        )
        curated = curation.validate(root, path)
        require(curated["dataset_id"] == dataset["dataset_id"], "Inspection curation differs")
        require(not local, "Met identities derive from metadata; overrides are not accepted")
    else:
        if dataset["version"] == 2:
            operation = parse_json(read_document(dataset_path.parent / "operation.json"))
            require(
                operation["definition"]["provider"] == "local",
                "Met dataset inspection requires its curation reference",
            )
        require(len(local) == len(declared), "Local identity declarations must cover all samples")
        seen = set()
        for row in local:
            identity.local(row)
            require(
                isinstance(row["sample"], str)
                and row["sample"] in declared
                and row["sample"] not in seen,
                "Unknown/repeated local identity sample",
            )
            seen.add(row["sample"])
    seen = set()
    exclusions = array(value["exclusions"], "retained exclusions")
    require(len(exclusions) <= 256, "Too many retained exclusions")
    for row in exclusions:
        object_fields(row, {"id", "source", "metadata", "reason", "limitations"}, "exclusion")
        identifier(row["id"], "exclusion id")
        require(row["id"] not in seen | declared, "Repeated/current sample in external exclusions")
        seen.add(row["id"])
        text(row["reason"], "exclusion reason")
        text(row["limitations"], "exclusion limitations")
        require(
            row["source"] is not None or row["metadata"] is not None,
            "Exclusion requires retained source or metadata evidence",
        )
        for field in ("source", "metadata"):
            if row[field] is not None:
                file_ref(root, row[field], maximum=(32 if field == "source" else 4) * 1024**2)
    return dataset, curated


def worker(python, arguments):
    path = Path(__file__).with_name("dataset_features.py")
    try:
        run = subprocess.run(
            [str(python), "-I", str(path), *map(str, arguments)],
            capture_output=True,
            timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired as error:
        raise ValueError("Review decoder exceeded 60 seconds") from error
    try:
        result = parse_json(run.stdout)
    except ValueError as error:
        raise ValueError(
            "Review decoder failed: " + run.stderr.decode(errors="replace")[-2000:]
        ) from error
    require(isinstance(result, dict), "Invalid review decoder response")
    require(
        run.returncode == 0 and result.get("ok") is True,
        "Review decoder: " + str(result.get("error", "No successful result")),
    )
    require(isinstance(result.get("value"), dict), "Missing review decoder evidence")
    return result["value"]


def feature(value, sample):
    object_fields(
        value,
        {
            "source_sha256",
            "source_size",
            "oriented_size",
            "rgb_sha256",
            "dhash",
            "ahash",
            "luma_range",
        },
        "image fingerprints",
    )
    require(value["source_sha256"] == sample["source"]["sha256"], "Fingerprint source differs")
    digest(value["rgb_sha256"], "source RGB hash")
    for field in ("source_size", "oriented_size"):
        size = value[field]
        require(
            isinstance(size, list)
            and len(size) == 2
            and all(type(n) is int and n > 0 for n in size)
            and size[0] * size[1] <= 32_000_000,
            "Invalid decoded dimensions",
        )
    require(
        sorted(value["source_size"]) == sorted(value["oriented_size"]),
        "Source orientation dimensions differ",
    )
    for field in ("dhash", "ahash"):
        require(
            isinstance(value[field], str) and re.fullmatch(r"[0-9a-f]{16}", value[field]),
            "Invalid 64-bit fingerprint",
        )
    require(
        type(value["luma_range"]) is int and 0 <= value["luma_range"] <= 255,
        "Invalid grayscale range",
    )
    return value


def caption_issues(caption, trigger, labels=()):
    words = caption.split()
    issues = []
    if not words or words[0] != trigger or words.count(trigger) != 1:
        issues.append("Caption must begin with exactly one literal trigger token")
    if len(words) < 2:
        issues.append("Caption lacks a descriptive body")
    normalized = identity.normalized(caption)
    if any(label and label in normalized for label in labels):
        issues.append("Caption contains a provider creator label; inspect unintended conditioning")
    return issues


def pairwise(rows):
    pairs = []
    for left, right in combinations(rows, 2):
        a, b = left["features"], right["features"]
        d = (int(a["dhash"], 16) ^ int(b["dhash"], 16)).bit_count()
        h = (int(a["ahash"], 16) ^ int(b["ahash"], 16)).bit_count()
        exact = []
        if a["source_sha256"] == b["source_sha256"]:
            exact.append("source_bytes")
        if a["oriented_size"] == b["oriented_size"] and a["rgb_sha256"] == b["rgb_sha256"]:
            exact.append("source_pixels")
        if left["image"]["sha256"] == right["image"]["sha256"]:
            exact.append("prepared_bytes")
        work = sorted(set(left["identity"]["work_tokens"]) & set(right["identity"]["work_tokens"]))
        creator = sorted(
            set(left["identity"]["creator_tokens"]) & set(right["identity"]["creator_tokens"])
        )
        names = sorted(
            set(left["identity"]["creator_labels"]) & set(right["identity"]["creator_labels"])
        )
        name_ambiguity = bool(names and not creator)
        body = {
            "left": left["sample"],
            "right": right["sample"],
            "exact": exact,
            "dhash_distance": d,
            "ahash_distance": h,
            "work_overlap": work,
            "creator_overlap": creator,
            "creator_name_ambiguity": name_ambiguity,
            "cross_split": left["split"] != right["split"],
            "flagged": bool(
                exact
                or work
                or name_ambiguity
                or d <= POLICY["dhash_distance_max"]
                or h <= POLICY["ahash_distance_max"]
            ),
        }
        pairs.append(seal(body, "pair_id"))
    return pairs


def derive(root, definition, declaration, engine, features):
    dataset, curated = inputs(root, definition)
    object_fields(engine, {"profile", "worker_sha256", "decoder"}, "review engine")
    require(
        engine["profile"] == PROFILE and isinstance(engine["decoder"], dict),
        "Invalid review engine",
    )
    digest(engine["worker_sha256"], "fingerprint worker hash")
    samples = sorted(dataset["dataset"]["samples"], key=lambda s: s["id"])
    require(set(features) == {s["id"] for s in samples}, "Incomplete fingerprint coverage")
    works = {w["sample"]: w for w in curated["document"]["works"]} if curated else {}
    locals_by_id = {r["sample"]: r for r in definition["local_identities"]}
    rows = []
    for sample in samples:
        key = sample["id"]
        if curated:
            path, _ = file_ref(root, works[key]["metadata"], maximum=4 * 1024**2)
            who = identity.met(parse_json(read_document(path)))
        else:
            who = identity.local(locals_by_id[key])
        caption = read_document(safe_path(root, sample["caption"]["path"])).decode("utf-8")
        issues = caption_issues(caption, definition["trigger"], who["creator_labels"])
        rows.append(
            {
                "sample": key,
                "split": sample["split"],
                "declared_group": sample["group"],
                "source": sample["source"],
                "image": sample["image"],
                "caption_ref": sample["caption"],
                "caption": caption,
                "caption_issues": issues,
                "identity": who,
                "features": feature(features[key], sample),
                "low_information": features[key]["luma_range"] < POLICY["low_luma_range"],
            }
        )
    pairs = pairwise(rows)
    groups = {
        kind: identity.components(rows, field)
        for kind, field in (("work", "work_tokens"), ("creator", "creator_tokens"))
    }
    splits = {r["sample"]: r["split"] for r in rows}
    leaks = [
        {"kind": kind, **g}
        for kind, clusters in groups.items()
        for g in clusters
        if len({splits[key] for key in g["members"]}) > 1
    ]
    captions = {}
    for row in rows:
        captions.setdefault(identity.normalized(row["caption"]), []).append(row["sample"])
    return seal(
        {
            "version": 1,
            "scope": "dataset_duplicate_identity_caption_observations",
            "status": "review_pending",
            "definition": definition,
            "declaration": declaration,
            "dataset_id": dataset["dataset_id"],
            "curation_id": curated["curation_id"] if curated else None,
            "engine": engine,
            "policy": POLICY,
            "samples": rows,
            "pairs": pairs,
            "groups": groups,
            "split_leakage": leaks,
            "repeated_captions": sorted(v for v in captions.values() if len(v) > 1),
            "counts": {
                **dataset["counts"],
                "pairs": len(pairs),
                "flagged_pairs": sum(p["flagged"] for p in pairs),
                "unresolved_samples": sum(bool(r["identity"]["issues"]) for r in rows),
            },
            "limits": LIMITS,
        },
        "inspection_id",
    )


def load(root, path):
    value = check_seal(parse_json(read_document(path)), "inspection_id")
    require(value.get("version") == 1, "Unsupported inspection version")
    definition = unretain(value.get("declaration"))
    require(isinstance(value.get("samples"), list), "Invalid inspection samples")
    features = {}
    for row in value["samples"]:
        require(
            isinstance(row, dict)
            and isinstance(row.get("sample"), str)
            and row["sample"] not in features
            and isinstance(row.get("features"), dict),
            "Invalid/repeated inspection sample",
        )
        features[row["sample"]] = row["features"]
    require(
        value == derive(root, definition, value["declaration"], value.get("engine"), features),
        "Inspection differs from reconstruction",
    )
    return value


def template(root, path, value):
    return {
        "version": 1,
        "inspection": ref(root, path),
        "reviewer": {
            "kind": "assistant",
            "name": "PENDING",
            "method": "PENDING",
            "limitations": "PENDING",
        },
        "samples": [
            {
                "sample": r["sample"],
                "decision": "pending",
                "split": r["split"],
                "caption": r["caption"],
                "caption_verdict": "pending",
                "caption_notes": "PENDING",
                "target_fit": "pending",
                "target_notes": "PENDING",
                "decision_notes": "PENDING",
            }
            for r in value["samples"]
        ],
        "pairs": [
            {"pair_id": r["pair_id"], "decision": "pending", "notes": "PENDING"}
            for r in value["pairs"]
            if r["flagged"]
        ],
    }


def markdown(root, value):
    def literal(item):
        # JSON strings escape internal newlines, so supplied text cannot close the fence.
        return ["```json", json.dumps(item, indent=2, ensure_ascii=True), "```", ""]

    lines = [
        "# Dataset inspection",
        "",
        f"Inspection: `{value['inspection_id']}`",
        "",
        "**PENDING REVIEW**. " + LIMITS,
        "",
        "Target:",
        "",
    ]
    lines += literal(value["definition"]["target"])
    for row in value["samples"]:
        lines += [
            f"## {row['sample']} ({row['split']})",
            "",
            f"![source]({safe_path(root, row['source']['path']).as_uri()})",
            "",
        ]
        lines += ["Caption:", "", *literal(row["caption"])]
        lines += ["Identity:", "", *literal(row["identity"])]
        lines += ["Caption findings:", "", *literal(row["caption_issues"])]
    lines += [
        "## Every pair",
        "",
        "Distances are candidates, not verdicts.",
        "",
        "| Left | Right | dHash / aHash | Exact | Flagged |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in value["pairs"]:
        lines.append(
            f"| {row['left']} | {row['right']} | {row['dhash_distance']} / "
            f"{row['ahash_distance']} | {', '.join(row['exact'])} | {row['flagged']} |"
        )
    lines += [
        "",
        "## Retained external exclusions",
        "",
        *literal(value["definition"]["exclusions"]),
    ]
    return ("\n".join(lines)).encode("utf-8")


def inspect(config, path, *, image_python=None, save=False):
    with EvidenceReads().capture() as reads:
        raw = read_document(path)
        definition = parse_json(raw)
        dataset, _ = inputs(config.root, definition)
        python = Path(image_python or sys.executable).absolute()
        engine = worker(python, ["--probe"])
        features = {}
        for sample in dataset["dataset"]["samples"]:
            result = worker(
                python,
                [safe_path(config.root, sample["source"]["path"]), sample["source"]["sha256"]],
            )
            require(result.pop("engine", None) == engine, "Review image engine changed")
            features[sample["id"]] = result
        require(
            worker(python, ["--probe"]) == engine, "Review image engine changed before publication"
        )
        value = derive(config.root, definition, retained(raw), engine, features)
        reads.verify()
        if not save:
            return value
        path = safe_path(
            config.root, f"state/dataset-reviews/inspections/{value['inspection_id']}.json"
        )
        publish(path, value)
        md = safe_path(
            config.root, path.with_suffix(".report-v1.md").relative_to(config.root).as_posix()
        )
        content = markdown(config.root, value)
        try:
            _atomic_write(md, content, exclusive=True)
        except FileExistsError:
            require(read_document(md) == content, "Saved inspection Markdown differs")
        draft = safe_path(
            config.root, path.with_suffix(".review.json").relative_to(config.root).as_posix()
        )
        try:
            _atomic_write(
                draft, canonical_bytes(template(config.root, path, value)) + b"\n", exclusive=True
            )
        except FileExistsError:
            pass  # Preserve operator edits; freeze validates the complete review.
        return {
            **value,
            "saved_path": str(path),
            "artifacts": {
                "inspection": str(path),
                "image report": str(md),
                "review template": str(draft),
            },
        }
