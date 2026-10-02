"""Shared, dependency-free identity rules for instrumented ComfyUI workloads."""

import hashlib
import json

MARKER = "--itov-vram-observer-v1"


def encoded(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def workload_key(graph: dict) -> str:
    """Ignore only reserved sampler seeds and stock output names, never conditioning."""
    graph = json.loads(encoded(graph))
    for node in graph.values():
        inputs = node["inputs"]
        if node["class_type"] == "KSampler":
            inputs["seed"] = 0
        if node["class_type"] in {"SaveImage", "SaveVideo", "SaveAudioAdvanced"}:
            inputs["filename_prefix"] = "itov-profile-output"
        # ComfyUI coerces FLOAT inputs in-place. Normalize only exact integral scalars.
        for key, value in inputs.items():
            if type(value) is float and value.is_integer():
                inputs[key] = int(value)
    return hashlib.sha256(encoded(graph)).hexdigest()
