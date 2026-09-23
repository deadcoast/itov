"""Execution/validation boundaries; fixtures do not establish trained model quality."""

import json

import pytest
from quality_fixtures import curated_inputs as curated_inputs
from test_evaluation import complete, save_result
from test_evaluation import completed as completed
from test_training import training_inputs as training_inputs

from itov import evaluation, training, training_results
from itov.cli import main


def snapshot(folder):
    return {str(p.relative_to(folder)): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


@pytest.mark.parametrize("as_json", [True, False])
@pytest.mark.parametrize(
    "case,boundary",
    [
        ("png_weights", "weights"),
        ("truncated", "weights"),
        ("heldout", "heldout_matrix"),
        ("preview", "preview_matrix"),
        ("result_id", "result_binding"),
        ("partial_result", "result_publication"),
        ("stale_dataset", "input_freshness"),
    ],
)
def test_status_reports_failed_boundary_without_rewriting_legacy_success(
    completed, capsys, as_json, case, boundary
):
    item = completed
    if case == "png_weights":
        item.result["weights"] = item.result["previews"][0]["candidate"]
    elif case == "heldout":
        item.result["heldout_after"] = []
    elif case == "preview":
        item.result["previews"] = []
    elif case == "truncated":
        from itov.catalog import sha256

        path = item.folder / item.result["weights"]["path"]
        path.write_bytes(path.read_bytes()[:-4])
        item.result["weights"]["sha256"] = sha256(path.read_bytes())
    save_result(item)
    if case == "result_id":
        record = training.read_record(item.config, item.plan_path)
        record.pop("record_id")
        record["result_id"] = "0" * 64
        training._record(item.folder, record)
    elif case == "partial_result":
        (item.folder / "result.json").write_bytes(b'{"version":')
    elif case == "stale_dataset":
        (item.config.root / "data/0.txt").write_text("changed")
    before = snapshot(item.folder)
    observed = training.status(item.config, item.plan_path)
    assert observed["recorded_status"] == "succeeded"
    assert observed["status"] == "failed"
    assert observed["worker_completion"] == "completed"
    assert observed["artifact_validation"] == "failed"
    assert observed["failure_boundary"] == boundary
    assert observed["candidate_assessment"] == "not_performed_by_training"
    args = ["training", "status", str(item.plan_path), "--config", str(item.config.file)]
    assert main([*args, *(["--json"] if as_json else [])]) == 1
    output = capsys.readouterr().out
    if as_json:
        assert json.loads(output)["failure_boundary"] == boundary
    else:
        assert "FAILED" in output and f"Cause (failure_boundary): {boundary}" in output
        assert "Next:" in output and "Artifact (run.json):" in output
    with pytest.raises(training_results.ResultValidationError) as caught:
        evaluation.assess(item.config, item.plan_path, save=True)
    assert caught.value.boundary == boundary
    assert snapshot(item.folder) == before


def test_successful_replay_preserves_historical_assessment_and_requires_separate_review(completed):
    item = completed
    before = snapshot(item.folder)
    first = evaluation.assess(item.config, item.plan_path)
    for _ in range(2):
        observed = training.status(item.config, item.plan_path)
        assert observed["status"] == "artifacts_validated"
        assert observed["recorded_status"] == "succeeded"
        assert observed["candidate_assessment"] == "not_performed_by_training"
        assert evaluation.assess(item.config, item.plan_path) == first
    assert first["technical_pass"] is True and first["promotion_eligible"] is False
    assert snapshot(item.folder) == before


@pytest.mark.parametrize("case", ["missing", "duplicate", "wrong_seed", "missing_image"])
def test_complete_curated_matrix_is_required_at_shared_boundary(curated_inputs, case):
    item = complete(curated_inputs, "training")
    if case == "missing":
        item.result["quality_matrix"].pop()
    elif case == "duplicate":
        item.result["quality_matrix"][1] = item.result["quality_matrix"][0]
    elif case == "wrong_seed":
        item.result["quality_matrix"][0]["seed"] += 1
    else:
        (item.folder / item.result["quality_matrix"][0]["image"]["path"]).unlink()
    save_result(item)
    observed = training.status(item.config, item.plan_path)
    assert observed["status"] == "failed" and observed["failure_boundary"] == "quality_matrix"


def test_assessment_cli_includes_boundary(completed, capsys):
    item = completed
    item.result["weights"] = item.result["previews"][0]["candidate"]
    save_result(item)
    assert (
        main(
            [
                "evaluation",
                "assess",
                str(item.plan_path),
                "--config",
                str(item.config.file),
                "--json",
            ]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().out)["failure_boundary"] == "weights"
