"""Calibration protocol tests; synthetic images/labels do not prove model quality."""

import copy
import json
import os

import pytest
from quality_fixtures import curated_inputs as curated_inputs
from test_evaluation_runtime import execute, planned
from test_evaluation_runtime import runtime_case as runtime_case
from test_training import document, png
from test_training import training_inputs as training_inputs

from itov import evaluation_runtime, image_checks, image_media, image_metrics
from itov.catalog import sha256
from itov.cli import main
from itov.config import initialize
from itov.evidence_reads import EvidenceReads
from itov.training_data import seal


def labels(packet):
    _, reference, response = image_checks.templates(packet)
    reference.update(
        reviewer="fixture",
        method="Constructed protocol labels",
        limitations="No natural-image quality evidence",
    )
    response["evaluator"].update(
        kind="fixture",
        name="fixture",
        adapter_version="fixture-1",
        method="Constructed response",
        limitations="Not a real evaluator",
    )
    for record in (reference, response):
        for row in record["observations"]:
            for judgment in row["judgments"].values():
                judgment.update(verdict="pass", notes="Constructed passing reference")
                if "uncertainty" in judgment:
                    judgment["uncertainty"] = "Protocol fixture, no semantic confidence"
    return reference, response


@pytest.fixture
def checked(tmp_path, monkeypatch):
    config = initialize(tmp_path / "workspace", tmp_path / "runtime")
    source = document(config.root / "evaluation.json", {"test": "protocol-only"})
    rows = []
    for index in range(2):
        path = config.root / f"output/{index}.png"
        path.write_bytes(png(index))
        rows.append(
            {
                "index": index,
                "case_id": "fixture",
                "seed": index,
                "role": "base_plain",
                "prompt": "one object",
                "negative_prompt": "frame",
                "image": {
                    "path": path.relative_to(config.root).as_posix(),
                    "sha256": sha256(path.read_bytes()),
                },
                "decoded": image_media.verify_image(path, {"width": 512, "height": 512}),
            }
        )
    report = {"matrix": rows, "suite": {"cases": [{"id": "fixture", "expectation": "one object"}]}}
    monkeypatch.setattr(evaluation_runtime, "replay", lambda *a, **kw: copy.deepcopy(report))
    packet = image_checks.packet(config, source, save=True)
    path = config.root / f"state/evaluation/checks/packets/{packet['packet_id']}.json"
    reference, response = labels(packet)
    reference_path = document(config.root / "reference.json", reference)
    response_path = document(config.root / "response.json", response)
    return config, source, packet, path, reference_path, response_path


def test_known_rgb_controls_retain_misses_without_quality_acceptance():
    controls = image_metrics.controls()
    assert len(controls) == 5
    by_id = {row["id"]: row for row in controls}
    assert by_id["solid-gray"]["measurement"]["judgments"] == {
        "constant_frame": "fail",
        "edge_bands": "unavailable",
    }
    assert by_id["gradient"]["measurement"]["judgments"]["edge_bands"] == "pass"
    assert by_id["bars-16"]["measurement"]["judgments"]["edge_bands"] == "fail"
    result = image_checks.confusion(
        (row["reference"]["edge_bands"], row["measurement"]["judgments"]["edge_bands"])
        for row in controls
    )
    assert result["false_accepts"] == 2
    assert result["false_accept_fraction"] == {"numerator": 2, "denominator": 3}
    assert all(row["measurement"]["quality_acceptance"] == "unavailable" for row in controls)


@pytest.mark.parametrize("edge", ["top", "bottom", "left", "right"])
def test_all_edges_detect_bands_without_conflating_orientation(edge):
    size = 64
    rgb = bytearray(bytes(v for y in range(size) for x in range(size) for v in (x * 3, y * 3, 64)))
    for y in range(size):
        for x in range(size):
            if {"top": y < 4, "bottom": y >= size - 4, "left": x < 4, "right": x >= size - 4}[edge]:
                offset = (y * size + x) * 3
                rgb[offset : offset + 3] = b"\xff\xff\xff"
    value = image_metrics.measure(bytes(rgb), size, size)
    assert value["edges"][edge]["flagged"]
    assert sum(row["flagged"] for row in value["edges"].values()) == 1


@pytest.mark.parametrize(
    "rgb,width,height", [(b"", 512, 512), (b"123", True, 1), (b"123", 1025, 1), (b"123", 0, 1)]
)
def test_bad_rgb_bounds_refused(rgb, width, height):
    with pytest.raises(ValueError):
        image_metrics.measure(rgb, width, height)


def test_confusion_preserves_each_unknown_and_zero_denominators():
    pairs = [(a, b) for a in image_checks.VERDICTS for b in image_checks.VERDICTS]
    value = image_checks.confusion(pairs)
    assert value["examples"] == 16
    assert value["false_accepts"] == value["false_rejects"] == 1
    assert value["prediction_unavailable"] == value["prediction_uncertain"] == 4
    assert value["reference_unavailable"] == value["reference_uncertain"] == 4
    assert value["known_reference_decisive_predictions"] == 4
    assert value["known_reference_examples"] == 8
    empty = image_checks.confusion([("uncertain", "pass"), ("unavailable", "unavailable")])
    assert empty["false_accept_fraction"]["denominator"] is None
    assert empty["false_reject_fraction"]["denominator"] is None


def test_missing_optional_evaluator_is_unavailable_and_replayable(checked):
    config, source, packet, path, reference_path, _ = checked
    request, _, _ = image_checks.templates(packet)
    assert "reference" not in request and "measurements" not in request
    report = image_checks.calibrate(config, path, reference_path, save=True)
    assert report["evaluator_status"] == "unavailable"
    assert report["summary"]["prompt_adherence"]["prediction_unavailable"] == 2
    assert report["summary"]["prompt_adherence"]["known_reference_decisive_predictions"] == 0
    assert report["summary"]["constant_frame"]["false_rejects"] == 2
    assert not report["promotion_eligible"]
    saved = config.root / f"state/evaluation/checks/calibrations/{report['calibration_id']}.json"
    assert image_checks.replay(config, saved) == report
    editable = path.with_suffix(".reference.json")
    editable.write_text("preserve user edit")
    assert image_checks.packet(config, source, save=True) == packet
    assert editable.read_text() == "preserve user edit"
    assert image_checks.inspect(config, path) == packet


def test_optional_evaluator_records_versions_configuration_and_abstention(checked):
    config, _, _, path, reference_path, response_path = checked
    response = json.loads(response_path.read_bytes())
    response["evaluator"].update(
        model_revision="fixture-weights-sha256-not-a-model", configuration={"temperature_milli": 0}
    )
    response["observations"][0]["judgments"]["prompt_adherence"]["verdict"] = "fail"
    response["observations"][1]["judgments"]["image_quality"]["verdict"] = "uncertain"
    document(response_path, response)
    value = image_checks.calibrate(config, path, reference_path, evaluator_path=response_path)
    assert value["summary"]["prompt_adherence"]["false_rejects"] == 1
    assert value["summary"]["image_quality"]["prediction_uncertain"] == 1
    assert value["evaluator_metadata"] == response["evaluator"]
    assert value["rows"][0]["evaluator_observations"] == response["observations"][0]["judgments"]


@pytest.mark.parametrize(
    "kind,mutation",
    [
        (kind, mutation)
        for kind in ("reference", "response")
        for mutation in (
            "missing",
            "duplicate",
            "bool_index",
            "image_hash",
            "pixels",
            "pending",
            "notes",
            "extra_criterion",
            "version",
            "binding",
            "source",
        )
    ]
    + [("response", "uncertainty"), ("response", "adapter_version"), ("response", "float")],
)
def test_incomplete_or_stale_judgments_refused(checked, kind, mutation):
    config, _, _, path, reference_path, response_path = checked
    target = reference_path if kind == "reference" else response_path
    value = json.loads(target.read_bytes())
    row = value["observations"][0]
    if mutation == "missing":
        value["observations"].pop()
    elif mutation == "duplicate":
        value["observations"][1] = copy.deepcopy(row)
    elif mutation == "bool_index":
        row["index"] = False
    elif mutation == "image_hash":
        row["image_sha256"] = "0" * 64
    elif mutation == "pixels":
        row["decoded_rgb_sha256"] = "0" * 64
    elif mutation in ("pending", "notes", "uncertainty"):
        field = "verdict" if mutation == "pending" else mutation
        row["judgments"]["image_quality"][field] = None if mutation == "pending" else ""
    elif mutation == "extra_criterion":
        row["judgments"]["quality_score"] = 100
    elif mutation == "version":
        value["version"] = True
    elif mutation == "binding":
        value["packet_id" if kind == "reference" else "request_id"] = "0" * 64
    elif mutation == "source":
        value["sources"] = [{"path": "../outside.json", "sha256": "0" * 64}]
    elif mutation == "adapter_version":
        value["evaluator"]["adapter_version"] = ""
    else:
        value["evaluator"]["configuration"]["temperature"] = 0.1
    # Deliberately serialize malformed floats without the fixture's canonical writer.
    target.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError):
        image_checks.calibrate(
            config, path, reference_path, evaluator_path=response_path, save=True
        )
    assert not (config.root / "state/evaluation/checks/calibrations").exists()


@pytest.mark.parametrize("mutation", ["omit", "metric", "checker", "bool_version", "source"])
def test_resealed_packet_cannot_rewrite_measured_evidence(checked, mutation):
    config, source, packet, path, _, _ = checked
    value = copy.deepcopy(packet)
    value.pop("packet_id")
    if mutation == "omit":
        value["measurements"].pop()
    elif mutation == "metric":
        value["measurements"][0]["measurement"]["judgments"]["constant_frame"] = "pass"
    elif mutation == "checker":
        value["checker"]["parameters"]["flat_channel_span_max"] = 255
    elif mutation == "bool_version":
        value["version"] = True
    else:
        source.write_text("stale evaluation source")
    document(path, seal(value, "packet_id"))
    with pytest.raises(ValueError):
        image_checks.inspect(config, path)


def test_resealed_calibration_cannot_drop_failure(checked):
    config, _, _, path, reference_path, _ = checked
    report = image_checks.calibrate(config, path, reference_path)
    report.pop("calibration_id")
    report["summary"]["constant_frame"]["false_rejects"] = 0
    saved = document(config.root / "edited.json", seal(report, "calibration_id"))
    with pytest.raises(ValueError, match="Calibration or evidence differs"):
        image_checks.replay(config, saved)


def test_changed_semantic_rubric_requires_new_packet_and_reference(checked, monkeypatch):
    config, source, packet, path, reference_path, _ = checked
    monkeypatch.setitem(image_checks.RUBRICS, "prompt_adherence", "Different rubric version")
    with pytest.raises(ValueError, match="packet or inputs differ"):
        image_checks.inspect(config, path)
    new_packet = image_checks.packet(config, source, save=True)
    assert new_packet["packet_id"] != packet["packet_id"]
    new_path = config.root / f"state/evaluation/checks/packets/{new_packet['packet_id']}.json"
    with pytest.raises(ValueError, match="Reference packet binding differs"):
        image_checks.calibrate(config, new_path, reference_path)


def test_final_freshness_blocks_same_length_restored_timestamp_mutation(checked, monkeypatch):
    config, _, _, path, reference_path, _ = checked
    original = reference_path.stat()
    verify = EvidenceReads.verify

    def change(reads):
        raw = reference_path.read_bytes()
        reference_path.write_bytes(raw.replace(b"fixture", b"changed"))
        os.utime(reference_path, ns=(original.st_atime_ns, original.st_mtime_ns))
        verify(reads)

    # The nested packet verification also calls this; target is observed at the final boundary.
    def final_only(reads):
        if any(row.path == reference_path for row in reads.observations):
            change(reads)
        else:
            verify(reads)

    monkeypatch.setattr(EvidenceReads, "verify", final_only)
    with pytest.raises(ValueError, match="Evidence changed"):
        image_checks.calibrate(config, path, reference_path, save=True)
    assert not (config.root / "state/evaluation/checks/calibrations").exists()


def test_public_completed_runtime_calibration_has_no_new_submissions(runtime_case, capsys):
    item = runtime_case
    _, evaluation_path = planned(item)
    assert execute(item, evaluation_path)["succeeded"] == 16
    before = list(item.requests)
    options = ["--config", str(item.config.file), "--json"]
    assert main(["checks", "packet", str(evaluation_path), "--save", *options]) == 0
    packet = json.loads(capsys.readouterr().out)
    path = item.config.root / f"state/evaluation/checks/packets/{packet['packet_id']}.json"
    reference, response = labels(packet)
    ref = document(item.config.root / "reference.json", reference)
    response_path = document(item.config.root / "response.json", response)
    assert (
        main(
            [
                "checks",
                "calibrate",
                str(path),
                "--reference",
                str(ref),
                "--evaluator",
                str(response_path),
                "--save",
                *options,
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["summary"]["image_quality"]["correct_accepts"] == 16
    assert result["summary"]["constant_frame"]["false_rejects"] == 16
    assert not result["promotion_eligible"]
    assert "_cli" not in json.loads(path.read_bytes())
    assert main(["checks", "replay", result["saved_path"], "--config", str(item.config.file)]) == 0
    assert "false rejects 16" in capsys.readouterr().out
    assert item.requests == before
    bad_image = item.config.root / packet["evaluation"]["matrix"][0]["image"]["path"]
    bad_image.write_bytes(b"corrupt image")
    assert main(["checks", "inspect", str(path), *options]) == 2
    assert json.loads(capsys.readouterr().out)["_cli"]["exit_code"] == 2
