"""Shared offline lint inputs, deterministic reports and explicit publication."""

from __future__ import annotations

import unicodedata
from pathlib import Path

from itov.batch import load_plan, replay_plan
from itov.catalog import (
    MAX_DOCUMENT_BYTES,
    array,
    canonical_bytes,
    identifier,
    object_fields,
    read_document,
    require,
    sha256,
    text,
)
from itov.catalog_store import CatalogStore, _atomic_write
from itov.comfyui import parse_json
from itov.locking import file_lock
from itov.qualification import safe_path

NORMALIZATION = {"algorithm": "nfc-casefold-whitespace-v1", "unicode": unicodedata.unidata_version}
LIMITS = (
    "Offline lexical/metadata checks only. No prompt rewriting, model execution, "
    "activation proof, semantic quality score, catalog promotion or execution authorization."
)


def normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value.casefold()).split())


def terms(value, location, *, maximum=512):
    result = array(value, location)
    require(len(result) <= maximum, f"{location}: too many terms")
    seen = set()
    for term in result:
        text(term, location)
        require(len(term) <= 128 and bool(normalize(term)), f"{location}: invalid term length")
        require(normalize(term) not in seen, f"{location}: duplicate normalized term")
        seen.add(normalize(term))
    return result


def ids(value, location, *, maximum=256):
    result = array(value, location)
    require(len(result) <= maximum, f"{location}: too many IDs")
    for item in result:
        identifier(item, location)
    require(len(result) == len(set(result)), f"{location}: duplicate IDs")
    return result


def origin(value):
    object_fields(value, {"title", "reference"}, "origin")
    for item in value.values():
        text(item, "origin")
        require(len(item) <= 2048, "Origin text is too long")


def document(path: Path):
    raw = read_document(path)
    return parse_json(raw), {"sha256": sha256(raw), "bytes": len(raw)}


def context(config, plan_path=None):
    store = CatalogStore(config.root)
    snapshot = store.snapshot(require_clean=True)
    plan = load_plan(plan_path) if plan_path is not None else None
    if plan is not None:
        require(plan["catalog_head"] == snapshot.head, "Stale plan catalog head")
        replay_plan(config.root, plan)
    return store, snapshot, plan


def contains(prompt: str, term: str) -> bool:
    """Literal phrase match with Unicode word boundaries; never interpret regex or DSL."""
    prompt, term = normalize(prompt), normalize(term)

    def word(char):
        return char.isalnum() or char == "_" or unicodedata.category(char).startswith("M")

    start = 0
    while (at := prompt.find(term, start)) >= 0:
        end = at + len(term)
        if (not word(term[0]) or at == 0 or not word(prompt[at - 1])) and (
            not word(term[-1]) or end == len(prompt) or not word(prompt[end])
        ):
            return True
        start = at + 1
    return False


def finish(store, snapshot, *, kind, inputs, findings, details, strict=False, save=False):
    require(type(strict) is bool, "strict must be boolean")
    findings = sorted(findings, key=canonical_bytes)
    require(len(findings) <= 10000, "Too many lint findings; narrow the input scope")
    counts = {
        severity: sum(f["severity"] == severity for f in findings)
        for severity in ("error", "warning")
    }
    body = {
        "version": 1,
        "scope": "offline_" + kind + "_lint",
        "catalog_head": snapshot.head,
        "ledger_head": snapshot.report()["ledger_head"],
        "normalization": dict(NORMALIZATION),
        "inputs": inputs,
        "strict": strict,
        "ok": counts["error"] == 0 and (not strict or counts["warning"] == 0),
        "counts": counts,
        "findings": findings,
        "details": details,
        "limits": LIMITS,
    }
    report = {**body, "report_id": sha256(canonical_bytes(body))}
    raw = canonical_bytes(report) + b"\n"
    require(len(raw) <= MAX_DOCUMENT_BYTES, "Lint report exceeds document limit")
    path = None
    # Check freshness even for read-only reports. Publish only against the same clean head.
    with file_lock(store._path("catalog.lock"), timeout=store.lock_timeout):
        store._clean()
        require(store._head() == snapshot.head, "Catalog changed during lint")
        if save:
            path = safe_path(store.workspace, f"state/lint/{kind}/{report['report_id']}.json")
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                _atomic_write(path, raw, exclusive=True)
            except FileExistsError:
                require(read_document(path) == raw, "Existing lint report differs; preserve it")
    return {**report, "saved_path": str(path) if path else None}
