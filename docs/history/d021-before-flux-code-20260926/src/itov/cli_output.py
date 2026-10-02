"""Operator presentation only: never persist this metadata in sealed evidence."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

INCOMPLETE = frozenset(
    {
        "not_started",
        "incomplete",
        "inconclusive",
        "reserved",
        "prepared",
        "review_pending",
        "running",
        "validating",
        "submitting",
        "observing",
        "collecting",
        "submission_unknown",
        "timed_out",
        "detached",
        "paused",
        "abandoned",
        "held",
        "queued",
    }
)
FAILED = frozenset(
    {"failed", "validation_failed", "collection_failed", "artifact_invalid", "observation_failed"}
)


def outcome(result, *, exception=False, interrupted=False):
    if interrupted:
        return "interrupted", 130
    if exception:
        return "error", 2
    status = result.get("status", result.get("result", {}).get("status"))
    if (
        status == "rejected"
        or result.get("scope") == "promotion_refused"
        or result.get("admitted") is False
        or result.get("eligible") is False
    ):
        return "refused", 1
    if status in FAILED:
        return "failed", 1
    if status in INCOMPLETE or result.get("recovery_required"):
        return "incomplete", 1
    if any(result.get(key) is False for key in ("ok", "valid", "technical_pass")):
        return "failed", 1
    return "ok", 0


def _causes(result):
    causes = []

    def add(location, value):
        if value:
            causes.append({"location": location, "detail": value})

    for key in ("error", "failure_boundary", "blockers", "reasons", "server_error"):
        add(key, result.get(key))
    if result.get("error") or result.get("code"):
        add("details", result.get("details"))
    for key in ("result", "profile"):
        if isinstance(result.get(key), dict):
            causes.extend(
                {**cause, "location": key + "." + cause["location"]}
                for cause in _causes(result[key])
            )
    if result.get("document", {}).get("qualified") is False:
        add("document.qualified", "Required managed-worker execution overlap was not observed")
    for key in ("checks", "issues", "findings", "matrix", "images", "jobs", "members"):
        rows = result.get(key, [])
        if not isinstance(rows, list):
            continue
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                add(f"{key}[{i}]", row)
                continue
            if key == "issues" or row.get("status") in FAILED | {"fail", "rejected"}:
                add(f"{key}[{i}]", row)
            elif (
                row.get("error")
                or row.get("severity") == "error"
                or (key == "findings" and result.get("ok") is False)
            ):
                add(f"{key}[{i}]", row)
    validation = result.get("validation")
    if isinstance(validation, dict):
        add("validation.issues", validation.get("issues"))
    execution = result.get("execution")
    if isinstance(execution, dict) and result.get("status") == "failed":
        add("execution.status", execution.get("status"))
    return causes


def _artifacts(args, result):
    """Report references without opening files or claiming they exist/validate."""
    refs = _artifacts(args, result["result"]) if isinstance(result.get("result"), dict) else []
    root = Path(getattr(args, "config", "workspace/itov.toml")).absolute().parent

    def add(label, value, *, workspace=False):
        if isinstance(value, str) and value:
            path = Path(value)
            if workspace and not path.is_absolute():
                path = root / path
            ref = {"label": label, "path": str(path.absolute())}
            if ref not in refs:
                refs.append(ref)

    for key in ("config", "record_path", "saved_path", "path", "catalog", "directory"):
        add(key, result.get(key))
    add("evidence", result.get("evidence"))
    if getattr(args, "file", None):
        add("input document", str(args.file))
    if getattr(args, "artifact", None):
        add("verified artifact", str(args.artifact))
    artifacts = result.get("artifacts", {})
    if isinstance(artifacts, dict):
        for key, path in artifacts.items():
            add(key, path)
    elif isinstance(artifacts, list):
        for i, row in enumerate(artifacts):
            add(f"output {i + 1}", row.get("path"))
    for key in ("images", "matrix"):
        for i, row in enumerate(result.get(key, [])):
            add(f"{key} {i + 1}", row.get("image", {}).get("path"), workspace=True)
            add(f"{key} {i + 1} record", row.get("record_path"))
    for row in result.get("jobs", []) if isinstance(result.get("jobs"), list) else []:
        # Owned request ids originate in the dispatcher. Do not resolve untrusted paths.
        request = row.get("request_id", "")
        if re.fullmatch(r"[0-9a-f-]{36}", request):
            add("job record", f"state/jobs/{request}.json", workspace=True)
    if getattr(args, "save", False):
        folders = {
            "assessment_id": "training/assessments",
            "candidate_id": "training/candidates",
            "packet_id": "training/reviews",
            "report_id": f"{args.command}/reports",
        }
        # These commands return their sealed document directly, without a saved_path.
        identities = {
            ("evaluation", "assess"): "assessment_id",
            ("training", "candidate"): "candidate_id",
            ("evaluation", "packet"): "packet_id",
            ("evaluation", "replay"): "report_id",
            ("inference", "replay"): "report_id",
        }
        key = identities.get((args.command, getattr(args, "action", None)))
        if key and result.get(key):
            add("saved document", f"state/{folders[key]}/{result[key]}.json", workspace=True)
        if key == "candidate_id" and "entry" in result:
            add("candidate weights", result["entry"]["asset"]["path"], workspace=True)
        if key == "packet_id" and result.get(key):
            base = f"state/training/reviews/{result[key]}"
            add("review packet", base + ".md", workspace=True)
            add("pending review template", base + ".review.json", workspace=True)
    return refs


def _guidance(args, result, state):
    command, action = args.command, getattr(args, "action", None)
    source = str(getattr(args, "file", ""))
    config = str(getattr(args, "config", "workspace/itov.toml"))
    actions = []

    def suggest(label, *argv, when="After inspecting the result"):
        actions.append({"label": label, "argv": ["itov", *map(str, argv)], "when": when})

    def configured(label, *argv, when="After inspecting the result"):
        suggest(label, *argv, "--config", config, when=when)

    status = result.get("status")
    message = "Requested operation completed. Inspect its scope and limits."
    if state == "error":
        message = (
            "Correct the reported cause before retrying. Inspect durable state "
            "first if execution was attempted."
        )
    elif state in {"failed", "refused"}:
        message = (
            "Inspect the causes and retained evidence; this result does not meet "
            "the requested checks."
        )
    elif state in {"incomplete", "interrupted"}:
        message = (
            "Work is unfinished. Inspect ownership and resume observation; do not "
            "duplicate a submission."
        )

    if command == "arguments":
        suggest("Inspect command syntax", "--help")
    elif command == "init" and state == "ok":
        suggest("Check installation", "doctor", "--config", result["config"], "--offline")
        suggest(
            "Start the installed workflow",
            "workspace",
            "guide",
            "setup",
            "--config",
            result["config"],
        )
    elif command == "workspace":
        message = "Inspect recorded state and follow the owning command; no execution is automatic."
        actions.extend(result.get("actions", []))
        if action == "guide":
            message = (
                "Follow the displayed sequence; supply every named input before running its step."
            )
        elif action == "starter" and state == "ok":
            root = Path(config).absolute().parent
            configured(
                "Validate the starter against the server",
                "workflow",
                "validate",
                root / "workflows/itov-starter.api.json",
                "--live",
            )
            configured("Follow the image-copy sequence", "workspace", "guide", "generation")
        elif action == "request" and result.get("saved_path"):
            configured("Plan this pinned request", "batch", "plan", result["saved_path"], "--save")
        elif action == "dependencies":
            message = (
                "Inspect each package result; metadata does not qualify the GPU, runtime or model."
            )
        if action != "guide":
            configured("Choose a workflow", "workspace", "guide")
    elif command == "doctor":
        message = (
            "Inspect each diagnostic; start the configured server before live "
            "checks. Preflight does not establish rendering quality."
        )
        configured("Live diagnostics", "doctor")
    elif command == "job":
        record = result.get("record_path") or (source if action == "wait" else None)
        if record:
            configured(
                "Verify saved output" if state == "ok" else "Observe the same job",
                "job",
                "wait",
                record,
                when="Use this record; wait never submits a replacement workflow",
            )
        else:
            message += (
                " Inspect state/jobs in the configured workspace for a retained request record."
            )
        if status == "submission_unknown":
            message += (
                " Acceptance is unknown. Inspect server history; only a provenance- "
                "matched prompt id may be supplied to job wait --prompt-id."
            )
    elif command == "batch" and action == "cancel":
        message = (
            (
                "Cancellation requested. Keep the owning controller running, or resume this plan "
                "to observe accepted work and retire remaining picks. Seeds stay reserved."
            )
            if state == "ok"
            else message
        )
        configured("Observe and settle cancellation", "batch", "resume", source)
    elif command == "video" and action == "bind-source" and state == "ok":
        message = "Source job and image bytes are bound; prepare the saved specification next."
        if result.get("saved_path"):
            configured("Stage the bound video source", "video", "prepare", result["saved_path"])
    elif command == "inference" and action == "spec" and state == "ok":
        message = "Image request described; inspect its prompt and settings before planning."
        if result.get("saved_path"):
            configured(
                "Check the model and prepare this image",
                "inference",
                "prepare",
                result["saved_path"],
            )
        else:
            message += " Use --save to keep the specification."
    elif command == "av":
        if action == "spec" and state == "ok":
            message = "Sources and audio offset are bound. Inspect the specification before muxing."
            if result.get("saved_path"):
                configured("Compose the saved A/V specification", "av", "mux", result["saved_path"])
        elif state == "ok":
            message = "Decode and timing checks passed. Inspect full playback for media quality."
            configured("Reverify published A/V output", "av", "replay", source)
    elif command in {"batch", "inference", "evaluation"} and action in {
        "run",
        "resume",
        "status",
        "replay",
        "abandon",
    }:
        configured("Inspect plan state", command, "status", source)
        if state == "ok":
            if command in {"inference", "evaluation"}:
                configured(
                    "Verify and save technical evidence", command, "replay", source, "--save"
                )
                message = (
                    "Inspect all generated images against the declared cases. "
                    "Technical completion does not establish quality acceptance."
                )
            else:
                configured("Reverify collected artifacts", "batch", "resume", source)
        elif status == "not_started" and command != "batch":
            configured("Start the saved plan", command, "run", source)
        elif state == "incomplete" and status != "abandoned":
            configured(
                "Resume the owned plan",
                command,
                "resume",
                source,
                when="Accepted work is observed; only an unsubmitted remainder may be submitted",
            )
        if status == "abandoned":
            message = (
                "This plan is retired. Preserve its evidence; create a new "
                "specification and use new seeds."
            )
        elif state == "failed":
            message = (
                "Inspect failed records and artifacts. Resume can retry collection, "
                "but cannot rerun a terminal failed job. Abandon only after "
                "outcomes are known."
            )
    elif command == "dataset" and action in {"inspect", "freeze", "review-verify"}:
        refs = result.get("artifacts", {})
        if refs.get("review template"):
            configured(
                "Validate and freeze the review",
                "dataset",
                "freeze",
                refs["review template"],
                "--save",
                when="After inspecting every image/caption and disposing of flagged pairs",
            )
        elif action == "inspect" and state != "error":
            configured("Save inspection and pending review", "dataset", "inspect", source, "--save")
        if refs.get("freeze"):
            configured("Verify the frozen selection", "dataset", "review-verify", refs["freeze"])
            configured(
                "Prepare the reviewed selection",
                "dataset",
                "import",
                refs["import declaration"],
                "--source-root",
                str(Path(config).absolute().parent),
                when="Using the pinned Pillow image environment; this creates a new dataset",
            )
        elif action == "freeze" and state != "error":
            configured(
                "Recheck the explicit review",
                "dataset",
                "freeze",
                source,
                "--save",
                when="After resolving blockers or explicitly excluding unresolved samples",
            )
        if state != "error":
            message = (
                "Inspect all images, captions, identity warnings and pair findings. "
                "Similarity is a review aid; freezing does not accept model quality."
            )
    elif command == "dataset" and action in {"import", "status", "recover"}:
        refs = result.get("artifacts", {})
        operation = refs.get("operation") or (source if action != "import" else None)
        if operation:
            configured("Inspect the import", "dataset", "status", operation)
            if state != "ok" and status != "artifact_invalid":
                configured(
                    "Rebuild in a new retained attempt",
                    "dataset",
                    "recover",
                    operation,
                    when="With the original pinned inputs and image engine available",
                )
        if refs.get("prepared"):
            configured("Verify the committed dataset", "dataset", "verify", refs["prepared"])
        message = (
            "Inspect the retained attempt and causes. Recovery rebuilds in a new attempt; "
            "it reconciles the journal if publication already completed."
            if state != "ok"
            else "Dataset committed and verified. Use prepared.json and its SHA-256 in training "
            "inputs; inspect captions, splits and visual suitability before training."
        )
        if status == "artifact_invalid":
            message = "Published data failed verification. Preserve the bundle and investigate."
    elif command == "evaluation" and action in {
        "mapping",
        "mapping-inspect",
        "review-packet",
        "review-inspect",
        "decide",
        "decision-replay",
    }:
        message = "Loader evidence and complete matrix review do not activate a candidate."
        if result.get("scope") == "deployed_review_packet":
            message = (
                "Inspect every image and matched comparison, then fill the sibling "
                ".review.json including uncertainty."
            )
            if result.get("saved_path"):
                configured(
                    "Record candidate disposition",
                    "evaluation",
                    "decide",
                    result["saved_path"],
                    "--review",
                    str(Path(result["saved_path"]).with_suffix(".review.json")),
                    "--save",
                )
        if result.get("scope") == "deployed_candidate_decision":
            message = (
                "Recorded disposition: "
                + result["disposition"]
                + ". No candidate activation occurred."
            )
    elif command == "checks":
        message = "Artifact measurements and calibration retain uncertainty; no model is accepted."
        if result.get("scope") == "image_check_packet":
            message = (
                "Inspect all images and fill the sibling .reference.json. The .request.json "
                "and .response.json define the optional evaluator exchange."
            )
            if result.get("saved_path"):
                configured(
                    "Record calibration",
                    "checks",
                    "calibrate",
                    result["saved_path"],
                    "--reference",
                    str(Path(result["saved_path"]).with_suffix(".reference.json")),
                    "--save",
                )
    elif command == "corpus":
        message = "Frozen coverage and baseline observations do not establish candidate quality."
        if result.get("status") == "review_pending":
            message = "Inspect every baseline image, then fill the saved sibling .review.json."
            configured(
                "Record baseline observations",
                "corpus",
                "baseline",
                source,
                "--evaluation",
                str(getattr(args, "evaluation", "EVALUATION_PLAN")),
                "--review",
                "BASELINE.review.json",
                "--save",
            )
        elif result.get("baseline_id"):
            message = "Baseline observations retained, including failures and uncertainty."
        elif result.get("corpus_id"):
            message = "Coverage frozen. Plan a version-two baseline evaluation before tuning."
    elif command == "experiment":
        message = (
            "Inspect every declared checkpoint and repetition against the frozen cases. "
            "Loss does not select a checkpoint; selection does not authorize promotion."
        )
        if action in {"variance", "variance-replay"}:
            message = (
                "Numerical repetition measurements retain exact-equality failures separately "
                "from declared tolerances. Inspect each pair; no quality or causal conclusion "
                "follows."
            )
            if action == "variance" and result.get("saved_path"):
                configured(
                    "Replay numerical evidence",
                    "experiment",
                    "variance-replay",
                    source,
                    "--report",
                    result["saved_path"],
                )
        manifest = result.get("saved_path") if action == "plan" else source
        if action in {"plan", "run", "status"} and manifest:
            configured("Inspect experiment members", "experiment", "status", manifest)
        if action == "status" and status == "review_pending":
            configured("Save review packet", "experiment", "packet", source, "--save")
        if action == "packet" and result.get("saved_path"):
            configured(
                "Record checkpoint selection",
                "experiment",
                "decide",
                source,
                "--review",
                str(Path(result["saved_path"]).with_suffix(".review.json")),
                "--save",
                when="After completing all case verdicts and observations",
            )
        if action == "decide" and result.get("saved_path"):
            configured(
                "Replay decision evidence",
                "experiment",
                "replay",
                source,
                "--decision",
                result["saved_path"],
            )
    elif command == "training" and action == "checkpoints":
        message = (
            "Inspect each checkpoint status. Select an exact complete checkpoint for "
            "resume-plan; no worker started."
        )
        configured("Inspect continuation syntax", "training", "resume-plan", "--help")
    elif command == "training" and action == "resume-plan" and state == "ok":
        message = (
            "Continuation planned in a new attempt; the source attempt remains preserved. "
            "No worker started."
        )
        if result.get("saved_path"):
            configured("Inspect run syntax", "training", "run", "--help")
        else:
            configured(
                "Save continuation plan",
                "training",
                "resume-plan",
                source,
                "--checkpoint",
                str(args.checkpoint),
                "--save",
            )
    elif command == "training" and action in {"run", "status", "recover"}:
        configured("Inspect the training attempt", "training", "status", source)
        if state == "ok":
            configured("Assess technical evidence", "evaluation", "assess", source, "--save")
        elif status in {"running", "validating"} or state in {"error", "interrupted"}:
            configured(
                "Recover the stopped attempt",
                "training",
                "recover",
                source,
                when="After controller and worker exit are confirmed; recovery never retrains",
            )
        else:
            message = (
                "Inspect result.json and worker.log. Preserve the failed attempt; "
                "correct inputs and create a new plan."
            )
        if "checkpoints" in result.get("artifacts", {}):
            configured("Inspect retained checkpoints", "training", "checkpoints", source)
    elif (
        action == "plan"
        and command in {"batch", "inference", "evaluation", "training", "audio", "video"}
        and state == "ok"
    ):
        saved = result.get("saved_path") or result.get("path")
        message = "Planning only; no jobs submitted."
        if not saved:
            configured("Save the immutable plan", command, "plan", source, "--save")
        elif command in {"batch", "audio", "video"} or (
            command == "inference" and result.get("plan", {}).get("version") != 2
        ):
            configured("Qualify the saved plan", "batch", "qualify", saved, "--save")
        elif command == "training":
            message += (
                " Select the exact GPU UUID from nvidia-smi -L, then training run PLAN --gpu UUID."
            )
            configured("Inspect run syntax", "training", "run", "--help")
        else:
            configured("Run the saved plan", command, "run", saved)
    elif command == "batch" and action == "qualify" and state == "ok":
        if result.get("path"):
            configured(
                "Run the qualified plan", "batch", "run", source, "--qualification", result["path"]
            )
        else:
            configured("Save qualification", "batch", "qualify", source, "--save")
        message = "Preflight only; execution and media quality remain unverified."
    elif command in {"inference", "audio", "video"} and action == "prepare" and state == "ok":
        if result.get("catalog"):
            configured(
                "Import prepared catalog",
                "catalog",
                "import",
                result["catalog"],
                "--expected-head",
                result["expected_head"],
                when="After reviewing the catalog candidate",
            )
        configured(
            "Save an execution plan",
            command,
            "plan",
            source,
            "--save",
            when="After any required catalog import and server startup",
        )
    elif command == "evaluation" and action == "assess" and state == "ok":
        configured("Save candidate export", "training", "candidate", source, "--save")
        message = (
            "Technical assessment is separate from model quality. Inspect previews "
            "and evaluate the deployed candidate."
        )
    elif command == "training" and action == "candidate" and state == "ok":
        message = (
            "Use these exact candidate and export hashes in a version-two inference "
            "or evaluation specification. Candidate export does not activate it."
        )
        configured("Inspect supported inference capabilities", "inference", "capabilities")
    elif command == "evaluation" and action == "packet":
        message = (
            "Inspect every case and record an evidence-backed review. Pending "
            "templates are not approvals."
        )
        if not getattr(args, "save", False) and state == "ok":
            configured("Save packet and review template", "evaluation", "packet", source, "--save")
    elif command == "candidate":
        message = "Inspect current deployed evidence and the exact entry change before applying."
        if action in {"summary", "deployment"}:
            message = "Deployment validation is separate from activation eligibility."
        elif action in {"preview", "retirement", "rollback"}:
            message = "Preview only; the catalog has not changed."
            if result.get("eligible") and result.get("saved_path"):
                configured(
                    "Apply the reviewed entry change", "candidate", "apply", result["saved_path"]
                )
        elif action in {"apply", "recover", "status", "replay"}:
            message = "Historical lifecycle integrity does not revalidate current model quality."
            configured("Inspect catalog lifecycle", "candidate", "status")
            if result.get("recovery_required"):
                configured("Recover the lifecycle transaction", "candidate", "recover")
        if result.get("operation_id") and action == "apply":
            configured("Verify committed lineage", "candidate", "replay", result["operation_id"])
    elif command == "promotion":
        message = (
            "Training-only previews are historical evidence. Activation requires candidate "
            "preview with a complete deployed decision, then candidate apply."
        )
    elif command == "catalog":
        configured("Verify catalog and assets", "catalog", "verify", "--check-files")
        if result.get("recovery_required"):
            configured("Recover interrupted transaction", "catalog", "recover")
    elif command == "device":
        suggest("Inspect device ownership", "device", "status", "--gpu", args.gpu)
        if status == "held" and result.get("lease_id"):
            suggest(
                "Recover the exact lease",
                "device",
                "recover",
                "--gpu",
                args.gpu,
                "--lease",
                result["lease_id"],
                when="Only after owner exit and positive terminal request or worker evidence",
            )
        message = (
            "Inspect cooperative ownership. An idle registry is not proof that "
            "unrelated GPU clients are absent."
        )
    elif command == "parallel":
        configured("Observe owned workers", "parallel", "resume", source)
        if state != "ok":
            configured(
                "Retire stopped workers",
                "parallel",
                "recover",
                source,
                when="Only after owned workers are confirmed dead; uncertain seeds remain reserved",
            )
    elif command == "vram" and action == "capture":
        configured("Inspect captured batch state", "batch", "status", source)
        message = (
            "Inspect the profile and batch records. Incomplete cold/warm capture is not usable "
            "admission evidence; resume observation before planning another capture."
        )
    elif command == "vram" and action == "check":
        message = "Inspect every admission reason and workload estimate before execution."
    if not actions:
        suggest("Inspect command options", command, *([action] if action else []), "--help")
    if command in {"job", "batch", "training", "evaluation", "candidate", "catalog"}:
        configured("Navigate this workspace", "workspace", "guide")
    return message, actions


def _text(result, meta):
    lines = [f"{meta['outcome'].upper()} {' '.join(meta['command'])} (exit {meta['exit_code']})"]
    details = result.get("decision", result.get("plan", result.get("qualification", result)))
    if result.get("scope", "").startswith("candidate_"):
        details = result
    for key in (
        "status",
        "scope",
        "operation_id",
        "summary_id",
        "diagnostic_id",
        "identity",
        "interpreter",
        "entry_id",
        "action",
        "catalog_head",
        "disposition",
        "eligible",
        "activation_eligible",
        "plan_id",
        "experiment_id",
        "corpus_id",
        "baseline_id",
        "calibration_id",
        "evaluator_status",
        "selected_endpoint",
        "dataset_id",
        "import_id",
        "inspection_id",
        "freeze_id",
        "review_id",
        "candidate_id",
        "assessment_id",
        "packet_id",
        "report_id",
        "decision_id",
        "request_id",
        "prompt_id",
        "head",
        "expected_head",
        "capability",
        "recorded_status",
        "worker_completion",
        "artifact_validation",
        "quality_acceptance",
        "purpose",
        "recovery",
        "preset_id",
        "admitted",
        "samples",
        "sample_rate",
        "channels",
        "frames",
        "width",
        "height",
        "duration_ms",
        "sha256",
        "lease_id",
        "kind",
        "gpu_uuid",
        "technical_pass",
        "candidate_assessment",
        "code",
        "index",
    ):
        if key in details and not (
            key == "samples" and isinstance(details[key], list) and is_dataset_inspection(result)
        ):
            lines.append(f"{key.replace('_', ' ').capitalize()}: {details[key]}")
    if "entry" in result:
        lines.append(f"Candidate weights: {result['entry']['asset']['path']}")
        lines.append(f"Export SHA-256: {result['entry']['asset']['sha256']}")
    if "adapter_order" in result:
        lines.append("Adapter order: " + " -> ".join(result["adapter_order"]))
    if result.get("scope") == "frozen_evaluation_corpus":
        coverage = result["coverage"]
        lines.append(
            f"Coverage: {coverage['case_seed_pairs']} case/seed pairs; "
            f"{coverage['baseline_images']} baseline images; "
            f"{coverage['comparison_images']} comparison images"
        )
    if result.get("scope") == "image_check_packet":
        lines.append(f"Measured images: {len(result['measurements'])}")
        lines.append("Semantic quality: unavailable from artifact measurements")
    if result.get("scope") == "deployed_loader_mapping":
        lines.append(f"Mapped targets: {len(result['mapping']['rows'])}")
        lines.append("Loader registration verified; image quality is separate")
    if result.get("scope") == "deployed_review_packet":
        lines.append(
            f"Images: {len(result['evaluation']['matrix'])}; comparisons: {len(result['groups'])}"
        )
        lines.append("Quality review pending")
    if result.get("scope") in {
        "deployed_candidate_decision",
        "candidate_summary",
        "candidate_deployment_validation",
    }:
        lines.append(
            "Required judgments: " + json.dumps(result["required_judgments"], sort_keys=True)
        )
        if "promotion_eligible" in result:
            lines.append(f"Promotion eligible: {result['promotion_eligible']}")
    if result.get("scope") == "workspace_guide":
        lines.append(result["description"])
        for index, step in enumerate(result["steps"], 1):
            lines.append(f"{index}. {step['label']}: {step['when']}")
            if step["needs"]:
                lines.append("   Supply: " + ", ".join(step["needs"]))
            lines.append(
                "   & " + " ".join("'" + arg.replace("'", "''") + "'" for arg in step["argv"])
            )
    if result.get("scope") == "workspace_inventory":
        lines.append(
            f"Saved artifacts: {result['total']}; page offset {result['offset']}; "
            f"more: {result['more']}"
        )
        lines.append("Catalog: " + json.dumps(result["catalog"], sort_keys=True))
        for row in result["entries"]:
            lines.append(f"  {row['kind']}: {row['recorded_status']} {row['path']}")
    if result.get("scope") == "workspace_inspection":
        lines.append("Document integrity: " + result["integrity"])
        lines.append("Related: " + json.dumps(result["related"], sort_keys=True))
    if result.get("scope") == "candidate_lifecycle_status":
        lines.append(f"Lifecycle operations: {len(result['operations'])}")
        lines.append(f"Recovery required: {result['recovery_required']}")
        for entry in result["entries"]:
            lines.append(f"  {entry['id']}: {entry['status']}; strength {entry['strength_milli']}")
        lines.append(result["quality"])
    if result.get("scope") == "candidate_lifecycle_preview":
        lines.append("Entry before: " + json.dumps(result["before"], ensure_ascii=False))
        lines.append("Entry after: " + json.dumps(result["after"], ensure_ascii=False))
    if result.get("scope") == "image_check_calibration":
        for criterion, row in result["summary"].items():
            lines.append(
                f"{criterion}: {row['examples']} images; false accepts {row['false_accepts']}; "
                f"false rejects {row['false_rejects']}; predictions uncertain "
                f"{row['prediction_uncertain']}, unavailable {row['prediction_unavailable']}; "
                f"reference uncertain {row['reference_uncertain']}, unavailable "
                f"{row['reference_unavailable']}"
            )
        lines.append("Promotion eligible: False")
    if result.get("scope") == "corpus_base_model_baseline":
        lines.append("Baseline image outcomes: " + json.dumps(result["outcomes"], sort_keys=True))
        lines.append("Promotion eligible: False")
    if result.get("scope", "").startswith("experiment_"):
        for key in ("budget", "allocated"):
            if key in result:
                lines.append(key.capitalize() + ": " + json.dumps(result[key], sort_keys=True))
        for row in result.get("members", []):
            lines.append(
                f"Member {row['id']}: " + str(row.get("disposition", row.get("status", "planned")))
            )
    for key in ("owner", "worker", "controller"):
        if key in result:
            lines.append(f"{key.capitalize()}: " + json.dumps(result[key], ensure_ascii=True))
    if isinstance(result.get("document"), dict):
        for key in ("qualified", "overlap_ns", "limits"):
            if key in result["document"]:
                lines.append(f"{key}: {result['document'][key]}")
    for estimate in result.get("estimates", []):
        lines.append("Workload: " + json.dumps(estimate, ensure_ascii=True))
    if "train" in result.get("counts", {}):
        lines.append(
            f"Dataset: {result['counts']['train']} training, "
            f"{result['counts']['validation']} held-out"
        )
    if "completed_images" in result:
        lines.append(f"Progress: {result['completed_images']}/{result['total']} images prepared")
    if is_dataset_inspection(result):
        lines.append(
            f"Review pool: {len(result['samples'])} samples, "
            f"{result['counts']['pairs']} pairs, {result['counts']['flagged_pairs']} flagged"
        )
        lines.append(f"Unresolved identities: {result['counts']['unresolved_samples']}")
    for row in result.get("checks", []):
        lines.append(f"{row['status'].upper()} {row['name']}: {row['detail']}")
    for row in result.get("findings", []):
        if row.get("severity") != "error" and result.get("ok") is not False:
            lines.append("Finding: " + json.dumps(row, ensure_ascii=True))
    observed = result.get("result", result)
    rows = observed.get("matrix", observed.get("images", observed.get("jobs", [])))
    if isinstance(rows, list) and rows:
        completed = observed.get("succeeded")
        if completed is None and all("status" in row for row in rows):
            completed = sum(row["status"] == "succeeded" for row in rows)
        if completed is not None:
            lines.append(f"Progress: {completed}/{len(rows)} completed")
        for i, row in enumerate(rows):
            label = " ".join(
                str(row[k])
                for k in ("case_id", "role", "seed", "request_id", "prompt_id")
                if row.get(k) is not None
            )
            lines.append(f"  {i + 1}: {row.get('status', 'planned')} {label}")
    if isinstance(result.get("plan", {}).get("jobs"), list):
        lines.append(f"Planned {len(result['plan']['jobs'])} jobs")
    for cause in meta["causes"]:
        detail = cause["detail"]
        text = detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=True)
        lines.append(f"Cause ({cause['location']}): {text}")
    for artifact in meta["artifacts"]:
        lines.append(f"Artifact ({artifact['label']}): {artifact['path']}")
    if result.get("limits"):
        lines.append(f"Limits: {result['limits']}")
    lines.append(f"Next: {meta['next_action']}")
    for action in meta["actions"]:
        # PowerShell literal quoting; argv remains the shell-independent authority.
        rendered = " ".join("'" + arg.replace("'", "''") + "'" for arg in action["argv"])
        lines.extend([f"  {action['label']} ({action['when']}):", f"  & {rendered}"])
    return "\n".join(lines)


def is_dataset_inspection(result):
    return result.get("scope") == "dataset_duplicate_identity_caption_observations"


def present(args, result, *, exception=False, interrupted=False):
    state, code = outcome(result, exception=exception, interrupted=interrupted)
    message, actions = _guidance(args, result, state)
    meta = {
        "version": 1,
        "command": [args.command, *([args.action] if getattr(args, "action", None) else [])],
        "outcome": state,
        "exit_code": code,
        "next_action": message,
        "actions": actions,
        "artifacts": _artifacts(args, result),
        "causes": _causes(result),
    }
    if getattr(args, "json", False):
        print(json.dumps({**result, "_cli": meta}, indent=2, ensure_ascii=True, allow_nan=False))
    else:
        print(_text(result, meta), file=sys.stderr if exception or interrupted else sys.stdout)
    return code
