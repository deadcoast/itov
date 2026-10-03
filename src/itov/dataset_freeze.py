"""Explicit reviewed selection, frozen captions/splits and a reproducible import declaration."""

from __future__ import annotations

import uuid

from itov import dataset_inspection as inspection
from itov import dataset_manifest
from itov.catalog import array, canonical_bytes, object_fields, require, sha256, text
from itov.catalog_store import _atomic_write
from itov.comfyui import parse_json, parse_json_object
from itov.curation import TRANSFORM
from itov.evidence_reads import EvidenceReads, read_document
from itov.locking import file_lock
from itov.qualification import safe_path
from itov.training_data import check_seal, file_ref, publish, seal


def review(value, observed):
    object_fields(
        value, {"version", "inspection", "reviewer", "samples", "pairs"}, "dataset review"
    )
    require(
        type(value["version"]) is int and value["version"] == 1, "Invalid dataset review version"
    )
    who = value["reviewer"]
    object_fields(who, {"kind", "name", "method", "limitations"}, "dataset reviewer")
    require(who["kind"] in ("assistant", "human"), "Invalid reviewer kind")
    for field in ("name", "method", "limitations"):
        text(who[field], "reviewer " + field)
    rows = array(value["samples"], "sample reviews")
    wanted = {s["sample"] for s in observed["samples"]}
    require(len(rows) == len(wanted), "Review must cover every sample")
    seen = set()
    for row in rows:
        object_fields(
            row,
            {
                "sample",
                "decision",
                "split",
                "caption",
                "caption_verdict",
                "caption_notes",
                "target_fit",
                "target_notes",
                "decision_notes",
            },
            "sample review",
        )
        require(
            isinstance(row["sample"], str) and row["sample"] in wanted - seen,
            "Unknown/repeated reviewed sample",
        )
        seen.add(row["sample"])
        require(
            row["decision"] in ("pending", "include", "exclude", "unresolved"),
            "Invalid sample decision",
        )
        require(row["split"] in (None, "train", "validation"), "Invalid reviewed split")
        require(
            row["caption_verdict"] in ("pending", "accept", "reject", "uncertain"),
            "Invalid caption verdict",
        )
        require(
            row["target_fit"] in ("pending", "match", "mismatch", "uncertain"),
            "Invalid target verdict",
        )
        require(
            isinstance(row["caption"], str) and len(row["caption"]) <= 4096,
            "Invalid reviewed caption",
        )
        text(row["caption"].strip(), "reviewed caption")
        for field in ("caption_notes", "target_notes", "decision_notes"):
            text(row[field], field)
    pairs = array(value["pairs"], "pair reviews")
    wanted_pairs = {p["pair_id"] for p in observed["pairs"]}
    required = {p["pair_id"] for p in observed["pairs"] if p["flagged"]}
    seen = set()
    for row in pairs:
        object_fields(row, {"pair_id", "decision", "notes"}, "pair review")
        require(
            isinstance(row["pair_id"], str) and row["pair_id"] in wanted_pairs - seen,
            "Unknown/repeated pair review",
        )
        seen.add(row["pair_id"])
        require(
            row["decision"] in ("pending", "distinct", "duplicate", "same_work", "unresolved"),
            "Invalid pair verdict",
        )
        text(row["notes"], "pair notes")
    require(required <= seen, "Every flagged pair requires a recorded disposition")
    return value


def decide(observed, value, declaration):
    review(value, observed)
    blockers = []

    def block(code, subjects, detail):
        blockers.append({"code": code, "subjects": sorted(subjects), "detail": detail})

    who = value["reviewer"]
    if any(who[k].strip().casefold() == "pending" for k in ("name", "method", "limitations")):
        block("reviewer_pending", [], "Record the actual reviewer, method and limitations")
    rows = {r["sample"]: r for r in observed["samples"]}
    decisions = {r["sample"]: r for r in value["samples"]}
    selected = []
    for key, row in sorted(decisions.items()):
        if row["decision"] in ("pending", "unresolved"):
            block("sample_unresolved", [key], "Include or explicitly exclude this sample")
        if row["decision"] != "pending" and any(
            row[k].strip().casefold() == "pending"
            for k in ("caption_notes", "target_notes", "decision_notes")
        ):
            block("notes_pending", [key], "Record caption, target and selection observations")
        if row["decision"] != "include":
            continue
        original = rows[key]
        if row["split"] is None:
            block("split_missing", [key], "Included sample needs an explicit split")
        if row["target_fit"] != "match" or row["caption_verdict"] != "accept":
            block(
                "review_not_accepted",
                [key],
                "Included samples need accepted captions and matching target",
            )
        for detail in original["identity"]["issues"]:
            block("identity_unresolved", [key], detail)
        for detail in inspection.caption_issues(
            row["caption"],
            observed["definition"]["trigger"],
            original["identity"]["creator_labels"],
        ):
            block("caption_issue", [key], detail)
        selected.append(
            {
                "sample": key,
                "split": row["split"],
                "caption": row["caption"],
                "caption_sha256": sha256(row["caption"].encode("utf-8")),
                "source": original["source"],
                "image": original["image"],
                "original_caption": original["caption_ref"],
            }
        )
    by_id = {r["sample"]: r for r in selected}
    counts = {
        split: sum(r["split"] == split for r in selected) for split in ("train", "validation")
    }
    if not all(counts.values()):
        block("empty_split", [], "Both train and validation selections are required")
    # Group across the whole inspected pool first: excluding an alias bridge must
    # not erase the identity evidence that connects two retained samples.
    for kind, groups in observed["groups"].items():
        for group in groups:
            keys = sorted(set(group["members"]) & by_id.keys())
            if (kind == "work" and len(keys) > 1) or len({by_id[k]["split"] for k in keys}) > 1:
                block(
                    kind + "_overlap",
                    keys,
                    "Keep one sample per work and creators within one split",
                )
    declared = {}
    for key in by_id:
        declared.setdefault(rows[key]["declared_group"], []).append(key)
    for keys in declared.values():
        if len({by_id[k]["split"] for k in keys}) > 1:
            block("declared_group_leakage", keys, "Original grouping cannot cross the frozen split")
    pair_reviews = {p["pair_id"]: p for p in value["pairs"]}
    for pair in observed["pairs"]:
        keys = [pair["left"], pair["right"]]
        both = all(k in by_id for k in keys)
        decision = pair_reviews.get(pair["pair_id"])
        if decision and (
            decision["decision"] == "pending" or decision["notes"].strip().casefold() == "pending"
        ):
            block("pair_pending", keys, "Complete the recorded pair disposition")
        if both and (pair["exact"] or pair["creator_name_ambiguity"]):
            block(
                "exact_or_identity_conflict",
                keys,
                "Exact duplicates and ambiguous creator identities cannot both be retained",
            )
        if (
            both
            and decision
            and decision["decision"] in ("duplicate", "same_work", "unresolved", "pending")
        ):
            block(
                "pair_unresolved_or_duplicate",
                keys,
                "Exclude a duplicate or resolve this pair before freezing both",
            )
    body = {
        "version": 1,
        "scope": "reviewed_dataset_selection",
        "ok": not blockers,
        "status": "review_blocked" if blockers else "frozen",
        "inspection": value["inspection"],
        "inspection_id": observed["inspection_id"],
        "dataset_id": observed["dataset_id"],
        "review": value,
        "declaration": declaration,
        "target": observed["definition"]["target"],
        "selected": selected,
        "counts": counts,
        "blockers": blockers,
        "limits": "Frozen assistant/operator judgments, split and exact captions; no model-quality "
        "acceptance. Attributed identities and heuristic pair observations retain their "
        "limitations. Exclusions and unresolved cases remain in the inspection/review.",
    }
    return seal(body, "review_id" if blockers else "freeze_id")


def documents(root, value, observed):
    """Construct the exact B-01 declaration and captions from the frozen selection."""
    dataset, curated = inspection.inputs(root, observed["definition"])
    base = f"state/dataset-reviews/freezes/{value['freeze_id']}"
    originals = {r["id"]: r for r in dataset["dataset"]["samples"]}
    reviewed = {r["sample"]: r for r in value["review"]["samples"]}
    locals_by_id = {r["sample"]: r for r in observed["definition"]["local_identities"]}
    works = {w["sample"]: w for w in curated["document"]["works"]} if curated else {}
    note = "Frozen dataset review " + value["freeze_id"]
    samples, files = [], {}
    for row in value["selected"]:
        key = row["sample"]
        original = originals[key]
        relative = f"captions/{key}.txt"
        files[relative] = row["caption"].encode("utf-8")
        p = {
            "selection_note": note + ": " + reviewed[key]["decision_notes"],
            "caption_note": note + ": " + reviewed[key]["caption_notes"],
        }
        if curated:
            p.update({k: works[key][k] for k in ("object_id", "metadata", "image_url")})
            group = original["group"]
        else:
            p["reference"] = locals_by_id[key]["notes"]
            # Keep the original declared group as an additional no-leak constraint.
            group = original["group"]
        samples.append(
            {
                "id": key,
                "split": row["split"],
                "group": group,
                "source": original["source"],
                "caption": {"path": base + "/" + relative, "sha256": row["caption_sha256"]},
                "provenance": p,
            }
        )
    manifest = {
        "version": 1,
        "id": value["target"]["id"],
        "provider": "met-open-access" if curated else "local",
        "purpose": dataset["dataset"]["purpose"],
        "origin": dataset["dataset"]["origin"],
        "rights": dataset["dataset"]["rights"],
        "transform": TRANSFORM,
        "curation": None,
        "samples": samples,
    }
    if curated:
        old = curated["document"]
        manifest["curation"] = {
            "curator": value["review"]["reviewer"]["name"],
            "selection_policy": note + ": " + value["target"]["description"],
            "policy_url": old["rights"]["policy_url"],
            "policy_snapshot": old["rights"]["policy_snapshot"],
        }
    dataset_manifest.validate(manifest)
    files["import.json"] = canonical_bytes(manifest) + b"\n"
    files["freeze.json"] = canonical_bytes(value) + b"\n"
    return base, files


def verify_files(folder, files):
    names = []
    for path in folder.iterdir():
        safe_path(folder, path.name)
        if path.is_dir():
            require(path.name == "captions", "Unexpected freeze directory")
            for child in path.iterdir():
                relative = child.relative_to(folder).as_posix()
                safe_path(folder, relative)
                require(child.is_file(), "Unexpected nested freeze directory")
                names.append(relative)
        else:
            names.append(path.name)
    require(set(names) == set(files), "Frozen selection has extra/missing artifacts")
    for name, raw in files.items():
        require(read_document(safe_path(folder, name)) == raw, "Frozen artifact differs: " + name)


def load(root, path):
    value = check_seal(parse_json(read_document(path)), "freeze_id")
    require(value.get("status") == "frozen" and value.get("ok") is True, "Selection is not frozen")
    review_value = inspection.unretain(value.get("declaration"))
    object_fields(review_value, {"version", "inspection", "reviewer", "samples", "pairs"}, "review")
    source, _ = file_ref(root, review_value["inspection"], maximum=32 * 1024**2)
    observed = inspection.load(root, source)
    require(
        value == decide(observed, review_value, value["declaration"]),
        "Frozen review differs from reconstruction",
    )
    base, files = documents(root, value, observed)
    folder = safe_path(root, base)
    require(path.absolute() == folder / "freeze.json", "Use the committed freeze.json")
    verify_files(folder, files)
    return value


def artifacts(root, base):
    folder = safe_path(root, base)
    return {
        "freeze": str(folder / "freeze.json"),
        "import declaration": str(folder / "import.json"),
        "captions": str(folder / "captions"),
    }


def freeze(config, path, *, save=False):
    with EvidenceReads().capture() as reads:
        raw = read_document(path)
        review_value = parse_json_object(raw, message="Expected dataset review object")
        source, _ = file_ref(config.root, review_value.get("inspection"), maximum=32 * 1024**2)
        observed = inspection.load(config.root, source)
        value = decide(observed, review_value, inspection.retained(raw))
        reads.verify()
        if not save:
            return value
        if not value["ok"]:
            destination = safe_path(
                config.root, f"state/dataset-reviews/blocked/{value['review_id']}.json"
            )
            publish(destination, value)
            return {**value, "saved_path": str(destination)}
        base, files = documents(config.root, value, observed)
        folder = safe_path(config.root, base)
        lock = safe_path(config.root, f"state/dataset-reviews/locks/{value['freeze_id']}.lock")
        lock.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(lock):
            if folder.exists():
                verify_files(folder, files)
            else:
                stage = safe_path(config.root, f"state/dataset-reviews/attempts/{uuid.uuid4()}")
                stage.mkdir(parents=True)
                for name, content in files.items():
                    target = safe_path(stage, name)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    _atomic_write(target, content, exclusive=True)
                verify_files(stage, files)
                reads.verify()
                folder.parent.mkdir(parents=True, exist_ok=True)
                require(
                    folder.resolve() == folder.absolute() and not folder.exists(),
                    "Freeze destination changed",
                )
                stage.rename(folder)
        return {
            **value,
            "saved_path": str(folder / "freeze.json"),
            "artifacts": artifacts(config.root, base),
        }


def verify(config, path):
    with EvidenceReads().capture() as reads:
        value = load(config.root, path)
        reads.verify()
    return {
        **value,
        "artifacts": artifacts(config.root, f"state/dataset-reviews/freezes/{value['freeze_id']}"),
    }
