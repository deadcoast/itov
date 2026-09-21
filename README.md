# ITOV

ITOV is a local ComfyUI tooling project. The first development stage provides workspace setup, environment diagnostics, and validation of exported API workflows. Runtime code uses the Python standard library and does not require installing Torch into the development environment.

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

The retained `ComfyUI_windows_portable_nvidia_cu126.7z` is not extracted or installed by these commands. Review current [official portable installation guidance](https://docs.comfy.org/installation/comfyui_portable_windows) before selecting a runtime for the RTX 5090.

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

The included example links `LoadImage` to `SaveImage` and expects `example.png` in ComfyUI's input directory. It is a neutral preflight example; it has not been rendered as part of this development stage.

Checks cover API graph shape, duplicate JSON keys, malformed or missing links, cycles, installed classes, required inputs, declared choices and numeric bounds, output indices, link types, and the presence of an output node when node metadata is supplied. Dynamically declared custom-node inputs are not rejected solely because they are absent from static metadata. Node-specific `VALIDATE_INPUTS`, file availability checks implemented by nodes, GPU execution, and media quality still require ComfyUI execution. These commands make no queue submissions.

Exit codes are `0` for passed checks, `1` for a failed diagnostic or invalid graph, and `2` for configuration, file, argument, or HTTP errors. The JSON response states whether validation covered only graph structure or node schemas.

## Development

```powershell
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
uv run --locked pytest --basetemp .test-tmp
uv run --locked ruff check .
uv run --locked ruff format --check .
uv build
```

Tests use temporary workspaces and a local HTTP fixture. They establish CLI and protocol behavior, not real model execution. The [development review](docs/development-review.md) records the remaining runtime acceptance gate and subsequent stages.
