"""Read-only training result validation, shared by execution and assessment."""

from __future__ import annotations

import array
import io
import math
import struct
import sys
from contextlib import contextmanager

from itov.catalog import array as json_array
from itov.catalog import canonical_bytes, integer, object_fields, require, sha256
from itov.comfyui import parse_json
from itov.evidence_reads import observe, read_document
from itov.records import Document
from itov.training_data import check_seal, file_ref, load_dataset
from itov.training_records import ValidatedTrainingResult, WeightSnapshot


class ResultValidationError(ValueError):
    """A failed technical boundary; never a candidate quality verdict."""

    def __init__(self, boundary, message):
        self.boundary = boundary
        super().__init__(message)


@contextmanager
def boundary(name):
    try:
        yield
    except ResultValidationError:
        raise
    except KeyboardInterrupt as error:
        error.boundary = name
        raise
    except (OSError, ValueError, KeyError, TypeError, struct.error) as error:
        raise ResultValidationError(name, str(error)) from error


def read_result(folder, plan, *, expected_result_id=None):
    with boundary("result_publication"):
        result = check_seal(parse_json(read_document(folder / "result.json")), "result_id")
    with boundary("result_binding"):
        require(
            result.get("plan_id") == plan["plan_id"]
            and (expected_result_id is None or result["result_id"] == expected_result_id),
            "Training result binding differs",
        )
        require(result.get("status") in ("succeeded", "failed"), "Invalid worker result status")
    with boundary("worker_execution"):
        require(
            result["status"] == "succeeded",
            "Training worker failed: " + str(result.get("error", "inspect worker.log")),
        )
    return result


def inspect_weights(path, rank):
    size = path.stat().st_size
    require(8 < size <= 256 * 1024 * 1024, "LoRA file size is unsupported")
    with path.open("rb") as handle:
        return _inspect_weights(handle, size, rank)


def weight_snapshot(path, rank, expected_sha256):
    size = path.stat().st_size
    require(8 < size <= 256 * 1024 * 1024, "LoRA file size is unsupported")
    with path.open("rb") as source:
        raw = source.read(size + 1)
    require(
        len(raw) == size and sha256(raw) == expected_sha256, "Source LoRA changed during export"
    )
    observe(path, expected_sha256, size)
    integrity = _inspect_weights(io.BytesIO(raw), size, rank)
    return WeightSnapshot(raw, expected_sha256, rank, Document.capture(integrity))


def _inspect_weights(handle, size, rank):
    header_size = struct.unpack("<Q", handle.read(8))[0]
    require(2 <= header_size <= min(4 * 1024 * 1024, size - 8), "Invalid safetensors header size")
    header = parse_json(handle.read(header_size))
    require(isinstance(header, dict), "Invalid safetensors header")
    tensors = {k: v for k, v in header.items() if k != "__metadata__"}
    require(0 < len(tensors) <= 4096, "Invalid LoRA tensor count")
    spans, pairs = [], {}
    for name, tensor in tensors.items():
        require(name.startswith("unet."), "Only UNet LoRA tensors are allowed")
        suffix = next(
            (
                suffix
                for suffix in (".lora.down.weight", ".lora.up.weight")
                if name.endswith(suffix)
            ),
            None,
        )
        require(suffix is not None, "Unexpected LoRA tensor name")
        object_fields(tensor, {"dtype", "shape", "data_offsets"}, "LoRA tensor")
        require(tensor["dtype"] in ("F32", "F16", "BF16"), "Unsupported LoRA dtype")
        shape, offsets = tensor["shape"], tensor["data_offsets"]
        require(
            isinstance(shape, list)
            and len(shape) == 2
            and all(type(n) is int and 0 < n <= 65536 for n in shape),
            "Invalid LoRA matrix shape",
        )
        down = suffix == ".lora.down.weight"
        require(shape[0 if down else 1] == rank, "LoRA rank differs from training plan")
        width = 4 if tensor["dtype"] == "F32" else 2
        require(
            isinstance(offsets, list)
            and len(offsets) == 2
            and all(type(n) is int and n >= 0 for n in offsets)
            and offsets[1] - offsets[0] == math.prod(shape) * width,
            "Invalid LoRA byte offsets",
        )
        spans.append((offsets[0], offsets[1], tensor["dtype"]))
        pairs.setdefault(name[: -len(suffix)], set()).add(down)
    require(all(pair == {True, False} for pair in pairs.values()), "Incomplete LoRA matrix pair")
    position = 0
    for start, end, dtype in sorted(spans):
        require(
            start == position and end <= size - 8 - header_size,
            "Overlapping, gapped or truncated LoRA data",
        )
        mask = {"F32": 0x7F800000, "F16": 0x7C00, "BF16": 0x7F80}[dtype]
        remaining = end - start
        while remaining:
            raw = handle.read(min(1024 * 1024, remaining))
            require(bool(raw), "Truncated LoRA tensor")
            values = array.array("I" if dtype == "F32" else "H", raw)
            if sys.byteorder != "little":
                values.byteswap()
            require(all(bits & mask != mask for bits in values), "Nonfinite LoRA tensor")
            remaining -= len(raw)
        position = end
    require(position == size - 8 - header_size, "Trailing undeclared LoRA bytes")
    return {"bytes": size, "tensors": len(tensors), "pairs": len(pairs), "all_finite": True}


def validate(config, plan, folder, *, expected_result_id=None):
    return _validate(config, plan, folder, expected_result_id=expected_result_id, capture=False)


def validate_record(config, plan, folder, *, expected_result_id=None):
    """Capture owned immutable values for one assessment/export/packet operation."""
    return _validate(config, plan, folder, expected_result_id=expected_result_id, capture=True)


def _validate(config, plan, folder, *, expected_result_id, capture):
    result = read_result(folder, plan, expected_result_id=expected_result_id)
    with boundary("result_schema"):
        object_fields(
            result,
            {
                "version",
                "plan_id",
                "status",
                "weights",
                "optimizer_steps",
                "training_loss_billionths",
                "heldout_before",
                "heldout_after",
                "previews",
                "changed_adapter_tensors",
                "trainable_parameters",
                "adapter_only",
                "export_reloaded",
                "max_memory_allocated",
                "max_memory_reserved",
                "quality_acceptance",
                "purpose",
                "limits",
                "elapsed_ns",
                "result_id",
            }
            | ({"quality_matrix"} if plan["specification"]["version"] in (2, 3, 4) else set())
            | ({"optimization"} if plan["specification"]["version"] in (3, 4) else set())
            | ({"checkpoints"} if plan["specification"]["version"] == 4 else set()),
            "successful training result",
        )
        require(
            type(result["version"]) is int
            and result["version"] == plan["specification"]["version"],
            "Invalid result version",
        )
        for key in (
            "trainable_parameters",
            "max_memory_allocated",
            "max_memory_reserved",
            "elapsed_ns",
        ):
            integer(result[key], key)
        require(result["trainable_parameters"] > 0, "No trainable parameters recorded")
        require(
            result["quality_acceptance"] == "not_established",
            "Worker results cannot establish candidate quality acceptance",
        )
    with boundary("input_freshness"):
        dataset_path, _ = file_ref(config.root, plan["specification"]["dataset"])
        dataset = load_dataset(config.root, dataset_path)
        require(dataset["dataset_id"] == plan["dataset_id"], "Evaluation dataset differs")
        require(
            result["purpose"] == plan["purpose"] == dataset["dataset"]["purpose"],
            "Dataset purpose differs",
        )
    params = plan["specification"]["parameters"]
    with boundary("weights"):
        weights, _ = file_ref(folder, result["weights"], maximum=256 * 1024**2)
        snapshot = (
            weight_snapshot(weights, params["rank"], result["weights"]["sha256"])
            if capture
            else None
        )
        integrity = (
            snapshot.integrity.to_dict() if snapshot else inspect_weights(weights, params["rank"])
        )
    with boundary("optimizer_evidence"):
        require(
            result["adapter_only"] is True
            and result["export_reloaded"] is True
            and type(result["changed_adapter_tensors"]) is int
            and result["changed_adapter_tensors"] > 0,
            "Adapter update evidence is missing",
        )
        require(
            type(result["optimizer_steps"]) is int and result["optimizer_steps"] == params["steps"],
            "Training step count differs",
        )
        require(
            len(json_array(result["training_loss_billionths"], "training losses"))
            == params["steps"],
            "Incomplete training losses",
        )
        for loss in result["training_loss_billionths"]:
            integer(loss, "training loss")
    ids = sorted(s["id"] for s in dataset["samples"] if s["split"] == "validation")
    if result["version"] in (3, 4):
        with boundary("optimization_evidence"):
            from itov import training_config

            effective = training_config.resolve(
                plan["specification"], dataset["dataset"]["samples"]
            )
            require(
                effective == plan["optimization"],
                "Planned optimization differs from dataset/config",
            )
            trace_path, _ = file_ref(folder, result["optimization"], maximum=32 * 1024**2)
            trace = training_config.validate_trace(
                parse_json(read_document(trace_path)), effective, result
            )
            expected_files = {"effective.json": effective, "precision.json": trace["precision"]}
            for kind, rows in (("step", trace["steps"]), ("validation", trace["validation"])):
                expected_files.update({f"{kind}-{row['step']:06d}.json": row for row in rows})
            from itov.qualification import safe_path

            for name, expected in expected_files.items():
                require(
                    read_document(safe_path(folder, "optimization/" + name))
                    == canonical_bytes(expected) + b"\n",
                    "Optimization event differs or is incomplete: " + name,
                )
        if result["version"] == 4:
            with boundary("checkpoint_evidence"):
                from itov import training_checkpoints

                training_checkpoints.validate_result(config, plan, folder, result, trace)
    with boundary("heldout_matrix"):
        for phase in ("heldout_before", "heldout_after"):
            rows = json_array(result[phase], phase)
            require(
                [r.get("sample") for r in rows if isinstance(r, dict)] == ids,
                "Held-out evaluation coverage differs",
            )
            for index, row in enumerate(rows):
                object_fields(row, {"sample", "noise_seed", "loss_billionths"}, "held-out loss")
                integer(row["loss_billionths"], "held-out loss")
                integer(row["noise_seed"], "held-out noise seed")
                require(
                    row["noise_seed"] == (params["seed"] + 100000 + index) % 2**32,
                    "Held-out noise seed differs",
                )
    with boundary("preview_matrix"):
        previews = json_array(result["previews"], "previews")
        require(
            [p.get("sample") for p in previews if isinstance(p, dict)] == ids[:2],
            "Missing held-out preview pairs",
        )
        for index, pair in enumerate(previews):
            object_fields(
                pair, {"sample", "seed", "prompt", "baseline", "candidate"}, "preview pair"
            )
            integer(pair["seed"], "preview seed")
            require(
                pair["seed"] == (params["seed"] + 200000 + index) % 2**32, "Preview seed differs"
            )
            sample = next(s for s in dataset["dataset"]["samples"] if s["id"] == pair["sample"])
            require(
                pair["prompt"]
                == (config.root / sample["caption"]["path"]).read_text(encoding="utf-8").strip(),
                "Preview prompt differs",
            )
            for role in ("baseline", "candidate"):
                file_ref(folder, pair[role], maximum=32 * 1024 * 1024)
            require(
                pair["baseline"]["path"].casefold() != pair["candidate"]["path"].casefold(),
                "Preview pair paths overlap",
            )
    with boundary("quality_matrix"):
        evidence = None
        if result["version"] in (2, 3, 4):
            from itov.quality import matrix_evidence

            for row in json_array(result["quality_matrix"], "quality matrix"):
                require(isinstance(row, dict), "Quality image must be an object")
                integer(row.get("seed"), "quality result seed")
            evidence = matrix_evidence(config.root, plan["specification"], result, folder)
    if capture:
        return ValidatedTrainingResult(
            Document.capture(result), Document.capture(dataset), snapshot, evidence
        )
    return {"result": result, "dataset": dataset, "integrity": integrity}
