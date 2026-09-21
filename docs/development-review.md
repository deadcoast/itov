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
4. **Next:** add deterministic batch expansion and rotation over validated catalog snapshots. Define seed/node bindings, slot/status/conflict filtering, configurable strength budgets, and reproducible plan provenance before queueing expanded jobs. Introduce parallel workers only after measuring GPU capacity and isolated job ownership.
5. Implement model-specific video and audio integration against actual upstream APIs, with real checkpoints and separately defined output acceptance. Training, scraping, promotion, and scheduling remain later work.

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
