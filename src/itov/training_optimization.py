"""Optional Torch optimization loop; importing this module does not import Torch."""

from __future__ import annotations

import time

from itov.catalog import require


def optimize(
    model,
    learned,
    effective,
    loss,
    evaluate,
    observe,
    emit,
    synchronize,
    *,
    restore=None,
    checkpoint=None,
):
    """Fixed-size micro-batches, one clipped AdamW update per accumulated mean loss."""
    import torch

    require(
        bool(learned) and all(p.requires_grad and p.dtype == torch.float32 for p in learned),
        "Optimization requires FP32 trainable adapters",
    )
    config = effective["config"]
    settings = config["optimizer"]
    optimizer = torch.optim.AdamW(
        learned,
        lr=config["peak_learning_rate_trillionths"] / 10**12,
        betas=tuple(n / 10**6 for n in settings["betas_millionths"]),
        eps=settings["epsilon_trillionths"] / 10**12,
        weight_decay=settings["weight_decay_millionths"] / 10**6,
        foreach=settings["foreach"],
        fused=settings["fused"],
    )
    steps, validation = restore(optimizer) if restore else ([], [])

    def check_validation(step):
        synchronize()
        started = time.monotonic_ns()
        model.eval()
        with torch.no_grad():
            losses = evaluate()
        synchronize()
        row = {
            "step": step,
            "losses": losses,
            "elapsed_ns": time.monotonic_ns() - started,
            "resources": observe(),
        }
        emit("validation", step, row)
        validation.append(row)

    if not steps:
        check_validation(0)
    for planned in effective["steps"][len(steps) :]:
        model.train()
        optimizer.zero_grad(set_to_none=True)
        for group in optimizer.param_groups:
            group["lr"] = planned["learning_rate_trillionths"] / 10**12
        synchronize()
        started = time.monotonic_ns()
        losses = []
        for batch in planned["micro_batches"]:
            measured = loss(batch)
            require(
                measured.ndim == 0
                and measured.dtype == torch.float32
                and bool(torch.isfinite(measured)),
                "Nonfinite/incorrect FP32 mean loss",
            )
            (measured / len(planned["micro_batches"])).backward()
            losses.append(round(float(measured.detach()) * 10**9))
        require(
            all(
                p.grad is not None
                and p.grad.dtype == torch.float32
                and bool(torch.isfinite(p.grad).all())
                for p in learned
            ),
            "Missing/nonfinite/non-FP32 LoRA gradient",
        )
        norm = torch.nn.utils.clip_grad_norm_(
            learned,
            settings["clip_norm_millionths"] / 10**6,
            error_if_nonfinite=True,
            foreach=False,
        )
        optimizer.step()
        require(
            all(p.dtype == torch.float32 and bool(torch.isfinite(p).all()) for p in learned),
            "Nonfinite/non-FP32 updated adapter",
        )
        for parameter in learned:
            state = optimizer.state[parameter]
            require(int(state["step"].item()) == planned["step"], "Optimizer state step differs")
            require(
                all(
                    state[key].dtype == torch.float32 and bool(torch.isfinite(state[key]).all())
                    for key in ("exp_avg", "exp_avg_sq")
                ),
                "Nonfinite/non-FP32 AdamW state",
            )
        synchronize()
        row = {
            **planned,
            "micro_loss_billionths": losses,
            "loss_billionths": (sum(losses) + len(losses) // 2) // len(losses),
            "gradient_norm_billionths": round(float(norm) * 10**9),
            "gradient_tensors": len(learned),
            "optimizer_state_step": planned["step"],
            "optimizer_state_fp32_finite": True,
            "adapter_fp32_finite": True,
            "elapsed_ns": time.monotonic_ns() - started,
            "resources": observe(),
        }
        emit("step", planned["step"], row)
        steps.append(row)
        print(
            f"Optimizer step {planned['step']}/{config['optimizer_steps']}: "
            f"loss_billionths={row['loss_billionths']}, "
            f"lr_trillionths={planned['learning_rate_trillionths']}",
            flush=True,
        )
        if planned["step"] in effective["validation_steps"]:
            check_validation(planned["step"])
        if checkpoint:
            optimizer.zero_grad(set_to_none=True)
            checkpoint(optimizer, steps, validation)
    optimizer.zero_grad(set_to_none=True)
    return steps, validation
