"""Versioned, dependency-light optimization configuration and deterministic sample order."""

from __future__ import annotations

from itov.catalog import canonical_bytes, integer, object_fields, require, sha256

PROFILE = "sdxl-unet-lora-v2"
PRECISION = "bf16-frozen-fp32-adapter-v1"


def validate(value, parameters):
    object_fields(
        value,
        {
            "micro_batch_size",
            "accumulation_steps",
            "sampling",
            "schedule",
            "warmup_steps",
            "validation_every_steps",
            "precision",
        },
        "optimization configuration",
    )
    for key in ("micro_batch_size", "accumulation_steps", "warmup_steps", "validation_every_steps"):
        integer(value[key], key)
    require(
        (value["micro_batch_size"], value["accumulation_steps"]) in {(1, 1), (1, 2), (2, 1)},
        "Supported micro-batch/accumulation pairs are 1/1, 1/2 and 2/1",
    )
    require(value["sampling"] in ("sequential", "shuffle_epoch"), "Unsupported sampling policy")
    require(value["schedule"] in ("constant", "linear_warmup_decay"), "Unsupported LR schedule")
    if value["schedule"] == "constant":
        require(value["warmup_steps"] == 0, "Constant schedule has no warmup")
    else:
        require(1 <= value["warmup_steps"] < parameters["steps"], "Warmup must precede final step")
    require(
        1 <= value["validation_every_steps"] <= parameters["steps"],
        "Validation cadence must be within the optimizer-step budget",
    )
    require(value["precision"] == PRECISION, "Only BF16 frozen/FP32 adapter precision is supported")


def learning_rate(parameters, settings, step):
    """Rate used by a one-based optimizer step, quantized to 1e-12; never batch-scaled."""
    peak = parameters["learning_rate_millionths"] * 10**6
    if settings["schedule"] == "constant":
        return peak
    warmup, total = settings["warmup_steps"], parameters["steps"]
    numerator, denominator = (
        (step, warmup) if step <= warmup else (total - step + 1, total - warmup)
    )
    return peak * numerator // denominator


def resolve(spec, samples):
    parameters, settings = spec["parameters"], spec["optimization"]
    validate(settings, parameters)
    train = sorted(row["id"] for row in samples if row["split"] == "train")
    heldout = sorted(row["id"] for row in samples if row["split"] == "validation")
    require(bool(train) and bool(heldout), "Optimization requires both dataset splits")
    require(len(train) >= settings["micro_batch_size"], "Micro-batch exceeds training sample count")
    batch, accumulation = settings["micro_batch_size"], settings["accumulation_steps"]
    order, epoch_order = [], []
    for position in range(parameters["steps"] * batch * accumulation):
        epoch, offset = divmod(position, len(train))
        if offset == 0:
            epoch_order = train
            if settings["sampling"] == "shuffle_epoch":
                epoch_order = sorted(
                    train,
                    key=lambda key: (
                        sha256(
                            canonical_bytes(
                                {"seed": parameters["seed"], "epoch": epoch, "sample": key}
                            )
                        ),
                        key,
                    ),
                )
        order.append(
            {
                "sample": epoch_order[offset],
                "epoch": epoch,
                "position": position,
                "noise_seed": (parameters["seed"] + position) % 2**32,
            }
        )
    steps = []
    for index in range(parameters["steps"]):
        start = index * batch * accumulation
        steps.append(
            {
                "step": index + 1,
                "learning_rate_trillionths": learning_rate(parameters, settings, index + 1),
                "micro_batches": [
                    order[start + n * batch : start + (n + 1) * batch] for n in range(accumulation)
                ],
            }
        )
    return {
        "config": {
            "version": 1,
            "profile": PROFILE,
            **settings,
            "resolution": parameters["resolution"],
            "rank": parameters["rank"],
            "seed": parameters["seed"],
            "optimizer_steps": parameters["steps"],
            "effective_batch_size": batch * accumulation,
            "peak_learning_rate_trillionths": parameters["learning_rate_millionths"] * 10**6,
            "automatic_batch_lr_scaling": False,
            "optimizer": {
                "name": "AdamW",
                "betas_millionths": [900000, 999000],
                "epsilon_trillionths": 10000,
                "weight_decay_millionths": 10000,
                "clip_norm_millionths": 1000000,
                "foreach": False,
                "fused": False,
            },
            "sampling_algorithm": "sha256-seed-epoch-id-v1"
            if settings["sampling"] == "shuffle_epoch"
            else "sorted-id-cycle-v1",
            "epoch_boundary": "continue_into_next_epoch_to_fill_each_micro_batch",
            "reduction": "mean_per_sample_then_mean_micro_batches",
            "gradient_checkpointing": True,
            "lora_alpha": parameters["rank"],
            "lora_dropout": 0,
            "tf32": False,
        },
        "steps": steps,
        "validation_steps": sorted(
            {
                0,
                parameters["steps"],
                *range(
                    settings["validation_every_steps"],
                    parameters["steps"],
                    settings["validation_every_steps"],
                ),
            }
        ),
        "validation_samples": [
            {"sample": key, "noise_seed": (parameters["seed"] + 100000 + index) % 2**32}
            for index, key in enumerate(heldout)
        ],
    }


def validate_trace(value, effective, result):
    """Validate measured evidence against the exact planned config/order, without Torch."""
    object_fields(
        value,
        {"version", "plan_id", "config", "precision", "steps", "validation"},
        "optimization trace",
    )
    require(type(value["version"]) is int and value["version"] == 1, "Invalid trace version")
    require(
        value["plan_id"] == result["plan_id"]
        and canonical_bytes(value["config"]) == canonical_bytes(effective["config"]),
        "Optimization trace binding differs",
    )
    precision = value["precision"]
    object_fields(
        precision,
        {
            "frozen_unet_dtype",
            "adapter_dtype",
            "gradient_dtype",
            "vae_dtype",
            "autocast_dtype",
            "loss_dtype",
            "tf32",
            "adapter_tensors",
        },
        "precision observations",
    )
    require(
        {k: v for k, v in precision.items() if k != "adapter_tensors"}
        == {
            "frozen_unet_dtype": "torch.bfloat16",
            "adapter_dtype": "torch.float32",
            "gradient_dtype": "torch.float32",
            "vae_dtype": "torch.float32",
            "autocast_dtype": "torch.bfloat16",
            "loss_dtype": "torch.float32",
            "tf32": False,
        },
        "Unsupported observed training precision",
    )
    integer(precision["adapter_tensors"], "adapter tensor count", minimum=1)
    require(precision["tf32"] is False, "TF32 must be disabled")
    require(
        isinstance(value["steps"], list) and len(value["steps"]) == len(effective["steps"]),
        "Incomplete optimization steps",
    )
    for row, planned, aggregate in zip(
        value["steps"], effective["steps"], result["training_loss_billionths"], strict=True
    ):
        object_fields(
            row,
            {
                *planned,
                "micro_loss_billionths",
                "loss_billionths",
                "gradient_norm_billionths",
                "gradient_tensors",
                "optimizer_state_step",
                "optimizer_state_fp32_finite",
                "adapter_fp32_finite",
                "elapsed_ns",
                "resources",
            },
            "optimization step",
        )
        require(
            canonical_bytes({k: row[k] for k in planned}) == canonical_bytes(planned),
            "Executed sample order or learning rate differs",
        )
        micro = row["micro_loss_billionths"]
        require(
            isinstance(micro, list) and len(micro) == len(planned["micro_batches"]),
            "Incomplete micro-batch losses",
        )
        for loss in micro:
            integer(loss, "micro-batch loss")
        integer(row["loss_billionths"], "optimizer loss")
        require(
            row["loss_billionths"] == aggregate == (sum(micro) + len(micro) // 2) // len(micro),
            "Accumulated mean loss differs",
        )
        for field in (
            "gradient_norm_billionths",
            "elapsed_ns",
            "gradient_tensors",
            "optimizer_state_step",
        ):
            integer(row[field], field)
        require(
            row["gradient_tensors"] == precision["adapter_tensors"]
            and row["optimizer_state_step"] == planned["step"],
            "Missing gradients or optimizer step mismatch",
        )
        require(
            row["optimizer_state_fp32_finite"] is True and row["adapter_fp32_finite"] is True,
            "Nonfinite/incorrect optimization precision",
        )
        resources(row["resources"])
    require(
        isinstance(value["validation"], list)
        and len(value["validation"]) == len(effective["validation_steps"]),
        "Incomplete validation cadence",
    )
    for row, step in zip(value["validation"], effective["validation_steps"], strict=True):
        object_fields(row, {"step", "losses", "elapsed_ns", "resources"}, "validation observation")
        integer(row["step"], "validation step")
        integer(row["elapsed_ns"], "validation elapsed")
        require(row["step"] == step, "Validation step differs")
        require(
            isinstance(row["losses"], list)
            and len(row["losses"]) == len(effective["validation_samples"]),
            "Incomplete validation samples",
        )
        for measured, sample in zip(row["losses"], effective["validation_samples"], strict=True):
            object_fields(measured, {*sample, "loss_billionths"}, "validation loss")
            require(
                canonical_bytes({k: measured[k] for k in sample}) == canonical_bytes(sample),
                "Validation identity/seed differs",
            )
            integer(measured["loss_billionths"], "validation loss")
        resources(row["resources"])
    require(
        value["validation"][0]["losses"] == result["heldout_before"]
        and value["validation"][-1]["losses"] == result["heldout_after"],
        "Validation endpoints differ",
    )
    observations = sorted(
        [(row["step"], 0, row["resources"]) for row in value["steps"]]
        + [(row["step"], 1, row["resources"]) for row in value["validation"]]
    )
    for key, total in (
        ("cuda_peak_allocated_bytes", "max_memory_allocated"),
        ("cuda_peak_reserved_bytes", "max_memory_reserved"),
    ):
        peaks = [row[key] for _, _, row in observations]
        require(
            peaks == sorted(peaks) and max(peaks) <= result[total],
            "Recorded allocator peaks differ from cumulative run counters",
        )
    return value


def resources(value):
    object_fields(
        value,
        {
            "cuda_allocated_bytes",
            "cuda_reserved_bytes",
            "cuda_peak_allocated_bytes",
            "cuda_peak_reserved_bytes",
            "host_available_physical_bytes",
            "host_available_commit_bytes",
        },
        "training resources",
    )
    for key, number in value.items():
        integer(number, key)
    require(
        value["cuda_allocated_bytes"]
        <= value["cuda_reserved_bytes"]
        <= value["cuda_peak_reserved_bytes"]
        and value["cuda_allocated_bytes"]
        <= value["cuda_peak_allocated_bytes"]
        <= value["cuda_peak_reserved_bytes"],
        "Inconsistent CUDA allocator counters",
    )
