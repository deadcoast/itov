"""Curated lineage and independent-review refusal tests; no model acceptance."""

import json

import pytest
from quality_fixtures import curated_inputs as curated_inputs
from test_evaluation import approving_fixture_review, complete, save_result
from test_training import document, save_plan
from test_training import training_inputs as training_inputs

from itov import curation, evaluation, quality, training
from itov.catalog import sha256
from itov.catalog_store import CatalogStore
from itov.cli import main


def test_curated_plan_binds_provenance_and_preregistered_suite(curated_inputs):
    item = curated_inputs
    plan, _ = save_plan(item)
    training.revalidate(item.config, plan)
    item.suite["cases"][0]["seeds"][0] += 1
    document(item.suite_path, item.suite)
    with pytest.raises(ValueError, match="SHA-256"):
        training.revalidate(item.config, plan)


@pytest.mark.parametrize(
    "case", ["missing", "duplicate", "group", "rights", "url", "artist", "hash"]
)
def test_curation_rejects_incomplete_or_leaking_provenance(curated_inputs, case):
    item = curated_inputs
    value = item.curation
    if case == "missing":
        value["works"].pop()
    if case == "duplicate":
        value["works"][1] = value["works"][0]
    if case == "url":
        value["works"][0]["image_url"] = "https://example.com/image.jpg"
    if case == "group":
        value["works"][0]["object_id"] = 999
    if case in ("rights", "artist", "hash"):
        ref = value["works"][-1]["metadata"]
        path = item.config.root / ref["path"]
        metadata = json.loads(path.read_bytes())
        if case == "rights":
            metadata["isPublicDomain"] = False
        else:
            metadata["artistDisplayName"] = "Synthetic artist 1"
        document(path, metadata)
        if case != "hash":
            ref["sha256"] = sha256(path.read_bytes())
    document(item.curation_path, value)
    with pytest.raises(ValueError):
        curation.validate(item.config.root, item.curation_path)


@pytest.mark.parametrize("case", ["caption", "trigger", "seed", "kind", "duplicate", "extra"])
def test_suite_refuses_training_reuse_and_ambiguous_cases(curated_inputs, case):
    item = curated_inputs
    row = item.suite["cases"][0]
    if case == "caption":
        row["prompt"] = "geometry"
    if case == "trigger":
        row["prompt"] = "testtrigger a vase"
    if case == "seed":
        row["seeds"] = [True, 17]
    if case == "kind":
        row["kind"] = "regression"
    if case == "duplicate":
        item.suite["cases"].append(row)
    if case == "extra":
        row["posthoc"] = True
    document(item.suite_path, item.suite)
    item.spec["qualification"]["suite"]["sha256"] = sha256(item.suite_path.read_bytes())
    with pytest.raises(ValueError):
        save_plan(item)


@pytest.mark.parametrize(
    "case", ["missing", "seed", "prompt", "role", "image", "reused", "png_weights"]
)
def test_assessment_refuses_incomplete_or_changed_quality_matrix(curated_inputs, case):
    item = complete(curated_inputs, "training")
    rows = item.result["quality_matrix"]
    if case == "missing":
        rows.pop()
    elif case == "png_weights":
        item.result["weights"] = rows[-1]["image"]
    elif case == "image":
        (item.folder / rows[0]["image"]["path"]).write_bytes(b"changed")
    elif case == "reused":
        rows[1]["image"] = rows[0]["image"]
    else:
        rows[0][case] = 999 if case == "seed" else "changed"
    save_result(item)
    with pytest.raises(ValueError):
        evaluation.assess(item.config, item.plan_path)


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "duplicate",
        "seed",
        "failed",
        "nonhuman",
        "not_independent",
        "curator",
        "pending",
        "stale",
    ],
)
def test_independent_review_requires_all_cases_and_real_attestation(curated_inputs, case):
    item = complete(curated_inputs, "training")
    path = approving_fixture_review(item)
    value = json.loads(path.read_bytes())
    if case == "missing":
        value["cases"].pop()
    if case == "duplicate":
        value["cases"][-1] = value["cases"][0]
    if case == "seed":
        value["cases"][0]["seed"] = 12345
    if case == "failed":
        value["cases"][0]["verdicts"]["image_quality"] = False
    if case == "nonhuman":
        value["reviewer_kind"] = "assistant"
    if case == "not_independent":
        value["independent_of_training"] = False
    if case == "curator":
        value["reviewer"] = item.curation["curator"]
    if case == "pending":
        value["cases"][0]["verdicts"]["activation"] = None
    if case == "stale":
        value["packet"]["sha256"] = "0" * 64
    document(path, value)
    before = CatalogStore(item.config.root).snapshot()
    if case == "failed":
        assert not evaluation.promotion(item.config, item.plan_path, path)["ok"]
    else:
        with pytest.raises(ValueError):
            evaluation.promotion(item.config, item.plan_path, path)
    assert CatalogStore(item.config.root).snapshot() == before


def test_legacy_non_smoke_approval_cannot_bypass_curated_gate(training_inputs):
    item = complete(training_inputs, "training")
    path = approving_fixture_review(item)
    result = evaluation.promotion(item.config, item.plan_path, path)
    assert not result["ok"] and "every case and seed" in result["blockers"][0]


def test_generated_pending_template_never_approves_and_preserves_user_edits(curated_inputs):
    item = complete(curated_inputs, "training")
    packet = quality.packet(item.config, item.plan_path, save=True)
    template = item.config.root / f"state/training/reviews/{packet['packet_id']}.review.json"
    with pytest.raises(ValueError):
        evaluation.promotion(item.config, item.plan_path, template)
    value = json.loads(template.read_bytes())
    value["notes"] = "User observations in progress"
    document(template, value)
    saved = template.read_bytes()
    quality.packet(item.config, item.plan_path, save=True)
    assert template.read_bytes() == saved


def test_result_seed_boolean_cannot_equal_prescribed_integer(curated_inputs):
    item = curated_inputs
    item.suite["cases"][0]["seeds"][0] = 1
    document(item.suite_path, item.suite)
    item.spec["qualification"]["suite"]["sha256"] = sha256(item.suite_path.read_bytes())
    item = complete(item, "training")
    item.result["quality_matrix"][0]["seed"] = True
    save_result(item)
    with pytest.raises(ValueError, match="quality result seed"):
        evaluation.assess(item.config, item.plan_path)


@pytest.mark.parametrize("as_json", [True, False])
def test_curation_and_packet_cli_offline_idempotent(curated_inputs, capsys, monkeypatch, as_json):
    import socket

    monkeypatch.setattr(socket.socket, "connect", lambda *_: pytest.fail("Unexpected network"))
    item = complete(curated_inputs, "training")
    for command in (
        ["dataset", "curate", str(item.curation_path)],
        ["evaluation", "packet", str(item.plan_path)],
    ):
        args = [*command, "--config", str(item.config.file), "--save"]
        if as_json:
            args.append("--json")
        for _ in range(2):
            assert main(args) == 0
            output = capsys.readouterr().out
            assert (
                ("curation_id" in output or "packet_id" in output) if as_json else "id:" in output
            )
    packet = quality.packet(item.config, item.plan_path)
    assert len(packet["images"]) == 16 and packet["scope"] == "quality_review_pending"


def assistant_fixture_review(item):
    path = approving_fixture_review(item)
    value = json.loads(path.read_bytes())
    value.pop("independent_of_training")
    value.update(
        version=3,
        reviewer_kind="assistant",
        reviewer=item.curation["curator"],
        method="Synthetic policy fixture with complete evidence references",
        limitations="No actual image assessment; this is a policy test only",
    )
    document(path, value)
    return path, value


def test_assistant_review_can_qualify_without_human_or_independence_claim(curated_inputs):
    item = complete(curated_inputs, "training")
    path, _ = assistant_fixture_review(item)
    store = CatalogStore(item.config.root)
    before = store.snapshot()
    result = evaluation.promotion(item.config, item.plan_path, path)
    assert result["ok"] and result["decision"]["review"]["coverage_passed"]
    assert store.snapshot() == before  # Preview never activates even an approving fixture.


@pytest.mark.parametrize(
    "case", ["reject", "failed", "method", "limitations", "missing", "stale", "kind"]
)
def test_assistant_review_keeps_evidence_and_failed_case_requirements(curated_inputs, case):
    item = complete(curated_inputs, "training")
    path, value = assistant_fixture_review(item)
    if case == "reject":
        value["decision"] = "reject"
    if case == "failed":
        value["cases"][0]["verdicts"]["activation"] = False
    if case in ("method", "limitations"):
        value[case] = ""
    if case == "missing":
        value["cases"].pop()
    if case == "stale":
        value["packet"]["sha256"] = "0" * 64
    if case == "kind":
        value["reviewer_kind"] = "unknown"
    document(path, value)
    before = CatalogStore(item.config.root).snapshot()
    if case in ("reject", "failed"):
        assert not evaluation.promotion(item.config, item.plan_path, path)["ok"]
    else:
        with pytest.raises(ValueError):
            evaluation.promotion(item.config, item.plan_path, path)
    assert CatalogStore(item.config.root).snapshot() == before
