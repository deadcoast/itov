"""Version-one catalog contracts and integer-only canonical JSON encoding."""

from __future__ import annotations

import hashlib
import json
import re
from itertools import combinations
from pathlib import Path

from itov.comfyui import parse_json
from itov.workflow import validate_workflow

MAX_DOCUMENT_BYTES = 32 * 1024 * 1024
MAX_INTEGER = 2**64 - 1


def require(condition: bool, message: str):
    if not condition:
        raise ValueError(message)


def object_fields(value, fields: set[str], location: str):
    require(isinstance(value, dict), f"{location}: expected an object")
    require(set(value) == fields, f"{location}: expected exactly {', '.join(sorted(fields))}")


def array(value, location: str) -> list:
    require(isinstance(value, list), f"{location}: expected an array")
    return value


def text(value, location: str, *, empty: bool = False) -> str:
    require(isinstance(value, str) and (empty or bool(value.strip())), f"{location}: invalid text")
    value.encode("utf-8")  # Reject lone surrogates, including escaped JSON input.
    require(not any(ord(c) < 32 for c in value), f"{location}: control characters are forbidden")
    return value


def identifier(value, location: str) -> str:
    text(value, location)
    require(bool(re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,127}", value)), f"{location}: invalid ID")
    return value


def digest(value, location: str) -> str:
    require(
        isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value)),
        f"{location}: expected lowercase SHA-256",
    )
    return value


def integer(value, location: str, *, minimum: int = 0) -> int:
    require(type(value) is int and minimum <= value <= MAX_INTEGER, f"{location}: invalid integer")
    return value


def canonical_bytes(value) -> bytes:
    """ITOV encoding v1, not RFC 8785: sorted keys, UTF-8, no floats or whitespace."""

    def check(item):
        if isinstance(item, dict):
            require(all(isinstance(key, str) for key in item), "Canonical keys must be strings")
            for child in item.values():
                check(child)
        elif isinstance(item, list):
            for child in item:
                check(child)
        elif type(item) is int:
            require(-MAX_INTEGER <= item <= MAX_INTEGER, "Canonical integer exceeds 64-bit range")
        else:
            require(item is None or type(item) in {str, bool}, "Canonical JSON forbids floats")

    check(value)
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_document(path: Path) -> bytes:
    with path.open("rb") as source:
        raw = source.read(MAX_DOCUMENT_BYTES + 1)
    require(len(raw) <= MAX_DOCUMENT_BYTES, f"Document exceeds {MAX_DOCUMENT_BYTES} bytes: {path}")
    return raw


def _strings(value, location: str, *, ids: bool = False) -> list[str]:
    values = array(value, location)
    for item in values:
        (identifier if ids else text)(item, location)
    require(len(set(values)) == len(values), f"{location}: duplicate values")
    return values


def relative_path(value, location: str) -> str:
    relative = text(value, location)
    parts = relative.split("/")
    reserved = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
    require(
        not any(c in relative for c in '\\:<>"|?*')
        and all(part not in {"", ".", ".."} and not part.endswith((".", " ")) for part in parts)
        and all(part.split(".")[0].upper() not in reserved for part in parts),
        f"{location}: expected a portable relative path",
    )
    return relative


def _asset(value, location: str):
    object_fields(value, {"path", "sha256"}, location)
    relative_path(value["path"], location + ".path")
    digest(value["sha256"], location + ".sha256")


def empty_catalog() -> dict:
    return {
        "version": 1,
        "presets": [],
        "loras": [],
        "compatibility": {
            "hard_conflicts": [],
            "soft_conflicts": [],
            "synergies": [],
            "preset_pairings": [],
        },
    }


def validate_catalog(value) -> dict:
    object_fields(value, {"version", "presets", "loras", "compatibility"}, "catalog")
    require(type(value["version"]) is int and value["version"] == 1, "Catalog version must be 1")
    presets, loras = {}, {}
    for preset in array(value["presets"], "presets"):
        object_fields(
            preset,
            {"id", "category", "tags", "workflow", "base_model", "rotation_weight_milli", "seed"},
            "preset",
        )
        key = identifier(preset["id"], "preset.id")
        require(key not in presets, f"Duplicate preset ID: {key}")
        identifier(preset["category"], f"{key}.category")
        _strings(preset["tags"], f"{key}.tags")
        _asset(preset["workflow"], f"{key}.workflow")
        if preset["base_model"] is not None:
            identifier(preset["base_model"], f"{key}.base_model")
        integer(preset["rotation_weight_milli"], f"{key}.rotation_weight_milli", minimum=1)
        if preset["seed"] is not None:
            object_fields(preset["seed"], {"base", "step"}, f"{key}.seed")
            integer(preset["seed"]["base"], f"{key}.seed.base")
            integer(preset["seed"]["step"], f"{key}.seed.step", minimum=1)
        presets[key] = preset
    paths = {}
    for lora in array(value["loras"], "loras"):
        object_fields(
            lora,
            {
                "id",
                "asset",
                "category",
                "slot",
                "base_models",
                "strength_milli",
                "rotation_weight_milli",
                "trigger_words",
                "status",
            },
            "lora",
        )
        key = identifier(lora["id"], "lora.id")
        require(key not in loras, f"Duplicate LoRA ID: {key}")
        _asset(lora["asset"], f"{key}.asset")
        path = lora["asset"]["path"].casefold()
        require(path not in paths, f"Duplicate LoRA asset path: {path}")
        paths[path] = key
        identifier(lora["category"], f"{key}.category")
        identifier(lora["slot"], f"{key}.slot")
        require(
            bool(_strings(lora["base_models"], f"{key}.base_models", ids=True)),
            f"{key}: at least one base model is required",
        )
        strength = lora["strength_milli"]
        object_fields(strength, {"min", "recommended", "max"}, f"{key}.strength_milli")
        for name, number in strength.items():
            integer(number, f"{key}.strength_milli.{name}")
        require(
            strength["min"] <= strength["recommended"] <= strength["max"],
            f"{key}: strength range is unordered",
        )
        integer(lora["rotation_weight_milli"], f"{key}.rotation_weight_milli", minimum=1)
        _strings(lora["trigger_words"], f"{key}.trigger_words")
        require(
            isinstance(lora["status"], str)
            and lora["status"] in {"candidate", "active", "flagged", "quarantined"},
            f"{key}: invalid status",
        )
        loras[key] = lora
    matrix = value["compatibility"]
    object_fields(
        matrix,
        {"hard_conflicts", "soft_conflicts", "synergies", "preset_pairings"},
        "compatibility",
    )

    def references(items, location, minimum=2):
        ids = _strings(items, location, ids=True)
        require(
            len(ids) >= minimum and set(ids) <= loras.keys(),
            f"{location}: missing, unknown, or insufficient LoRA references",
        )
        return frozenset(ids)

    conflicts = set()
    hard = set()
    for relation in ("hard_conflicts", "soft_conflicts"):
        for pair in array(matrix[relation], relation):
            ids = references(pair, relation)
            require(
                len(ids) == 2 and ids not in conflicts, f"{relation}: duplicate or invalid pair"
            )
            conflicts.add(ids)
            if relation == "hard_conflicts":
                hard.add(ids)
    synergies = set()
    for synergy in array(matrix["synergies"], "synergies"):
        object_fields(synergy, {"loras", "weight_milli"}, "synergy")
        ids = references(synergy["loras"], "synergy.loras")
        require(ids not in synergies, "Duplicate synergy")
        require(
            not any(frozenset(pair) in hard for pair in combinations(ids, 2)),
            "Synergy includes a hard conflict",
        )
        integer(synergy["weight_milli"], "synergy.weight_milli", minimum=1)
        synergies.add(ids)
    pairings = set()
    for pairing in array(matrix["preset_pairings"], "preset_pairings"):
        object_fields(pairing, {"preset", "loras"}, "preset_pairing")
        key = identifier(pairing["preset"], "preset_pairing.preset")
        require(key in presets and key not in pairings, "Duplicate or unknown preset pairing")
        refs = references(pairing["loras"], "preset_pairing.loras", minimum=1)
        require(
            all(presets[key]["base_model"] in loras[item]["base_models"] for item in refs),
            f"{key}: pairing base model mismatch",
        )
        pairings.add(key)
    canonical_bytes(value)
    return value


def load_catalog(path: Path) -> dict:
    return validate_catalog(parse_json(read_document(path)))


def verify_assets(catalog: dict, root: Path) -> list[dict]:
    """Pin actual bytes; workflow validation is structural, never a render claim."""
    validate_catalog(catalog)
    root = root.resolve()
    evidence = []
    for collection, field in (("presets", "workflow"), ("loras", "asset")):
        for item in catalog[collection]:
            asset = item[field]
            path = root / asset["path"]
            require(
                path.resolve().is_relative_to(root), f"Asset escapes workspace: {asset['path']}"
            )
            with path.open("rb") as source:
                actual = hashlib.file_digest(source, "sha256").hexdigest()
            require(actual == asset["sha256"], f"Asset SHA-256 mismatch: {asset['path']}")
            if field == "workflow":
                # Recheck the exact bytes parsed, rather than trusting a prior read.
                raw = read_document(path)
                require(sha256(raw) == actual, f"Asset changed during validation: {asset['path']}")
                result = validate_workflow(parse_json(raw))
                require(result.to_dict()["valid"], f"Invalid API workflow: {asset['path']}")
            evidence.append({"id": item["id"], "path": asset["path"], "sha256": actual})
    return evidence
