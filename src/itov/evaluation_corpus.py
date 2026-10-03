"""Frozen evaluation coverage and observed base-model baselines, without ML imports."""

from __future__ import annotations

from itov.catalog import array, identifier, integer, object_fields, require, sha256, text
from itov.comfyui import parse_json
from itov.evidence_reads import EvidenceReads, read_document
from itov.linting import contains, normalize
from itov.qualification import safe_path
from itov.training_data import check_seal, file_ref, load_dataset, publish, seal

AXES = (
    "counts",
    "attributes",
    "layout",
    "textures",
    "trigger_specificity",
    "strength_range",
    "unrelated_regression",
)
CASE_FIELDS = {"id", "kind", "prompt", "negative_prompt", "expectation", "seeds"}
POLICY = {
    "retention": "all_cases_seeds_and_failures",
    "holdout": "excluded_from_training_and_tuning",
    "contamination": "declare_exposure_and_add_new_holdouts_without_removing_old_cases",
}


def validate_suite(value):
    object_fields(
        value,
        {"version", "id", "trigger", "cases", "strengths_milli", "policy"},
        "evaluation corpus suite",
    )
    require(type(value["version"]) is int and value["version"] == 2, "Unsupported corpus suite")
    identifier(value["id"], "corpus id")
    identifier(value["trigger"], "corpus trigger")
    object_fields(value["policy"], {*POLICY, "method", "limitations"}, "held-out policy")
    require(all(value["policy"][k] == v for k, v in POLICY.items()), "Invalid held-out policy")
    text(value["policy"]["method"], "corpus method")
    text(value["policy"]["limitations"], "corpus limitations")
    strengths = array(value["strengths_milli"], "corpus strengths")
    require(2 <= len(strengths) <= 3, "Corpus requires two or three positive strengths")
    for strength in strengths:
        integer(strength, "corpus strength", minimum=1)
        require(strength <= 1000, "Corpus strength exceeds 1000 milli")
    require(
        strengths == sorted(set(strengths)) and strengths[-1] == 1000,
        "Strengths must be distinct, increasing and include 1000 milli",
    )
    cases = array(value["cases"], "corpus cases")
    require(8 <= len(cases) <= 24, "Corpus requires 8..24 cases")
    ids, prompts = set(), set()
    coverage = {axis: [] for axis in AXES}
    partitions = {"holdout": [], "regression": []}
    for case in cases:
        object_fields(case, CASE_FIELDS | {"coverage", "exposure"}, "corpus case")
        key = identifier(case["id"], "corpus case id")
        require(key not in ids, "Repeated corpus case")
        ids.add(key)
        require(case["kind"] in ("holdout", "regression"), "Invalid corpus partition")
        partitions[case["kind"]].append(key)
        require(case["exposure"] in ("legacy_diagnostic", "baseline_only"), "Invalid case exposure")
        if case["exposure"] == "legacy_diagnostic":
            require(case["kind"] == "regression", "Previously inspected cases are regressions")
        prompt = text(case["prompt"], "corpus prompt")
        require(
            len(prompt) <= 2048 and not contains(prompt, value["trigger"]),
            "Corpus prompt must omit trigger and fit 2048 characters",
        )
        require(normalize(prompt) not in prompts, "Repeated corpus prompt")
        prompts.add(normalize(prompt))
        negative = case["negative_prompt"]
        require(
            isinstance(negative, str)
            and len(negative) <= 2048
            and not contains(negative, value["trigger"]),
            "Invalid corpus negative prompt",
        )
        text(case["expectation"], "corpus expectation")
        seeds = array(case["seeds"], "corpus seeds")
        require(3 <= len(seeds) <= 8, "Each corpus case requires 3..8 fixed seeds")
        seeds_seen = set()
        for seed in seeds:
            integer(seed, "corpus seed")
            require(seed < 2**32 and seed not in seeds_seen, "Repeated or invalid corpus seed")
            seeds_seen.add(seed)
        axes = array(case["coverage"], "case coverage")
        require(
            axes and all(axis in AXES for axis in axes) and len(set(axes)) == len(axes),
            "Invalid or duplicate coverage axis",
        )
        for axis in axes:
            coverage[axis].append(key)
    require(
        all(len(keys) >= 2 for keys in coverage.values()),
        "Each coverage axis requires at least two cases",
    )
    require(
        all(len(keys) >= 2 for keys in partitions.values()),
        "At least two held-out and two regression cases are required",
    )
    count = sum(len(case["seeds"]) for case in cases)
    require(count * (2 + 2 * len(strengths)) <= 768, "Corpus comparison exceeds 768 images")
    return {
        "axes": coverage,
        "partitions": partitions,
        "case_seed_pairs": count,
        "baseline_images": count * 2,
        "comparison_images": count * (2 + 2 * len(strengths)),
    }


def _freeze(config, spec):
    from itov import quality, training

    object_fields(spec, {"version", "training_plan", "suite"}, "corpus specification")
    require(type(spec["version"]) is int and spec["version"] == 1, "Unsupported corpus version")
    coverage = validate_suite(spec["suite"])
    path, _ = file_ref(config.root, spec["training_plan"])
    trained = training.load_plan(path)
    require(trained["specification"]["version"] in (2, 3, 4), "Corpus needs curated training")
    _, legacy = quality.qualification(config.root, trained["specification"])
    suite = spec["suite"]
    require(suite["trigger"] == legacy["trigger"], "Corpus trigger differs from training")
    cases = {case["id"]: case for case in suite["cases"]}
    for old in legacy["cases"]:
        case = cases.get(old["id"])
        if case is None or case["exposure"] != "legacy_diagnostic":
            raise ValueError("All legacy cases must remain declared diagnostics")
        require(
            all(case[key] == old[key] for key in CASE_FIELDS - {"kind", "seeds"})
            and case["seeds"][: len(old["seeds"])] == old["seeds"],
            "Legacy prompts, expectations and seeds must be preserved",
        )
    dataset_path, _ = file_ref(config.root, trained["specification"]["dataset"])
    dataset = load_dataset(config.root, dataset_path)
    captions = set()
    for sample in dataset["dataset"]["samples"]:
        caption_path, _ = file_ref(config.root, sample["caption"])
        captions.add(normalize(read_document(caption_path).decode("utf-8")))
    for case in suite["cases"]:
        require(
            normalize(case["prompt"]) not in captions
            and normalize(suite["trigger"] + " " + case["prompt"]) not in captions,
            "Corpus prompt repeats a training or validation caption",
        )
    return seal(
        {
            "version": 1,
            "scope": "frozen_evaluation_corpus",
            "specification": spec,
            "dataset_id": dataset["dataset_id"],
            "legacy_suite": legacy,
            "coverage": coverage,
            "limits": "Declared semantic coverage and exact caption exclusion; not a proof "
            "of perceptual independence, hidden holdouts or corpus sufficiency.",
        },
        "corpus_id",
    )


def freeze(config, path, *, save=False):
    with EvidenceReads().capture() as reads:
        value = _freeze(config, parse_json(read_document(path)))
    reads.verify()
    if save:
        publish(
            safe_path(config.root, f"state/evaluation/corpora/{value['corpus_id']}.json"), value
        )
    return value


def inspect(config, path):
    with EvidenceReads().capture() as reads:
        value = check_seal(parse_json(read_document(path)), "corpus_id")
        expected = _freeze(config, value["specification"])
        require(value == expected, "Frozen corpus coverage or bindings differ")
    reads.verify()
    return value


def _reference(config, path):
    return {
        "path": path.absolute().relative_to(config.root).as_posix(),
        "sha256": sha256(read_document(path)),
    }


def _baseline(config, corpus_path, evaluation_path, review):
    from itov import evaluation_runtime

    frozen = inspect(config, corpus_path)
    plan = evaluation_runtime.load_plan(evaluation_path)
    spec = plan["specification"]
    require(
        spec["version"] == 2
        and spec["mode"] == "baseline"
        and spec["corpus"] == _reference(config, corpus_path),
        "Baseline must use this frozen corpus in baseline mode",
    )
    report = evaluation_runtime.replay(config, evaluation_path)
    rows = report["matrix"]
    template = {
        "version": 1,
        "evaluation_report_id": report["report_id"],
        "reviewer": "",
        "reviewer_kind": "assistant",
        "method": "",
        "limitations": "",
        "observations": [
            {
                "index": row["index"],
                "case_id": row["case_id"],
                "seed": row["seed"],
                "role": row["role"],
                "prompt_adherence": None,
                "image_quality": None,
                "notes": "",
            }
            for row in rows
        ],
    }
    counts = {"pass": 0, "fail": 0, "uncertain": 0}
    if review is not None:
        object_fields(review, set(template), "baseline review")
        require(
            type(review["version"]) is int
            and review["version"] == 1
            and review["evaluation_report_id"] == report["report_id"],
            "Review binding differs",
        )
        require(review["reviewer_kind"] in ("human", "assistant"), "Invalid reviewer kind")
        for key in ("reviewer", "method", "limitations"):
            text(review[key], key)
        observations = array(review["observations"], "baseline observations")
        require(len(observations) == len(rows), "All baseline images require observations")
        for row, wanted in zip(observations, template["observations"], strict=True):
            object_fields(row, set(wanted), "baseline observation")
            require(
                all(
                    row[k] == wanted[k] and type(row[k]) is type(wanted[k])
                    for k in ("index", "case_id", "seed", "role")
                ),
                "Review coverage differs",
            )
            text(row["notes"], "observation notes")
            verdicts = [row[k] for k in ("prompt_adherence", "image_quality")]
            require(
                all(v in ("pass", "fail", "uncertain") for v in verdicts),
                "Pending or invalid observation",
            )
            counts[
                "fail" if "fail" in verdicts else "uncertain" if "uncertain" in verdicts else "pass"
            ] += 1
    value = seal(
        {
            "version": 1,
            "scope": "corpus_base_model_baseline",
            "status": "review_pending" if review is None else "observed",
            "corpus": _reference(config, corpus_path),
            "corpus_id": frozen["corpus_id"],
            "evaluation_plan": _reference(config, evaluation_path),
            "evaluation": report,
            "review": review,
            "outcomes": counts,
            "promotion_eligible": False,
            "limits": "Base/plain and base/trigger observations only. Trigger effects here "
            "are base-model effects. Adapter specificity/strengths and candidate acceptance "
            "remain unevaluated. Every failure and uncertain image remains in the corpus.",
        },
        "baseline_id",
    )
    return value, template


def baseline(config, path, evaluation_path, *, review_path=None, save=False):
    with EvidenceReads().capture() as reads:
        review = None if review_path is None else parse_json(read_document(review_path))
        value, template = _baseline(config, path, evaluation_path, review)
    reads.verify()
    if save:
        destination = safe_path(
            config.root, f"state/evaluation/baselines/{value['baseline_id']}.json"
        )
        publish(destination, value)
        _markdown(config, destination.with_suffix(".md"), value)
        if review is None:
            review_file = destination.with_suffix(".review.json")
            if not review_file.exists():
                publish(review_file, template)
    return value


def _markdown(config, destination, value):
    from itov.catalog_store import _atomic_write

    report = value["evaluation"]
    review = value["review"]
    observations = {} if review is None else {row["index"]: row for row in review["observations"]}
    cases = {case["id"]: case for case in report["suite"]["cases"]}
    lines = [
        "# Frozen corpus baseline",
        "",
        f"Baseline: `{value['baseline_id']}`",
        "",
        f"Status: **{value['status']}**. {value['limits']}",
        "",
    ]
    if review:
        lines += ["Method: " + review["method"], "", "Limitations: " + review["limitations"], ""]
    for row in report["matrix"]:
        case = cases[row["case_id"]]
        lines += [
            f"## {case['id']} / {row['seed']} / {row['role']}",
            "",
            row["prompt"],
            "",
            "Expected: " + case["expectation"],
            "",
        ]
        if row["index"] in observations:
            observed = observations[row["index"]]
            lines += [
                f"Prompt: **{observed['prompt_adherence']}**; image quality: "
                f"**{observed['image_quality']}**. {observed['notes']}",
                "",
            ]
        lines += [f"![{case['id']}]({(config.root / row['image']['path']).as_uri()})", ""]
    raw = ("\n".join(lines) + "\n").encode("utf-8")
    try:
        _atomic_write(destination, raw, exclusive=True)
    except FileExistsError:
        require(destination.read_bytes() == raw, "Existing baseline Markdown differs; preserve it")


def replay(config, path):
    with EvidenceReads().capture() as reads:
        value = check_seal(parse_json(read_document(path)), "baseline_id")
        corpus_path, _ = file_ref(config.root, value["corpus"])
        evaluation_path, _ = file_ref(config.root, value["evaluation_plan"])
        expected, _ = _baseline(config, corpus_path, evaluation_path, value["review"])
        require(value == expected, "Baseline observations or evidence differ")
    reads.verify()
    return value
