# Pinned image inference

This page describes the historical version-one preset/catalog route. For explicit trained-candidate inputs, ordered LoRA stacks, configurable samplers and the integrated inference commands, use the [version-two candidate inference runbook](candidate-inference.md). Version-one specs and plans retain their original behavior.

ITOV 0.6.0 adds stock SDXL inference preparation on top of the existing catalog, deterministic planner, and sequential executor. The two profiles are deliberately small qualification baselines. Preparation does not download weights, import a catalog, reserve seeds, or submit a prompt.

## Profiles and assets

| Profile | Diffusion settings | LoRA |
| --- | --- | --- |
| `sdxl-base-v1` | 20 steps, CFG 7, `dpmpp_2m`, `karras` | None |
| `sdxl-lcm-v1` | 4 steps, CFG 1, `lcm`, `sgm_uniform` | One LCM SDXL LoRA at model strength 1.0 |

Both profiles use `CheckpointLoaderSimple`, `CLIPTextEncode`, `EmptyLatentImage`, `KSampler`, `VAEDecode`, and `SaveImage`. LCM adds `LoraLoaderModelOnly`; CLIP continues to come from the checkpoint. The LCM settings follow the [official ComfyUI example](https://comfyanonymous.github.io/ComfyUI_examples/lcm/). The bounded profile does not add the optional `ModelSamplingDiscrete` node.

The supplied examples reference the publisher's [SDXL 1.0 base checkpoint](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0) and [LCM SDXL LoRA](https://huggingface.co/latent-consistency/lcm-lora-sdxl). [The asset manifest](../../examples/inference-assets.json) records immutable upstream revisions, byte counts, SHA-256 hashes, model-card links, and reported license labels. Refer to those model cards for model terms and limitations. Their combined download size is 7,331,933,558 bytes; inference preparation also keeps a verified 393,855,224-byte LoRA copy in the workspace catalog assets.

The optional download helper is explicit:

```powershell
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
uv run --locked python scripts/fetch_inference_baseline.py
```

It writes into the configured ComfyUI model directories, which are ignored by Git in the default repository setup. Downloads use revision-pinned URLs, stream into unpublished partial files, and are published only after exact length and SHA-256 verification. Existing differing weights are never overwritten. Interrupted or invalid downloads remain as identified partial files for inspection; automatic partial-download resume is not implemented. Successful receipts are saved under `workspace/state/model-downloads`. No remote code, package installation, or custom node installation is performed by this helper.

## Prepare, review, import, and plan

With an initialized catalog, prepare the base example:

```powershell
uv run --locked itov inference prepare examples/sdxl-base.inference.json --json
```

The response prints a catalog candidate path and its `expected_head`. The candidate preserves every current entry and adds the pinned inference preset. Preparation also publishes its immutable API workflow, and copies/hash-verifies a LoRA into `models_shared/inference` when needed. It reads local model bytes without contacting ComfyUI. Changed existing files or conflicting catalog entries cause an error rather than being replaced. A failed preparation may leave complete, unreferenced candidate files; the live catalog remains unchanged.

Import the candidate explicitly, using the exact path/head printed by preparation:

```powershell
uv run --locked itov catalog import CATALOG_CANDIDATE_PATH --expected-head HEAD_FROM_PREPARE
uv run --locked itov inference plan examples/sdxl-base.inference.json --save
uv run --locked itov batch qualify workspace/state/plans/PLAN_ID.json --save
uv run --locked itov batch run workspace/state/plans/PLAN_ID.json --qualification workspace/state/qualifications/QUALIFICATION_ID.json
```

Use `batch status` and `batch resume` as described in the [execution contract](../contracts/batch-execution.md). Complete or safely abandon this batch before importing another profile: catalog imports invalidate old plans for further submission. Repeat the procedure with `examples/sdxl-lcm.inference.json` for the LoRA profile. The two examples use disjoint seed ranges. Running a completed plan again verifies its artifacts without resubmitting it; another inference run requires a new specification and unused seeds.

The configured server must satisfy the existing stock-local qualification profile. Restart it after model/search-path changes if it may have cached earlier model bytes. New weights in an installation that has only executed the neutral image-copy workflow have no previously loaded checkpoint cache to invalidate.

## Specification contract

Specifications contain exactly these fields:

- `version`: integer 1; `profile`: one of the two versioned profiles above.
- `checkpoint`: `loader_name` and lowercase SHA-256; `lora`: the same fields for LCM, otherwise null. Names are portable relative paths ending in `.safetensors` under the stock model folders.
- `prompt` and `negative_prompt`: text up to 4096 characters each. The positive prompt must be nonempty. External `embedding:` references and control characters are not supported.
- `width` and `height`: multiples of 64 from 512 through 1024. Each ComfyUI prompt has latent batch size one.
- `seed`: an unsigned 64-bit integer; `count`: 1 through 16. Jobs use consecutive seeds and overflow is rejected. Existing workspace reservations still apply.

The specification's canonical hash determines its preset ID, workflow filename, and output prefix. Fixed sampler settings belong to the profile version. `inference plan` rechecks local model hashes and requires the exact prepared entries in the current catalog; its output is an ordinary version-one batch plan.

The checkpoint's expected SHA-256 is retained in the loader node's `_meta.itov_asset_sha256`. Live qualification enforces that pin, so replacing a same-named checkpoint cannot silently establish a new receipt for an old plan. LoRA bytes remain covered by the catalog asset hash and live loader-resolution check. The SDXL family declaration is a profile assumption, not architecture detection for arbitrary user-supplied files.

## Server normalization and ownership

Real ComfyUI validation converts numeric scalar inputs to their declared types before storing the queue/history graph. For example, KSampler CFG 7 and denoise 1 appear as 7.0 and 1.0 in history. Ownership verification accepts only lossless integer/float equality for scalar node input values. It still requires the exact request ID, node IDs, class names, input keys, nonnumeric values, connection arrays, and metadata. Booleans and rounded large integer seeds are rejected. Original plan and submitted workflow bytes remain unchanged.

This comparison applies to acknowledged-job observation and lost-acknowledgement reconciliation. It does not infer acceptance from missing history and does not authorize resubmission. The initial real SDXL observation failure and server graph are retained in the stage-six evidence.

Nested output folders from Windows ComfyUI may use backslashes. Collection validates either separator form as a safe relative path, then uses the server's original descriptor for retrieval. Traversal, absolute paths, and drive paths remain rejected. The first collection failure is retained, and recovery collected the already rendered image without another submission.

## Local acceptance evidence

On 2026-09-21, the local ComfyUI 0.37.0 / Torch 2.13.0+cu130 / RTX 5090 runtime completed all four jobs. The base seeds were 620260921–620260922; the LCM seeds were 620260931–620260932. Each artifact decodes to a nonuniform 1024×1024 RGB image, and all four pixel hashes differ. The runtime log records 788 attached model patches for LCM. Completed batches resume successfully, and earlier job records remain unchanged.

- [Execution records, pinned assets, image checks, and GPU observations](../evidence/stage-06-inference-20260921.json).
- Base outputs: [first](../evidence/stage-06-output-01.png), [second](../evidence/stage-06-output-02.png). LCM outputs: [first](../evidence/stage-06-output-03.png), [second](../evidence/stage-06-output-04.png).
- Retained [observation failure](../evidence/stage-06-initial-observation-20260921.json), [raw server history](../evidence/stage-06-initial-server-history-20260921.json), and [collection failure](../evidence/stage-06-initial-collection-20260921.json). The original accepted prompt was resumed through both fixes.
- [Runtime log](../evidence/stage-06-runtime-20260921.log) and [400-test source/wheel verification](../evidence/stage-06-verification-20260921.json).

Visual inspection found the red-teapot/green-fruit still life recognisable in every output. Both base images contain four pears instead of the requested two. The LCM images have fruit and shape inconsistencies, and the second includes an extra teapot. These limitations are retained: passing image decoding and ownership checks does not establish exact prompt compliance or general quality. Model weights are kept in ignored local folders; the small result images are retained as reviewable evidence.

## Qualification boundaries

Functional acceptance requires actual model execution, correct prompt ownership, durable artifacts, decoded 1024×1024 images with nonuniform pixels, and distinct outputs for the supplied distinct seeds. Visual inspection records whether the neutral still-life prompt is recognisable; it is not a benchmark of general aesthetic quality or exact object counting. Fixed seeds do not establish identical pixels across runtimes, GPUs, or future dependency versions.

GPU samples collected during the local exercise are whole-device `nvidia-smi` observations. They are lower bounds on memory peaks and include other allocations; they do not calibrate Part 11's predictor, prove per-model memory deltas, or authorize parallel workers. Later [video](image-to-video.md), [retained audio](audio-and-av.md), [adapter inference](candidate-inference.md) and [candidate lifecycle](../evaluation/candidate-lifecycle.md) have separate contracts and evidence. These original samples do not qualify those paths, custom nodes, throughput or general model quality.
