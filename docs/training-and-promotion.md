# Training, evaluation and reviewed promotion

ITOV 0.12.0 adds a bounded SDXL UNet LoRA path. The user selected neutral synthetic images for the first smoke test. This exercises optimization, export, reload and paired diagnostics. It does not establish a useful learned style, reliable trigger activation, generalization or production quality.

The [curated review extension](curated-quality-review.md) adds v2 training plans and full case coverage. Version 0.13.1 supports assistant-authored v3 reviews after the user shelved the human-only gate. Historical v1 results remain inspectable; v1 non-smoke reviews alone cannot qualify for promotion. This remains a prototype trainer with substantial open work in the [active TODO](../TODO.md); the smoke evidence below is historical.

[Training specification v3](training-configuration.md) adds declared batch/accumulation, deterministic sampling, constant or warmup/decay learning rates, validation cadence and checked optimizer/precision traces. This specification version is separate from review-document versions. It retains the curated quality matrix and existing execution/assessment path; the fixed-loop description and trials below document historical v1/v2 behavior.

## Authority and baseline

[Durable v4 checkpoints](training-checkpoints.md) preserve optimizer/RNG state for explicit compatible continuation. [Experiment manifests](training-experiments.md) preregister independent final-checkpoint endpoints, repetitions, hypotheses, budgets and frozen case reviews. Experiment selection uses quality verdicts separately from loss and is only a decision about further evaluation; it does not replace deployed-runtime review or promotion policy.

Part 5's voice/LTX sketch contains unresolved configuration, data-loader and optimization functions and assumed audio APIs. Part 7's evaluator leaves rendering and workflow construction unimplemented. Its promotion example moves weights before separate manifest/ledger writes, substitutes an empty manifest after corruption and deletes quarantined weights. Those examples remain unchanged as design inputs; they are not installed or executed.

The implemented worker uses the [official Diffusers SDXL LoRA example](https://github.com/huggingface/diffusers/blob/275869dcae4ebcfee6a80253fdabc56033335020/examples/text_to_image/train_text_to_image_lora_sdxl.py) as the API reference. This is a project-specific bounded worker, not a claim to implement that example's full feature set. [Diffusers' LoRA documentation](https://huggingface.co/docs/diffusers/training/lora) describes adapter training and serialization. The trial pins these dependencies:

| Component | Qualified trial selection |
| --- | --- |
| Base model | Existing official `sd_xl_base_1.0.safetensors`; SHA-256 `31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b` |
| Model configuration/tokenizers | `stabilityai/stable-diffusion-xl-base-1.0`, revision `462165984030d82259a11f4367a4eed129e94a7b`; 14 individually hashed files |
| Trainer packages | Diffusers 0.38.0, PEFT 0.21.0, Accelerate 1.15.0 |
| CLIP dependencies | Transformers 4.57.6, huggingface-hub 0.36.0, tokenizers 0.22.2 |
| Runtime | Python 3.13.9, Torch 2.13.0+cu130, torchvision 0.28.0+cu130, NVIDIA RTX 5090 |
| Training | 512×512 RGB, UNet attention LoRA rank 4, eight AdamW steps, learning rate 0.0001, seed 11260921 |
| Precision | Frozen BF16 UNet/text encoders, float32 VAE encoding, float32 trainable adapters; gradient checkpointing |
| Evaluation | Two held-out images, fixed paired denoising noise; two baseline/candidate prompt pairs at 20 inference steps and CFG 7 |

The dedicated environment is `workspace/training/environment`. It adds the existing ComfyUI embedded `Lib/site-packages` through a `.pth` file, then installs the six pinned packages above locally. Torch and the existing ComfyUI installation are reused read-only. The core CLI remains standard-library code; it never imports Torch, Diffusers, PEFT or Pillow. Environment package versions and executable bytes are bound into each plan; this is not a hermetic binary lock of every transitive dependency.

The original Transformers 5.15.1 failed because this Diffusers single-file loader expected `CLIPTextModel.text_model`. Installing the [pinned Transformers 4.57.6 release](https://pypi.org/project/transformers/4.57.6/) and compatible hub package in the separate training environment fixed the observed interface. No ComfyUI package was replaced. The next attempt completed optimization but offline adapter reload required an explicit `weight_name`; that failure and its weights remain retained.

## Dataset and plans

Generate the procedural fixture once, then validate and prepare it:

```powershell
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
uv run --locked python scripts/create_training_fixture.py
uv run --locked itov dataset validate workspace/training/data/neutral-geometry-v1/dataset.json --json
uv run --locked itov dataset prepare workspace/training/data/neutral-geometry-v1/dataset.json --json
```

The generator refuses an existing output folder. It creates eight training and two validation PNG/caption pairs: a red disk and blue square on an ivory background, with the literal trigger `itovgeom`. All variants share one generator and caption; separate groups do **not** establish natural-data independence or prompt diversity. The dataset is explicitly marked `purpose: "smoke"`.

Dataset manifests require exactly `version`, `id`, `purpose`, `origin`, `rights`, `preprocessing` and `samples`. Each sample declares `id`, `split`, `group`, plus `source`, `image` and `caption` file references containing workspace-relative paths and SHA-256 hashes. Both splits are required. Reused prepared paths/images and group/source hashes crossing splits are refused. Rights are operator declarations, not independently authenticated permissions.

The legacy preprocessing is `prepared-square-rgb-png-v1`. Its validation checks PNG headers, byte hashes, UTF-8 captions and portable nonredirecting paths; full image decoding occurs in the trainer. New datasets should use [transactional import](dataset-import.md), which prepares 512px images, records source/output full decode and requires a committed version-two snapshot. Both snapshot versions are accepted by training planning. Legacy bounds are 2–256 samples, 32 MiB per image/source, 64 KiB per caption file, 4096 caption characters, 1 GiB of verified input bytes and 32 MiB per JSON document. Training currently requires 512px images even though legacy dataset validation accepts square RGB8 PNGs from 64 to 2048px.

`examples/sdxl-neutral.training.json` records this local trial's exact specification. A fresh checkout must recreate the fixture, prepare its manifest, provision the separately pinned environment/configuration and update the references for its own files. Planning does not install dependencies or download files.

```powershell
uv run --locked itov training plan examples/sdxl-neutral.training.json --save --json
uv run --locked itov training run workspace/state/training/plans/PLAN_ID.json --gpu GPU_UUID --json
uv run --locked itov training status workspace/state/training/plans/PLAN_ID.json --json
```

Use the printed plan ID and observed GPU UUID. Plans bind the prepared dataset, model checkpoint, all 14 configuration/tokenizer files, executable, selected package versions and the trainer/result-validation source modules. Added config files, changed captions, changed dependencies and stale plans are refused before training. Plans permit rank 4 or 8, 1–256 steps and 60–3600 seconds. Fixed seeds do not guarantee bitwise reproducibility across different runtimes/devices.

For reviewed Met inputs, [B-02 freezing](dataset-review.md) produces a new import declaration and `dataset curate --freeze` produces a v2 curation declaration for `qualification.curation`. It binds the exact frozen selection and captions through the existing training-specification v2 path. New plans pin the review validators; completed historical plans keep their existing evidence semantics. The current reviewed corpus is only two training works and one validation work, so it is unsuitable as proof of broad quality.

## Ownership, failures and resource limits

Training acquires the existing whole-workspace execution lock and a same-user GPU UUID lease. It refuses an unfinished batch, a nonempty ComfyUI queue or an existing attempt. One hidden Windows worker enters the owned Job Object while suspended and starts only after its identity is journaled. The worker sets Hugging Face offline flags and uses local checkpoint/configuration files.

Experimental start floors are 16 GiB free GPU memory, 16 GiB available physical RAM and 24 GiB available host commit. They are policy floors, not measured capacity guarantees or reservations. The controller stops its worker on timeout or less than 1 GiB available commit. A-03 extends [cooperative device/workspace ownership](execution-ownership.md) to ordinary jobs, batches and evaluation. Other users, external GPU clients and older executables can still bypass it. Training is not qualified for concurrent model workloads.

Run records, logs, weights and diagnostic images remain under `workspace/state/training/runs/PLAN_ID`. The controller now separates worker completion from artifact validation: `artifacts_validated` requires the shared result/weights/diagnostic-coverage checks and fresh input/environment revalidation. Candidate assessment remains separate. Read the [state, boundary and recovery contract](training-result-states.md), including read-only reinspection of historical `succeeded` records. Failure preserves the attempt. There is no automatic retry, overwrite, checkpoint resume or implicit deletion. After a controller interruption, inspect the record and explicitly recover it only when its controller, worker and native job are confirmed dead:

```powershell
uv run --locked itov training recover workspace/state/training/plans/PLAN_ID.json --json
```

Recovery marks interrupted execution failed. An interrupted version 2 validation/final-publication step can be finalized only after complete artifact and execution-input revalidation; otherwise it records the failed boundary. Neither path reruns training. Correcting a dependency or trainer implementation creates a different plan. An unchanged plan cannot silently execute a second time.

## Assessment, candidates and promotion

For version 2 curated training plans, use the [supported deployed evaluation workflow](deployed-evaluation.md) after technical assessment. It stages the candidate and executes the frozen four-condition case/seed matrix through public commands. The old local ComfyUI qualification helper is historical investigation tooling; it is no longer required for this workflow. Quality disposition and promotion remain separate.

```powershell
uv run --locked itov evaluation assess workspace/state/training/plans/PLAN_ID.json --save --json
uv run --locked itov training candidate workspace/state/training/plans/PLAN_ID.json --save --json
uv run --locked itov promotion prepare workspace/state/training/plans/PLAN_ID.json --json
```

Assessment revalidates the dataset, owned success record, finite safetensors matrix pairs, exact optimizer-step count, changed-adapter evidence, held-out coverage/noise seeds and paired image hashes. Saved weights are reloaded into Diffusers before candidate previews. Inspection bounds weights to 256 MiB and requires only supported UNet LoRA tensor pairs. A technical pass does not assert image quality, activation or intended-runtime compatibility.

Saving a candidate converts Diffusers tensor names to stock ComfyUI-compatible `lora_unet_…lora_down/up.weight` names and writes `models_shared/trained/SHA256.safetensors`. Every tensor payload byte and offset is preserved. The worker fixes alpha equal to rank; the loader's absent-alpha scale is one. Name collisions are refused. The candidate binds both original weights and conversion/output hashes. The main catalog remains unchanged. Content hashes provide consistency, not signatures or historical authentication.

Legacy `promotion prepare` refuses every plan with dataset purpose `smoke`, including one accompanied by an approving review. Its training-only preview binds assessment and exported candidate IDs, reviewer, approve/reject decision, notes and exactly five criteria: `activation`, `prompt_adherence`, `image_quality`, `regression`, `runtime_compatibility`. Each criterion supplies a boolean verdict and 1–16 hash-pinned local evidence files. This historical preview is insufficient for activation; command output now explicitly reports `activation_eligible: false`.

```powershell
uv run --locked itov promotion prepare workspace/state/training/plans/PLAN_ID.json --review review.json --save --json
```

Since C-05, legacy `promotion apply` refuses activation even for a complete training-only approval. Follow the [candidate lifecycle](candidate-lifecycle.md): complete deployed comparison, loader mapping and case review, then `candidate summary`, `deployment`, `preview --strength-milli VALUE --save` and explicit `candidate apply PREVIEW`. That path freshly validates the decision and atomically binds its one-entry change to the catalog ledger. Retirement, targeted rollback and journal recovery preserve unrelated entries and prior evidence. Manual catalog imports remain a separate explicit operator interface.

CLI exits are `0` for successful commands, `1` for a completed failed attempt or refused promotion, and `2` for malformed inputs, stale evidence, missing files or operational errors.

## Qualification records and next gate

Actual attempts are retained separately from fixture tests: [initial CLIP incompatibility](evidence/stage-11-training-attempt-01-20260921.json), [offline reload refusal after eight steps](evidence/stage-11-training-attempt-02-20260921.json), and [preview VAE dtype mismatch](evidence/stage-11-training-attempt-03-20260921.json). The worker now renders denoising latents and explicitly casts them to float32 for VAE decoding. The [source/package checks](evidence/stage-11-verification-20260921.json) cover contracts, native process protocols and policy behavior; their synthetic reviews are test fixtures, never real acceptance records.

The [complete fourth trial](evidence/stage-11-training-attempt-04-20260921.json) passed eight steps in 28.135 worker seconds with 5,806,080 trainable parameters and 1,120 finite changed tensors. Paired held-out losses fell from 0.002440360 to 0.002062644 and from 0.003842753 to 0.003004410. Torch peaks were 8,344,747,008 allocated and 9,588,178,944 reserved bytes; these are single-trial allocator observations, not whole-device peaks or general memory envelopes. Every attempt released its owned worker/lease and preserved the main catalog and prior jobs.

The first [ComfyUI export check](evidence/stage-11-comfy-export-20260921.json) completed both jobs but produced identical decoded pixels because the stock loader ignored the raw Diffusers tensor names. The original [transport-only receipt](evidence/stage-11-comfy-export-transport-20260921.json) remains retained. Name conversion preserves payload bytes; the [corrected fixed-seed pair](evidence/stage-11-comfy-export-qualified-20260921.json) has different decoded pixels. [Installed loader mapping](evidence/stage-11-comfy-mapping-20260921.json) verifies all 1,120 tensors against 560 actual checkpoint target shapes. These four ComfyUI jobs ran sequentially through the existing server, preserving its prior history and the main catalog; they are not managed parallel-worker evidence.

Visual inspection found repeated grids, extra shapes, and an unrequested arrow in one Diffusers candidate. The ComfyUI candidate also misses the requested single disk/square composition. Lower denoising losses and changed pixels do not override those failures. No human acceptance review or production promotion was recorded.

| Retained comparison | Baseline | Candidate |
| --- | --- | --- |
| Diffusers held-out seed 11460921 | [Image](evidence/stage-11-geometry-08-baseline.png) | [Image](evidence/stage-11-geometry-08-candidate.png) |
| Diffusers held-out seed 11460922 | [Image](evidence/stage-11-geometry-09-baseline.png) | [Image](evidence/stage-11-geometry-09-candidate.png) |
| ComfyUI seed 11660921, corrected export | [Image](evidence/stage-11-comfy-baseline.png) | [Image](evidence/stage-11-comfy-candidate.png) |

Further quality work requires developed data/training methods, representative frozen cases, deployed-runtime comparisons and evidence-backed evaluation. The assistant is responsible for continuing that work; a mandatory human review is no longer required. The neutral smoke candidate remains ineligible for production promotion.

Final verification passed 837 source tests on Python 3.13.9 and 837 installed-wheel tests on Python 3.11.14, lint/format/build and 40-module byte parity. Both JSON and default text commands were exercised against the actual local run/candidate; offline checks preserved 146 prior files and the main catalog, with no ML imports. The [verification record](evidence/stage-11-verification-20260921.json) retains the earlier text-renderer failure separately. Stage 11A is complete for the bounded smoke baseline; Stage 11B quality acceptance remains open.
