# Candidate and adapter-stack inference

For a base image without adapters, start with the
[description-based image workflow](base-image-workflow.md):
`inference spec --prompt "..." --seed 926202600 --save` creates a version-two
request with 1024×1024 defaults. The same prepare/plan/run commands below execute
it. This convenience does not establish visual quality.

The separate [FLUX.2 Klein text-to-image contract](flux-image-workflow.md) uses
version-three specifications and the same owned prepare/plan/run/status/resume/
replay commands. It does not support SDXL adapters or establish model acceptance.
The version-two SDXL contract below retains its existing meaning.

A-04 introduces version-two inference specifications. Model capabilities, pure graph construction, asset deployment and runtime qualification live in separate modules. Sampler settings and adapter strengths are explicit inputs. The existing [version-one catalog profiles](image-inference.md) and saved historical plans remain supported without migration.

This is a bounded SDXL inference path. Deployment is permission to experiment with a technically validated artifact, not production promotion. The current curated candidate remains rejected for the [observed object-count, regression and trigger-specificity problems](deployed-evaluation-review-20260923.md). No command here activates catalog entries or changes that disposition.

## Public workflow

Use the configured workspace and its existing optional training results. A fresh checkout needs the referenced training artifacts and pinned model files; the examples do not download or recreate them.

```powershell
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
uv run --inexact --locked itov inference capabilities --json
uv run --inexact --locked itov training candidate workspace/state/training/plans/TRAINING_PLAN_ID.json --save --json
uv run --inexact --locked itov inference prepare examples/still-life-candidate.inference.json --json
uv run --inexact --locked itov server start
```

`training candidate` prints the candidate ID and exported asset hash for a new specification. The supplied example already pins the local curated candidate. `inference prepare` verifies the training plan, current technically valid result, candidate/export identity, exact training checkpoint and local assets. It publishes immutable exported weights, a hash-addressed ComfyUI loader file and a deployment receipt. Preparation is offline and makes no seed reservation or catalog import. Conflicting existing files are preserved and refused. An interrupted preparation may leave complete unreferenced files; repeat it with unchanged inputs to finish. Staging multiple files is not a single atomic transaction.

In a second terminal, after the stock server starts:

```powershell
uv run --inexact --locked itov inference plan examples/still-life-candidate.inference.json --save --json
uv run --inexact --locked itov inference run workspace/state/inference/plans/PLAN_ID.json --json
uv run --inexact --locked itov inference status workspace/state/inference/plans/PLAN_ID.json
uv run --inexact --locked itov inference replay workspace/state/inference/plans/PLAN_ID.json --save --json
```

Use the path printed by planning. Planning qualifies the actual stock runtime, node schemas, executable/source files, resolved weights and image decoder. It submits nothing. Saved plans include the deployment, exact ordered graph and runtime binding. Every new POST rechecks those inputs. No handwritten API graph or catalog activation is required.

`examples/still-life-stack.inference.json` adds the pinned LCM adapter before the candidate and uses compatible LCM sampler settings. Prepare and plan that specification through the same commands. Changing a prompt, stack, strength, sampler or seed changes the plan identity. Seeds are consecutive, permanently reserved in the same ordinary batch namespace, and cannot be reused by changing strength or renaming a plan. The two examples use separate seeds.

## Capability and specification

All v2 fields are required and unknown fields are refused:

| Field | Contract |
| --- | --- |
| `version`, `capability` | Integer `2`, `sdxl-1.0-unet-v1` |
| `checkpoint` | Portable relative `.safetensors` loader name plus exact pinned SDXL 1.0 base SHA-256 |
| `adapters` | Ordered array: optional `lcm`, then optional `trained_candidate`; at most one of each |
| `sampler` | `steps`, `cfg_milli`, `sampler_name`, `scheduler`; integer milli-units avoid ambiguous float serialization |
| `prompt`, `negative_prompt` | At most 4096 characters; positive nonempty; external embeddings/control characters refused |
| `width`, `height` | Multiples of 64 from 512 through 1024 |
| `seed`, `count` | Uint64 starting seed, 1..16 jobs without overflow; latent batch size one |

A trained-candidate layer contains `kind`, a workspace-relative `training_plan` path/hash, `candidate_id`, exported `sha256` and `strength_milli` from 1 through 1000. The candidate is reconstructed from its owned training result and must match every declared identity. It must use the current `comfy-unet-lora-v1` export with alpha equal to rank and the exact inference checkpoint hash. The CLI derives its loader name as `itov_candidate_EXPORT_HASH.safetensors`. Filename aliases for the same checkpoint bytes are allowed.

An LCM layer contains `kind`, `loader_name`, `sha256` and `strength_milli`. Only the pinned SDXL LCM artifact recorded by `inference capabilities` is supported, at strength 1000. Without LCM, the contract permits `dpmpp_2m`/`karras`, 1..50 steps and CFG 1..15000 milli. With LCM it permits `lcm`/`sgm_uniform`, 4..8 steps and CFG exactly 1000 milli. These are validated configuration bounds, not evidence of good quality at every value.

Both layers use stock `LoraLoaderModelOnly`. Each receives the preceding model output; the checkpoint supplies CLIP and VAE. Strengths are bound independently and recorded in both the declaration and graph. There is no automatic trigger insertion. CLIP adapters, arbitrary third-party LoRAs, alternate base hashes/architectures, reversed or duplicate layers, and incompatible samplers fail before submission. Supporting another capability requires implementation and evidence rather than relabeling an unknown file as SDXL.

## Ownership, recovery and replay

Inference uses the shared workspace dispatcher, seed registry and [same-user device lease](execution-ownership.md). The supported submission environment is Windows, one local NVIDIA GPU and the exactly configured stock ComfyUI runtime. Extra model search paths and custom nodes are outside this qualification profile. Restart the server after replacing previously loaded model bytes; filesystem hashes do not attest cached in-memory weights. Immutable candidate filenames avoid replacing an earlier candidate's cache entry.

`--wait-timeout` or Ctrl+C detaches observation; it does not cancel server execution. Resume the exact saved plan:

```powershell
uv run --inexact --locked itov inference resume workspace/state/inference/plans/PLAN_ID.json --json
```

An unknown acknowledgement is reconciled using exact request/graph history, optionally with `--prompt-id`. Missing or conflicting evidence never causes a retry POST. Accepted work can be collected even if later inputs have changed; changed inputs block the next submission. `inference abandon` can retire the remainder only once submitted outcomes are known terminal. Seeds and failure evidence are retained. Device recovery follows the shared positive-proof rules.

`status` reads ownership records and fully decodes completed PNGs without HTTP. `replay` also rechecks candidate/deployed bytes, every frozen runtime file and the decoder, then publishes an immutable technical report. Completed resume is an offline artifact observation. Corrupted evidence is reported without rewriting it. Status may still describe a historically completed render after source inputs change; replay refuses to certify current input integrity in that case.

JSON and text are supported. New v2 commands return 0 for completed operations, 1 for an incomplete/invalid execution status, and 2 for a refused or malformed operation. A technical report establishes bound inputs, owned execution and decoded artifacts. It does not certify every tensor's loader target, Diffusers/ComfyUI parity, prompt adherence or general stack quality.

The [A-04 installed trial and image inspection](candidate-inference-review-20260923.md) records actual candidate-only and LCM-stack renders, detach/resume without duplication, incompatible-input refusal, offline replay and preserved history. The trial exercises 512px, candidate strength 750, DPM++ 2M/Karras at 20 steps/CFG 7 and LCM/SGM uniform at 4 steps/CFG 1. Other permitted values are configuration bounds, not broadly qualified quality settings.
