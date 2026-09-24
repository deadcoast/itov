"""Run actual Torch CPU optimization checks in the optional training environment.

This tests reduction, update frequency, scheduling and precision on a small model.
It does not substitute for the separately retained SDXL/CUDA trials.
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import torch

from itov import training_config
from itov.catalog import sha256
from itov.training_optimization import optimize


def main():
    torch.set_num_threads(2)
    torch.manual_seed(9426)
    inputs = torch.tensor([[0.2, -0.3], [0.7, 0.1], [-0.4, 0.8]])
    targets = torch.tensor([[0.4], [-0.2], [0.1]])
    initial = torch.nn.Linear(2, 1)
    samples = [{"id": str(n), "split": "train"} for n in range(3)]
    samples += [{"id": "heldout", "split": "validation"}]
    base = {
        "parameters": {
            "seed": 11,
            "steps": 5,
            "rank": 4,
            "resolution": 512,
            "learning_rate_millionths": 100,
        },
        "optimization": {
            "micro_batch_size": 1,
            "accumulation_steps": 2,
            "sampling": "shuffle_epoch",
            "schedule": "linear_warmup_decay",
            "warmup_steps": 2,
            "validation_every_steps": 2,
            "precision": training_config.PRECISION,
        },
    }
    # Declared before executing: FP32 full-batch reference versus mean accumulation.
    tolerance = 1e-6
    observations = []
    for sampling in ("sequential", "shuffle_epoch"):
        for schedule in ("constant", "linear_warmup_decay"):
            for batch, accumulation in ((1, 1), (1, 2), (2, 1)):
                spec = copy.deepcopy(base)
                spec["optimization"].update(
                    micro_batch_size=batch,
                    accumulation_steps=accumulation,
                    sampling=sampling,
                    schedule=schedule,
                    warmup_steps=0 if schedule == "constant" else 2,
                )
                effective = training_config.resolve(spec, samples)
                model, reference = copy.deepcopy(initial), copy.deepcopy(initial)
                events, validation_modes = [], []

                def loss(rows, model=model):
                    assert model.training and torch.is_grad_enabled()
                    ids = [int(r["sample"]) for r in rows]
                    return torch.nn.functional.mse_loss(model(inputs[ids]), targets[ids])

                def evaluate(model=model, validation_modes=validation_modes):
                    validation_modes.append((model.training, torch.is_grad_enabled()))
                    return [
                        {
                            "sample": "heldout",
                            "noise_seed": 100011,
                            "loss_billionths": round(
                                float(model(torch.ones(1, 2)).square().mean()) * 10**9
                            ),
                        }
                    ]

                with contextlib.redirect_stdout(io.StringIO()):
                    steps, validations = optimize(
                        model,
                        list(model.parameters()),
                        effective,
                        loss,
                        evaluate,
                        lambda: {},
                        lambda *row, events=events: events.append(row),
                        lambda: None,
                    )
                optimizer = torch.optim.AdamW(
                    reference.parameters(),
                    lr=0.0001,
                    betas=(0.9, 0.999),
                    eps=1e-8,
                    weight_decay=0.01,
                    foreach=False,
                    fused=False,
                )
                reference_losses = []
                for row in effective["steps"]:
                    optimizer.zero_grad(set_to_none=True)
                    optimizer.param_groups[0]["lr"] = row["learning_rate_trillionths"] / 10**12
                    ids = [int(r["sample"]) for micro in row["micro_batches"] for r in micro]
                    measured = torch.nn.functional.mse_loss(reference(inputs[ids]), targets[ids])
                    measured.backward()
                    torch.nn.utils.clip_grad_norm_(
                        reference.parameters(), 1.0, error_if_nonfinite=True, foreach=False
                    )
                    optimizer.step()
                    reference_losses.append(float(measured.detach()))
                error = max(
                    float((a - b).detach().abs().max())
                    for a, b in zip(model.parameters(), reference.parameters(), strict=True)
                )
                assert error <= tolerance, error
                assert all(
                    abs(r["loss_billionths"] / 1e9 - expected) <= tolerance
                    for r, expected in zip(steps, reference_losses, strict=True)
                )
                assert [r["step"] for r in validations] == [0, 2, 4, 5]
                assert validation_modes == [(False, False)] * 4
                assert [kind for kind, *_ in events].count("step") == 5
                assert all(p.grad is None for p in model.parameters())
                observations.append(
                    {
                        "batch": batch,
                        "accumulation": accumulation,
                        "sampling": sampling,
                        "schedule": schedule,
                        "max_parameter_error": error,
                        "optimizer_steps": len(steps),
                        "validation_steps": [r["step"] for r in validations],
                    }
                )
    # BF16 autocast versus FP32 for the same CPU linear fixture. This is not a CUDA/SDXL tolerance.
    fp32, mixed = copy.deepcopy(initial), copy.deepcopy(initial)
    expected = fp32(inputs)
    expected.square().mean().backward()
    with torch.autocast("cpu", dtype=torch.bfloat16):
        actual = mixed(inputs)
    actual.float().square().mean().backward()
    assert actual.dtype == torch.bfloat16
    assert all(
        p.dtype == torch.float32 and p.grad.dtype == torch.float32 for p in mixed.parameters()
    )
    precision_error = float((actual.float() - expected).detach().abs().max())
    assert precision_error <= 0.01
    # A missing/nonfinite gradient must stop before publication of an optimizer step.
    failures = []
    for kind in ("missing_gradient", "nonfinite_loss", "nonfinite_gradient"):
        model = copy.deepcopy(initial)
        learned = list(model.parameters())
        if kind == "missing_gradient":
            learned.append(torch.nn.Parameter(torch.ones(1)))
        if kind == "nonfinite_gradient":
            learned[0].register_hook(lambda grad: grad * float("nan"))
        published = []

        def bad_loss(rows, model=model, kind=kind):
            value = model(inputs[:1]).square().mean()
            return value * float("nan") if kind == "nonfinite_loss" else value

        try:
            optimize(
                model,
                learned,
                training_config.resolve(base, samples),
                bad_loss,
                lambda: [],
                lambda: {},
                lambda *row, published=published: published.append(row),
                lambda: None,
            )
        except (ValueError, RuntimeError) as error:
            assert not any(row[0] == "step" for row in published)
            failures.append({"case": kind, "error": str(error), "optimizer_step_published": False})
        else:
            raise AssertionError(kind + " was accepted")
    print(
        json.dumps(
            {
                "python": sys.version,
                "torch": torch.__version__,
                "device": "cpu",
                "fp32_update_tolerance": tolerance,
                "observations": observations,
                "bf16_fixture_output_tolerance": 0.01,
                "bf16_fixture_output_error": precision_error,
                "refused_failures": failures,
                "optimization_module_sha256": sha256(
                    (
                        Path(__file__).resolve().parents[1] / "src/itov/training_optimization.py"
                    ).read_bytes()
                ),
                "limits": "Actual Torch CPU fixture checks; no SDXL, CUDA resource "
                "or model-quality acceptance.",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
