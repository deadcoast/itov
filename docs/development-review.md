# Development review and build plan

Reviewed 2026-09-21. The repository started with eleven Markdown documents, two published document commits, and a local ComfyUI download. There was no executable package, environment lock, test suite, or installed ComfyUI under the documented repository path. The documents describe a broad image/video pipeline, but their embedded scripts need reconciliation before use.

## Findings that affect implementation

| Priority | Source | Finding and consequence |
| --- | --- | --- |
| Critical | `09_concurrency_layer.md:160` | `_pid_alive` calls `os.kill(pid, 0)` on Windows. This can terminate the process being inspected. Do not execute this example. A Windows liveness implementation must inspect a process handle and preserve unknown/permission-denied states. |
| High | `10_ledger_integrity.md:168`, `:987` | The seal writer hashes `bytes.fromhex(prev)`, while the later verifier hashes `prev_hash.encode("utf-8")`. These are different byte sequences, so the later verifier cannot validate rows from that writer. Establish one versioned schema and golden hash vectors before ledger adoption. |
| High | `10_ledger_integrity.md:177` | `append_sealed` reads the tail and appends without acquiring a lock itself. Its append is not an atomic replacement despite the preceding description. Two writers can derive the same predecessor; crashes can tear rows. Lock scope, durable journaling, and recovery need a single implementation. |
| High | `09_concurrency_layer.md:171` | Age alone marks a holder stale, including live or remote holders. Clearing a metadata sidecar does not release the OS lock. The timeout path also formats an absent holder's age as a float. Use the acquired OS lock as authority; test live contention and crash recovery on Windows. |
| High | `02_workflow_pipeline.md:78` | The sample workflow uses a descriptive `workflow`/`nodes`/`type`/`params` structure. ComfyUI API exports use a node-ID mapping with `class_type` and `inputs`. These examples are not ready for `/prompt`. Export a real installed workflow and validate its node registry. |
| High | `03_rotation.md:804`, `04_LoRA_Stack.md:432`, `06_audio_visual_batch.md:418` | Python fences end inside a function declaration or f-string. AST inspection confirms syntax errors. Part 3 also duplicates the Part 4 material; Part 5 contains a continuation. Extracting fences directly would produce broken or conflicting modules. |
| High | `05_LoRA_voice_pipeline.md:240`, `07_scraper.md:253` | The trainer is explicitly a skeleton with unresolved configuration, loader, optimizer, conversion, and validation functions. The sandbox renderer and workflow builder contain ellipses. These cannot establish training, rendering, scoring, or promotion acceptance. |
| Medium | `06_audio_visual_batch.md:181` | Worker submission does not check HTTP status; polling does not surface execution errors promptly. Output discovery is based on globbing local filenames rather than verified history artifacts. Start with one worker and explicit failure states before parallel jobs. |
| Medium | Parts 1, 5, 6, 7 and 8 | Hard-coded roots alternate between `D:\AI\ComfyUI`, `D:\AI\ComfyUI_portable`, `batch`, and `workshop`. Configurations and ledger schemas differ across examples. Centralize path resolution before implementing their consumers. |
| Medium | Parts 8, 9 and 10 | Query indexes depend on manifests and ledger formats that are not yet canonical. Part 9 repeats sections 9.6 and 9.7; Part 10 includes multiple verifier/journal/repair versions. Reconcile versions and snapshot consistency before exposing a query service. |

Python's [documented Windows signal behavior](https://docs.python.org/3/library/os.html#os.kill) confirms the process-liveness issue. This review did not execute the unsafe snippet.

The workflow shape and metadata endpoints are established by the [official API example](https://github.com/Comfy-Org/ComfyUI/blob/master/script_examples/basic_api_example.py) and [server routes](https://docs.comfy.org/development/comfyui-server/comms_routes). Static validation cannot replace the server's custom-node validation or a successful render.

## Current compatibility and local evidence

The documents' blanket prohibition on Python 3.12+ is outdated. Current [ComfyUI system requirements](https://docs.comfy.org/installation/system_requirements) recommend Python 3.13 and describe 3.12 as a fallback. The [portable installation guide](https://docs.comfy.org/installation/comfyui_portable_windows) lists CUDA 13.0/Python 3.13 for modern RTX hardware and the CUDA 12.6/Python 3.12 build for older NVIDIA hardware. Re-check those sources when installing; this is not a permanent version pin for ComfyUI or custom nodes.

Initial read-only inspection found an NVIDIA GeForce RTX 5090 with 32607 MiB VRAM and driver 616.64. FFmpeg and 7-Zip are on PATH. At that checkpoint, the repository contained only `AI/ComfyUI/ComfyUI_windows_portable_nvidia_cu126.7z`, not an extracted runtime. Stage two subsequently qualified a current runtime as recorded below. Hardware detection alone does not establish Torch compatibility, SageAttention availability, the examples' speed claims, or render quality.

The ITOV development environment is separate from ComfyUI's environment. It uses an installed Python 3.13 through uv and has no runtime dependencies on Torch, custom nodes, or model downloads.

## Stage one implementation

The new package implements:

- `itov init`: configurable workspace creation with an explicit TOML version, paths resolved relative to the configuration, and no configuration overwrite.
- `itov doctor`: local directory/runtime/tool checks and optional read-only ComfyUI metadata checks, with timeouts and structured failure reporting.
- `itov workflow validate`: graph checks offline and optional checks against live or saved node metadata, without queueing work.
- A neutral `LoadImage` to `SaveImage` API example, source tests, reproducible development dependencies, and Git exclusions for generated state and model weights.

This is an implemented preflight stage. It is not completion of the studio, an installation of ComfyUI, or a tested image/video generation pipeline. Original design documents remain unchanged.

## Development gates

1. **Complete for the neutral workflow:** qualified ComfyUI v0.37.0, recorded embedded Python/Torch/CUDA/node metadata, passed a BF16 GPU operation, and completed real image-copy execution. Model inference remains a separate acceptance gate.
2. **Complete for one workflow per command:** implemented submission/history tracking, bounded polling, structured errors, timeout/detachment semantics, resumable observation, and exact artifact retrieval. Real success, timeout/resume, and execution-error cases were exercised. Targeted server-side cancellation and parallel worker orchestration remain deferred.
3. **Complete for catalog revisions:** defined version-one preset, LoRA manifest, compatibility, and catalog-event ledger schemas; implemented one canonical hash encoding, OS-backed locking, immutable catalog/history snapshots, stale-update rejection, and explicit recovery. Windows process-crash and contention checks passed. Automated promotion, legacy CSV migration, backup restore, and power-loss qualification remain separate work.
4. **Complete for deterministic planning and sequential execution:** deterministic batch expansion, explicit seed/loader bindings, rotation/cooldowns, immutable replayable plans, stock runtime/path qualification, atomic workspace seed reservations, durable per-job ownership, one-at-a-time submission, verified artifacts, and uncertain-outcome reconciliation are implemented. Stage five exercised neutral image-copy success/recovery, and stage six exercised actual model inference. Parallel workers require measured GPU capacity and isolated job ownership.
5. **Complete for the pinned image-inference baseline:** stock SDXL base and SDXL+LCM graphs, expected model hashes, inference preparation/planning, and four seeded 1024×1024 outputs are qualified on the local runtime. Visual inspection found recognisable subjects but object-count/shape errors. This establishes functional execution for this selected checkpoint/LoRA pair, not general media quality, arbitrary compatibility, or cross-runtime pixel determinism.
6. **Next:** select and qualify a model-specific image-to-video workflow against its actual upstream API, including input-image binding, frame/video artifact validation, and observed GPU capacity. Audio integration follows with explicit timing/output contracts. Reconcile Part 11's measurement assumptions before implementing VRAM prediction or parallel admission. Training, scraping, promotion, scheduling, and the later trigger/curation proposals remain subsequent work.

## Stage one verification record

On Windows, all 74 tests passed against the source on Python 3.13.9 (6.56 seconds). All 74 also passed against the built wheel in an isolated Python 3.11.14 environment (6.42 seconds); the imported package path was confirmed to be that environment's `site-packages`. Ruff lint and formatting checks passed, and both the wheel and source distribution built successfully. The example workflow passed structural validation only. Package hashes and verification scope are retained in [the verification record](evidence/stage-01-verification-20260921.json).

The real local `doctor` command returned exit code 1: workspace directories, FFmpeg, and NVIDIA diagnostics passed; the configured ComfyUI program, embedded interpreter, and live API checks failed. The complete [failed preflight result](evidence/stage-01-doctor-20260921.json) is retained. There was no listening ComfyUI server at the configured address, and no real workflow was submitted or rendered. Installing and qualifying an appropriate runtime was the next gate at this checkpoint and is addressed in stage two below.

The original eleven documents were checked against Git and remain unchanged. Tests exercise protocol fixtures and package behavior; they do not establish live ComfyUI, model, CUDA execution, or media-quality acceptance.

## Stage two runtime and job execution

The runtime and single-worker increment is described in [runtime and job guidance](runtime-and-jobs.md) and [CHANGELOG.md](../CHANGELOG.md). Its [runtime evidence](evidence/stage-02-runtime-20260921.json) records actual local checks, separately from the [automated verification record](evidence/stage-02-verification-20260921.json).

The live doctor now passes, a BF16 CUDA operation completed, and the neutral image-copy workflow produced a pixel-identical output. Timeout/resume preserved the acknowledged prompt ID; a deliberately invalid input produced a retained execution failure. This qualifies the runtime and job transport/image-I/O path. No checkpoint-based image or video generation, voice training, custom-node acceptance, or performance tuning acceptance is claimed.

All 101 tests passed against source on Python 3.13.9 and against the built 0.2.0 wheel in isolated Python 3.11.14. Ruff lint and formatting, wheel and source-distribution builds, and packaged-source byte parity passed. Automated tests include a child-process crash releasing its job lock; these checks do not qualify the future ledger or concurrent GPU workers.

## Stage three catalog contracts and ledger integrity

Version 0.3.0 adds `catalog validate`, `init`, `import`, `show`, `verify`, and `recover`. The [catalog and ledger contract](catalog-and-ledger.md) is the executable schema authority for this stage. Original design documents remain unchanged. Presets bind real API workflow files; LoRA assets bind workspace-relative paths and SHA-256 values; compatibility relationships validate references and contradictory declarations. Integer thousandths give weights and strengths an exact serialized representation.

Catalog imports validate asset bytes and workflow structure, acquire the shared OS lock, and require the caller's reviewed head. A complete redo journal precedes snapshot publication and a single HEAD replacement. Readers pin one immutable generation, and recovery only finishes a validated prepared transaction or clears an already committed intent. Corrupt data is preserved rather than re-sealed or silently truncated. The ledger records catalog revisions; render picks and model promotion are not implemented.

Windows verification covers simultaneous writers, concurrent readers, process exits after intent/object/HEAD publication, interrupted temporary writes, repeat recovery, hash tampering, stale imports, and workspace junction escapes. The [local catalog exercise](evidence/stage-03-catalog-20260921.json) and [automated/package verification](evidence/stage-03-verification-20260921.json) retain results and scope. LoRA tests use plain-byte fixtures; no real LoRA compatibility or inference acceptance is established. Power loss, other operating systems, remote storage, and backup restore remain unqualified.

All 186 tests passed against source on Python 3.13.9 (24.24 seconds) and the installed 0.3.0 wheel on Python 3.11.14 (21.70 seconds). Lint, formatting, wheel and source-distribution builds, and byte parity for all 13 packaged source modules passed. The local workspace holds one neutral preset with verified workflow bytes and two ledger events; repeated import was idempotent and a stale import failed without changing the head. The initial focused-test failure caused by a CRLF test pointer, and its LF-fixture correction, are retained in the verification record.

## Stage four deterministic batch and rotation planning

Version 0.4.0 adds `batch plan` and `batch verify`. The [batch planning contract](batch-planning.md) defines exact request fields, selection order, integer random draws, seed derivation, LoRA weights and budgets, workflow bindings, resource limits, and provenance. The existing version-one catalog and ledger formats remain compatible; planning controls are a separate request format.

Plans are previews with optional immutable persistence, not queued jobs. Constraint exhaustion fails with the job index and per-preset reasons; the planner never silently relaxes cooldowns, chooses non-active LoRAs, or scales below minimum strengths. Verification replays all choices and expanded workflow bytes against the same current clean catalog head and asset hashes. Catalog history and job records remain unchanged.

The [local planning exercise](evidence/stage-04-planning-20260921.json) and [automated/package verification](evidence/stage-04-verification-20260921.json) record acceptance. Tests use neutral workflows and synthetic model/LoRA fixtures. Actual model inference, server asset-name resolution, global render seed reservations, batch submission/resume, and parallel GPU execution are not established by this stage.

All 234 tests passed against source on Python 3.13.9 (35.34 seconds) and the installed 0.4.0 wheel on Python 3.11.14 (33.10 seconds), including the same frozen selection and workflow-hash vectors. Lint, formatting, both package builds, and byte parity for all 16 source modules passed. The local neutral request produced one four-job plan with identical preview/repeated-save content and successful replay; an impossible cooldown request failed at index 1 without a partial plan. Catalog generations and existing job records were hash-checked unchanged.

## Stage five qualified sequential execution

Version 0.5.0 adds `batch qualify`, `run`, `status`, `resume`, and `abandon`. The [execution contract](batch-execution.md) defines the supported stock profile, immutable receipts, transactional reservations, ownership, failure states, and recovery limits. SQLite execution observations remain separate from the unchanged version-one catalog revision ledger. Existing planning and standalone job commands retain their scopes.

Qualification replays the plan and checks live node schemas, controlled launch arguments, runtime source identity, safe input/output bindings, actual checkpoint paths, and LoRA loader names against planned asset bytes. It is checked again before each new submission. Accepted work remains observable even if the catalog has changed. Unknown acceptance is reconciled only from matching server request IDs and exact graphs, never retried on absence. Abandonment retains seeds and refuses unresolved work.

The [real neutral execution evidence](evidence/stage-05-execution-20260921.json) records four sequential jobs, two jobs around an injected lost acknowledgement after actual server acceptance, and one timeout/resume job. All seven collected outputs were pixel-identical to the 64×64 input. Completed primary-batch resume made no runtime requests; no prior standalone job record or catalog generation changed. ComfyUI may cache identical neutral graphs. This is real transport/image-I/O acceptance, not checkpoint-based generation, GPU throughput, or media-quality qualification.

The newly added [Part 11 VRAM budget](design_spec/11_VRAM_budget.md) and [Part 12 trigger linter](design_spec/12_trigger_word_linter.md) were noticed during this increment and inspected at the outline level. They remain unchanged by this implementation and are design inputs for the next model-oriented work. Their measurement assumptions, alias semantics, legacy paths, and embedded examples still require reconciliation with the implemented catalog/executor before adoption; no VRAM predictor or trigger-linter acceptance is claimed here.

All 281 final tests passed against source on Python 3.13.9 (72.41 seconds) and the installed 0.5.0 wheel on Python 3.11.14 (68.06 seconds). Lint, formatting, wheel/source-distribution builds, and byte parity for all 20 packaged and imported modules passed. The installed wheel also resumed the completed real four-job batch. The [verification record](evidence/stage-05-verification-20260921.json) preserves both earlier packaging failures: a wheel preceding the final annotation-path guard and uv reusing that earlier installation after a same-path rebuild. Installing the rebuilt artifact through a content-addressed local path and checking imported bytes resolved the latter. No test assertion was weakened.

## Stage six pinned image inference

Version 0.6.0 adds `inference prepare` and `inference plan`, two versioned stock SDXL profiles, and an optional download helper using immutable upstream revisions, lengths, and SHA-256 pins. Preparation preserves existing catalog entries and publishes immutable candidate files without importing, reserving seeds, or submitting. Explicit import, qualification, and sequential execution reuse the existing contracts. Checkpoint pins in workflow metadata are now enforced during live qualification; LoRA bytes retain catalog and runtime-path verification. See the [inference contract](image-inference.md).

The [real inference evidence](evidence/stage-06-inference-20260921.json) records two base jobs and two LCM jobs on ComfyUI 0.37.0 / Torch 2.13.0+cu130 / RTX 5090. All four outputs decode to 1024×1024 RGB, have nonuniform pixels and distinct pixel hashes, and retain verified ownership, reserved seeds, prompt IDs, and artifact bytes. The server log reports 788 attached model patches for the LCM jobs. Existing standalone and stage-five job records remained unchanged; the catalog now contains the neutral preset, two inference presets, one LoRA, and four revision events. Model weights remain local and Git-ignored.

Actual inference exposed two defects that the neutral workflow had not exercised. ComfyUI converts integer CFG/denoise inputs to floats before retaining history; ownership matching now permits only lossless scalar integer/float equivalence, keeping booleans, links, metadata, and rounded large integers strict. Windows `SaveImage` returns backslashes in nested subfolders; validation now understands both separators while retaining the exact descriptor and rejecting traversal/absolute paths. Both initial failures and raw server history are preserved. Recovery collected the original accepted prompt and continued the batch without duplicate submission.

Visual inspection of all four retained images found recognisable red teapots and green fruit on wooden tables. Both base renders show four pears instead of two; the LCM renders show fruit/shape inconsistencies, and the final image adds another teapot. Functional execution passes; exact semantic compliance and human aesthetic acceptance do not. Whole-device GPU samples are observations, not per-model peak measurements or a calibrated Part 11 predictor.

All 400 tests passed against source on Python 3.13.9 (79.57 seconds) and the installed 0.6.0 wheel on Python 3.11.14 (79.85 seconds). Lint, formatting, wheel/source-distribution builds, and byte parity for all 21 source modules passed. The [verification record](evidence/stage-06-verification-20260921.json) separates fixture/package checks from the real model exercise and retains the initial test-directory setup failure. The full checkout suite also includes the independently developed cipher and Markdown utilities. Original design specifications remain unchanged by this increment.
