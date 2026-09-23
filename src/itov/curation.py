"""Offline per-work provenance checks for a bounded Met Open Access dataset."""

from __future__ import annotations

from itov.catalog import array, integer, object_fields, require, text
from itov.comfyui import parse_json
from itov.evidence_reads import read_document
from itov.qualification import safe_path
from itov.training_data import file_ref, load_dataset, publish, seal

POLICY = "https://www.metmuseum.org/hubs/open-access"
TRANSFORM = "rgb-fit-pad-512-lanczos-ivory-v1"


def validate(root, path, *, save=False):
    value = parse_json(read_document(path))
    object_fields(
        value,
        {"version", "dataset", "curator", "selection_policy", "rights", "transform", "works"},
        "curation",
    )
    require(type(value["version"]) is int and value["version"] == 1, "Unsupported curation version")
    text(value["curator"], "curator")
    text(value["selection_policy"], "selection policy")
    require(value["transform"] == TRANSFORM, "Unsupported curation transform")
    dataset_path, _ = file_ref(root, value["dataset"], maximum=32 * 1024**2)
    dataset = load_dataset(root, dataset_path)
    require(
        dataset["dataset"]["purpose"] == "training", "Curated data must declare training purpose"
    )
    rights = value["rights"]
    object_fields(rights, {"provider", "policy_url", "policy_snapshot"}, "curation rights")
    require(
        rights["provider"] == "met-open-access" and rights["policy_url"] == POLICY,
        "Unsupported provenance provider or policy",
    )
    file_ref(root, rights["policy_snapshot"], maximum=4 * 1024**2)
    works = array(value["works"], "curated works")
    samples = {sample["id"]: sample for sample in dataset["dataset"]["samples"]}
    require(len(works) == len(samples), "Curation must cover every sample exactly once")
    seen, objects, urls, artists = set(), set(), set(), {}
    for work in works:
        object_fields(
            work,
            {"sample", "object_id", "metadata", "image_url", "caption_note", "selection_note"},
            "curated work",
        )
        key = text(work["sample"], "curated sample")
        require(key in samples and key not in seen, "Unknown or repeated curated sample")
        seen.add(key)
        oid = integer(work["object_id"], "Met object id", minimum=1)
        require(oid not in objects, "Repeated artwork in curated dataset")
        objects.add(oid)
        metadata_path, _ = file_ref(root, work["metadata"], maximum=4 * 1024**2)
        metadata = parse_json(read_document(metadata_path))
        require(
            isinstance(metadata, dict)
            and type(metadata.get("objectID")) is int
            and metadata["objectID"] == oid
            and metadata.get("isPublicDomain") is True,
            "Metadata lacks matching public-domain artwork declaration",
        )
        url = text(work["image_url"], "source image URL")
        require(
            url.startswith("https://images.metmuseum.org/CRDImages/")
            and url in (metadata.get("primaryImage"), metadata.get("primaryImageSmall"))
            and url not in urls,
            "Source image URL differs or is reused",
        )
        urls.add(url)
        sample = samples[key]
        require(sample["group"] == f"met-{oid}", "Dataset group must identify its artwork")
        artist = text(metadata.get("artistDisplayName"), "artist").strip().casefold()
        require(
            artists.get(artist, sample["split"]) == sample["split"],
            "Artist crosses curated training and validation splits",
        )
        artists[artist] = sample["split"]
        text(work["caption_note"], "caption note")
        text(work["selection_note"], "selection note")
    report = seal(
        {
            "version": 1,
            "scope": "curated_metadata_and_byte_consistency",
            "document": value,
            "dataset_id": dataset["dataset_id"],
            "counts": dataset["counts"],
            "artists": len(artists),
            "limits": "Supplied provider metadata and declared transform only; not source "
            "authentication, perceptual deduplication, legal advice, or proof of absence "
            "from foundation-model pretraining. Full decode and visual curation are separate.",
        },
        "curation_id",
    )
    if save:
        destination = safe_path(root, f"state/training/curation/{report['curation_id']}.json")
        publish(destination, report)
    return report
