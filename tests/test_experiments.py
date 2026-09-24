"""Preregistration, finite budgets and loss-independent checkpoint decisions."""

import copy
import json
import shutil
import subprocess
import sys

import pytest
from quality_fixtures import curated_inputs as curated_inputs
from test_training import document, write
from test_training import training_inputs as training_inputs
from test_training_checkpoints import checkpoint
from test_training_checkpoints import completed_checkpoint as completed_checkpoint
from test_training_config import save_trace, trace_for

from itov import experiments, training, training_checkpoints
from itov.catalog import canonical_bytes
from itov.cli import main
from itov.training_data import seal


@pytest.fixture
def declared(completed_checkpoint):
    item = completed_checkpoint
    endpoints = []
    for name, steps in (("short", 4), ("long", 8)):
        spec = copy.deepcopy(item.spec)
        spec["parameters"]["steps"] = steps
        endpoints.append(
            {
                "id": name,
                "hypothesis": "A bounded fixture hypothesis",
                "training": write(item.config.root, name + ".json", canonical_bytes(spec)),
            }
        )
    item.experiment = {
        "version": 1,
        "id": "fixture-experiment",
        "hypothesis": "Duration might affect adherence",
        "endpoints": endpoints,
        "repetitions": 2,
        "budget": {"max_attempts": 4, "max_optimizer_steps": 24, "max_worker_seconds": 240},
        "protocol": {
            "selection": experiments.RULE,
            "method": "Inspect all four conditions",
            "limitations": "Synthetic test fixtures cannot establish image quality",
        },
    }
    item.experiment_path = document(item.config.root / "experiment.json", item.experiment)
    return item


def register(item):
    document(item.experiment_path, item.experiment)
    value = experiments.plan(item.config, item.experiment_path, save=True)
    item.manifest = item.config.root / f"state/experiments/plans/{value['experiment_id']}.json"
    return value


def finish(item, value, *, failed=None):
    for row in value["members"]:
        child = copy.copy(item)
        child.plan_path = item.config.root / row["plan"]["path"]
        child.plan = training.load_plan(child.plan_path)
        child.spec = child.plan["specification"]
        child.folder = training.run_folder(item.config, child.plan)
        child.folder.mkdir(parents=True)
        if row["id"] == failed:
            training._record(
                child.folder,
                {
                    "version": 2,
                    "status": "failed",
                    "plan_id": child.plan["plan_id"],
                    "error": "Retained failed fixture",
                },
            )
            continue
        child.result = copy.deepcopy(item.result)
        for ref in [
            child.result["weights"],
            *[r["image"] for r in child.result["quality_matrix"]],
            *[r[k] for r in child.result["previews"] for k in ("baseline", "candidate")],
        ]:
            shutil.copyfile(item.folder / ref["path"], child.folder / ref["path"])
        steps = child.spec["parameters"]["steps"]
        child.result.update(
            plan_id=child.plan["plan_id"],
            optimizer_steps=steps,
            training_loss_billionths=[100] * steps,
        )
        child.trace = trace_for(child.plan)
        child.result["checkpoints"] = [
            checkpoint(child, n)[1] for n in training_checkpoints.checkpoint_steps(child.plan)
        ]
        save_trace(child, child.trace)


def review(item, *, verdict="pass"):
    value = experiments.packet(item.config, item.manifest, save=True)
    path = item.config.root / f"state/experiments/packets/{value['packet_id']}.review.json"
    v = json.loads(path.read_bytes())
    v.update(
        reviewer="Fixture reviewer",
        method="Synthetic contract inspection",
        limitations="Not real image quality evidence",
    )
    for member in v["members"]:
        member["notes"] = "Retained observation for this checkpoint"
        for case in member["cases"]:
            case["verdicts"] = dict.fromkeys(case["verdicts"], verdict)
            case["notes"] = "Synthetic case observation"
    document(path, v)
    return path, v


def test_preregistered_repetitions_budget_and_no_execution(declared):
    item = declared
    value = register(item)
    assert value == experiments.plan(item.config, item.experiment_path, save=True)
    assert len(value["members"]) == 4
    loaded = [training.load_plan(item.config.root / m["plan"]["path"]) for m in value["members"]]
    assert len({p["plan_id"] for p in loaded}) == 4
    for first, second in ((loaded[0], loaded[1]), (loaded[2], loaded[3])):
        a, b = copy.deepcopy(first["specification"]), copy.deepcopy(second["specification"])
        a.pop("id"), b.pop("id")
        assert a == b
        assert first["optimization"] == second["optimization"]
    assert {r["status"] for r in experiments.status(item.config, item.manifest)["members"]} == {
        "not_started"
    }
    with pytest.raises(ValueError, match="Every declared member"):
        experiments.packet(item.config, item.manifest)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s.update(version=True),
        lambda s: s.update(repetitions=True),
        lambda s: s.update(repetitions=0),
        lambda s: s.update(repetitions=4),
        lambda s: s.update(hypothesis=" "),
        lambda s: s["endpoints"].append(s["endpoints"][0]),
        lambda s: s["budget"].update(max_attempts=3),
        lambda s: s["budget"].update(max_optimizer_steps=23),
        lambda s: s["budget"].update(max_worker_seconds=239),
        lambda s: s["budget"].update(max_attempts=True),
        lambda s: s["budget"].update(max_worker_seconds=28801),
        lambda s: s["protocol"].update(selection="lowest_loss"),
        lambda s: s["endpoints"][0]["training"].update(path="../outside.json"),
    ],
)
def test_invalid_preregistration_refused(declared, mutate):
    mutate(declared.experiment)
    with pytest.raises(ValueError):
        register(declared)
    assert not (declared.config.root / "state/experiments/plans").exists()


def test_completed_selection_and_replay_are_read_only(declared, capsys):
    item = declared
    value = register(item)
    finish(item, value)
    with pytest.raises(ValueError, match="already attempted"):
        experiments.plan(item.config, item.experiment_path, save=True)
    path, _ = review(item)
    decision = experiments.decide(item.config, item.manifest, path, save=True)
    assert decision["selected_endpoint"] == "short" and len(decision["selected_members"]) == 2
    assert decision["promotion_eligible"] is False
    saved = item.config.root / f"state/experiments/decisions/{decision['decision_id']}.json"
    before = {p: p.read_bytes() for p in item.config.root.rglob("*") if p.is_file()}
    assert experiments.replay(item.config, item.manifest, saved)["valid"]
    assert (
        main(
            [
                "experiment",
                "replay",
                str(item.manifest),
                "--decision",
                str(saved),
                "--config",
                str(item.config.file),
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["_cli"]["outcome"] == "ok"
    assert all(p.read_bytes() == raw for p, raw in before.items())
    decision["selected_endpoint"] = "long"
    decision.pop("decision_id")
    document(saved, seal(decision, "decision_id"))
    with pytest.raises(ValueError, match="selection differs"):
        experiments.replay(item.config, item.manifest, saved)


@pytest.mark.parametrize("verdict,expected", [("fail", "rejected"), ("uncertain", "inconclusive")])
def test_quality_failures_and_uncertainty_never_selected(declared, verdict, expected):
    item = declared
    finish(item, register(item))
    path, _ = review(item, verdict=verdict)
    result = experiments.decide(item.config, item.manifest, path)
    assert result["status"] == expected and result["selected_endpoint"] is None


def test_one_failed_repetition_disqualifies_endpoint_and_is_preserved(declared):
    item = declared
    value = register(item)
    finish(item, value, failed="short-r2")
    path, v = review(item)
    assert not v["members"][1]["cases"]
    result = experiments.decide(item.config, item.manifest, path)
    assert result["members"][1]["disposition"] == "failed"
    assert result["selected_endpoint"] == "long"
    assert experiments.status(item.config, item.manifest)["members"][1]["status"] == "failed"


def test_one_adverse_seed_in_one_repetition_overrides_lower_loss(declared):
    item = declared
    value = register(item)
    finish(item, value)
    # Give the longer endpoint worse validation loss, retaining valid trace/checkpoint evidence.
    for member in value["members"][2:]:
        child = copy.copy(item)
        child.plan_path = item.config.root / member["plan"]["path"]
        child.plan = training.load_plan(child.plan_path)
        child.folder = training.run_folder(item.config, child.plan)
        child.result = json.loads((child.folder / "result.json").read_bytes())
        child.result.pop("result_id")
        child.trace = trace_for(child.plan)
        for key in ("heldout_before", "heldout_after"):
            for row in child.result[key]:
                row["loss_billionths"] = 200
        for row in child.trace["validation"]:
            for loss in row["losses"]:
                loss["loss_billionths"] = 200
        child.result["checkpoints"] = [
            checkpoint(child, n)[1] for n in training_checkpoints.checkpoint_steps(child.plan)
        ]
        save_trace(child, child.trace)
    path, v = review(item)
    v["members"][1]["cases"][1]["verdicts"]["prompt_adherence"] = "fail"
    document(path, v)
    result = experiments.decide(item.config, item.manifest, path)
    assert result["selected_endpoint"] == "long"
    assert result["members"][0]["disposition"] == "eligible"
    assert result["members"][1]["disposition"] == "rejected"


def test_decision_rechecks_evidence_before_publication(declared, monkeypatch):
    item = declared
    finish(item, register(item))
    path, _ = review(item)
    actual = experiments._decide

    def changed(*args):
        result = actual(*args)
        item.suite_path.write_bytes(b"changed during decision")
        return result

    monkeypatch.setattr(experiments, "_decide", changed)
    with pytest.raises(ValueError, match="Evidence changed"):
        experiments.decide(item.config, item.manifest, path, save=True)
    assert not (item.config.root / "state/experiments/decisions").exists()


def test_pending_review_edits_survive_packet_replay(declared):
    item = declared
    finish(item, register(item))
    path, _ = review(item)
    before = path.read_bytes()
    experiments.packet(item.config, item.manifest, save=True)
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "mutate",
    [
        lambda v: v["members"].pop(),
        lambda v: v["members"][0]["cases"].pop(),
        lambda v: v["members"][0]["cases"][0].update(seed=True),
        lambda v: v["members"][0]["cases"][0]["verdicts"].update(activation="pending"),
        lambda v: v["members"][0]["cases"][0]["verdicts"].update(activation=True),
        lambda v: v["members"][0]["cases"][0].update(notes=""),
        lambda v: v.update(method=""),
        lambda v: v.update(reviewer_kind="loss_optimizer"),
        lambda v: v["members"][0].update(id="long-r1"),
    ],
)
def test_incomplete_or_forged_review_refused(declared, mutate):
    item = declared
    finish(item, register(item))
    path, v = review(item)
    mutate(v)
    document(path, v)
    with pytest.raises(ValueError):
        experiments.decide(item.config, item.manifest, path, save=True)
    assert not (item.config.root / "state/experiments/decisions").exists()


def test_stale_suite_image_and_plan_bindings(declared):
    item = declared
    value = register(item)
    finish(item, value)
    path, _ = review(item)
    packet = experiments.packet(item.config, item.manifest)
    image = item.config.root / packet["members"][0]["images"][0]["image"]["path"]
    old = image.read_bytes()
    image.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="stale"):
        experiments.decide(item.config, item.manifest, path)
    image.write_bytes(old)
    item.suite_path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="SHA-256"):
        experiments.status(item.config, item.manifest)


def test_run_delegates_only_declared_member_and_published_manifest(declared, monkeypatch):
    item = declared
    value = register(item)
    calls = []
    monkeypatch.setattr(training, "run", lambda *args: calls.append(args) or {"status": "failed"})
    with pytest.raises(ValueError, match="Unknown"):
        experiments.run(item.config, item.manifest, "invented", "GPU-test")
    assert not calls
    experiments.run(item.config, item.manifest, "short-r1", "GPU-test")
    assert calls[0][1] == item.config.root / value["members"][0]["plan"]["path"]


def test_no_optional_ml_imports():
    code = (
        "from itov import experiments; import sys; "
        "assert not {'torch','numpy','PIL','diffusers','safetensors'} & set(sys.modules)"
    )
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)
