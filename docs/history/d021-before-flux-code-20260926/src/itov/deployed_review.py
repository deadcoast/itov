"""Complete deployed comparisons and conservative, evidence-bound quality decisions."""

from copy import deepcopy
from html import escape
from urllib.parse import quote

from itov import deployed_loader, evaluation_runtime
from itov.catalog import array, canonical_bytes, object_fields, require, text
from itov.catalog_store import _atomic_write
from itov.comfyui import parse_json
from itov.evidence_reads import EvidenceReads, read_document
from itov.qualification import safe_path
from itov.training_data import check_seal, file_ref, publish, seal

IMAGE_RUBRICS = {
    "prompt_adherence": "Requested objects, count, attributes, material, layout and domain "
    "are visible; unobservable details are uncertain.",
    "image_quality": "Usable coherent image without malformed objects, unintended panels, "
    "frames, repeated scenes or severe artifacts.",
}
PAIR_RUBRICS = {
    "activation_specificity": "Intended adapter style is visibly supported with the trigger "
    "and meaningfully more specific than without it; difference alone is insufficient.",
    "preservation": "Matched base comparisons show no adapter-induced content/quality "
    "regression, including unrelated prompts. Existing base failures are recorded separately.",
    "usable_strength": "Both adapter conditions at this strength remain usable and satisfy "
    "the case expectation.",
}
POLICY = {
    "failure": "Any failing adapter-image or pair criterion rejects the candidate for this "
    "complete matrix.",
    "uncertainty": "Absent failures, any uncertain/unavailable required judgment makes the "
    "decision inconclusive.",
    "acceptance": "All adapter-image and pair criteria must pass. Base judgments are recorded "
    "as comparison evidence, not candidate gates.",
    "promotion": "No catalog mutation or production eligibility; candidate lifecycle is separate.",
}
VERDICTS = ("pass", "fail", "uncertain", "unavailable")


def _binding(row):
    return {
        "index": row["index"],
        "image_sha256": row["image"]["sha256"],
        "rgb_sha256": row["decoded"]["decoded_rgb_sha256"],
    }


def groups(report):
    result = []
    rows = report["matrix"]
    for case in report["suite"]["cases"]:
        for seed in case["seeds"]:
            for strength in report["strengths_milli"]:
                matching = [
                    r
                    for r in rows
                    if r["case_id"] == case["id"]
                    and r["seed"] == seed
                    and (r["role"].startswith("base_") or r["strength_milli"] == strength)
                ]
                require(
                    len(matching) == 4
                    and {r["role"] for r in matching}
                    == {"base_plain", "base_trigger", "adapter_plain", "adapter_trigger"},
                    "Incomplete comparison group",
                )
                result.append(
                    {
                        "case_id": case["id"],
                        "seed": seed,
                        "strength_milli": strength,
                        "images": {r["role"]: _binding(r) for r in matching},
                    }
                )
    return result


def _packet(config, path, mapping_path):
    report = evaluation_runtime.replay(config, path)
    require(
        report.get("mode") == "comparison" and report["suite"]["version"] == 2,
        "Deployed review requires a complete corpus comparison",
    )
    mapping = deployed_loader.inspect(config, mapping_path)
    require(
        mapping["plan_id"] == report["plan_id"]
        and mapping["candidate_id"] == report["candidate"]["candidate_id"],
        "Loader mapping belongs to a different candidate/plan",
    )
    return seal(
        {
            "version": 1,
            "scope": "deployed_review_packet",
            "evaluation_plan": deployed_loader.reference(config, path),
            "mapping": deployed_loader.reference(config, mapping_path),
            "mapping_id": mapping["mapping_id"],
            "evaluation": report,
            "groups": groups(report),
            "image_rubrics": IMAGE_RUBRICS,
            "pair_rubrics": PAIR_RUBRICS,
            "policy": POLICY,
            "limits": "Exposed fixed cases, not an independent blind holdout or "
            "sampler-parity experiment. Review assertions require method and uncertainty; "
            "hashes are not signatures.",
        },
        "packet_id",
    )


def template(packet):
    def pending(rubrics):
        return {k: {"verdict": None, "notes": "", "uncertainty": ""} for k in rubrics}

    return {
        "version": 1,
        "packet_id": packet["packet_id"],
        "reviewer": "",
        "reviewer_kind": "assistant",
        "method": "",
        "limitations": "",
        "sources": [],
        "observations": [
            {**_binding(row), "judgments": pending(IMAGE_RUBRICS)}
            for row in packet["evaluation"]["matrix"]
        ],
        "comparisons": [
            {**deepcopy(group), "judgments": pending(PAIR_RUBRICS)} for group in packet["groups"]
        ],
    }


def _destination(config, folder, identity):
    return safe_path(config.root, f"state/evaluation/{folder}/{identity}.json")


def _markdown(value):
    lines = [
        "# Deployed comparison review",
        "",
        f"Packet: `{value['packet_id']}`",
        "",
        "Review every image and matched strength comparison in the sibling review JSON. "
        "Technical success does not establish quality or authorize promotion.",
        "",
    ]
    for case in value["evaluation"]["suite"]["cases"]:
        lines += [
            "## " + case["id"],
            "",
            "Prompt: " + escape(case["prompt"]),
            "",
            "Expected: " + escape(case["expectation"]),
            "",
        ]
        for seed in case["seeds"]:
            lines += [
                f"### Seed {seed}",
                "",
                "| Strength | Plain | Trigger |",
                "| --- | --- | --- |",
            ]
            rows = [
                r
                for r in value["evaluation"]["matrix"]
                if r["case_id"] == case["id"] and r["seed"] == seed
            ]
            for strength in [0, *value["evaluation"]["strengths_milli"]]:
                pair = [r for r in rows if r["strength_milli"] == strength]
                require(len(pair) == 2, "Incomplete Markdown comparison")
                pictures = [
                    f"{r['index']} / {r['role']}<br>"
                    f"![image](../../../{quote(r['image']['path'], safe='/')})"
                    for r in pair
                ]
                lines.append(f"| {strength} milli | " + " | ".join(pictures) + " |")
            lines.append("")
    return ("\n".join(lines) + "\n").encode("utf-8")


def packet(config, path, mapping_path, *, save=False):
    with EvidenceReads().capture() as reads:
        value = _packet(config, path, mapping_path)
    reads.verify()
    if save:
        destination = _destination(config, "review-packets", value["packet_id"])
        publish(destination, value)
        markdown = destination.with_suffix(".md")
        raw = _markdown(value)
        try:
            _atomic_write(markdown, raw, exclusive=True)
        except FileExistsError:
            require(markdown.read_bytes() == raw, "Existing review Markdown differs; preserve it")
        review_path = destination.with_suffix(".review.json")
        if not review_path.exists():
            publish(review_path, template(value))
    return value


def _read_packet(config, path):
    value = check_seal(parse_json(read_document(path)), "packet_id")
    require(value.get("scope") == "deployed_review_packet", "Expected deployed review packet")
    expected = _packet(
        config,
        file_ref(config.root, value["evaluation_plan"])[0],
        file_ref(config.root, value["mapping"])[0],
    )
    require(
        canonical_bytes(value) == canonical_bytes(expected), "Review packet or evidence differs"
    )
    return value


def inspect(config, path):
    with EvidenceReads().capture() as reads:
        value = _read_packet(config, path)
    reads.verify()
    return value


def _judgments(value, rubrics):
    object_fields(value, set(rubrics), "review criteria")
    for judgment in value.values():
        object_fields(judgment, {"verdict", "notes", "uncertainty"}, "review judgment")
        require(judgment["verdict"] in VERDICTS, "Pending or invalid review judgment")
        text(judgment["notes"], "review notes")
        text(judgment["uncertainty"], "review uncertainty")


def validate_review(config, value, packet):
    object_fields(
        value,
        {
            "version",
            "packet_id",
            "reviewer",
            "reviewer_kind",
            "method",
            "limitations",
            "sources",
            "observations",
            "comparisons",
        },
        "deployed review",
    )
    require(
        type(value["version"]) is int
        and value["version"] == 1
        and value["packet_id"] == packet["packet_id"],
        "Review packet binding differs",
    )
    require(value["reviewer_kind"] in ("assistant", "human"), "Invalid reviewer kind")
    for key in ("reviewer", "method", "limitations"):
        text(value[key], key)
    sources = array(value["sources"], "review sources")
    require(len(sources) <= 64, "Too many review sources")
    for source in sources:
        file_ref(config.root, source, maximum=32 * 1024**2)
    for name, bindings, rubrics in (
        ("observations", [_binding(r) for r in packet["evaluation"]["matrix"]], IMAGE_RUBRICS),
        ("comparisons", packet["groups"], PAIR_RUBRICS),
    ):
        rows = array(value[name], name)
        require(len(rows) == len(bindings), "Incomplete review coverage")
        for row, binding in zip(rows, bindings, strict=True):
            object_fields(row, {*binding, "judgments"}, "review row")
            require(
                canonical_bytes({k: row[k] for k in binding}) == canonical_bytes(binding),
                "Review image/comparison binding differs",
            )
            _judgments(row["judgments"], rubrics)
    return value


def _counts(values):
    return {verdict: values.count(verdict) for verdict in VERDICTS}


def _decide(config, path, review_path):
    packet = _read_packet(config, path)
    review = validate_review(config, parse_json(read_document(review_path)), packet)
    rows = packet["evaluation"]["matrix"]
    required = [
        j["verdict"]
        for row, observation in zip(rows, review["observations"], strict=True)
        if row["role"].startswith("adapter_")
        for j in observation["judgments"].values()
    ]
    required += [j["verdict"] for row in review["comparisons"] for j in row["judgments"].values()]
    verdict = (
        "rejected"
        if "fail" in required
        else ("inconclusive" if any(v != "pass" for v in required) else "accepted_for_matrix")
    )
    summary = {}
    for case in packet["evaluation"]["suite"]["cases"]:
        summary[case["id"]] = {
            "images": {
                key: _counts(
                    [
                        o["judgments"][key]["verdict"]
                        for row, o in zip(rows, review["observations"], strict=True)
                        if row["case_id"] == case["id"]
                    ]
                )
                for key in IMAGE_RUBRICS
            },
            "comparisons": {
                key: _counts(
                    [
                        r["judgments"][key]["verdict"]
                        for r in review["comparisons"]
                        if r["case_id"] == case["id"]
                    ]
                )
                for key in PAIR_RUBRICS
            },
        }
    return seal(
        {
            "version": 1,
            "scope": "deployed_candidate_decision",
            "packet": deployed_loader.reference(config, path),
            "packet_id": packet["packet_id"],
            "review": deployed_loader.reference(config, review_path),
            "candidate_id": packet["evaluation"]["candidate"]["candidate_id"],
            "plan_id": packet["evaluation"]["plan_id"],
            "mapping_id": packet["mapping_id"],
            "technical_report_id": packet["evaluation"]["report_id"],
            "technical_pass": True,
            "disposition": verdict,
            "required_judgments": _counts(required),
            "by_case": summary,
            "observations": review["observations"],
            "comparisons": review["comparisons"],
            "review_metadata": {
                k: v for k, v in review.items() if k not in {"observations", "comparisons"}
            },
            "policy": POLICY,
            "promotion_eligible": False,
            "limits": packet["limits"],
        },
        "decision_id",
    )


def decide(config, path, review_path, *, save=False):
    with EvidenceReads().capture() as reads:
        value = _decide(config, path, review_path)
    reads.verify()
    if save:
        publish(_destination(config, "decisions", value["decision_id"]), value)
    return value


def replay(config, path):
    with EvidenceReads().capture() as reads:
        value = check_seal(parse_json(read_document(path)), "decision_id")
        require(value.get("scope") == "deployed_candidate_decision", "Expected deployed decision")
        expected = _decide(
            config,
            file_ref(config.root, value["packet"])[0],
            file_ref(config.root, value["review"])[0],
        )
        require(canonical_bytes(value) == canonical_bytes(expected), "Decision or evidence differs")
    reads.verify()
    return value
