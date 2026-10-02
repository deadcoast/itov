# Describe and generate a base image

`inference spec` builds a normal version-two request from an image description.
It uses the pinned SDXL base without adapters, at 1024×1024, 20 steps and CFG 7
unless explicitly changed. No hand-written JSON or catalog import is required.
Model quality remains unaccepted: the
[D-02.1 comparison](d021-image-results-20260926.md) completed and rejected this
recipe for missing/extra objects, shape and layout failures. Native-size defaults
do not imply that these failures are fixed.

Use an initialized workspace and its configured, installed SDXL checkpoint. Start
the configured ComfyUI server before planning. Installed PowerShell example:

```powershell
$config = 'C:\path\to\workspace\itov.toml'
$request = itov inference spec --prompt 'One red ceramic teapot on a plain wooden table, studio photograph' --seed 926202600 --save --config $config --json | ConvertFrom-Json
itov inference prepare $request.saved_path --config $config
$plan = itov inference plan $request.saved_path --save --config $config --json | ConvertFrom-Json
itov inference run $plan.saved_path --config $config
```

In a source checkout, prefix commands with `uv run --inexact --locked` and use the
repository-local `UV_CACHE_DIR`. `workspace guide models` includes this path.

## Settings and saved state

- `--prompt` is the requested image description; `--negative-prompt` is optional
  and empty by default. Neither is rewritten or supplemented automatically.
- `--width` and `--height` default to 1024. The existing explicit range remains
  512..1024, in multiples of 64. The [ComfyUI SDXL reference](https://comfyanonymous.github.io/ComfyUI_examples/sdxl/)
  recommends roughly one megapixel; lower resolutions remain available for
  declared comparisons, not an automatic memory-pressure fallback.
- `--seed` defaults to 0; `--count` defaults to 1 and permits up to 16 consecutive
  seeds. Choose an unused seed range for a new run. Repeating a saved request does
  not grant permission to duplicate an accepted job or erase seed reservations.
- `--steps` defaults to 20; `--cfg-milli` defaults to 7000 (CFG 7). Existing
  `dpmpp_2m`/`karras` bounds are enforced. Settings are exposed without claiming
  that all combinations produce useful images.
- `--checkpoint` selects a local loader name for the pinned SDXL base bytes. It
  does not authorize a different checkpoint, download a model or apply an adapter.

Without `--save`, the command returns a preview and writes nothing. With `--save`,
the specification is published under `state/inference/specifications/` using its
content identity. Repeating the same save is idempotent; changed existing bytes
are refused and preserved. Editing the prompt/settings creates a different
specification. Drafting does not read model files, contact a server, reserve seeds
or start generation. `prepare` checks the exact model bytes; `plan` qualifies the
live runtime, and `run` owns actual submission.

Inspect every generated image for subject count, identity, layout and framing.
The PNG decoder and a successful command exit cannot judge those requirements.
The existing candidate remains rejected; this base-only workflow does not train
or activate it. Use [status/resume/replay](candidate-inference.md) for the saved
plan rather than starting a replacement job after a timeout.
