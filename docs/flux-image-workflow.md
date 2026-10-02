# Experimental FLUX.2 Klein image workflow

The code supports a pinned FLUX.2 Klein 4B FP8 text-to-image path. **Actual GPU
execution and visual quality are unqualified and deferred by the user.** No FLUX
weights were downloaded or images generated during this code-only increment.
The existing SDXL baseline and rejected candidate remain unchanged.

## Describe an image without loading a model

In an initialized workspace:

```powershell
itov inference capabilities --model flux2-klein-4b-fp8 --json
itov inference spec --model flux2-klein-4b-fp8 --prompt "One red ceramic teapot on a bare wooden table" --seed 926100 --save --config workspace/itov.toml
```

The first command reports the exact assets and capability limits without requiring
a configuration. The second saves an immutable version-three specification and
returns its path. Omit `--save` for a draft. Both work without ComfyUI, model weights,
GPU access or network contact. In the source checkout, use `uv run --inexact
--locked` with the repository-local `UV_CACHE_DIR`.

The description, dimensions and seed range are explicit; descriptions are not
rewritten. The default size is 1024×1024, with the existing bounded range of
512..1024 in multiples of 64. Up to sixteen consecutive uint64 seeds are allowed.
The distilled recipe fixes Euler sampling, the Flux2 scheduler, four steps and
CFG 1. It uses zeroed negative conditioning, so a nonempty `--negative-prompt`
is refused. `--checkpoint` is SDXL-only. Adapters, other model hashes, other
samplers and SDXL sampling settings are refused rather than silently ignored.

SDXL remains the default when `--model` is omitted. Its v1/v2 specifications,
sampler defaults, content identities and runtime receipts retain their meaning.

## Pinned model files

The implementation reads existing local files only; it does not download weights.
`inference capabilities --model flux2-klein-4b-fp8 --json` supplies each SHA-256,
repository revision, file size and stock folder. The pinned upstream sources are:

| Stock folder | File | Pinned source |
| --- | --- | --- |
| `models/diffusion_models` | `flux-2-klein-4b-fp8.safetensors` | [BFL FP8 diffusion](https://huggingface.co/black-forest-labs/FLUX.2-klein-4b-fp8/blob/5b4408e59397a4a37ccb46afe426d8ed86379441/flux-2-klein-4b-fp8.safetensors) |
| `models/text_encoders` | `qwen_3_4b.safetensors` | [Comfy Qwen3 encoder](https://huggingface.co/Comfy-Org/z_image_turbo/blob/6fc90a3b1b653e935a0d175e260736de25b84df5/split_files/text_encoders/qwen_3_4b.safetensors) |
| `models/vae` | `flux2-vae.safetensors` | [Comfy Flux2 VAE](https://huggingface.co/Comfy-Org/flux2-dev/blob/ed33133cd56476eac818c0943b6f9419b3e4a3a1/split_files/vae/flux2-vae.safetensors) |

The Qwen encoder's advertised file hash also matches the file in Comfy's
`flux2-klein` repository. Metadata snapshots and both official workflow references
are retained under `docs/evidence/phase-d021-flux-sources/`. These metadata checks
do not claim that the uninstalled model weights were locally verified.

`prepare` hashes all three local model files before publishing a deployment
receipt. Missing, changed or ambiguous stock loader paths fail. Renamed local
files can be explicitly bound in a specification if their hashes match; arbitrary
replacement checkpoints are outside this capability.

## Execution and recovery when GPU work resumes

After the exact assets are installed and GPU work has been resumed, the public
path is the same as existing image inference:

```powershell
itov inference prepare SAVED_SPEC --config workspace/itov.toml
# Start the configured stock ComfyUI server before planning.
itov inference plan SAVED_SPEC --save --config workspace/itov.toml
itov inference run SAVED_PLAN --config workspace/itov.toml
itov inference status SAVED_PLAN --config workspace/itov.toml
itov inference resume SAVED_PLAN --config workspace/itov.toml
itov inference replay SAVED_PLAN --save --config workspace/itov.toml
```

Planning validates the live stock node schemas, all model hashes, key model and
tokenizer source files, decoder identity and exact server configuration. The graph
connects the FLUX loader to CFGGuider, Qwen encoding to positive/zeroed negative
conditioning, the dimensional Flux2 schedule and reserved RandomNoise seed to
SamplerCustomAdvanced, and its output to the pinned VAE and PNG writer.

New custom sampler nodes are admitted only for this exact version-three capability
graph and its seed bindings. They do not broaden arbitrary batch workflows.
Changed graphs, missing seed ownership, stale schemas/model/tokenizer bytes and
non-stock node replacements prevent a new submission. Each new image is checked
through the existing sequential owner and shared device lease. After a lost
acknowledgement, `resume` reconciles the accepted request rather than resubmitting
it; missing server evidence remains paused. Completed replay is offline and never
grants model-quality acceptance.

The [Comfy reference template](https://github.com/Comfy-Org/workflow_templates/blob/25ff90a51cc8f6ee56bd78ec3b11f294925fb36d/templates/image_flux2_klein_text_to_image.json)
supplies the distilled text-to-image topology. The
[official FP8 edit template](https://github.com/Comfy-Org/workflow_templates/blob/25ff90a51cc8f6ee56bd78ec3b11f294925fb36d/templates/image_flux2_klein_image_edit_4b_distilled.json)
confirms the selected FP8 loader/settings. This implementation does not include
the reference-image editing part of that template.

Before calling this path operational, it still needs real model acquisition and
hash verification, actual runtime/schema execution, resource observations,
interruption/recovery checks and complete visual review of newly declared cases.
The [earlier SDXL failures](d021-image-results-20260926.md) remain regressions;
their exposed cases must not be presented as fresh holdouts. This inference
capability is not a training backend or the requested graphical training workspace.
