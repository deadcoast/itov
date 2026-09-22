"""Synthetic curation declarations for policy tests, never real review evidence."""

from pathlib import Path

import pytest
from test_training import document, write

from itov import curation, training_data
from itov.catalog import canonical_bytes, sha256


@pytest.fixture
def curated_inputs(training_inputs):
    item = training_inputs
    root = item.config.root
    item.dataset["purpose"] = "training"
    works = []
    for index, sample in enumerate(item.dataset["samples"], 1):
        sample["group"] = f"met-{index}"
        url = f"https://images.metmuseum.org/CRDImages/fixture/{index}.jpg"
        metadata = {
            "objectID": index,
            "isPublicDomain": True,
            "primaryImage": url,
            "artistDisplayName": f"Synthetic artist {index}",
        }
        works.append(
            {
                "sample": sample["id"],
                "object_id": index,
                "image_url": url,
                "metadata": write(root, f"metadata/{index}.json", canonical_bytes(metadata)),
                "caption_note": "Synthetic fixture",
                "selection_note": "Synthetic fixture",
            }
        )
    document(item.dataset_path, item.dataset)
    prepared = training_data.prepare(root, item.dataset_path)
    dataset_path = Path(prepared["saved_path"])
    item.spec["dataset"] = {
        "path": dataset_path.relative_to(root).as_posix(),
        "sha256": sha256(dataset_path.read_bytes()),
    }
    item.curation = {
        "version": 1,
        "dataset": item.spec["dataset"],
        "curator": "fixture curator",
        "selection_policy": "Synthetic policy test",
        "transform": curation.TRANSFORM,
        "rights": {
            "provider": "met-open-access",
            "policy_url": curation.POLICY,
            "policy_snapshot": write(root, "policy.txt", b"Synthetic fixture"),
        },
        "works": works,
    }
    item.curation_path = document(root / "curation.json", item.curation)
    item.suite = {
        "version": 1,
        "id": "fixture-suite",
        "trigger": "testtrigger",
        "cases": [
            {
                "id": kind,
                "kind": kind,
                "prompt": f"A new {kind} composition",
                "negative_prompt": "",
                "expectation": "Synthetic rubric",
                "seeds": [17, 29],
            }
            for kind in ("holdout", "regression")
        ],
    }
    item.suite_path = document(root / "suite.json", item.suite)
    item.spec.update(
        version=2,
        qualification={
            "curation": {
                "path": "curation.json",
                "sha256": sha256(item.curation_path.read_bytes()),
            },
            "suite": {"path": "suite.json", "sha256": sha256(item.suite_path.read_bytes())},
        },
    )
    return item
