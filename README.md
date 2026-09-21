# ITOV

ITOV is a local ComfyUI tooling project. It provides workspace setup, environment diagnostics, exported API workflow validation, local server startup, single-workflow execution with verified output downloads, versioned preset/LoRA catalogs, deterministic batch planning, and qualified sequential execution. Runtime code uses the Python standard library and does not require installing Torch into the development environment.

To combine a directory of Markdown specifications into one searchable PDF, run
`.\markdown-to-pdf.ps1` (prompts for a path) or `.\markdown-to-pdf.ps1 "C:\path\to\specs"`.
See the [converter guide](tools/markdown_pdf/README.md) for exclusions and output options.

The original material in `docs/01_*` through `docs/10_*` is a design reference, not an executable installation guide. Read the [development review](docs/development-review.md) for defects, current compatibility findings, and the implementation sequence.

## Quick start

From PowerShell in this repository:

```powershell
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
uv sync --locked
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

Imports verify asset hashes and reject stale heads. Each revision keeps the catalog and its hash-chained ledger together in an immutable snapshot. Interrupted transactions require explicit `catalog recover`; ordinary reads never repair data. See [catalog schemas, commands, and recovery](docs/catalog-and-ledger.md) for the contract and qualification boundaries. Automated promotion remains a later development stage.

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

The real local acceptance run uses the neutral image-copy workflow: seven jobs across sequential, lost-acknowledgement, and timeout/resume cases produced pixel-identical images. Checkpoint/LoRA inference, video/audio integration, and parallel GPU execution remain unqualified.

## Development

Follow the gates in the [development review](docs/development-review.md) and update [CHANGELOG.md](CHANGELOG.md) with each completed development increment. Record passing checks and any unfulfilled runtime or rendering acceptance separately.

```powershell
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
uv run --locked pytest --basetemp .test-tmp
uv run --locked ruff check .
uv run --locked ruff format --check .
uv build
```

Automated tests use temporary workspaces, a local HTTP fixture, and owned child processes for lock contention and crash recovery. Real runtime qualification is recorded separately. The [development review](docs/development-review.md) records completed gates, acceptance limits, and the next stage.
