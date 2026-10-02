"""Attributed stable identifiers and conservative connected grouping for dataset review."""

from __future__ import annotations

import re
import unicodedata

from itov.catalog import array, object_fields, require, text


def normalized(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def token(value):
    text(value, "identity token")
    require(
        bool(
            re.fullmatch(
                r"(?:local:[a-z0-9_.-]+:[a-z0-9_.-]+|wikidata:Q[1-9][0-9]*|"
                r"ulan:[1-9][0-9]*|met:(?:work|creator):[1-9][0-9]*)",
                value,
            )
        )
        and len(value) <= 180,
        "Invalid namespaced identity token",
    )
    return value


def aliases(value):
    rows = array(value, "identity aliases")
    require(len(rows) <= 32, "Too many identity aliases")
    for row in rows:
        token(row)
    require(len(set(rows)) == len(rows), "Repeated identity alias")
    return sorted(rows)


def local(value):
    object_fields(value, {"sample", "work", "creators", "notes"}, "local identity")
    text(value["notes"], "identity evidence/limitations")
    works, creators = aliases(value["work"]), aliases(value["creators"])
    issues = []
    if not works:
        issues.append("Work identity unresolved")
    if not creators:
        issues.append("Creator identity unresolved")
    return {
        "work_tokens": works,
        "creator_tokens": creators,
        "creator_labels": [],
        "issues": issues,
        "notes": value["notes"],
    }


def met(metadata):
    issues, creators, labels = [], set(), set()
    work = {f"met:work:{metadata['objectID']}"}

    def uri(raw, kind, target):
        if not raw:
            return
        pattern = (
            r"https?://(?:www\.)?wikidata.org/(?:wiki|entity)/(Q[1-9][0-9]*)/?"
            if kind == "wikidata"
            else r"https?://vocab.getty.edu/(?:page/)?ulan/([1-9][0-9]*)/?"
        )
        match = re.fullmatch(pattern, raw) if isinstance(raw, str) else None
        if match:
            target.add(f"{kind}:{match[1]}")
        else:
            issues.append(f"Unrecognized {kind} identifier in retained metadata")

    uri(metadata.get("objectWikidata_URL"), "wikidata", work)
    parts = metadata.get("constituents") or []
    if not isinstance(parts, list):
        parts = []
        issues.append("Malformed constituent list")
    for part in parts:
        if not isinstance(part, dict):
            issues.append("Malformed constituent record")
            continue
        oid = part.get("constituentID")
        if type(oid) is int and oid > 0:
            creators.add(f"met:creator:{oid}")
        else:
            issues.append("Missing stable constituent identifier")
        role = part.get("role")
        if not isinstance(role, str) or normalized(role) not in {
            "artist",
            "painter",
            "maker",
            "designer",
            "engraver",
            "sculptor",
            "photographer",
        }:
            issues.append("Unresolved creator role; associated identifiers retained conservatively")
        name = part.get("name")
        if isinstance(name, str) and name.strip():
            labels.add(normalized(name))
            if re.search(
                r"\b(style of|after|workshop of|circle of|attributed to|follower of)\b",
                normalized(name),
            ):
                issues.append("Qualified creator attribution in constituent name")
        uri(part.get("constituentWikidata_URL"), "wikidata", creators)
        uri(part.get("constituentULAN_URL"), "ulan", creators)
    uri(metadata.get("artistWikidata_URL"), "wikidata", creators)
    uri(metadata.get("artistULAN_URL"), "ulan", creators)
    display = metadata.get("artistDisplayName")
    if isinstance(display, str) and display.strip():
        labels.add(normalized(display))
    if metadata.get("artistPrefix") or metadata.get("artistSuffix"):
        issues.append("Qualified creator attribution in provider prefix/suffix")
    if not creators:
        issues.append("Creator identity unresolved; display name is not an identifier")
    return {
        "work_tokens": sorted(work),
        "creator_tokens": sorted(creators),
        "creator_labels": sorted(labels),
        "issues": sorted(set(issues)),
        "notes": "Identifiers and attribution supplied by retained Met metadata; not authenticated",
    }


def components(rows, field):
    """Connected overlap, including multi-creator works and transitive aliases."""
    groups = []
    for row in sorted(rows, key=lambda r: r["sample"]):
        tokens = set(row["identity"][field])
        if not tokens:
            continue
        members = {row["sample"]}
        rest = []
        for group in groups:
            if tokens & group["tokens"]:
                tokens |= group["tokens"]
                members |= group["members"]
            else:
                rest.append(group)
        groups = [*rest, {"tokens": tokens, "members": members}]
    return sorted(
        ({"tokens": sorted(g["tokens"]), "members": sorted(g["members"])} for g in groups),
        key=lambda g: g["tokens"],
    )
