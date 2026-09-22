"""Preregistered four-condition evaluation and evidence-backed review packets."""

from __future__ import annotations

from itov.catalog import (
    array,
    canonical_bytes,
    identifier,
    integer,
    object_fields,
    read_document,
    require,
    sha256,
    text,
)
from itov.comfyui import parse_json
from itov.linting import contains, normalize
from itov.qualification import safe_path
from itov.training_data import check_seal, file_ref, load_dataset, publish, seal

ROLES = ("base_plain", "base_trigger", "adapter_plain", "adapter_trigger")
CASE_CRITERIA = {"activation", "prompt_adherence", "image_quality", "regression"}


def suite(root, path, dataset, trigger):
    value = parse_json(read_document(path))
    object_fields(value, {"version", "id", "trigger", "cases"}, "quality suite")
    require(type(value["version"]) is int and value["version"] == 1, "Unsupported suite version")
    identifier(value["id"], "suite id")
    require(value["trigger"] == trigger, "Suite trigger differs")
    cases = array(value["cases"], "quality cases")
    require(2 <= len(cases) <= 4, "Quality suite requires 2..4 cases")
    training_captions = {
        normalize((root / sample["caption"]["path"]).read_text(encoding="utf-8"))
        for sample in dataset["dataset"]["samples"]
        if sample["split"] == "train"
    }
    seen, prompts, kinds = set(), set(), set()
    for case in cases:
        object_fields(
            case,
            {"id", "kind", "prompt", "negative_prompt", "expectation", "seeds"},
            "quality case",
        )
        key = identifier(case["id"], "case id")
        require(key not in seen, "Repeated quality case")
        seen.add(key)
        require(case["kind"] in ("holdout", "regression"), "Invalid quality case kind")
        kinds.add(case["kind"])
        prompt = text(case["prompt"], "quality prompt")
        require(
            len(prompt) <= 2048 and not contains(prompt, trigger),
            "Quality prompt must omit the trigger",
        )
        normalized = normalize(prompt)
        require(normalized not in prompts, "Repeated quality prompt")
        prompts.add(normalized)
        require(
            normalized not in training_captions
            and normalize(f"{trigger} {prompt}") not in training_captions,
            "Quality prompt repeats a training caption",
        )
        require(
            isinstance(case["negative_prompt"], str)
            and len(case["negative_prompt"]) <= 2048
            and not contains(case["negative_prompt"], trigger),
            "Invalid negative prompt",
        )
        text(case["expectation"], "quality expectation")
        seeds = array(case["seeds"], "quality seeds")
        require(len(seeds) == 2, "Each quality case requires two fixed seeds")
        for seed in seeds:
            integer(seed, "quality seed")
            require(seed < 2**32, "Quality seed out of range")
        require(len(set(seeds)) == 2, "Repeated quality seed")
    require(kinds == {"holdout", "regression"}, "Both held-out and regression cases are required")
    return value


def qualification(root, spec):
    from itov import curation

    object_fields(spec["qualification"], {"curation", "suite"}, "training qualification")
    dataset_path, _ = file_ref(root, spec["dataset"])
    dataset = load_dataset(root, dataset_path)
    curation_path, _ = file_ref(root, spec["qualification"]["curation"], maximum=32 * 1024**2)
    report = curation.validate(root, curation_path)
    require(report["dataset_id"] == dataset["dataset_id"], "Curation dataset differs")
    suite_path, _ = file_ref(root, spec["qualification"]["suite"], maximum=32 * 1024**2)
    return report, suite(root, suite_path, dataset, spec["trigger"])


def expected(suite_value):
    return [
        {
            "case_id": case["id"],
            "seed": seed,
            "role": role,
            "prompt": ((suite_value["trigger"] + " ") if role.endswith("trigger") else "")
            + case["prompt"],
            "negative_prompt": case["negative_prompt"],
        }
        for case in suite_value["cases"]
        for seed in case["seeds"]
        for role in ROLES
    ]


def validate_matrix(root, spec, result, folder):
    _, suite_value = qualification(root, spec)
    rows = array(result.get("quality_matrix"), "quality matrix")
    wanted = expected(suite_value)
    require(len(rows) == len(wanted), "Incomplete quality matrix")
    paths = set()
    for row, prescribed in zip(rows, wanted, strict=True):
        object_fields(row, {*prescribed, "image"}, "quality image")
        require({k: row[k] for k in prescribed} == prescribed, "Quality matrix binding differs")
        file_ref(folder, row["image"], maximum=32 * 1024**2)
        key = row["image"]["path"].casefold()
        require(key not in paths, "Quality matrix reuses an image path")
        paths.add(key)
    return rows


def packet(config, plan_path, *, save=False):
    from itov import evaluation, training

    plan = training.load_plan(plan_path)
    require(plan["specification"]["version"] == 2, "Review packet requires curated training v2")
    report = evaluation.assess(config, plan_path)
    candidate = evaluation.candidate(config, plan_path)
    curated, suite_value = qualification(config.root, plan["specification"])
    folder = training.run_folder(config, plan)
    result = check_seal(parse_json(read_document(folder / "result.json")), "result_id")
    rows = validate_matrix(config.root, plan["specification"], result, folder)
    images = [
        {
            **row,
            "image": {
                **row["image"],
                "path": (folder / row["image"]["path"]).relative_to(config.root).as_posix(),
            },
        }
        for row in rows
    ]
    value = seal(
        {
            "version": 2,
            "scope": "quality_review_pending",
            "plan_id": plan["plan_id"],
            "assessment_id": report["assessment_id"],
            "candidate_id": candidate["candidate_id"],
            "curation_id": curated["curation_id"],
            "curator": curated["document"]["curator"],
            "suite": suite_value,
            "images": images,
            "limits": "Complete fixed-seed Diffusers comparisons, not a quality verdict. "
            "Human or assistant review must state its method and limitations; reviewer "
            "identity alone is not quality evidence. Labels disclose conditions; runtime "
            "compatibility evidence is also required.",
        },
        "packet_id",
    )
    if save:
        destination = safe_path(config.root, f"state/training/reviews/{value['packet_id']}.json")
        publish(destination, value)
        # Markdown is an inspectable static report, never an automatically approving review.
        lines = [
            "# Quality review",
            "",
            f"Packet: `{value['packet_id']}`",
            "",
            "Decision: **PENDING**. Inspect every condition and both seeds. Compare target "
            "appearance, prompt compliance and unintended changes. Record failures; do not "
            "use training loss or changed pixels as quality acceptance.",
            "",
        ]
        for case in suite_value["cases"]:
            lines += [
                f"## {case['id']} ({case['kind']})",
                "",
                case["prompt"],
                "",
                "Expected: " + case["expectation"],
                "",
            ]
            for row in images:
                if row["case_id"] == case["id"]:
                    uri = (config.root / row["image"]["path"]).as_uri()
                    lines += [f"### Seed {row['seed']} / {row['role']}", "", f"![image]({uri})", ""]
        from itov.catalog_store import _atomic_write

        raw = ("\n".join(lines) + "\n").encode("utf-8")
        md = destination.with_suffix(".md")
        try:
            _atomic_write(md, raw, exclusive=True)
        except FileExistsError:
            require(md.read_bytes() == raw, "Existing review packet differs; preserve it")
        template = {
            "version": 3,
            "assessment_id": value["assessment_id"],
            "candidate_id": value["candidate_id"],
            "reviewer": "",
            "reviewer_kind": "assistant",
            "method": "",
            "limitations": "",
            "decision": "pending",
            "packet": {
                "path": destination.relative_to(config.root).as_posix(),
                "sha256": sha256(destination.read_bytes()),
            },
            "checks": [
                {"criterion": key, "passed": None, "evidence": []}
                for key in sorted(evaluation.CRITERIA)
            ],
            "cases": [
                {
                    "case_id": case["id"],
                    "seed": seed,
                    "verdicts": {key: None for key in sorted(CASE_CRITERIA)},
                    "notes": "",
                }
                for case in suite_value["cases"]
                for seed in case["seeds"]
            ],
            "notes": "Pending. Supply your own observations and hashed runtime evidence. "
            "This template cannot authorize promotion.",
        }
        try:
            _atomic_write(
                destination.with_suffix(".review.json"),
                canonical_bytes(template) + b"\n",
                exclusive=True,
            )
        except FileExistsError:
            pass  # Preserve the reviewer's edits; this file is not part of the immutable packet.
    return value


def review_coverage(config, plan_path, value):
    current = packet(config, plan_path)
    packet_path, _ = file_ref(config.root, value["packet"], maximum=32 * 1024**2)
    require(
        parse_json(read_document(packet_path)) == current, "Review packet is stale or incomplete"
    )
    if value["version"] == 2:
        # Historical v2 attestations retain their declared meaning. New v3 reviews
        # implement the user's removal of the mandatory independent-human gate.
        require(
            value["reviewer_kind"] == "human" and value["independent_of_training"] is True,
            "Legacy v2 attestation is invalid; use v3 for evidence-backed assistant review",
        )
        require(
            value["reviewer"].strip().casefold() != current["curator"].strip().casefold(),
            "Legacy v2 independence declaration conflicts with curator identity",
        )
    else:
        require(value["reviewer_kind"] in ("assistant", "human"), "Unsupported reviewer kind")
        for key in ("method", "limitations"):
            text(value[key], "review " + key)
            require(len(value[key]) <= 4096, "Review method/limitations exceed supported bounds")
    wanted = [(c["id"], s) for c in current["suite"]["cases"] for s in c["seeds"]]
    rows = array(value["cases"], "case reviews")
    observed = []
    for row in rows:
        object_fields(row, {"case_id", "seed", "verdicts", "notes"}, "case review")
        identifier(row["case_id"], "reviewed case")
        integer(row["seed"], "reviewed seed")
        observed.append((row["case_id"], row["seed"]))
        object_fields(row["verdicts"], CASE_CRITERIA, "case verdicts")
        require(
            all(type(v) is bool for v in row["verdicts"].values()),
            "Every case criterion needs a boolean verdict",
        )
        text(row["notes"], "case review notes")
    require(
        sorted(observed) == sorted(wanted), "Review must cover every case and seed exactly once"
    )
    return all(all(row["verdicts"].values()) for row in rows)
