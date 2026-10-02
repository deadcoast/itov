"""Build and save a base-image request through the existing inference contract."""

from itov.catalog import canonical_bytes, sha256
from itov.inference import _publish
from itov.inference_capabilities import CAPABILITY, CHECKPOINT, validate_spec
from itov.qualification import safe_path


def specification(
    prompt,
    *,
    negative_prompt="",
    width=1024,
    height=1024,
    seed=0,
    count=1,
    steps=20,
    cfg_milli=7000,
    checkpoint="sd_xl_base_1.0.safetensors",
):
    """No model reads, network, catalog change, seed reservation or generation."""
    return validate_spec(
        {
            "version": 2,
            "capability": CAPABILITY,
            "checkpoint": {"loader_name": checkpoint, "sha256": CHECKPOINT},
            "adapters": [],
            "sampler": {
                "steps": steps,
                "cfg_milli": cfg_milli,
                "sampler_name": "dpmpp_2m",
                "scheduler": "karras",
            },
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "seed": seed,
            "count": count,
        }
    )


def create(config, *, save=False, **settings):
    spec = specification(**settings)
    raw = canonical_bytes(spec) + b"\n"
    identity = sha256(canonical_bytes(spec))
    path = safe_path(config.root, f"state/inference/specifications/{identity}.json")
    if save:
        _publish(path, raw)
    return {
        "ok": True,
        "scope": "base_image_specification",
        "spec_id": identity,
        "specification": spec,
        "saved_path": str(path) if save else None,
        "quality_acceptance": "not_established",
        "limits": (
            "Pinned SDXL base only. 1024x1024 defaults follow its reference resolution; "
            "settings do not guarantee prompt adherence. No model loaded or job submitted."
        ),
    }
