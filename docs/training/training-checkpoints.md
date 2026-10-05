# Durable training checkpoints and explicit continuation (B-04)

For preregistered endpoint comparisons, use the [B-05 experiment workflow](training-experiments.md). Its [fresh repetitions](../reports/2026-09-24/training-experiment-trial-20260924.md) exposed numerical variation despite matching order/RNG in the same pinned GPU environment. The exact B-04 match below remains bounded evidence for that trial; it is not a universal determinism guarantee.

Training specification **version 4** adds optimizer checkpoints to the [configured SDXL trainer](training-configuration.md). It keeps profile `sdxl-unet-lora-v2` and the existing 512px, rank-4/8, BF16 computation and FP32 adapter/AdamW bounds. Add the required policy:

```json
"checkpoints": {"every_steps": 2}
```

The cadence is an integer from one through the total optimizer-step budget. The worker saves after each cadence multiple and the final update. A checkpoint boundary follows gradient accumulation, clipping, the optimizer update, any scheduled validation, and gradient clearing. Mid-micro-batch/mid-update continuation is unsupported. Legacy v1/v2/v3 attempts remain readable; their exports and diagnostic step files do not contain enough state for restart.

## Inspect, recover, plan, execute

Use a new v4 specification for training; the [local checkpoint example](../../examples/sdxl-tabletop-checkpoint.training.json) uses the unchanged reviewed B-02 selection. Declare inputs and save/run its plan through the existing commands. After interruption:

```powershell
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
uv run --inexact --locked itov training status SOURCE_PLAN --json
uv run --inexact --locked itov training recover SOURCE_PLAN --json
uv run --inexact --locked itov training checkpoints SOURCE_PLAN --json
uv run --inexact --locked itov training resume-plan SOURCE_PLAN --checkpoint CHECKPOINT_JSON --save --json
uv run --inexact --locked itov training run NEW_PLAN --gpu GPU_UUID --json
uv run --inexact --locked itov evaluation assess NEW_PLAN --save --json
```

Replace the uppercase placeholders with the reported paths/UUID. `recover` is needed only when the recorded attempt remains `running` or `validating` after its controller and workers exit. It finalizes that attempt and releases only its matching abandoned lease; it never starts training. Already terminal attempts skip recovery.

`checkpoints` is a read-only observation. It reports complete, invalid and partial entries individually; the final checkpoint is complete but has no remaining updates. `resumable` means that the local bundle is complete with updates remaining, not that current execution inputs or ownership have passed admission. `resume-plan` selects one exact complete manifest, freshly validates execution inputs and requires a stopped terminal source attempt. It creates a distinct immutable plan, optionally saved with `--save`. It does not run a worker. Completed attempts may also be deliberately branched from an earlier checkpoint, preserving the original result.

Run the new plan using normal native ownership, same-user GPU lease, queue and memory checks. The continuation keeps the original **total** step budget, remaining sample order and schedule. It does not add more updates or restart warmup. Each attempt has the existing per-attempt wall-time bound. Repeated continuation does not create an implicit unlimited execution loop; each new attempt requires an explicit command.

## What is stored

Each run's `checkpoints/step-NNNNNN/` contains exactly two files:

- `state.safetensors`: FP32 adapter parameters and AdamW first/second moments, plus Torch CPU and selected-device CUDA RNG byte tensors. No pickle is loaded.
- `checkpoint.json`: a sealed manifest binding the tensor hash, ordered parameter names/shapes, completed update count, next sample position/rate, full optimization configuration, Python and NumPy RNG state, execution device/backend identity, and the exact optimization/validation history through that boundary.

AdamW step counters are shared at the committed update count, checked for every parameter before saving and restored for every parameter. Fixed optimizer hyperparameters come from the bound effective configuration. The learning-rate schedule is a stateless function of that configuration and the saved completed-step index; its next rate is independently reconstructed. Per-occurrence noise seeds and epoch positions are in the bound plan. The SDXL noise scheduler configuration is part of the pinned model configuration. The BF16 profile has no GradScaler state. Frozen model components and cached embeddings/latents are rebuilt from the same declared inputs, then adapter/optimizer/RNG state is restored before the next update.

Tensor files have bounded sizes, exact declared keys/shapes, contiguous complete payloads, finite FP32 values and nonnegative second moments. Core inspection imports no Torch, NumPy, Diffusers or Pillow. The optional worker separately checks its actual parameter order, precision and RNG restoration. Hashes bind bytes; they do not authenticate who produced a checkpoint or prove that an arbitrary fabricated state came from training.

The compatibility identity binds the specification (including ID, full budget and timeout), dataset, effective sample/rate plan, environment, trainer source hashes and policy. Resume refuses changed inputs/settings/source/environment. Execution additionally requires the same GPU UUID, name, driver, CUDA capability and backend flags. This deliberately excludes migration across devices, changed dependencies, changed data, modified schedules and larger training budgets. A v4 continuation can itself publish checkpoints and later serve as a new source.

## Publication and failures

The worker writes a uniquely named `.partial-UUID` directory, flushes/fsyncs the tensor payload, publishes the manifest, validates the complete bundle, then renames the directory to its final step name. An existing complete destination is refused. A failure or process interruption leaves its partial directory and previous complete checkpoints intact. Selection requires the final directory/manifest name, complete declared files and valid content; no automatic latest-checkpoint fallback occurs.

This is complete-bundle visibility and local file flushing, not a claim of transactional durability across arbitrary storage hardware or power loss. Published bundles are revalidated before planning, execution, restoration and result acceptance. Unsupported/corrupt state fails with retained evidence. A successful continuation writes into a new run folder; the source run's incomplete steps, checkpoint staging directories and failure record remain unchanged.

Only the selected committed checkpoint determines progress. Events written after it in the interrupted source are not adopted. The new run copies the committed prefix exactly and executes the remaining updates, so a partially executed update may be recomputed. Final validation requires that inherited history, every newly due complete checkpoint and the final trace agree. Missing or altered checkpoint evidence fails at `checkpoint_evidence`. Existing result/image/weight checks and quality gates still apply.

Current CUDA allocation/reservation readings belong to the current process. V4 peak counters carry the maximum observed high-water mark across the restored prefix and current segment so that the full trace remains monotonic; they are not a sum of allocations. Per-step timings remain segment observations. Final worker elapsed time describes the current attempt. None of these counters establishes a device-capacity or throughput guarantee.

## Verification boundary

[B-04 verification](../evidence/phase-b04-verification-20260924.json) separates dependency-free schema/corruption/lineage tests, actual Torch CPU restart checks, native GPU interruption/continuation and package/historical replay. The [native trial and visual review](../reports/2026-09-24/training-checkpoint-trial-20260924.md) records the actual interrupted publication, comparison results and persistent image failures. The CPU fixture deliberately consumes Python, NumPy and Torch randomness, uses BF16 linear/dropout computation and compares FP32 parameters and AdamW moments at a predeclared 1e-7 tolerance. It tests cadence that does not coincide with checkpoint boundaries and publication failure. Its checkpoint precision labels exercise the SDXL schema; it does not contain actual frozen SDXL components.

The bounded SDXL experiment declares separate tolerances before execution. Equality of continuation state/loss verifies restart semantics for that environment and budget. It does not establish image quality, useful learning or general determinism. The reviewed three-work corpus remains inadequate for broad model claims, and the previous candidate remains rejected. Experiment/checkpoint selection is B-05; broader quality work remains Phase C.
