"""Internal records, unchanged wire contracts, and operation-boundary freshness."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from quality_fixtures import curated_inputs as curated_inputs  # noqa: F401
from test_evaluation import approving_fixture_review, complete
from test_training import training_inputs as training_inputs  # noqa: F401

from itov import evaluation, quality, training, training_results
from itov.assessment_context import assessment_context
from itov.catalog import canonical_bytes, sha256
from itov.evaluation_cases import EvaluationCase, conditions
from itov.evidence_reads import EvidenceReads, read_document
from itov.review_records import CaseReview, ReviewDecision, review_coverage


@pytest.fixture
def assessed(curated_inputs):
    return complete(curated_inputs, "training")


def change_bytes_preserving_metadata(path):
    before = path.stat()
    raw = bytearray(path.read_bytes())
    raw[-1] ^= 1
    path.write_bytes(raw)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))


def test_validated_records_own_their_values_and_keep_wire_documents(assessed):
    item = assessed
    original = training_results.validate(item.config, item.plan, item.folder)
    with assessment_context(item.config, item.plan_path) as context:
        assert context.validated.to_dict() == original
        result = context.validated.result.to_dict()
        result["weights"]["sha256"] = "0" * 64
        result["quality_matrix"].clear()
        assert context.validated.to_dict() == original
        with pytest.raises(FrozenInstanceError):
            context.validated.weights.rank = 0
        report = evaluation._assessment(context)
        candidate, exported = evaluation._candidate(context, assessment=report)
        direct, metadata = evaluation.comfy_export(
            item.folder / item.result["weights"]["path"],
            item.spec["parameters"]["rank"],
            item.result["weights"]["sha256"],
        )
        assert exported == direct and candidate["export"] == metadata
        assert context.validated.evaluation.rows() == item.result["quality_matrix"]
    assert report == evaluation.assess(item.config, item.plan_path)
    assert candidate == evaluation.candidate(item.config, item.plan_path)


def test_case_conditions_keep_historical_order_and_own_seed_tuple(assessed):
    suite = assessed.suite
    case = EvaluationCase.from_validated(suite["cases"][0])
    wanted = [
        (c["id"], s, role)
        for c in suite["cases"]
        for s in c["seeds"]
        for role in ("base_plain", "base_trigger", "adapter_plain", "adapter_trigger")
    ]
    actual = conditions(suite)
    assert [(r.case_id, r.seed, r.role) for r in actual] == wanted
    for row in actual:
        source = next(c for c in suite["cases"] if c["id"] == row.case_id)
        assert (
            row.prompt
            == ((suite["trigger"] + " ") if row.role.endswith("trigger") else "") + source["prompt"]
        )
        assert row.negative_prompt == source["negative_prompt"]
    old = case.seeds
    suite["cases"][0]["seeds"].clear()
    assert case.seeds == old


@pytest.mark.parametrize(
    "field",
    [
        "plan",
        "run",
        "result",
        "weights",
        "dataset",
        "source",
        "image",
        "caption",
        "curation",
        "metadata",
        "rights",
        "suite",
        "preview",
        "matrix",
    ],
)
def test_packet_checks_every_input_after_reuse_before_publication(assessed, monkeypatch, field):
    item = assessed
    spec, result = item.plan["specification"], item.result
    dataset = json.loads((item.config.root / spec["dataset"]["path"]).read_bytes())
    curation = json.loads(
        (item.config.root / spec["qualification"]["curation"]["path"]).read_bytes()
    )
    sample = dataset["dataset"]["samples"][0]
    targets = {
        "plan": item.plan_path,
        "run": item.folder / "run.json",
        "result": item.folder / "result.json",
        "weights": item.folder / result["weights"]["path"],
        "dataset": item.config.root / spec["dataset"]["path"],
        **{key: item.config.root / sample[key]["path"] for key in ("source", "image", "caption")},
        "curation": item.config.root / spec["qualification"]["curation"]["path"],
        "metadata": item.config.root / curation["works"][0]["metadata"]["path"],
        "rights": item.config.root / curation["rights"]["policy_snapshot"]["path"],
        "suite": item.config.root / spec["qualification"]["suite"]["path"],
        "preview": item.folder / result["previews"][0]["baseline"]["path"],
        "matrix": item.folder / result["quality_matrix"][0]["image"]["path"],
    }
    original = evaluation._candidate

    def stale(context, **kwargs):
        value = original(context, **kwargs)
        change_bytes_preserving_metadata(targets[field])
        return value

    monkeypatch.setattr(evaluation, "_candidate", stale)
    with pytest.raises(training_results.ResultValidationError, match="Evidence changed") as error:
        quality.packet(item.config, item.plan_path, save=True)
    assert error.value.boundary == "input_freshness"
    assert not (item.config.root / "state/training/reviews").exists()
    assert not (item.config.root / "models_shared/trained").exists()


@pytest.mark.parametrize("operation", ["assessment", "candidate"])
def test_late_weight_change_cannot_publish_an_assessment_or_export(
    assessed, monkeypatch, operation
):
    item = assessed
    name = "_assessment" if operation == "assessment" else "_candidate"
    original = getattr(evaluation, name)

    def stale(context, **kwargs):
        value = original(context, **kwargs)
        change_bytes_preserving_metadata(item.folder / item.result["weights"]["path"])
        return value

    monkeypatch.setattr(evaluation, name, stale)
    with pytest.raises(training_results.ResultValidationError, match="Evidence changed"):
        (evaluation.assess if operation == "assessment" else evaluation.candidate)(
            item.config, item.plan_path, save=True
        )
    for folder in ("assessments", "candidates"):
        assert not (item.config.root / f"state/training/{folder}").exists()
    assert not (item.config.root / "models_shared/trained").exists()


def test_next_command_rereads_disk_after_success(assessed):
    item = assessed
    first = quality.packet(item.config, item.plan_path)
    assert quality.packet(item.config, item.plan_path) == first
    change_bytes_preserving_metadata(item.folder / item.result["weights"]["path"])
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        quality.packet(item.config, item.plan_path)


def test_packet_performs_one_full_validation_and_one_weight_scan(assessed, monkeypatch):
    counts = {"validation": 0, "weights": 0}
    validate, inspect = training_results.validate_record, training_results._inspect_weights

    def counted_validation(*args, **kwargs):
        counts["validation"] += 1
        return validate(*args, **kwargs)

    def counted_weights(*args, **kwargs):
        counts["weights"] += 1
        return inspect(*args, **kwargs)

    monkeypatch.setattr(training_results, "validate_record", counted_validation)
    monkeypatch.setattr(training_results, "_inspect_weights", counted_weights)
    first = quality.packet(assessed.config, assessed.plan_path)
    assert counts == {"validation": 1, "weights": 1}
    assert (
        first["candidate_id"]
        == evaluation.candidate(assessed.config, assessed.plan_path)["candidate_id"]
    )
    assert counts == {"validation": 2, "weights": 2}


def test_nested_read_scopes_and_exception_cleanup(tmp_path):
    path = tmp_path / "input.json"
    path.write_bytes(b"original")
    outer, inner = EvidenceReads(), EvidenceReads()
    with outer.capture():
        with pytest.raises(RuntimeError), inner.capture():
            read_document(path)
            raise RuntimeError("interrupt fixture")
        assert len(outer.observations) == len(inner.observations) == 1
    other = tmp_path / "unrelated.json"
    other.write_bytes(b"unrelated")
    read_document(other)
    assert len(outer.observations) == len(inner.observations) == 1
    change_bytes_preserving_metadata(path)
    with pytest.raises(ValueError, match="Evidence changed"):
        outer.verify()


def test_read_scopes_do_not_leak_between_threads(tmp_path):
    paths = [tmp_path / f"{index}.json" for index in range(2)]
    for index, path in enumerate(paths):
        path.write_bytes(str(index).encode())

    def capture(path):
        reads = EvidenceReads()
        with reads.capture():
            read_document(path)
        return reads

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(capture, paths))
    change_bytes_preserving_metadata(paths[0])
    with pytest.raises(ValueError):
        first.verify()
    second.verify()


@pytest.mark.parametrize("version", [1, 2, 3])
def test_review_record_keeps_version_policy_and_does_not_alias(assessed, version):
    item = assessed
    path = approving_fixture_review(item)
    value = json.loads(path.read_bytes())
    if version == 1:
        for key in ("packet", "reviewer_kind", "cases", "independent_of_training"):
            value.pop(key)
    elif version == 3:
        value.pop("independent_of_training")
        value.update(
            reviewer_kind="assistant",
            method="Synthetic regression exercise",
            limitations="No model or quality acceptance",
        )
    value["version"] = version
    record = ReviewDecision.parse(value, value["assessment_id"], value["candidate_id"])
    assert canonical_bytes(record.document.to_dict()) == canonical_bytes(value)
    assert record.approved
    value["decision"] = "reject"
    value["checks"][0]["passed"] = False
    assert record.approved and record.document.to_dict()["decision"] == "approve"
    if version > 1:
        doc = record.document.to_dict()
        current = quality.packet(item.config, item.plan_path)
        assert review_coverage(doc, current)
        doc["cases"][0]["verdicts"]["regression"] = False
        assert not review_coverage(doc, current)
        case = CaseReview.parse(doc["cases"][0])
        doc["cases"][0]["verdicts"]["regression"] = True
        assert dict(case.verdicts)["regression"] is False
        doc["reviewer_kind"] = "assistant"
        if version == 2:
            with pytest.raises(ValueError, match="Legacy v2"):
                review_coverage(doc, current)


def test_new_worker_manifest_pins_record_validation_dependencies():
    sources = training.worker_sources()
    for name in (
        "records.py",
        "training_records.py",
        "evaluation_cases.py",
        "review_records.py",
        "evidence_reads.py",
    ):
        assert sources[name] == sha256(Path(training.__file__).with_name(name).read_bytes())
