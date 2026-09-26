"""Repetition evidence and tolerance contracts; synthetic values are not GPU evidence."""

import json
import struct

import pytest
from quality_fixtures import curated_inputs as curated_inputs
from test_experiments import declared as declared
from test_experiments import finish, register
from test_training import document
from test_training import training_inputs as training_inputs
from test_training_checkpoints import completed_checkpoint as completed_checkpoint
from test_training_checkpoints import payload

from itov import experiment_variance as variance
from itov import experiments
from itov.cli import main
from itov.training_data import seal


def numerical(item):
    item.experiment.update(
        version=2,
        numerical_tolerances={
            "weight_abs_billionths": 1000,
            "optimizer_abs_billionths": 1000,
            "loss_abs_billionths": 1000,
        },
    )
    return register(item)


def test_exact_repetition_report_cli_and_replay(declared, capsys):
    value = numerical(declared)
    finish(declared, value)
    result = variance.measure(declared.config, declared.manifest, save=True)
    assert result["status"] == "pass" and result["exact_reproduction"]
    assert not result["promotion_eligible"]
    assert len(result["endpoints"]) == 2
    assert all(all(p["controls"].values()) for r in result["endpoints"] for p in r["pairs"])
    path = declared.config.root / f"state/experiments/variance/{result['variance_id']}.json"
    assert variance.replay(declared.config, declared.manifest, path)["valid"]
    assert (
        main(
            [
                "experiment",
                "variance-replay",
                str(declared.manifest),
                "--report",
                str(path),
                "--config",
                str(declared.config.file),
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["_cli"]["outcome"] == "ok"
    result["exact_reproduction"] = False
    result.pop("variance_id")
    document(path, seal(result, "variance_id"))
    with pytest.raises(ValueError, match="measurements differ"):
        variance.replay(declared.config, declared.manifest, path)


def test_all_three_pairs_and_failed_attempt_retained(declared):
    declared.experiment.update(
        repetitions=3,
        budget={
            "max_attempts": 6,
            "max_optimizer_steps": 36,
            "max_worker_seconds": 360,
        },
    )
    value = numerical(declared)
    finish(declared, value, failed="short-r2")
    result = variance.measure(declared.config, declared.manifest)
    assert result["status"] == "inconclusive" and not result["exact_reproduction"]
    assert [len(row["pairs"]) for row in result["endpoints"]] == [3, 3]
    assert sum(p["status"] == "unavailable" for r in result["endpoints"] for p in r["pairs"]) == 2


def test_v1_no_retrospective_tolerance_invention(declared):
    value = register(declared)
    finish(declared, value)
    with pytest.raises(ValueError, match="preregistered v2"):
        variance.measure(declared.config, declared.manifest)


@pytest.mark.parametrize("delta,status", [(1e-6, "pass"), (1.0001e-6, "failed")])
def test_tolerance_boundary_keeps_exact_failure(declared, monkeypatch, capsys, delta, status):
    value = numerical(declared)
    finish(declared, value)
    original = variance.compare_tensors

    def changed(*args):
        result = original(*args)
        result["parameters"]["weight"].update(
            max_absolute_difference_hex=delta.hex(), payload_exact=False, different_elements=1
        )
        return result

    monkeypatch.setattr(variance, "compare_tensors", changed)
    result = variance.measure(declared.config, declared.manifest)
    assert result["status"] == status and not result["exact_reproduction"]
    assert main(
        [
            "experiment",
            "variance",
            str(declared.manifest),
            "--config",
            str(declared.config.file),
            "--json",
        ]
    ) == (status == "failed")
    assert json.loads(capsys.readouterr().out)["status"] == status


def test_control_mismatch_never_counts_as_reproduction(declared, monkeypatch):
    value = numerical(declared)
    finish(declared, value)
    original = variance.compare_tensors

    def changed(*args):
        result = original(*args)
        result["torch_rng_exact"]["rng.cpu"] = False
        return result

    monkeypatch.setattr(variance, "compare_tensors", changed)
    result = variance.measure(declared.config, declared.manifest)
    assert result["status"] == "failed" and not result["exact_reproduction"]


def test_mutation_during_measurement_refused(declared, monkeypatch):
    value = numerical(declared)
    finish(declared, value)
    original = variance.compare_tensors

    def changed(left, right):
        result = original(left, right)
        left.write_bytes(left.read_bytes() + b"tamper")
        return result

    monkeypatch.setattr(variance, "compare_tensors", changed)
    with pytest.raises(ValueError, match="Evidence changed"):
        variance.measure(declared.config, declared.manifest, save=True)
    assert not (declared.config.root / "state/experiments/variance").exists()


@pytest.mark.parametrize("bad", [-1, True, 1.5, 1000000001, "1000", None])
def test_bad_tolerances(declared, bad):
    numerical(declared)
    declared.experiment["numerical_tolerances"]["weight_abs_billionths"] = bad
    with pytest.raises(ValueError):
        register(declared)


def test_missing_repetition_refused(declared):
    numerical(declared)
    declared.experiment["repetitions"] = 1
    with pytest.raises(ValueError, match="repeated endpoints"):
        register(declared)


def test_unfinished_and_changed_evidence_refused(declared):
    value = numerical(declared)
    with pytest.raises(ValueError, match="Every declared member"):
        variance.measure(declared.config, declared.manifest)
    finish(declared, value)
    result = variance.measure(declared.config, declared.manifest, save=True)
    packet = experiments.packet(declared.config, declared.manifest)
    path = declared.config.root / packet["members"][0]["checkpoint"]["path"]
    path.write_bytes(path.read_bytes() + b" ")
    report = declared.config.root / f"state/experiments/variance/{result['variance_id']}.json"
    with pytest.raises(ValueError):
        variance.replay(declared.config, declared.manifest, report)


@pytest.mark.parametrize("change,expected", [(0.125, 0.125), (-0.25, 0.25)])
def test_tensor_differences_measured_without_ml(tmp_path, change, expected):
    params = [{"shape": [2]}]

    def values(header, raw):
        for name in ("weight", "exp_avg", "exp_avg_sq"):
            offset = header["p000000." + name]["data_offsets"][0]
            struct.pack_into("<2f", raw, offset, 0.0, 0.5)

    left = tmp_path / "a"
    left.write_bytes(payload(params, values))

    def changed(header, raw):
        values(header, raw)
        offset = header["p000000.weight"]["data_offsets"][0]
        struct.pack_into("<f", raw, offset, change)
        raw[-1] = 0

    right = tmp_path / "b"
    right.write_bytes(payload(params, changed))
    measured = variance.compare_tensors(left, right)
    row = measured["parameters"]["weight"]
    assert float.fromhex(row["max_absolute_difference_hex"]) == expected
    assert row["different_elements"] == 1 and not row["payload_exact"]
    assert measured["parameters"]["exp_avg"]["payload_exact"]
    assert measured["torch_rng_exact"] == {"rng.cpu": False}
