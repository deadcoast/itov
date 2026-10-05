# Configured SDXL optimization (B-03)

Training specification **version 3**, profile `sdxl-unet-lora-v2`, adds explicit optimization settings to the [curated training workflow](curated-quality-review.md). Plans retain the effective configuration, complete sample/noise order, learning rate for every update and validation steps. The worker checks that contract and retains measured step evidence. This is bounded single-device SDXL UNet LoRA training. [Version 4 adds durable checkpoints and explicit continuation](training-checkpoints.md) using the same optimization configuration.

Existing v1/v2 specifications and completed results retain their schemas and identities. A changed trainer creates a new plan. Version-three plans use the existing public training, assessment, review-packet, candidate and deployed-evaluation commands. Execution success remains separate from model-quality acceptance.

## Configuration

Keep the existing dataset, checkpoint, environment, model configuration, trigger and qualification references. Set `version` to `3`, `profile` to `sdxl-unet-lora-v2`, and add:

```json
"optimization": {
  "micro_batch_size": 1,
  "accumulation_steps": 2,
  "sampling": "shuffle_epoch",
  "schedule": "linear_warmup_decay",
  "warmup_steps": 2,
  "validation_every_steps": 2,
  "precision": "bf16-frozen-fp32-adapter-v1"
}
```

All fields are required; unknown fields and unsupported values are refused. `parameters.steps` counts **optimizer updates**, not examples or backward passes. `parameters.learning_rate_millionths` is the peak rate. Existing bounds remain 1–256 updates, ranks 4/8, 512px prepared RGB images, seeds below 2³², rates 1–1000 millionths and 60–3600 seconds. Other resolutions/ranks/precision modes, optimizers and distributed execution are outside this delivery.

| Setting | Supported values |
| --- | --- |
| Micro-batch / accumulation | `1/1`, `1/2`, `2/1`; effective batch is their product, at most two |
| `sampling` | `sequential` or `shuffle_epoch`; training split only |
| `schedule` | `constant` or `linear_warmup_decay` |
| `warmup_steps` | Zero for constant; 1 through `steps - 1` for warmup/decay |
| `validation_every_steps` | 1 through `steps`; always includes before-training and final validation |
| `precision` | Literal `bf16-frozen-fp32-adapter-v1` |

There must be at least as many training samples as the micro-batch size and at least one validation sample. Micro-batches are full: the sampler continues into the next epoch rather than dropping a tail or changing the effective batch. With odd-sized pools, a batch can cross an epoch boundary; every epoch and position is visible in the plan.

Sequential sampling cycles through sorted IDs. Shuffled epochs sort IDs by SHA-256 of ITOV canonical JSON `{seed, epoch, sample}`, with ID as a tie-breaker. This avoids dependence on global Python/Torch random state. Every training occurrence records its absolute zero-based `position`, epoch, sample ID and noise seed `(seed + position) mod 2³²`. Micro-batching changes the grouping, not that stream. Separate per-example CUDA generators draw noise and timesteps before concatenation. Validation samples never enter the optimizer stream.

Validation covers every held-out sample in sorted ID order with seed `(seed + 100000 + index) mod 2³²`, using the same noise at every observation. It runs before training, at each cadence multiple and at the final update without duplication. The model uses `eval()` and `no_grad()` for validation and returns to `train()` for optimization. These paired denoising losses do not establish image quality or independence from foundation-model training.

## Optimization and precision

The effective configuration records AdamW betas 0.9/0.999, epsilon 1e-8, weight decay 0.01, `foreach=False`, `fused=False`, and gradient norm clipping at 1.0. LoRA alpha equals rank, dropout is zero, and gradient checkpointing is enabled. These are fixed explicit choices. Learning rate is never automatically scaled with batch size.

Each update clears gradients once, computes each micro-batch's mean per-example MSE in FP32, divides by the accumulation count, and backpropagates. The worker checks every trainable gradient, clips once after accumulation and performs one optimizer update. AdamW state steps must equal the planned update. Receipts retain micro-batch losses rounded to billionths and their integer-rounded mean; backpropagation uses the original tensors.

Learning rates are recorded in trillionths (1e-12). For peak `P`, total updates `N`, warmup updates `W` and one-based update `s`, warmup uses `P * s / W` for `s <= W`; remaining updates use `P * (N - s + 1) / (N - W)`. Rates round down to trillionths. The first decay update therefore uses the peak, and the final update uses a positive rate. No post-final zero-rate update is applied. Eight updates with two warmup updates and peak 0.0001 use `50000000, 100000000, 100000000, 83333333, 66666666, 50000000, 33333333, 16666666` trillionths. Constant schedules use `P` throughout.

Frozen UNet/text computations use BF16; VAE encoding/decoding uses FP32. Adapters, gradients, loss reduction and AdamW moments remain FP32. CUDA autocast uses BF16 and TF32 is disabled. Missing/nonfinite gradients, nonfinite loss/state/weights, unexpected precision and unchanged adapter exports fail the worker. This BF16 profile does not use an FP16 GradScaler. Explicit seeds/order do not guarantee bitwise equality across batch shapes, devices or library builds.

[PyTorch's accumulation guidance](https://docs.pytorch.org/docs/2.14/notes/amp_examples.html#gradient-accumulation) explains loss normalization and optimizer-update boundaries; [Diffusers' SDXL guide](https://huggingface.co/docs/diffusers/main/training/sdxl) describes batch/accumulation and mixed precision. These are newer/general references. Executed checks use the recorded Torch 2.13.0+cu130, Diffusers 0.38.0 and PEFT 0.21.0 environment; B-03 makes no dependency upgrade.

## Run and inspect

Use the exact [reviewed dataset and curation references](dataset-review.md) in a new specification. The [local trial example](../../examples/sdxl-tabletop.training.json) binds the retained two-train/one-validation selection. It is the completed installed B-03 trial: in this checkout, its plan can be inspected and assessed immediately; attempting to run it again refuses the existing attempt. Declare a new specification ID for a separate experiment. A fresh checkout must provision its declared inputs before planning.

```powershell
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
$plan = uv run --inexact --locked itov training plan examples/sdxl-tabletop.training.json --save --json | ConvertFrom-Json
$plan.optimization
$planPath = "workspace/state/training/plans/$($plan.plan_id).json"
uv run --inexact --locked itov training run $planPath --gpu GPU_UUID --json
uv run --inexact --locked itov training status $planPath --json
uv run --inexact --locked itov evaluation assess $planPath --save --json
```

Start the configured server before training so its queue can be checked. Admission retains the workspace lock, shared same-user GPU UUID lease, native Job Object ownership, idle queue, memory floors and timeout/commit-pressure stop. The device registry is in AppData; a sandbox that forbids those writes prevents admission before worker execution. Do not substitute a private registry to bypass contention or permission failures.

The run folder contains `optimization/effective.json`, `optimization/precision.json`, and immutable `step-NNNNNN.json` / `validation-NNNNNN.json` events. Each update records micro-batch losses, rate/order, gradient norm/count, optimizer state step, finite/dtype checks, synchronized elapsed time, CUDA allocator counters and available host physical/commit memory. Final `optimization.json` collects the trace and is hash-bound from `result.json`.

Result validation reconstructs the effective settings from the specification and dataset. It requires exact steps/order/rates, gradient/precision evidence, mean-loss consistency, complete validation cadence, consistent cumulative allocator counters and matching event files. Missing, changed or resealed inconsistent evidence fails at `optimization_evidence`. Results still require finite serialized weights, reload evidence, held-out previews and the complete frozen four-condition quality matrix. Read-only validation imports no Torch, Diffusers or Pillow.

Allocator counters describe this process at recorded points; they are not whole-device peak telemetry or a general admission envelope. Synchronized section timings include finite checks and exclude subsequent event publication. Host readings are observations, not reservations. Partial events are diagnostic evidence, not resumable optimizer/RNG checkpoints. [Recovery](training-result-states.md) never silently retrains a failed attempt.

## Verification and limits

Run the optional actual-Torch CPU checks with:

```powershell
workspace/training/environment/Scripts/python.exe -I scripts/verify_training_numerics.py
```

The script compares all 12 batch/accumulation × sampler × schedule combinations against an independent full-batch FP32 update reference on a small linear model, with a predeclared 1e-6 parameter/loss tolerance. It checks cadence, train/eval/gradient modes, FP32 parameter/gradient preservation under CPU BF16 autocast, and refusal of missing/nonfinite gradients or loss. Its CPU BF16 output tolerance of 0.01 is specific to that fixture, not an SDXL/CUDA threshold.

[B-03 verification](../evidence/phase-b03-verification-20260924.json) and the [trial/visual review](../reports/2026-09-24/training-trials-20260924.md) record source/installed tests, six preregistered four-update SDXL trials, resource observations, matched batch/accumulation comparisons and inspected diagnostics. GPU trials cover both existing ranks and every introduced option using unchanged quality prompts/seeds. CPU checks cover all 12 combinations; the six GPU trials are representative combinations, not every allowed numeric seed/rate/budget or a guarantee for other corpora and machines.

No new model is accepted on loss, finite weights, export success or changed pixels. The previous candidate remains rejected; the short-run outputs retain their own observations and limitations. The three-work selection cannot establish corpus adequacy or useful learning. The B-03 trials did not test checkpoint restart; see the separate [B-04 contract and evidence](training-checkpoints.md). Experiment/checkpoint selection remains B-05.
