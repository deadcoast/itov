"""Candidate integrity, evidence-backed evaluation, and reviewed catalog promotion."""

from __future__ import annotations

import struct

from itov import training_results
from itov.assessment_context import assessment_context
from itov.catalog import (
    canonical_bytes,
    read_document,
    require,
    sha256,
)
from itov.catalog_store import CatalogStore, _atomic_write
from itov.comfyui import parse_json_object
from itov.qualification import safe_path
from itov.review_records import CRITERIA as CRITERIA
from itov.review_records import ReviewDecision
from itov.training_data import file_ref, publish, seal
from itov.training_results import inspect_weights as inspect_weights


def assess(config, plan_path, *, save=False):
    with assessment_context(config, plan_path) as context:
        report = _assessment(context)
    if save:
        publish(
            safe_path(config.root, f"state/training/assessments/{report['assessment_id']}.json"),
            report,
        )
    return report


def _assessment(context):
    plan = context.plan.to_dict()
    validated = context.validated.to_dict()
    result, dataset, integrity = (validated["result"], validated["dataset"], validated["integrity"])
    previews = result["previews"]
    report = seal(
        {
            "version": 2,
            "scope": "training_technical_assessment",
            "plan_id": plan["plan_id"],
            "result_id": result["result_id"],
            "dataset_id": dataset["dataset_id"],
            "weights": result["weights"],
            "integrity": integrity,
            "technical_pass": True,
            "heldout_before": result["heldout_before"],
            "heldout_after": result["heldout_after"],
            "previews": previews,
            "purpose": plan["purpose"],
            "quality_acceptance": "evidence_review_required",
            "promotion_eligible": False,
            "limits": (
                "Successful optimization, finite weights and paired diagnostics do not establish "
                "quality, activation or runtime compatibility. Smoke datasets cannot be promoted."
            ),
        },
        "assessment_id",
    )
    return report


def candidate(config, plan_path, *, save=False):
    with assessment_context(config, plan_path) as context:
        value, raw = _candidate(context)
    if save:
        asset = value["entry"]["asset"]
        destination = safe_path(config.root, asset["path"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            _atomic_write(destination, raw, exclusive=True)
        except FileExistsError:
            file_ref(config.root, asset)
        publish(
            safe_path(config.root, f"state/training/candidates/{value['candidate_id']}.json"), value
        )
    return value


def _candidate(context, *, assessment=None):
    report = _assessment(context) if assessment is None else assessment
    plan = context.plan.to_dict()
    spec = plan["specification"]
    raw, export = _export(context.validated.weights)
    asset = {
        "path": f"models_shared/trained/{export['sha256']}.safetensors",
        "sha256": export["sha256"],
    }
    entry = {
        "id": "trained-" + asset["sha256"],
        "asset": asset,
        "category": "style",
        "slot": "style",
        "base_models": ["sdxl-1.0"],
        "strength_milli": {"min": 500, "recommended": 1000, "max": 1000},
        "rotation_weight_milli": 1000,
        "trigger_words": [spec["trigger"]],
        "status": "candidate",
    }
    value = seal(
        {
            "version": 1,
            "plan_id": plan["plan_id"],
            "assessment_id": report["assessment_id"],
            "result_id": report["result_id"],
            "entry": entry,
            "purpose": plan["purpose"],
            "export": export,
        },
        "candidate_id",
    )
    return value, raw


def comfy_export(path, rank, expected_sha256):
    """Rename verified UNet tensors for stock ComfyUI, preserving every payload byte.

    The worker fixes lora_alpha == rank. ComfyUI's absent-alpha scale is 1, so
    this format needs no additional scaling tensors. No quantization/conversion occurs.
    """
    return _export(training_results.weight_snapshot(path, rank, expected_sha256))


def _export(snapshot):
    integrity = snapshot.integrity.to_dict()
    raw, expected_sha256 = snapshot.raw, snapshot.sha256
    size = struct.unpack("<Q", raw[:8])[0]
    original = parse_json_object(raw[8 : 8 + size], message="Adapter header must be an object")
    header, mapping = {}, {}
    for name, tensor in original.items():
        if name == "__metadata__":
            continue
        stem, direction = name.removeprefix("unet.").rsplit(".lora.", 1)
        mapped = "lora_unet_" + stem.replace(".", "_") + ".lora_" + direction
        require(mapped not in header, "LoRA tensor names collide during export")
        header[mapped] = tensor
        mapping[name] = mapped
    header["__metadata__"] = {
        "format": "pt",
        "itov_format": "comfy-unet-lora-v1",
        "source_sha256": expected_sha256,
        "alpha_scale": "1; training alpha equals rank",
    }
    encoded = canonical_bytes(header)
    encoded += b" " * (-len(encoded) % 8)
    payload = raw[8 + size :]
    converted = struct.pack("<Q", len(encoded)) + encoded + payload
    return converted, {
        "format": "comfy-unet-lora-v1",
        "source_sha256": expected_sha256,
        "sha256": sha256(converted),
        "bytes": len(converted),
        "tensors": integrity["tensors"],
        "tensor_payload_sha256": sha256(payload),
        "mapping_sha256": sha256(canonical_bytes(mapping)),
        "alpha_scale_milli": 1000,
        "limits": "Tensor names changed, payload bytes preserved; runtime acceptance is separate.",
    }


def review(config, report, path, candidate_id, plan_path=None):
    raw = read_document(path)
    value = parse_json_object(raw)
    decision = ReviewDecision.parse(value, report["assessment_id"], candidate_id)
    for check in decision.checks:
        for ref in check.evidence:
            file_ref(config.root, ref.to_dict(), maximum=32 * 1024 * 1024)
    coverage = False
    if value["version"] in (2, 3):
        from itov.quality import review_coverage

        require(plan_path is not None, "Curated review needs a training plan")
        coverage = review_coverage(config, plan_path, value)
    return {
        "sha256": sha256(raw),
        "document": value,
        "approved": decision.approved,
        "coverage_passed": coverage,
    }


def promotion(config, plan_path, review_path=None, *, save=False):
    assessment = assess(config, plan_path)
    candidate_value = candidate(config, plan_path)
    blockers = []
    if assessment["purpose"] == "smoke":
        blockers.append("Smoke-test datasets are never eligible for production promotion")
    reviewed = (
        review(config, assessment, review_path, candidate_value["candidate_id"], plan_path)
        if review_path
        else None
    )
    if not reviewed or not reviewed["approved"]:
        blockers.append("A complete, evidence-backed approving review is required")
    if assessment["purpose"] != "smoke" and (not reviewed or not reviewed["coverage_passed"]):
        blockers.append(
            "Curated training v2 and passing review of every case and seed are required"
        )
    if blockers:
        return {
            "ok": False,
            "scope": "promotion_refused",
            "assessment_id": assessment["assessment_id"],
            "blockers": blockers,
        }
    snapshot = CatalogStore(config.root).snapshot(require_clean=True)
    catalog = snapshot.to_dict()["catalog"]
    entry = {**candidate_value["entry"], "status": "active"}
    existing = next((v for v in catalog["loras"] if v["id"] == entry["id"]), None)
    require(
        existing is None or existing == candidate_value["entry"] or existing == entry,
        "Existing LoRA metadata differs; preserve it",
    )
    catalog["loras"] = [v for v in catalog["loras"] if v["id"] != entry["id"]] + [entry]
    decision = seal(
        {
            "version": 1,
            "scope": "reviewed_promotion_preview",
            "expected_head": snapshot.head,
            "plan_id": candidate_value["plan_id"],
            "candidate_id": candidate_value["candidate_id"],
            "assessment_id": assessment["assessment_id"],
            "review": reviewed,
            "catalog": catalog,
        },
        "decision_id",
    )
    if save:
        candidate(config, plan_path, save=True)
        publish(
            safe_path(config.root, f"state/training/promotions/{decision['decision_id']}.json"),
            decision,
        )
    return {"ok": True, "decision": decision, "activation_eligible": False}


def apply_promotion(config, plan_path, review_path, expected_head, decision_id):
    result = promotion(config, plan_path, review_path)
    require(result["ok"], "; ".join(result.get("blockers", [])))
    decision = result["decision"]
    require(
        decision["expected_head"] == expected_head and decision["decision_id"] == decision_id,
        "Promotion preview is stale; review a fresh decision",
    )
    raise ValueError(
        "Training-only promotion cannot activate a candidate. Use candidate preview with a "
        "complete deployed decision, then candidate apply (C-05)."
    )
