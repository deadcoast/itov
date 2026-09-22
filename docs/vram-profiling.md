# Measured VRAM profiles and guarded admission

ITOV 0.9.0 measures exact, explicitly seeded workloads inside the configured ComfyUI process. Profiles support an optional conservative check before sequential submission. They do not authorize concurrent GPU execution or promise that a future peak will fit.

## Reconciliation with Part 11

The original [VRAM design](design_spec/11_VRAM_budget.md) remains a design input. Its LoRA strength exponent, attention multipliers, block-swap savings, asset fallback costs and fixed memory estimates have not been calibrated against the installed stock loaders. ITOV does not use those formulas. Missing profiles result in refusal; no interpolation across dimensions, duration, prompts, LoRA strengths or model combinations is performed.

Calling Torch memory functions from the controller would measure the wrong process. The observer runs under ComfyUI's configured Python and wraps its existing `PromptExecutor.execute` after ComfyUI has initialized its allocator environment. It synchronizes before and after each prompt, resets allocator peak counters, and records allocated/reserved peaks separately from CUDA global free/total samples taken every 50 ms. No sampler, model weights, precision or custom nodes are changed.

PyTorch allocator counters exclude memory managed by other allocators. This runtime uses Comfy-Aimdo dynamic memory, so the difference matters. With `cudaMallocAsync`, a reserved peak may sum pool high-water marks; it is not necessarily simultaneous physical occupancy. See the primary [PyTorch CUDA memory notes](https://docs.pytorch.org/docs/main/notes/cuda.html) and [reserved-peak API](https://docs.pytorch.org/docs/main/generated/torch.cuda.memory.max_memory_reserved.html). NVIDIA snapshots provide independent whole-device identity and pressure; Windows WDDM does not supply usable per-process memory figures in `nvidia-smi`. See [NVIDIA's documentation](https://docs.nvidia.com/deploy/nvidia-smi/).

Global CUDA samples include display, cache and other clients' allocations, and can miss short peaks. Profiles retain sampling times, gaps, allocator peaks, errors, prompt/request IDs and job-record hashes. A fresh process means an empty ComfyUI execution/model cache; it does not imply an empty GPU or a cold operating-system disk cache.

## Capture a workload

Use one observer process at a time in the workspace. Keep other GPU jobs idle during calibration. The qualification run uses `workspace/itov-vram.toml`, in the same workspace as `itov.toml`, with the same root/interpreter and URL `http://127.0.0.1:8190`. This local configuration is ignored by Git. If creating your own, copy those settings explicitly and select an unused loopback port.

```powershell
uv run --locked itov vram server --config workspace/itov-vram.toml --print-command
uv run --locked itov vram server --config workspace/itov-vram.toml
```

The foreground process uses dedicated user data, SQLite index and scratch/temp paths under `workspace/state/vram/`. Redirected paths are refused before ComfyUI's temp cleanup. Stock runtime/model files are unchanged. The ordinary server can remain idle on its own port, but its retained caches still contribute to device pressure.

In another terminal, prepare and import a supported image, video or audio specification with `count: 2` and fresh explicit seeds, then save its plan. Import all needed presets before planning. Follow the existing [image](image-inference.md), [video](image-to-video.md) or [audio](audio-and-av.md) preparation flow. Capture runs actual model jobs and permanently reserves their seeds:

```powershell
uv run --locked itov batch qualify workspace/state/plans/PLAN_ID.json --config workspace/itov-vram.toml --save --json
uv run --locked itov vram capture workspace/state/plans/PLAN_ID.json --qualification workspace/state/qualifications/QUALIFICATION_ID.json --config workspace/itov-vram.toml --json
```

Capture requires a fresh observer, one exact workload and two to four jobs. The first observation is `cold_process`; subsequent observations are `warm_exact` only if the previous workload matches. Stop that owned observer after completion, restart it, qualify another plan with unused seeds, and capture again. Admission requires at least two distinct cold sessions and two distinct warm sessions. A duplicated profile cannot satisfy repetition.

Profiles are immutable, canonical, hash-addressed JSON under `state/vram/profiles/`. Detailed telemetry remains under `state/vram/telemetry/SESSION_ID/`. Failed or incomplete capture evidence is retained and cannot admit work. Hashes detect inconsistency; they do not authenticate evidence against an operator who rewrites all records.

## Identity and policy

The workload key removes only explicit sampler seeds and output filename prefixes, and normalizes lossless integer/float coercion. All other graph content remains bound, including model pins, input images, prompt text, dimensions, duration, precision selections, steps and LoRA strengths. Runtime identity binds the stock source files, node schemas, launch arguments, package versions, CUDA/cuDNN, allocator and recorded environment, GPU UUID and driver. For the instrumented runtime only, the stock VAE filename choice list is sorted: ComfyUI builds part of it from a set, while every qualified VAE selection is explicit and byte-pinned. Changing available choices or defaults still changes the binding. Changing the observer code also invalidates prior profiles. Session ID, PID and start time may vary across calibration processes.

Policy version 1 requires successful observations at most seven days old, at least three samples per execution, and no sample gap or uncovered boundary exceeding one second. For each exact workload:

```text
additional envelope = max over observations of:
    sampled device peak minus that execution's initial device use
    PyTorch peak allocated
    PyTorch peak reserved

current use = max(NVIDIA used, CUDA global total minus free)
capacity = min(NVIDIA total, CUDA global total)
required = current use + envelope + ceil(20% of envelope) + 2 GiB
```

Admission requires `required <= capacity`, an idle server/observer and repeated matching evidence. Current cached allocations are not subtracted. A process that has executed a different workload is refused until a matching cache state can be demonstrated; restart the observer for a fresh state. The 20% margin, 2 GiB reserve and seven-day expiry are explicit conservative policy choices, not statistical confidence bounds or calibrated predictions. Host RAM and cross-process reservations remain outside this gate.

```powershell
uv run --locked itov vram check workspace/state/plans/NEW_PLAN_ID.json --profile workspace/state/vram/profiles/FIRST_PROFILE_ID.json --profile workspace/state/vram/profiles/SECOND_PROFILE_ID.json --config workspace/itov-vram.toml --save --json
```

Exit code 0 means admitted at that observation, 1 means refused, and 2 indicates a configuration/validation error. `--workers 2` is always refused with `parallel_execution_not_qualified`. A check queues nothing and reserves no seeds or GPU memory.

## Guard an actual sequential batch

Qualify the new plan against the current observer, then bind the profiles when running it:

```powershell
uv run --locked itov batch run workspace/state/plans/NEW_PLAN_ID.json --qualification workspace/state/qualifications/NEW_QUALIFICATION_ID.json --vram-profile workspace/state/vram/profiles/FIRST_PROFILE_ID.json --vram-profile workspace/state/vram/profiles/SECOND_PROFILE_ID.json --config workspace/itov-vram.toml
uv run --locked itov batch resume workspace/state/plans/NEW_PLAN_ID.json --config workspace/itov-vram.toml
```

The first refusal happens before claiming seeds. An admitted batch stores its exact profiles/policy in an immutable guard and records the guard hash in the same database transaction as the batch and seed reservations. Fresh headroom, qualification, cache and queue checks run before each new POST. A used process must retain a successful matching last-execution measurement; failed or missing telemetry cannot establish its cache state. Later refusal pauses the batch with its reservations intact. Omitting the profile options on resume retains the guard; missing or changed guard data fails closed. Already accepted prompts remain owned and observable. Completed resume verifies collected artifacts without runtime HTTP.

This uses the existing whole-workspace dispatcher lock. It cannot exclude another workspace or an external ComfyUI client, so there remains a check-to-submission race outside ITOV's ownership. A device-wide reservation protocol and actual isolated-worker tests are required before parallel admission.

## Evidence and remaining gate

The [final measurements](evidence/stage-09-vram-20260921.json), [held-out admission exercise](evidence/stage-09-admission-20260921.json), [final video admission](evidence/stage-09-video-admission-20260921.json) and [source/package checks](evidence/stage-09-verification-20260921.json) separate model execution from synthetic refusal/recovery tests. The [initial measurements](evidence/stage-09-initial-measurements-20260921.json) remain available but are invalid for the corrected observer identity. The [initial startup failure](evidence/stage-09-initial-startup-20260921.json) occurred before model submission and is retained.

The first video admission attempt correctly refused because VAE choice ordering changed between process launches. Five [read-only observer startups](evidence/stage-09-schema-order-20260921.json) isolated that schema difference. The [measurements before this correction](evidence/stage-09-initial-schema-measurements-20260921.json) and initial refusal remain available; both video calibration sessions were repeated after the narrow ordering correction. No capacity margin was reduced to obtain acceptance.

Final RTX 5090 observations below are maxima across four executions per workload. Memory columns use GiB (1024Ã‚Â³ bytes); the device column is sampled usage, not a per-job allocator peak.

| Workload | Allocated peak | Reserved peak | Device sample peak | Samples per job |
| --- | ---: | ---: | ---: | ---: |
| audio | 0.555 | 0.656 | 4.577 | 45â€“89 |
| sdxl-base | 2.175 | 2.750 | 10.920 | 49â€“115 |
| sdxl-lcm | 2.175 | 2.750 | 10.920 | 18â€“91 |
| wan22 | 3.824 | 5.281 | 27.404 | 241â€“321 |

Held-out fresh-process checks admitted audio, SDXL base and SDXL+LCM. Two new audio jobs then completed under the persistent guard, and completed replay made zero runtime requests. The final video check had matching repeated profiles but refused headroom: 38.391 GiB required by policy against 31.816 GiB capacity. That conservative refusal is retained despite successful calibration renders; it does not prove the video would OOM.

Stage 9A qualifies the bounded measurement and guarded sequential path. Stage 9B remains open: device-wide ownership, isolated worker state and artifacts, contention/crash recovery, host-memory budgeting, and an explicitly bounded real parallel workload. Image/video quality, human listening and semantic synchronization remain separate open acceptance gates in [TODO.md](../TODO.md).
