"""Committed dataset bundles and version-two snapshots, without optional decoders."""

from __future__ import annotations

from pathlib import Path

from itov import dataset_manifest as manifest
from itov.catalog import canonical_bytes, digest, object_fields, require, sha256
from itov.comfyui import parse_json
from itov.evidence_reads import read_document
from itov.qualification import safe_path
from itov.training_data import check_seal, file_ref, seal, validate_value

LIMITS = (
    "Committed source/caption/provenance bytes and fully decoded transform evidence. "
    "Provider and rights declarations are attributed, not authenticated. "
    "No perceptual deduplication, semantic suitability or model quality acceptance."
)


def prefix(import_id):
    digest(import_id, "import id")
    return f"training/imports/{import_id}"


def operation(value):
    check_seal(value, "import_id")
    object_fields(
        value,
        {"version", "definition", "declaration", "engine", "import_id"},
        "dataset import operation",
    )
    require(type(value["version"]) is int and value["version"] == 1, "Invalid operation version")
    manifest.validate(value["definition"])
    object_fields(value["declaration"], {"sha256", "bytes", "utf8"}, "import declaration")
    digest(value["declaration"]["sha256"], "declaration hash")
    require(
        type(value["declaration"]["bytes"]) is int
        and 0 < value["declaration"]["bytes"] <= 4 * 1024**2,
        "Invalid declaration size",
    )
    require(isinstance(value["declaration"]["utf8"], str), "Declaration must retain exact UTF-8")
    raw = value["declaration"]["utf8"].encode("utf-8")
    require(
        len(raw) == value["declaration"]["bytes"]
        and sha256(raw) == value["declaration"]["sha256"]
        and parse_json(raw) == value["definition"],
        "Retained declaration differs",
    )
    require(
        isinstance(value["engine"], dict)
        and value["engine"].get("profile") == value["definition"]["transform"],
        "Import engine profile differs",
    )
    return value


def filenames(folder):
    """Check redirects before descending; never walk unknown linked trees."""
    result = []

    def visit(directory):
        for path in directory.iterdir():
            name = path.relative_to(folder).as_posix()
            safe_path(folder, name)
            require(len(result) < 2048, "Dataset bundle has too many files")
            if path.is_dir():
                require(
                    directory == folder and name in {"sources", "images", "captions", "provenance"},
                    "Unexpected dataset directory",
                )
                visit(path)
            else:
                require(path.is_file(), "Unsupported dataset bundle entry")
                result.append(name)

    visit(folder)
    return sorted(result)


def inventory(folder):
    rows, total = [], 0
    for name in filenames(folder):
        if name == "READY.json":
            continue
        path = safe_path(folder, name)
        size = path.stat().st_size
        require(0 < size <= 32 * 1024**2, "Dataset bundle file size is unsupported")
        with path.open("rb") as handle:
            raw = handle.read(32 * 1024**2 + 1)
        require(len(raw) == size, "Dataset bundle changed during inventory")
        total += size
        require(total <= 1024**3, "Dataset bundle exceeds 1 GiB")
        rows.append({"path": name, "sha256": sha256(raw), "bytes": size})
    return rows


def definition(value, receipt, base):
    source = value["definition"]
    rows = receipt["images"]
    samples = []
    for sample, row in zip(sorted(source["samples"], key=lambda s: s["id"]), rows, strict=True):
        key = sample["id"]
        object_fields(
            row,
            {
                "sample",
                "engine",
                "source_sha256",
                "format",
                "source_mode",
                "source_size",
                "exif_orientation",
                "oriented_size",
                "oriented_rgb_sha256",
                "fitted_size",
                "offset",
                "background",
                "output_size",
                "output_sha256",
                "output_bytes",
                "decoded_rgb_sha256",
                "full_decode",
            },
            "transform row",
        )
        require(
            row["sample"] == key
            and row["source_sha256"] == sample["source"]["sha256"]
            and row["engine"] == value["engine"]
            and row["full_decode"] is True
            and row["output_size"] == [512, 512],
            "Transform receipt differs from inputs",
        )
        digest(row["decoded_rgb_sha256"], "decoded image hash")
        digest(row["oriented_rgb_sha256"], "oriented image hash")
        require(
            row["format"] in ("JPEG", "PNG") and row["source_mode"] in ("RGB", "L"),
            "Unsupported transform source",
        )
        require(
            type(row["exif_orientation"]) is int and 1 <= row["exif_orientation"] <= 8,
            "Invalid transform orientation",
        )
        for name in ("source_size", "oriented_size", "fitted_size"):
            require(
                isinstance(row[name], list)
                and len(row[name]) == 2
                and all(type(n) is int and n > 0 for n in row[name]),
                "Invalid transform dimensions",
            )
        require(
            row["source_size"][0] * row["source_size"][1] <= 32_000_000
            and max(row["fitted_size"]) == 512
            and row["oriented_size"]
            == (row["source_size"][::-1] if row["exif_orientation"] >= 5 else row["source_size"])
            and row["offset"] == [(512 - n) // 2 for n in row["fitted_size"]]
            and row["background"] == [245, 240, 225],
            "Transform geometry differs",
        )
        paths = {
            "source": f"sources/{key}.image",
            "caption": f"captions/{key}.txt",
            "image": f"images/{key}.png",
        }
        hashes = {
            "source": sample["source"]["sha256"],
            "caption": sample["caption"]["sha256"],
            "image": row["output_sha256"],
        }
        samples.append(
            {
                **{k: sample[k] for k in ("id", "split", "group")},
                **{
                    k: {"path": f"{base}/{p}" if base else p, "sha256": hashes[k]}
                    for k, p in paths.items()
                },
            }
        )
    return {
        "version": 1,
        **{k: source[k] for k in ("id", "purpose", "origin", "rights")},
        "preprocessing": "prepared-square-rgb-png-v1",
        "samples": samples,
    }


def snapshot(folder, value, receipt):
    base = prefix(value["import_id"])
    target = definition(value, receipt, base)
    raw = canonical_bytes(target) + b"\n"
    checked = validate_value(
        folder, definition(value, receipt, ""), {"sha256": sha256(raw), "bytes": len(raw)}
    )
    for row in receipt["images"]:
        require(
            type(row["output_bytes"]) is int
            and row["output_bytes"] == (folder / f"images/{row['sample']}.png").stat().st_size,
            "Derived image size differs from transform receipt",
        )
    body = {k: v for k, v in checked.items() if k != "dataset_id"}
    body.update(
        version=2,
        scope="committed_dataset_preparation",
        dataset=target,
        import_id=value["import_id"],
        limits=LIMITS,
        preparation={
            "path": base + "/preparation.json",
            "sha256": sha256(canonical_bytes(receipt) + b"\n"),
        },
    )
    return seal(body, "dataset_id")


def curation(value, prepared):
    """The existing curated-training contract, bound to the new committed snapshot."""
    source, base = value["definition"], prefix(value["import_id"])
    details = source["curation"]
    return {
        "version": 1,
        "dataset": {
            "path": base + "/prepared.json",
            "sha256": sha256(canonical_bytes(prepared) + b"\n"),
        },
        "curator": details["curator"],
        "selection_policy": details["selection_policy"],
        "rights": {
            "provider": source["provider"],
            "policy_url": details["policy_url"],
            "policy_snapshot": {
                "path": base + "/provenance/policy.json",
                "sha256": details["policy_snapshot"]["sha256"],
            },
        },
        "transform": source["transform"],
        "works": [
            {
                "sample": s["id"],
                **{
                    k: s["provenance"][k]
                    for k in ("object_id", "image_url", "caption_note", "selection_note")
                },
                "metadata": {
                    "path": base + f"/provenance/{s['id']}.json",
                    "sha256": s["provenance"]["metadata"]["sha256"],
                },
            }
            for s in sorted(source["samples"], key=lambda s: s["id"])
        ],
    }


def verify_bundle(folder, expected_id):
    ready = check_seal(parse_json(read_document(safe_path(folder, "READY.json"))), "commit_id")
    object_fields(ready, {"version", "import_id", "files", "commit_id"}, "dataset commit")
    require(
        type(ready["version"]) is int
        and ready["version"] == 1
        and ready["import_id"] == expected_id,
        "Dataset commit belongs to another import",
    )
    require(
        isinstance(ready["files"], list) and 1 <= len(ready["files"]) <= 2048,
        "Invalid commit inventory",
    )
    total, names = 0, []
    for ref in ready["files"]:
        object_fields(ref, {"path", "sha256", "bytes"}, "commit file")
        require(type(ref["bytes"]) is int, "Invalid committed size")
        _, size = file_ref(folder, {k: ref[k] for k in ("path", "sha256")}, maximum=32 * 1024**2)
        require(size == ref["bytes"], "Committed file size differs")
        names.append(ref["path"])
        total += size
    require(total <= 1024**3 and names == sorted(set(names)), "Invalid dataset inventory")
    require(filenames(folder) == sorted([*names, "READY.json"]), "Dataset has extra/missing files")
    value = operation(parse_json(read_document(safe_path(folder, "operation.json"))))
    require(value["import_id"] == expected_id, "Bundle operation differs")
    raw = read_document(safe_path(folder, "declaration.json"))
    require(
        raw == value["declaration"]["utf8"].encode("utf-8")
        and parse_json(raw) == value["definition"],
        "Import declaration differs",
    )
    expected_names = {name for name, _, _ in manifest.inputs(value["definition"])}
    expected_names |= {f"images/{s['id']}.png" for s in value["definition"]["samples"]}
    expected_names |= {
        "operation.json",
        "declaration.json",
        "preparation.json",
        "dataset.json",
        "prepared.json",
    }
    if value["definition"]["curation"]:
        expected_names.add("curation.json")
    require(set(names) == expected_names, "Dataset inventory includes undeclared files")
    for name, ref, maximum in manifest.inputs(value["definition"]):
        file_ref(folder, {"path": name, "sha256": ref["sha256"]}, maximum=maximum)
    manifest.verify_provenance(folder, value["definition"])
    receipt = check_seal(
        parse_json(read_document(safe_path(folder, "preparation.json"))), "preparation_id"
    )
    object_fields(receipt, {"version", "import_id", "images", "preparation_id"}, "preparation")
    require(
        type(receipt["version"]) is int
        and receipt["version"] == 1
        and receipt["import_id"] == expected_id,
        "Preparation receipt differs",
    )
    require(
        isinstance(receipt["images"], list)
        and len(receipt["images"]) == len(value["definition"]["samples"]),
        "Incomplete decoded image coverage",
    )
    prepared = snapshot(folder, value, receipt)
    for name, expected in (("dataset.json", prepared["dataset"]), ("prepared.json", prepared)):
        require(
            read_document(safe_path(folder, name)) == canonical_bytes(expected) + b"\n",
            f"Committed {name} differs from reconstruction",
        )
    if value["definition"]["curation"]:
        require(
            read_document(safe_path(folder, "curation.json"))
            == canonical_bytes(curation(value, prepared)) + b"\n",
            "Curation binding differs",
        )
    return prepared


def load(root: Path, path: Path, value):
    base = prefix(value.get("import_id"))
    folder = safe_path(root, base)
    require(
        path.absolute() == folder / "prepared.json",
        "Imported dataset must be loaded from its committed prepared.json",
    )
    require(value == verify_bundle(folder, value["import_id"]), "Dataset snapshot differs")
    return value
