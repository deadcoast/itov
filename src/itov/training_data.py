"""Explicit dataset lineage and immutable preparation for bounded image training."""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

from itov.catalog import (
    array,
    canonical_bytes,
    digest,
    identifier,
    object_fields,
    read_document,
    relative_path,
    require,
    sha256,
    text,
)
from itov.catalog_store import _atomic_write
from itov.comfyui import parse_json
from itov.linting import document, origin
from itov.qualification import safe_path


def file_ref(root: Path, value, *, maximum=None):
    object_fields(value, {"path", "sha256"}, "file reference")
    relative_path(value["path"], "file path")
    digest(value["sha256"], "file hash")
    path = safe_path(root, value["path"])
    require(path.is_file(), f"Missing file: {value['path']}")
    size = path.stat().st_size
    require(size > 0 and (maximum is None or size <= maximum), "File size outside supported bounds")
    with path.open("rb") as source:
        observed = hashlib.file_digest(source, "sha256").hexdigest()
    require(observed == value["sha256"], f"File SHA-256 mismatch: {value['path']}")
    return path, size


def seal(body, key):
    return {**body, key: sha256(canonical_bytes(body))}


def check_seal(value, key):
    require(isinstance(value, dict), "Expected a sealed object")
    digest(value.get(key), key)
    require(
        value[key] == sha256(canonical_bytes({k: v for k, v in value.items() if k != key})),
        "Document hash mismatch",
    )
    return value


def publish(path: Path, value):
    raw = canonical_bytes(value) + b"\n"
    require(len(raw) <= 32 * 1024 * 1024, "Training document exceeds 32 MiB")
    require(
        path.resolve() == path.absolute() and not path.is_symlink(), "Publication path redirects"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _atomic_write(path, raw, exclusive=True)
    except FileExistsError:
        require(read_document(path) == raw, "Existing training evidence differs; preserve it")
    return path


def validate(root: Path, path: Path):
    value, source = document(path)
    return validate_value(root, value, source)


def validate_value(root: Path, value, source):
    object_fields(source, {"sha256", "bytes"}, "dataset source")
    digest(source["sha256"], "dataset source hash")
    require(
        type(source["bytes"]) is int and 0 < source["bytes"] <= 32 * 1024 * 1024,
        "Invalid dataset document size",
    )
    object_fields(
        value,
        {"version", "id", "purpose", "origin", "rights", "preprocessing", "samples"},
        "dataset",
    )
    require(type(value["version"]) is int and value["version"] == 1, "Invalid dataset version")
    identifier(value["id"], "dataset id")
    require(value["purpose"] in ("smoke", "training"), "Invalid dataset purpose")
    origin(value["origin"])
    object_fields(value["rights"], {"basis", "reference", "training_permitted"}, "dataset rights")
    text(value["rights"]["basis"], "rights basis")
    text(value["rights"]["reference"], "rights reference")
    require(
        value["rights"]["training_permitted"] is True,
        "Training permission must be explicitly declared",
    )
    require(
        value["preprocessing"] == "prepared-square-rgb-png-v1", "Unsupported dataset preprocessing"
    )
    samples = array(value["samples"], "samples")
    require(2 <= len(samples) <= 256, "Dataset requires 2 to 256 samples")
    seen, paths, images, groups, sources, observations = set(), set(), set(), {}, {}, []
    splits = {"train": 0, "validation": 0}
    total = 0
    for sample in samples:
        object_fields(sample, {"id", "split", "group", "source", "image", "caption"}, "sample")
        key = identifier(sample["id"], "sample id")
        require(key not in seen, "Duplicate sample ID")
        seen.add(key)
        identifier(sample["group"], "sample group")
        require(sample["split"] in ("train", "validation"), "Invalid sample split")
        split = sample["split"]
        for field in ("source", "image", "caption"):
            asset, size = file_ref(
                root, sample[field], maximum=65536 if field == "caption" else 32 * 1024 * 1024
            )
            total += size
            require(total <= 1024 * 1024 * 1024, "Dataset exceeds 1 GiB verification budget")
            if field != "source":
                path_key = sample[field]["path"].casefold()
                require(path_key not in paths, "Dataset reuses a prepared image/caption path")
                paths.add(path_key)
            if field == "image":
                require(sample[field]["sha256"] not in images, "Duplicate prepared image content")
                images.add(sample[field]["sha256"])
                with asset.open("rb") as handle:
                    header = handle.read(33)
                require(
                    header[:16] == b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR" and len(header) == 33,
                    "Prepared image must be PNG",
                )
                width, height, depth, color, compression, filtering, interlace = struct.unpack(
                    ">IIBBBBB", header[16:29]
                )
                require(
                    64 <= width == height <= 2048
                    and (depth, color, compression, filtering, interlace) == (8, 2, 0, 0, 0),
                    "Prepared PNG must be square, 64..2048, RGB8 and noninterlaced",
                )
            elif field == "caption":
                caption = asset.read_bytes().decode("utf-8")
                text(caption.strip(), "caption")
                require(len(caption) <= 4096, "Caption exceeds 4096 characters")
        for field, mapping, item in (
            ("group", groups, sample["group"]),
            ("source", sources, sample["source"]["sha256"]),
        ):
            require(mapping.get(item, split) == split, f"Train/validation {field} leakage")
            mapping[item] = split
        observations.append(
            {"id": key, "split": split, "group": sample["group"], "width": width, "height": height}
        )
        splits[split] += 1
    require(all(splits.values()), "Both train and held-out validation samples are required")
    return seal(
        {
            "version": 1,
            "scope": "dataset_bytes_and_declared_lineage",
            "source": source,
            "dataset": value,
            "samples": sorted(observations, key=lambda item: item["id"]),
            "counts": splits,
            "limits": (
                "Byte/header integrity and declared group/source isolation only. "
                "Full image decode occurs in the trainer. Rights are supplied attestations; "
                "perceptual duplication, independence and model quality are not established."
            ),
        },
        "dataset_id",
    )


def prepare(root: Path, path: Path):
    report = validate(root, path)
    destination = safe_path(root, f"state/training/datasets/{report['dataset_id']}.json")
    publish(destination, report)
    return {**report, "saved_path": str(destination)}


def load_dataset(root: Path, path: Path):
    value = check_seal(parse_json(read_document(path)), "dataset_id")
    object_fields(
        value,
        {"version", "scope", "source", "dataset", "samples", "counts", "limits", "dataset_id"},
        "dataset snapshot",
    )
    require(
        value == validate_value(root, value["dataset"], value["source"]),
        "Dataset snapshot differs from revalidation",
    )
    return value
