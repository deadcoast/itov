"""Declared local inputs and retained Met snapshots; never a network downloader."""

from __future__ import annotations

from itov.catalog import (
    array,
    digest,
    identifier,
    integer,
    object_fields,
    relative_path,
    require,
    text,
)
from itov.comfyui import parse_json
from itov.curation import POLICY, TRANSFORM
from itov.evidence_reads import read_document
from itov.linting import origin
from itov.training_data import file_ref


def reference(value):
    object_fields(value, {"path", "sha256"}, "import file reference")
    relative_path(value["path"], "source file")
    digest(value["sha256"], "source hash")


def validate(value):
    object_fields(
        value,
        {
            "version",
            "id",
            "provider",
            "purpose",
            "origin",
            "rights",
            "transform",
            "curation",
            "samples",
        },
        "dataset import",
    )
    require(type(value["version"]) is int and value["version"] == 1, "Unsupported import version")
    identifier(value["id"], "dataset id")
    require(value["provider"] in ("local", "met-open-access"), "Unsupported import provider")
    require(value["purpose"] in ("smoke", "training"), "Invalid dataset purpose")
    origin(value["origin"])
    object_fields(value["rights"], {"basis", "reference", "training_permitted"}, "dataset rights")
    text(value["rights"]["basis"], "rights basis")
    text(value["rights"]["reference"], "rights reference")
    require(value["rights"]["training_permitted"] is True, "Explicit training permission required")
    require(value["transform"] == TRANSFORM, "Unsupported dataset import transform")
    met = value["provider"] == "met-open-access"
    if met:
        require(value["purpose"] == "training", "Met import must declare training purpose")
        object_fields(
            value["curation"],
            {"curator", "selection_policy", "policy_url", "policy_snapshot"},
            "import curation",
        )
        text(value["curation"]["curator"], "curator")
        text(value["curation"]["selection_policy"], "selection policy")
        require(value["curation"]["policy_url"] == POLICY, "Unsupported Met policy URL")
        reference(value["curation"]["policy_snapshot"])
    else:
        require(value["curation"] is None, "Local import has no Met curation declaration")
    samples = array(value["samples"], "import samples")
    require(2 <= len(samples) <= 256, "Import requires 2 to 256 samples")
    ids, splits, groups, sources, objects, urls = set(), set(), {}, {}, set(), set()
    for sample in samples:
        object_fields(
            sample, {"id", "split", "group", "source", "caption", "provenance"}, "import sample"
        )
        key = identifier(sample["id"], "sample id")
        # IDs become portable filenames as well as dataset keys.
        relative_path(key, "sample filename")
        require(key not in ids, "Duplicate import sample id")
        ids.add(key)
        group = identifier(sample["group"], "sample group")
        split = sample["split"]
        require(split in ("train", "validation"), "Invalid import split")
        splits.add(split)
        for name in ("source", "caption"):
            reference(sample[name])
        for label, mapping, field in (
            ("group", groups, group),
            ("source", sources, sample["source"]["sha256"]),
        ):
            require(mapping.get(field, split) == split, f"Train/validation {label} leakage")
            mapping[field] = split
        provenance = sample["provenance"]
        fields = {"selection_note", "caption_note"}
        fields |= {"object_id", "metadata", "image_url"} if met else {"reference"}
        object_fields(provenance, fields, "sample provenance")
        for name in ("selection_note", "caption_note"):
            text(provenance[name], name)
        if met:
            oid = integer(provenance["object_id"], "Met object id", minimum=1)
            require(group == f"met-{oid}", "Met group must identify its artwork")
            require(oid not in objects, "Repeated Met artwork")
            objects.add(oid)
            reference(provenance["metadata"])
            url = text(provenance["image_url"], "Met image URL")
            require(
                url.startswith("https://images.metmuseum.org/CRDImages/") and url not in urls,
                "Unsupported or repeated Met image URL",
            )
            urls.add(url)
        else:
            text(provenance["reference"], "source provenance reference")
    require(splits == {"train", "validation"}, "Both training and validation splits required")
    return value


def inputs(value):
    """Stable bundle names independent of the original paths or selected object IDs."""
    result = []
    if value["curation"]:
        result.append(("provenance/policy.json", value["curation"]["policy_snapshot"], 4 * 1024**2))
    for sample in sorted(value["samples"], key=lambda s: s["id"]):
        key = sample["id"]
        result.extend(
            [
                (f"sources/{key}.image", sample["source"], 32 * 1024**2),
                (f"captions/{key}.txt", sample["caption"], 65536),
            ]
        )
        if value["provider"] == "met-open-access":
            result.append((f"provenance/{key}.json", sample["provenance"]["metadata"], 4 * 1024**2))
    return result


def verify_provenance(folder, value):
    """Verify copied provider declarations; do not claim provider authentication."""
    artists = {}
    for sample in value["samples"]:
        path, _ = file_ref(
            folder,
            {"path": f"captions/{sample['id']}.txt", "sha256": sample["caption"]["sha256"]},
            maximum=65536,
        )
        caption = path.read_bytes().decode("utf-8")
        text(caption.strip(), "caption")
        require(len(caption) <= 4096, "Caption exceeds 4096 characters")
        if value["provider"] == "met-open-access":
            p = sample["provenance"]
            path, _ = file_ref(
                folder,
                {"path": f"provenance/{sample['id']}.json", "sha256": p["metadata"]["sha256"]},
                maximum=4 * 1024**2,
            )
            metadata = parse_json(read_document(path))
            require(
                isinstance(metadata, dict)
                and type(metadata.get("objectID")) is int
                and metadata["objectID"] == p["object_id"]
                and metadata.get("isPublicDomain") is True,
                "Met metadata lacks matching public-domain artwork declaration",
            )
            require(
                p["image_url"] in (metadata.get("primaryImage"), metadata.get("primaryImageSmall")),
                "Met image URL differs from retained metadata",
            )
            artist = text(metadata.get("artistDisplayName"), "Met artist").strip().casefold()
            require(
                artists.get(artist, sample["split"]) == sample["split"],
                "Met artist crosses train/validation splits",
            )
            artists[artist] = sample["split"]
