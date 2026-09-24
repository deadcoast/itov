"""Corpus lineage, complete baseline observations and owned runtime protocol fixtures."""

import copy
import json

import pytest
from quality_fixtures import curated_inputs as curated_inputs
from test_evaluation_runtime import execute
from test_evaluation_runtime import runtime_case as runtime_case
from test_training import document
from test_training import training_inputs as training_inputs

from itov import evaluation_corpus as corpus
from itov import evaluation_runtime as runtime
from itov.catalog import sha256
from itov.cli import main
from itov.evaluation_cases import conditions
from itov.evidence_reads import EvidenceReads
from itov.training_data import seal


def inputs(item):
    legacy = json.loads(
        (item.config.root / item.spec["qualification"]["suite"]["path"]).read_bytes()
    )
    cases = []
    for index, old in enumerate(legacy["cases"]):
        cases.append(
            {
                **old,
                "kind": "regression",
                "seeds": [*old["seeds"], 300 + index],
                "coverage": list(corpus.AXES),
                "exposure": "legacy_diagnostic",
            }
        )
    for index in range(6):
        cases.append(
            {
                "id": f"new-{index}",
                "kind": "holdout",
                "prompt": f"New subject {index}",
                "negative_prompt": "",
                "expectation": "One intact subject in one scene",
                "seeds": [1000 + index * 3 + n for n in range(3)],
                "coverage": list(corpus.AXES),
                "exposure": "baseline_only",
            }
        )
    spec = {
        "version": 1,
        "training_plan": item.eval_spec["training_plan"],
        "suite": {
            "version": 2,
            "id": "corpus-fixture",
            "trigger": legacy["trigger"],
            "cases": cases,
            "strengths_milli": [250, 500, 1000],
            "policy": {
                **corpus.POLICY,
                "method": "Direct inspection of every image",
                "limitations": "Protocol fixtures cannot prove semantics",
            },
        },
    }
    return spec, document(item.config.root / "corpus.json", spec)


def frozen(item):
    spec, source = inputs(item)
    value = corpus.freeze(item.config, source, save=True)
    path = item.config.root / f"state/evaluation/corpora/{value['corpus_id']}.json"
    return spec, value, path


def planned(item, mode="baseline"):
    spec, value, path = frozen(item)
    evaluation = {k: v for k, v in item.eval_spec.items() if k != "strength_milli"}
    evaluation.update(
        version=2,
        mode=mode,
        corpus={
            "path": path.relative_to(item.config.root).as_posix(),
            "sha256": sha256(path.read_bytes()),
        },
    )
    source = document(item.config.root / "corpus-evaluation.json", evaluation)
    plan = runtime.plan(item.config, source, save=True)
    plan_path = item.config.root / f"state/evaluation/plans/{plan['plan_id']}.json"
    return path, plan, plan_path


def test_freeze_is_immutable_and_preserves_all_legacy_seeds(runtime_case, capsys):
    item = runtime_case
    spec, value, path = frozen(item)
    assert corpus.inspect(item.config, path) == value
    assert corpus.freeze(item.config, item.config.root / "corpus.json", save=True) == value
    assert value["coverage"]["baseline_images"] == 48
    assert value["coverage"]["comparison_images"] == 192
    args = [str(path), "--config", str(item.config.file)]
    assert main(["corpus", "inspect", *args, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["corpus_id"] == value["corpus_id"]
    assert main(["corpus", "inspect", *args]) == 0
    assert "Coverage frozen" in capsys.readouterr().out
    assert not item.routes.get("_posted")


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_legacy",
        "legacy_prompt",
        "legacy_expectation",
        "legacy_seed",
        "legacy_exposure",
        "too_few",
        "repeat_prompt",
        "repeat_id",
        "repeat_seed",
        "too_few_seeds",
        "bool_seed",
        "trigger",
        "negative_trigger",
        "missing_axis",
        "duplicate_axis",
        "unknown_axis",
        "no_holdout",
        "strength_order",
        "strength_duplicate",
        "strength_bool",
        "strength_max",
        "policy",
        "caption",
    ],
)
def test_bad_corpus_refused_before_publication(runtime_case, mutation):
    item = runtime_case
    spec, path = inputs(item)
    suite = spec["suite"]
    cases = suite["cases"]
    if mutation == "missing_legacy":
        cases[0]["id"] = "replacement"
    elif mutation == "legacy_prompt":
        cases[0]["prompt"] += " changed"
    elif mutation == "legacy_expectation":
        cases[0]["expectation"] += " changed"
    elif mutation == "legacy_seed":
        cases[0]["seeds"].reverse()
    elif mutation == "legacy_exposure":
        cases[0]["exposure"] = "baseline_only"
    elif mutation == "too_few":
        cases.pop()
    elif mutation == "repeat_prompt":
        cases[-1]["prompt"] = cases[-2]["prompt"]
    elif mutation == "repeat_id":
        cases[-1]["id"] = cases[-2]["id"]
    elif mutation == "repeat_seed":
        cases[-1]["seeds"][0] = cases[-1]["seeds"][1]
    elif mutation == "too_few_seeds":
        cases[-1]["seeds"].pop()
    elif mutation == "bool_seed":
        cases[-1]["seeds"][0] = True
    elif mutation == "trigger":
        cases[-1]["prompt"] += " " + suite["trigger"]
    elif mutation == "negative_trigger":
        cases[-1]["negative_prompt"] = suite["trigger"]
    elif mutation == "missing_axis":
        for case in cases:
            case["coverage"].remove("counts")
    elif mutation == "duplicate_axis":
        cases[-1]["coverage"].append("counts")
    elif mutation == "unknown_axis":
        cases[-1]["coverage"].append("invented")
    elif mutation == "no_holdout":
        for case in cases:
            case["kind"] = "regression"
    elif mutation == "strength_order":
        suite["strengths_milli"].reverse()
    elif mutation == "strength_duplicate":
        suite["strengths_milli"] = [500, 500, 1000]
    elif mutation == "strength_bool":
        suite["strengths_milli"][0] = True
    elif mutation == "strength_max":
        suite["strengths_milli"][-1] = 1001
    elif mutation == "policy":
        suite["policy"]["retention"] = "remove_failures"
    elif mutation == "caption":
        from itov.training_data import load_dataset

        dataset = load_dataset(item.config.root, item.config.root / item.spec["dataset"]["path"])
        sample = dataset["dataset"]["samples"][0]
        cases[-1]["prompt"] = (item.config.root / sample["caption"]["path"]).read_text().strip()
    document(path, spec)
    with pytest.raises(ValueError):
        corpus.freeze(item.config, path, save=True)
    assert not (item.config.root / "state/evaluation/corpora").exists()


def test_resealed_coverage_and_stale_source_refused(runtime_case):
    item = runtime_case
    _, value, path = frozen(item)
    body = {k: v for k, v in value.items() if k != "corpus_id"}
    body["coverage"]["axes"]["counts"].pop()
    document(path, seal(body, "corpus_id"))
    with pytest.raises(ValueError, match="coverage or bindings"):
        corpus.inspect(item.config, path)
    document(path, value)
    item.plan_path.write_bytes(b"changed")
    with pytest.raises(ValueError):
        corpus.inspect(item.config, path)


def test_final_freshness_before_freeze_publication(runtime_case, monkeypatch):
    item = runtime_case
    _, path = inputs(item)
    verify = EvidenceReads.verify

    def change(reads):
        path.write_bytes(b"changed")
        verify(reads)

    monkeypatch.setattr(EvidenceReads, "verify", change)
    with pytest.raises(ValueError, match="changed during operation"):
        corpus.freeze(item.config, path, save=True)
    assert not (item.config.root / "state/evaluation/corpora").exists()


def test_strength_matrix_exact_graphs_and_resealed_omission_refusal(runtime_case):
    item = runtime_case
    _, plan, path = planned(item, "comparison")
    assert len(plan["jobs"]) == 192
    for job in plan["jobs"]:
        graph = json.loads(job["workflow_json"])
        if job["role"].startswith("adapter"):
            assert graph["2"]["inputs"]["strength_model"] == job["strength_milli"] / 1000
        else:
            assert "2" not in graph and job["strength_milli"] == 0
    assert len(conditions(plan["suite"], baseline=True)) == 48
    body = {k: v for k, v in plan.items() if k != "plan_id"}
    body["jobs"].pop()
    document(path, seal(body, "plan_id"))
    with pytest.raises(ValueError, match="coverage bindings"):
        runtime.load_plan(path)
    assert not item.routes.get("_posted")


def completed(item):
    path, plan, plan_path = planned(item)
    assert execute(item, plan_path)["succeeded"] == 48
    pending = corpus.baseline(item.config, path, plan_path, save=True)
    review_path = (
        item.config.root / f"state/evaluation/baselines/{pending['baseline_id']}.review.json"
    )
    review = json.loads(review_path.read_bytes())
    review.update(
        reviewer="fixture", method="Fixture coverage checks", limitations="No model inference"
    )
    for row in review["observations"]:
        row.update(
            prompt_adherence="fail",
            image_quality="uncertain",
            notes="Known fixture failure retained",
        )
    document(review_path, review)
    return path, plan_path, review_path, review


def test_owned_baseline_observations_and_offline_replay(runtime_case, capsys):
    item = runtime_case
    path, plan_path, review_path, _ = completed(item)
    before = list(item.requests)
    assert all("2" not in payload["prompt"] for payload in item.routes["_posted"])
    reviewed = corpus.baseline(item.config, path, plan_path, review_path=review_path, save=True)
    saved = item.config.root / f"state/evaluation/baselines/{reviewed['baseline_id']}.json"
    assert reviewed["outcomes"] == {"pass": 0, "fail": 48, "uncertain": 0}
    assert not reviewed["promotion_eligible"]
    assert corpus.replay(item.config, saved) == reviewed
    assert main(["corpus", "replay", str(saved), "--config", str(item.config.file), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["baseline_id"] == reviewed["baseline_id"]
    corpus.baseline(item.config, path, plan_path, save=True)
    assert json.loads(review_path.read_bytes())["reviewer"] == "fixture"
    assert item.requests == before
    bad = copy.deepcopy(reviewed)
    bad.pop("baseline_id")
    bad["outcomes"]["fail"] = 0
    document(saved, seal(bad, "baseline_id"))
    with pytest.raises(ValueError, match="observations or evidence"):
        corpus.replay(item.config, saved)
    document(saved, reviewed)
    image = item.config.root / reviewed["evaluation"]["matrix"][0]["image"]["path"]
    image.write_bytes(b"corrupt retained image")
    with pytest.raises(ValueError, match="incomplete or invalid"):
        corpus.replay(item.config, saved)


@pytest.mark.parametrize(
    "mutation", ["missing", "role", "pending", "no_notes", "report", "bool_index"]
)
def test_incomplete_or_misbound_reviews_refused(runtime_case, mutation):
    item = runtime_case
    path, plan_path, review_path, review = completed(item)
    if mutation == "missing":
        review["observations"].pop()
    elif mutation == "role":
        review["observations"][0]["role"] = "adapter_plain"
    elif mutation == "pending":
        review["observations"][0]["image_quality"] = None
    elif mutation == "no_notes":
        review["observations"][0]["notes"] = ""
    elif mutation == "report":
        review["evaluation_report_id"] = "0" * 64
    elif mutation == "bool_index":
        review["observations"][0]["index"] = False
    document(review_path, review)
    with pytest.raises(ValueError):
        corpus.baseline(item.config, path, plan_path, review_path=review_path, save=True)


def test_incomplete_matrix_cannot_become_baseline(runtime_case):
    item = runtime_case
    path, _, plan_path = planned(item)
    with pytest.raises(ValueError, match="incomplete or invalid"):
        corpus.baseline(item.config, path, plan_path, save=True)


def test_changed_frozen_corpus_refuses_before_submission(runtime_case):
    item = runtime_case
    path, _, plan_path = planned(item)
    path.write_bytes(b"stale corpus")
    with pytest.raises(ValueError):
        execute(item, plan_path)
    assert not item.routes.get("_posted")
