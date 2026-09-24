# ITOV

ITOV is an incomplete local ComfyUI application under development. Its current foundations cover workspace diagnostics, workflow validation, job records, catalogs, deterministic batches, a bounded Windows concurrency trial, lexical constraints and a small SDXL training/evaluation prototype. These low-level integrations still need substantial work to form a cohesive application. The core CLI uses the Python standard library; model training uses a separate optional environment.

The [current TODO](TODO.md) and [source audit](docs/development-audit-20260922.md) track the remaining architecture, dataset/training, autonomous evaluation and end-to-end work. The mandatory human-review gate has been shelved by the user. Assistant reviews record methods, limitations and case evidence; the current curated candidate is rejected on observed quality failures. Earlier successful tests and example runs establish only their documented scope.

Start with the [operator runbook](docs/operator-runbook.md) for the supported sequence from setup through execution, recovery and completed replay. Result commands now use consistent text/JSON outcomes, artifact references and suggested next commands. JSON adds `_cli` metadata without changing saved evidence; incomplete status/retirement returns exit 1, including batch status and abandonment.

To combine a directory of Markdown specifications into one searchable PDF, run
`.\markdown-to-pdf.ps1` (prompts for a path) or `.\markdown-to-pdf.ps1 "C:\path\to\specs"`.
See the [converter guide](tools/markdown_pdf/README.md) for exclusions and output options.

The original material in `docs/design_spec/` is a design reference, not an executable installation guide. Read the [development review](docs/development-review.md) for defects, current compatibility findings, and the implementation sequence.

## Quick start

From PowerShell in this repository:

```powershell
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
uv sync --inexact --locked
uv run itov init
uv run itov doctor
```

`init` creates `workspace/itov.toml` and local input, output, model, template, workflow, log, and state directories. Running it again refuses to overwrite the configuration. `workspace/` and downloaded model weights are ignored by Git.

The default configuration expects an extracted portable installation at `AI/ComfyUI/ComfyUI_windows_portable/ComfyUI`. For an existing installation elsewhere:

```powershell
uv run itov init workspace --comfyui-root 'D:\AI\ComfyUI_windows_portable'
```

For a manual installation, also pass `--comfyui-python 'D:\AI\ComfyUI\.venv\Scripts\python.exe'`. Paths in the configuration resolve relative to the configuration file, regardless of the directory from which later commands run.

`doctor` reports missing prerequisites and reads `/system_stats` and `/object_info` from the configured server. `--offline` skips HTTP checks. Use `--json` for machine-readable output and `--timeout 5` to adjust each probe's timeout. NVIDIA diagnostics are intentional for this project's documented RTX 5090 target. Finding the GPU is separate from validating a working Torch/CUDA runtime.

The local development workspace now has a checksum-verified ComfyUI v0.37.0 NVIDIA portable runtime. A fresh clone still needs a runtime: binaries and models are ignored by Git. The older `ComfyUI_windows_portable_nvidia_cu126.7z` remains untouched. See [runtime setup and job execution](docs/runtime-and-jobs.md) for the qualified release, launch commands, and remaining acceptance limits.

## Workflow validation

Export a workflow with ComfyUI's **Export (API)** action. Validate its structure without a running server:

```powershell
uv run itov workflow validate examples/image-copy.api.json
```

Validate against the installed node registry or a saved `/object_info` response:

```powershell
uv run itov workflow validate path\to\workflow.api.json --live
uv run itov workflow validate path\to\workflow.api.json --object-info path\to\object_info.json --json
```

The included example links `LoadImage` to `SaveImage` and expects `example.png` in ComfyUI's input directory. It has completed on the qualified local runtime with pixel-identical input/output. This establishes a real API and image-I/O path, not model inference or video generation.

Checks cover API graph shape, duplicate JSON keys, malformed or missing links, cycles, installed classes, required inputs, declared choices and numeric bounds, output indices, link types, and the presence of an output node when node metadata is supplied. Dynamically declared custom-node inputs are not rejected solely because they are absent from static metadata. Node-specific `VALIDATE_INPUTS`, file availability checks implemented by nodes, GPU execution, and media quality still require ComfyUI execution. These commands make no queue submissions.

Exit codes are `0` for passed checks, `1` for a failed diagnostic or invalid graph, and `2` for configuration, file, argument, or HTTP errors. The JSON response states whether validation covered only graph structure or node schemas.

## Run a workflow

Start the configured runtime in one terminal:

```powershell
uv run --locked itov server start
```

In another terminal, create the neutral sample input if it is absent, then submit the example:

```powershell
uv run --locked python scripts/create_preflight_image.py
uv run --locked itov job run examples/image-copy.api.json
```

The input helper refuses to overwrite an existing image. Skip it when `workspace/input/example.png` already exists. Server startup binds to loopback and disables custom nodes by default; `--custom-nodes` opts into installed extensions.

Every submitted job receives a record under `workspace/state/jobs/`. A successful result includes exact output descriptors, local downloaded paths, byte counts, and SHA-256 hashes. Stop waiting with Ctrl+C or use `--wait-timeout`; the server job may continue. Resume from the printed record path:

```powershell
uv run --locked itov job wait 'workspace/state/jobs/REQUEST_ID.json'
```

Resume never resubmits a workflow. An uncertain submission without an acknowledged prompt ID is recorded as `submission_unknown` and needs inspection before another submission. See [job states and limits](docs/runtime-and-jobs.md#job-states-and-limits).

## Catalogs and revision history

Create and inspect the neutral catalog example:

```powershell
uv run --locked python scripts/create_catalog_example.py
uv run --locked itov catalog validate workspace/templates/neutral.catalog.json --check-files
uv run --locked itov catalog init
uv run --locked itov catalog show --json
```

The helper and `catalog init` refuse to overwrite existing data. To record a reviewed catalog, pass the head printed by `show`:

```powershell
uv run --locked itov catalog import workspace/templates/neutral.catalog.json --expected-head HEAD_FROM_SHOW
uv run --locked itov catalog verify --check-files --json
```

Imports verify asset hashes and reject stale heads. Each revision keeps the catalog and its hash-chained ledger together in an immutable snapshot. Interrupted transactions require explicit `catalog recover`; ordinary reads never repair data. See [catalog schemas, commands, and recovery](docs/catalog-and-ledger.md) and the separate [reviewed training promotion contract](docs/training-and-promotion.md). Training never automatically activates a candidate.

## Deterministic batch planning

After importing the neutral catalog, create a reviewed planning request and preview it:

```powershell
uv run --locked python scripts/create_batch_example.py
uv run --locked itov batch plan workspace/templates/neutral.batch.json
uv run --locked itov batch plan workspace/templates/neutral.batch.json --save
uv run --locked itov batch verify workspace/state/plans/PLAN_ID.json
```

Plans pin the catalog head and asset hashes, select presets and compatible declared LoRA stacks, enforce cooldowns and strength budgets, and retain expanded workflow payloads for deterministic replay. Requests declare their seed and loader-node bindings explicitly. Planning does not queue jobs or change render history. See [batch request contracts, selection, and limits](docs/batch-planning.md).

## Qualified sequential batches

With the stock local server running, qualify a saved plan and execute it explicitly:

```powershell
uv run --locked itov batch qualify workspace/state/plans/PLAN_ID.json --save
uv run --locked itov batch run workspace/state/plans/PLAN_ID.json --qualification workspace/state/qualifications/QUALIFICATION_ID.json
uv run --locked itov batch status workspace/state/plans/PLAN_ID.json
uv run --locked itov batch resume workspace/state/plans/PLAN_ID.json
```

Use the IDs printed by planning and qualification. The executor reserves seeds and job ownership atomically, rechecks qualification before each new submission, and advances only after verified output collection. Lost acknowledgements are reconciled from server ownership evidence; uncertain work is never automatically submitted again. Timeouts and Ctrl+C detach observation without cancelling server work. See [execution, resume, and qualification limits](docs/batch-execution.md), including safe abandonment of an unsubmitted remainder.

The stage-five acceptance run used the neutral image-copy workflow: seven jobs across sequential, lost-acknowledgement, and timeout/resume cases produced pixel-identical images. Subsequent stages completed the pinned image, silent-video, audio and audiovisual jobs described below. Parallel GPU execution remains unqualified.

## Pinned image inference

A-04 adds version-two inference with explicit model capabilities, sampler settings and ordered LoRA bindings. Use `inference capabilities` to inspect the bounded SDXL contract, then `inference prepare`, `plan --save`, `run`, `status`, `resume` and `replay --save`. The [candidate and stack runbook](docs/candidate-inference.md) covers trained-candidate identity, deployment, strength controls and incompatible-stack refusals. This route stages experimental candidates without catalog activation; the current candidate remains rejected on quality. Version-one preset/catalog workflows below remain supported.

The SDXL base and SDXL+LCM profiles prepare stock workflows with expected checkpoint/LoRA hashes, fixed sampler settings, and explicit seeds:

```powershell
uv run --locked itov inference prepare examples/sdxl-base.inference.json --json
# Import the printed catalog candidate with its printed expected head.
uv run --locked itov inference plan examples/sdxl-base.inference.json --save
```

Run the saved plan through `batch qualify` and `batch run`. Preparation requires the named model files and does not download or submit anything. [Image-inference guidance](docs/image-inference.md) covers the optional pinned download helper, both example specifications, import commands, and acceptance limits.

The local RTX 5090 completed two SDXL base and two SDXL+LCM jobs with distinct reserved seeds and verified 1024×1024 outputs. The [execution evidence and saved images](docs/image-inference.md#local-acceptance-evidence) establish this selected model pair's functional path. Visual inspection found recognisable subjects with object-count and shape errors; general media quality, other model combinations, and calibrated VRAM prediction remain open.

## Pinned image-to-video

Version 0.7.0 adds the stock Wan 2.2 TI2V 5B profile with pinned diffusion/text-encoder/VAE files and a source PNG. Prepare and plan the neutral example:

```powershell
uv run --locked itov video prepare examples/wan22.video.json --image-source docs/evidence/stage-06-output-02.png --json
# Import the printed catalog candidate with its printed expected head.
uv run --locked itov video plan examples/wan22.video.json --save --json
```

Then use `batch qualify` and `batch run`. Each collected MP4 must pass dimensions, frame count/rate, duration, complete decode, constant timestamps, and frame-variation checks before the next job. The local runtime completed two 640×640 clips, each 33 frames at 24 fps. Representative-frame inspection found an unrequested hand in one clip; functional execution passes while general motion/prompt quality remains open. See [video setup, commands, evidence, and limits](docs/image-to-video.md).

## Pinned audio and audiovisual output

Version 0.8.0 adds stock Stable Audio Open 1.0 generation and composition of completed audio/video jobs:

```powershell
uv run --locked itov audio prepare examples/stable-audio.audio.json --json
# Import the printed catalog candidate with its printed expected head.
uv run --locked itov audio plan examples/stable-audio.audio.json --save --json
# Qualify and run through the existing batch commands.
uv run --locked itov av mux examples/stage-08-pair-01.av.json --json
```

The mux example references the completed jobs in this qualification workspace. For new work, bind your own completed job IDs, record hashes and artifact hashes. Audio is validated by full decode; composition retains a precisely aligned WAV, copies all video frames, and verifies both streams' timing. Repeating `av mux` verifies its immutable output. See [setup, contracts, commands and retained audio/A/V samples](docs/audio-and-av.md). Functional media checks pass for two neutral pairs; listening quality and semantic/lip synchronization remain open.

## Measured VRAM admission

Version 0.9.0 adds `vram server`, `vram capture` and `vram check`, plus optional `batch run --vram-profile` guards. The observer measures memory inside ComfyUI and keeps allocator peaks separate from sampled whole-device usage. Admission requires repeated cold/warm evidence for the exact workload and runtime, with conservative margins and fresh checks before each submission. Missing, stale or mismatched evidence is refused; resume retains its guard.

See [VRAM setup, commands, policy and evidence](docs/vram-profiling.md). These VRAM commands support sequential execution. Managed parallel workers use the separate [ownership and qualification path](docs/parallel-execution.md).

## Development

Use [TODO.md](TODO.md) as the working task list, including current stages, dependencies, newly discovered requirements, and evidence needed for completion. Follow the gates in the [development review](docs/development-review.md) and update [CHANGELOG.md](CHANGELOG.md) with each completed increment. Record passing checks and any unfulfilled runtime or rendering acceptance separately.

```powershell
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
uv run --locked pytest --basetemp .test-tmp
uv run --locked ruff check .
uv run --locked ruff format --check .
uv build
```

Automated tests use temporary workspaces, a local HTTP fixture, and owned child processes for lock contention and crash recovery. Real runtime qualification is recorded separately. The [development review](docs/development-review.md) records completed gates, acceptance limits, and the next stage.

## Managed parallel audio trials

ITOV 0.10.0 adds `parallel calibrate`, `parallel qualify`, `parallel resume/recover` and `device status/recover`. Two isolated Windows workers share one workspace seed registry and a same-user GPU lease. Repeated exact-workload calibration feeds aggregate GPU and host-memory admission. See the [commands, ownership scope, recovery and evidence](docs/parallel-execution.md).

Eight real calibration jobs passed. The first parallel trial refused insufficient host commit before submission; after memory was freed, two audio jobs passed unchanged admission and overlapped for 4.087 seconds. Distinct decoded FLACs, zero-HTTP completed replay and confirmed worker shutdown passed. [Live qualification and completion evidence](docs/parallel-execution.md#evidence) establish this bounded Windows/audio path; GPU-kernel overlap, speedup and media quality remain unqualified.

## Trigger and scene validation

ITOV 0.11.0 adds offline catalog/plan trigger collision review and explicit scene constraints:

```powershell
uv run --locked itov trigger lint examples/trigger.rules.json --json
uv run --locked itov scene lint examples/neutral-image.scene.json --plan PATH_TO_SAVED_PLAN --save --json
```

Rules bind supplied vocabulary bytes; scene constraints check the actual selected LoRAs and positive/negative text in replayed plans. Reports preserve provenance and use aliases only as labels; activation tokens and prompts are never rewritten. The included vocabularies are demonstration operator policy. See [contracts, examples, limits and evidence](docs/triggers-and-scenes.md). Passing lexical checks does not prove trigger activation or rendered-media quality; the current real LCM entry has no declared triggers.

## Bounded SDXL LoRA training

ITOV 0.12.0 adds explicit dataset preparation, pinned training plans, one owned Windows GPU worker, technical evaluation and reviewed promotion:

New local and retained Met datasets can use [transactional import and recovery](docs/dataset-import.md): `itov dataset import DECLARATION --source-root INPUTS --config WORKSPACE/itov.toml`. It fully decodes and transforms declared images, retains failed attempts and publishes complete bundles. Preparation requires the optional `dataset` extra (Pillow 12.3.0), available in the checkout dev environment, or `--image-python` pointing to that dependency. `dataset status`, `recover` and `verify` expose progress and commit integrity. The older commands below remain available for existing version-one data.

[Dataset review and freezing](docs/dataset-review.md) add all-pair content/perceptual observations, stable attributed work/creator groups, leakage checks and explicit caption/target judgments. `dataset inspect`, `freeze` and `review-verify` preserve exclusions and freeze the selected split/captions. `dataset curate --freeze` binds a newly imported Met selection into training qualification. The reviewed pilot now selects two training works and one validation work; it remains too small to establish useful model quality, and the existing candidate remains rejected.

```powershell
uv run --locked itov dataset prepare workspace/training/data/neutral-geometry-v1/dataset.json --json
uv run --locked itov training plan examples/sdxl-neutral.training.json --save --json
uv run --locked itov training run workspace/state/training/plans/PLAN_ID.json --gpu GPU_UUID --json
uv run --locked itov evaluation assess workspace/state/training/plans/PLAN_ID.json --save --json
uv run --locked itov training candidate workspace/state/training/plans/PLAN_ID.json --save --json
uv run --locked itov promotion prepare workspace/state/training/plans/PLAN_ID.json --json
```

The local smoke trial completed eight rank-four optimizer steps, exported/reloaded finite weights and produced paired held-out diagnostics. Candidate export preserves tensor payload bytes while converting names for stock ComfyUI; a real fixed-seed comparison and complete loader mapping passed. Images still miss the intended object count/composition. Smoke-data promotion is always refused, and the main catalog is unchanged. See [environment, dataset, commands, failure evidence and next quality gate](docs/training-and-promotion.md). Training dependencies are separate and optional; examples pin this workspace's files, which a fresh checkout must provision and revalidate.

Training now distinguishes worker completion, validated artifacts and separate candidate assessment. `training status` rechecks saved successful artifacts and identifies failed boundaries without rewriting historical records. New attempts use `artifacts_validated` only after shared technical checks pass. See [training states and interrupted-publication recovery](docs/training-result-states.md).

A-05 adds immutable internal records for validated results, evaluation conditions and review decisions. Review-packet generation shares one validated result and weight snapshot within the command, then rehashes its observed inputs before publication. Saved result, candidate, packet and review formats retain their existing meanings. See [record boundaries, compatibility and measured cost](docs/assessment-records.md).

Deployed evaluation now has supported `evaluation plan/run/status/resume/replay/abandon` commands. Plans stage the validated candidate, freeze runtime and sampler bindings, and cover every case/seed with base/adapter and plain/trigger comparisons. Resume observes owned jobs without duplicate submission; replay verifies the complete PNG matrix offline. See the [deployed evaluation runbook and limits](docs/deployed-evaluation.md). Technical completion does not accept or promote the candidate.

Execution now shares workspace and same-user device ownership across ordinary jobs, batches, evaluation, training and managed parallel workers. New client submissions use the bounded Windows/single-local-NVIDIA-GPU profile. Detached or uncertain server requests retain their lease until positively observed terminal; externally controlled servers and unrelated requests are preserved. See [ownership, supported scope and recovery](docs/execution-ownership.md).
