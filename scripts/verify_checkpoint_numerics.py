"""Actual Torch CPU checkpoint/restart checks; separate from SDXL/native GPU evidence."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import torch
from safetensors.torch import load_file

from itov import training_checkpoint_worker, training_checkpoints, training_config
from itov.catalog import sha256
from itov.training_checkpoint_worker import Checkpoints, runtime
from itov.training_data import publish, seal
from itov.training_optimization import optimize


class Interrupted(RuntimeError):
    pass


def seed(number):
    random.seed(number)
    np.random.seed(number)
    torch.manual_seed(number)


def execute(folder, plan, source=None, stop=None):
    folder.mkdir()
    seed(123 if source is None else 987)  # Prove restoration survives unrelated initialization.
    model = torch.nn.Sequential(torch.nn.Linear(2, 1), torch.nn.Dropout(0.15))
    precision = {
        "frozen_unet_dtype": "torch.bfloat16",
        "adapter_dtype": "torch.float32",
        "gradient_dtype": "torch.float32",
        "vae_dtype": "torch.float32",
        "autocast_dtype": "torch.bfloat16",
        "loss_dtype": "torch.float32",
        "tf32": False,
        "adapter_tensors": len(list(model.parameters())),
    }

    def emit(kind, step, row):
        publish(folder / "optimization" / f"{kind}-{step:06d}.json", row)

    manager = Checkpoints(plan, folder, model, precision, runtime(), emit, source)
    inputs = torch.tensor([[0.2, -0.3], [0.7, 0.1], [-0.4, 0.8]])
    target = torch.tensor([[0.4], [-0.2], [0.1]])

    def loss(rows):
        ids = [int(row["sample"]) for row in rows]
        noisy = inputs[ids] + torch.randn(len(ids), 2) * 0.01
        noisy += float(np.random.random()) * 0.01 + random.random() * 0.01
        with torch.autocast("cpu", dtype=torch.bfloat16):
            prediction = model(noisy)
        assert prediction.dtype == torch.bfloat16
        return torch.nn.functional.mse_loss(prediction.float(), target[ids])

    def evaluate():
        assert not model.training and not torch.is_grad_enabled()
        noise = torch.rand(1, 2) * (random.random() + float(np.random.random()))
        return [
            {
                "sample": "heldout",
                "noise_seed": 100011,
                "loss_billionths": round(float(model(noise).square().mean()) * 1e9),
            }
        ]

    def observe():
        return {
            key: 0
            for key in (
                "cuda_allocated_bytes",
                "cuda_reserved_bytes",
                "cuda_peak_allocated_bytes",
                "cuda_peak_reserved_bytes",
                "host_available_physical_bytes",
                "host_available_commit_bytes",
            )
        }

    def save(optimizer, steps, validation):
        manager.save(optimizer, steps, validation)
        if len(steps) == stop:
            raise Interrupted("Declared stop after committed checkpoint")

    with contextlib.redirect_stdout(io.StringIO()):
        try:
            steps, validation = optimize(
                model,
                list(model.parameters()),
                plan["optimization"],
                loss,
                evaluate,
                observe,
                emit,
                lambda: None,
                restore=manager.restore,
                checkpoint=save,
            )
        except Interrupted:
            return None
    return {
        "steps": steps,
        "validation": validation,
        "next_rng": {
            "python": random.random(),
            "numpy": float(np.random.random()),
            "torch": torch.rand(3).tolist(),
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    root = parser.parse_args().output
    root.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(2)
    tolerance = 1e-7  # Declared before execution, for CPU fixture state/loss only.
    samples = [{"id": str(n), "split": "train"} for n in range(3)]
    samples += [{"id": "heldout", "split": "validation"}]
    observations = []
    for batch, accumulation in ((1, 1), (1, 2), (2, 1)):
        for sampling in ("sequential", "shuffle_epoch"):
            for schedule in ("constant", "linear_warmup_decay"):
                name = f"{batch}-{accumulation}-{sampling}-{schedule}"
                spec = {
                    "version": 4,
                    "checkpoints": {"every_steps": 2},
                    "parameters": {
                        "seed": 11,
                        "steps": 5,
                        "rank": 4,
                        "resolution": 512,
                        "learning_rate_millionths": 100,
                    },
                    "optimization": {
                        "micro_batch_size": batch,
                        "accumulation_steps": accumulation,
                        "sampling": sampling,
                        "schedule": schedule,
                        "warmup_steps": 0 if schedule == "constant" else 2,
                        "validation_every_steps": 3,
                        "precision": training_config.PRECISION,
                    },
                }
                plan = seal(
                    {
                        "specification": spec,
                        "optimization": training_config.resolve(spec, samples),
                        "restart": None,
                        "purpose": "cpu_checkpoint_fixture",
                    },
                    "plan_id",
                )
                baseline_folder, interrupted_folder, resumed_folder = [
                    root / f"{name}-{part}" for part in ("full", "interrupted", "resumed")
                ]
                full = execute(baseline_folder, plan)
                assert execute(interrupted_folder, plan, stop=2) is None
                source = interrupted_folder / "checkpoints/step-000002/checkpoint.json"
                checkpoint = training_checkpoints.validate(source, plan)
                resumed_plan = seal(
                    {
                        **{k: v for k, v in plan.items() if k != "plan_id"},
                        "restart": {"fixture_checkpoint": checkpoint["checkpoint_id"]},
                    },
                    "plan_id",
                )
                resumed = execute(resumed_folder, resumed_plan, (source, checkpoint))
                assert full["next_rng"] == resumed["next_rng"]
                left = load_file(str(baseline_folder / "checkpoints/step-000005/state.safetensors"))
                right = load_file(str(resumed_folder / "checkpoints/step-000005/state.safetensors"))
                errors = {
                    k: float((left[k] - right[k]).abs().max()) for k in left if k != "rng.cpu"
                }
                assert max(errors.values()) <= tolerance
                assert torch.equal(left["rng.cpu"], right["rng.cpu"])
                for kind, field in (("steps", "loss_billionths"), ("validation", None)):
                    assert len(full[kind]) == len(resumed[kind])
                    for a, b in zip(full[kind], resumed[kind], strict=True):
                        if field:
                            assert abs(a[field] - b[field]) / 1e9 <= tolerance
                        else:
                            assert a["losses"] == b["losses"]
                assert [r["step"] for r in resumed["validation"]] == [0, 3, 5]
                # Restored history includes the original timing/resource observations.
                assert resumed["steps"][:2] == checkpoint["trace"]["steps"]
                observations.append(
                    {
                        "name": name,
                        "split_step": 2,
                        "updates": 5,
                        "validation_steps": [0, 3, 5],
                        "rng_exact": True,
                        "max_parameter_and_adamw_state_error": max(errors.values()),
                        "checkpoint_id": checkpoint["checkpoint_id"],
                    }
                )
    original_publish = training_checkpoint_worker.publish

    def fail_manifest(path, value):
        if value.get("position", {}).get("completed_steps") == 4:
            raise Interrupted("Injected interruption after tensor write, before manifest")
        return original_publish(path, value)

    failed_folder = root / "publication-failure"
    training_checkpoint_worker.publish = fail_manifest
    try:
        assert execute(failed_folder, plan) is None
    finally:
        training_checkpoint_worker.publish = original_publish
    committed = failed_folder / "checkpoints/step-000002/checkpoint.json"
    checkpoint = training_checkpoints.validate(committed, plan)
    partials = list((failed_folder / "checkpoints").glob(".partial-*"))
    assert len(partials) == 1 and (partials[0] / "state.safetensors").is_file()
    assert not (partials[0] / "checkpoint.json").exists()
    assert not (failed_folder / "checkpoints/step-000004").exists()
    # Completed bundles are immutable, even when a caller asks to save the same step again.
    retained = {p: p.read_bytes() for p in committed.parent.iterdir()}
    model = torch.nn.Sequential(torch.nn.Linear(2, 1), torch.nn.Dropout(0.15))
    optimizer = torch.optim.AdamW(model.parameters(), foreach=False, fused=False)
    manager = Checkpoints(
        plan,
        failed_folder,
        model,
        checkpoint["trace"]["precision"],
        runtime(),
        lambda *args: None,
        (committed, checkpoint),
    )
    steps, validation = manager.restore(optimizer)
    try:
        manager.save(optimizer, steps, validation)
    except ValueError as error:
        assert "already exists" in str(error)
    else:
        raise AssertionError("Existing checkpoint was overwritten")
    assert all(p.read_bytes() == raw for p, raw in retained.items())
    source_modules = {
        name: sha256((Path(__file__).resolve().parents[1] / "src/itov" / name).read_bytes())
        for name in (
            "training_optimization.py",
            "training_checkpoint_worker.py",
            "training_checkpoints.py",
            "checkpoint_tensors.py",
        )
    }
    print(
        json.dumps(
            {
                "python": sys.version,
                "torch": torch.__version__,
                "numpy": np.__version__,
                "tolerance": tolerance,
                "observations": observations,
                "source_modules": source_modules,
                "publication_failure": {
                    "committed_step_preserved": 2,
                    "partial_step": 4,
                    "partial_directory_retained": str(partials[0]),
                    "partial_has_tensor_but_no_manifest": True,
                    "existing_complete_checkpoint_refused_and_preserved": True,
                },
                "limits": (
                    "CPU BF16 linear/dropout fixture with Python/NumPy/Torch RNG consumption. "
                    "SDXL precision labels in checkpoint fixtures describe the schema, not actual "
                    "frozen SDXL modules. No CUDA/native-interruption or model-quality acceptance."
                ),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
