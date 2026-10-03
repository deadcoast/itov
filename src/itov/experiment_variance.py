"""Offline, evidence-bound repetition measurements with preregistered tolerances."""

from __future__ import annotations

import array
import itertools
import math
import struct
import sys
from contextlib import ExitStack

from itov.catalog import integer, object_fields, require
from itov.comfyui import parse_json, parse_json_object
from itov.evidence_reads import EvidenceReads, read_document
from itov.training_data import check_seal, file_ref, publish, seal

LIMITS = (
    "All within-endpoint repetition pairs are measured. Observed ranges are descriptive, "
    "not confidence bounds or causal attribution. Tolerances were declared in the experiment; "
    "passing them does not establish exact determinism or image quality. Image equality uses "
    "encoded file hashes, not a semantic or perceptual score. Failed attempts remain unavailable."
)


def validate_tolerances(value):
    object_fields(
        value,
        {"weight_abs_billionths", "optimizer_abs_billionths", "loss_abs_billionths"},
        "numerical tolerances",
    )
    for key, number in value.items():
        integer(number, key)
        require(number <= 10**9, "Numerical tolerance must be 0..1 in billionths")


def compare_tensors(left, right):
    """Compare already validated FP32 checkpoint payloads in bounded chunks."""
    groups = {
        key: {
            "elements": 0,
            "different_elements": 0,
            "max_absolute_difference": 0.0,
            "payload_exact": True,
        }
        for key in ("weight", "exp_avg", "exp_avg_sq")
    }
    rng = {}
    with ExitStack() as stack:
        streams = [stack.enter_context(path.open("rb")) for path in (left, right)]
        headers, bases = [], []
        for stream in streams:
            length = struct.unpack("<Q", stream.read(8))[0]
            require(2 <= length <= 4 * 1024**2, "Invalid checkpoint comparison header")
            headers.append(parse_json(stream.read(length)))
            bases.append(8 + length)
        require(set(headers[0]) == set(headers[1]), "Comparison tensor keys differ")
        for name in sorted(headers[0]):
            rows = [header[name] for header in headers]
            require(
                all(rows[0][key] == rows[1][key] for key in ("dtype", "shape")),
                "Comparison tensor shapes or precision differ",
            )
            sizes = [row["data_offsets"][1] - row["data_offsets"][0] for row in rows]
            require(sizes[0] == sizes[1], "Comparison payload sizes differ")
            for stream, base, row in zip(streams, bases, rows, strict=True):
                stream.seek(base + row["data_offsets"][0])
            remaining = sizes[0]
            exact = True
            while remaining:
                size = min(65536, remaining)
                raw = [stream.read(size) for stream in streams]
                require(all(len(data) == size for data in raw), "Truncated comparison payload")
                same = raw[0] == raw[1]
                exact &= same
                if rows[0]["dtype"] == "F32":
                    group = groups[name.rsplit(".", 1)[1]]
                    group["elements"] += size // 4
                    group["payload_exact"] &= same
                    if not same:
                        numbers = [array.array("f", data) for data in raw]
                        if sys.byteorder != "little":
                            for values in numbers:
                                values.byteswap()
                        count, maximum = 0, 0.0
                        for a, b in zip(*numbers, strict=True):
                            require(math.isfinite(a) and math.isfinite(b), "Nonfinite comparison")
                            delta = abs(a - b)
                            count += a != b
                            maximum = max(maximum, delta)
                        group["different_elements"] += count
                        group["max_absolute_difference"] = max(
                            group["max_absolute_difference"], maximum
                        )
                else:
                    require(
                        rows[0]["dtype"] == "U8" and name.startswith("rng."),
                        "Unsupported comparison tensor",
                    )
                remaining -= size
            if name.startswith("rng."):
                rng[name] = exact
    for group in groups.values():
        group["max_absolute_difference_hex"] = group.pop("max_absolute_difference").hex()
    return {"parameters": groups, "torch_rng_exact": rng}


def _pair(config, a, b, tolerance):
    checkpoints, states = [], []
    for member in (a, b):
        path, _ = file_ref(config.root, member["checkpoint"], maximum=32 * 1024**2)
        checkpoint = parse_json_object(read_document(path))
        state, _ = file_ref(path.parent, checkpoint["state"], maximum=256 * 1024**2)
        checkpoints.append(checkpoint)
        states.append(state)
    x, y = checkpoints
    require(x["parameters"] == y["parameters"], "Repetition parameter identities differ")
    measured = compare_tensors(*states)
    loss = {}
    for kind in ("steps", "validation"):
        left, right = x["trace"][kind], y["trace"][kind]
        if kind == "steps":
            differences = [
                abs(p["loss_billionths"] - q["loss_billionths"])
                for p, q in zip(left, right, strict=True)
            ]
        else:
            differences = [
                abs(p["loss_billionths"] - q["loss_billionths"])
                for u, v in zip(left, right, strict=True)
                for p, q in zip(u["losses"], v["losses"], strict=True)
            ]
        loss[kind + "_max_absolute_billionths"] = max(differences, default=0)
    order_keys = ("step", "micro_batches", "learning_rate_trillionths", "optimizer_state_step")
    controls = {
        "runtime_equal": x["runtime"] == y["runtime"],
        "position_equal": x["position"] == y["position"],
        "precision_equal": x["trace"]["precision"] == y["trace"]["precision"],
        "sample_noise_rate_order_equal": [
            {k: r[k] for k in order_keys} for r in x["trace"]["steps"]
        ]
        == [{k: r[k] for k in order_keys} for r in y["trace"]["steps"]],
        "python_numpy_rng_exact": x["rng"] == y["rng"],
        "torch_rng_exact": all(measured["torch_rng_exact"].values()),
    }
    parameters = measured["parameters"]
    within = (
        all(
            float.fromhex(row["max_absolute_difference_hex"])
            <= tolerance[
                "weight_abs_billionths" if name == "weight" else "optimizer_abs_billionths"
            ]
            / 1e9
            for name, row in parameters.items()
        )
        and max(loss.values()) <= tolerance["loss_abs_billionths"]
    )
    exact = all(row["payload_exact"] for row in parameters.values()) and not any(loss.values())
    images = []
    for p, q in zip(a["images"], b["images"], strict=True):
        require(
            {k: v for k, v in p.items() if k != "image"}
            == {k: v for k, v in q.items() if k != "image"},
            "Repetition image conditions differ",
        )
        images.append(
            {
                "case_id": p["case_id"],
                "seed": p["seed"],
                "role": p["role"],
                "file_sha256_equal": p["image"]["sha256"] == q["image"]["sha256"],
            }
        )
    return {
        "members": [a["id"], b["id"]],
        "controls": controls,
        "runtime": x["runtime"],
        **measured,
        "loss": loss,
        "images": images,
        "numerically_exact": exact and all(controls.values()),
        "within_declared_tolerance": within and all(controls.values()),
    }


def measure(config, path, *, save=False):
    from itov import experiments

    reads = EvidenceReads()
    with reads.capture():
        manifest, _ = experiments._load(config, path)
        spec = manifest["specification"]
        require(spec["version"] == 2, "Variance requires preregistered v2 tolerances")
        current = experiments.packet(config, path)
        rows = []
        for endpoint in spec["endpoints"]:
            members = [r for r in current["members"] if r["endpoint"] == endpoint["id"]]
            pairs = []
            for a, b in itertools.combinations(members, 2):
                if any(r["status"] != "artifacts_validated" for r in (a, b)):
                    pairs.append({"members": [a["id"], b["id"]], "status": "unavailable"})
                else:
                    pairs.append(
                        {"status": "measured", **_pair(config, a, b, spec["numerical_tolerances"])}
                    )
            rows.append({"endpoint": endpoint["id"], "pairs": pairs})
        all_pairs = [p for row in rows for p in row["pairs"]]
        available = all(p["status"] == "measured" for p in all_pairs)
        result = seal(
            {
                "version": 1,
                "scope": "experiment_numerical_variance",
                "experiment_id": current["experiment_id"],
                "packet_id": current["packet_id"],
                "tolerances": spec["numerical_tolerances"],
                "endpoints": rows,
                "status": "inconclusive"
                if not available
                else "pass"
                if all(p["within_declared_tolerance"] for p in all_pairs)
                else "failed",
                "exact_reproduction": available and all(p["numerically_exact"] for p in all_pairs),
                "promotion_eligible": False,
                "limits": LIMITS,
            },
            "variance_id",
        )
        reads.verify()
    if save:
        publish(experiments._destination(config, "variance", result["variance_id"]), result)
    return result


def replay(config, path, report_path):
    reads = EvidenceReads()
    with reads.capture():
        saved = check_seal(parse_json(read_document(report_path)), "variance_id")
        current = measure(config, path)
        require(current == saved, "Numerical variance evidence or measurements differ")
        reads.verify()
    return {
        "scope": "experiment_variance_replay",
        "valid": True,
        "variance_id": saved["variance_id"],
        "status": saved["status"],
        "exact_reproduction": saved["exact_reproduction"],
        "promotion_eligible": False,
        "limits": LIMITS,
    }
