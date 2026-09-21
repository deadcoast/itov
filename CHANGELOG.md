# Changelog

Record user-visible changes, verification, and incomplete acceptance gates here as development progresses. Entries under Unreleased describe repository work, not a published package release.

## Unreleased

### 2026-09-21 — Qualified sequential batch execution

- Advanced development to 0.5.0 and implemented opt-in `batch qualify`, `run`, `status`, `resume`, and `abandon` commands.
- Added immutable stock-runtime qualification receipts with live schema checks, controlled launch arguments, runtime/input/model hashes, exact planned LoRA loader resolution, safe output prefixes, and explicit sampler seed coverage. Recheck qualification before each new submission.
- Added transactional whole-batch ownership and permanent workspace seed reservations, deterministic per-job IDs, execution observations, and an OS-owned dispatcher lock. Only verified output collection permits the next job.
- Added safe acknowledgement reconciliation using exact server request IDs and graphs, timeout/crash resume without automatic resubmission, missing/regressed ownership refusal, and conservative abandonment that keeps seeds and refuses unresolved work.
- Qualified seven actual neutral ComfyUI jobs across a four-job sequential run, a two-job lost-acknowledgement recovery run, and a timeout/resume run. All outputs were pixel-identical; completed resume made zero runtime requests. Retained [real execution evidence](docs/evidence/stage-05-execution-20260921.json).
- Added [execution and recovery guidance](docs/batch-execution.md), updated the build plan, and retained the original eleven design documents. Checkpoint/LoRA inference, custom nodes, video/audio generation, parallel GPU workers, power loss, and backup restore remain unqualified.

### 2026-09-21 — Deterministic batch and rotation planning

- Advanced development to 0.4.0 and completed the planning portion of build-plan gate four.
- Added `itov batch plan` and `batch verify`, clean catalog-head pinning, explicit seed/LoRA loader bindings, exact workflow expansion, asset provenance, and optional immutable plan persistence.
- Added versioned deterministic weighted selection, preset/category/LoRA cooldowns, active/model/slot filtering, hard and explicit soft-conflict handling, preference and synergy weights, and configurable strength budgets that preserve declared minima.
- Added unsigned 64-bit seed derivation with in-plan collision checks and overflow rejection. Exhausted or oversized requests fail explicitly without saving partial plans or relaxing constraints.
- Added frozen random-draw, selection, strength, and workflow-hash vectors, cross-process reproducibility checks, replay/tamper checks, and a neutral planning example. Retained [local planning evidence](docs/evidence/stage-04-planning-20260921.json) and [verification evidence](docs/evidence/stage-04-verification-20260921.json).
- Passed all 234 tests against source on Python 3.13.9 and all 234 against the installed wheel on Python 3.11.14, including identical frozen rotation/workflow vectors. Lint, formatting, wheel/source-distribution builds, and byte parity for all 16 packaged source modules passed.
- Documented request fields, algorithm order, provenance, and limits in [batch planning guidance](docs/batch-planning.md). Catalog/ledger schema v1 remains compatible.
- Batch submission, global seed/history reservation, actual model and loader-name qualification, and GPU concurrency remain open. Planning does not queue work or change render history.

### 2026-09-21 — Catalog schemas and recoverable revision history

- Advanced development to 0.3.0 and implemented build-plan gate three for catalog revisions.
- Added strict version-one preset, LoRA asset, and compatibility contracts, workspace-relative asset hashes, API graph checks, exact integer weights/strengths, and one documented ledger hash encoding with frozen vectors.
- Added `itov catalog validate`, `init`, `import`, `show`, `verify`, and `recover`; imports require the reviewed head and verify referenced file bytes before recording a revision.
- Added immutable catalog/history generations, complete redo intent before publication, a single atomic commit pointer, shared OS-backed locking, and explicit idempotent recovery that preserves corrupt or divergent data.
- Tested Windows process crashes at commit boundaries and during partial temporary writes, competing writers, concurrent readers, stale updates, immutable reads, tampering, and junction containment. Retained [local catalog evidence](docs/evidence/stage-03-catalog-20260921.json) and [automated verification](docs/evidence/stage-03-verification-20260921.json).
- Passed all 186 tests against source on Python 3.13.9 and all 186 against the installed wheel on Python 3.11.14. Lint, formatting, wheel/source-distribution builds, and byte parity for all 13 packaged source modules passed. Retained the initial CRLF test-fixture failure and its correction in the verification record.
- Added [catalog schema and recovery guidance](docs/catalog-and-ledger.md) and a neutral example helper that refuses overwrites. Updated the build plan to deterministic batch/rotation planning next.
- Rotation, automated promotion, legacy ledger migration, backup restore, power-loss durability, and real LoRA/model acceptance remain open.

### 2026-09-21 — Runtime qualification and single-worker jobs

- Advanced the package to 0.2.0 in development; no package release was published.
- Downloaded and checksum-verified the official ComfyUI v0.37.0 NVIDIA portable archive, checked archive path containment, and installed the runtime locally while preserving the older archive.
- Qualified the RTX 5090 with embedded Python 3.13.14, PyTorch 2.13.0+cu130, CUDA 13.0, and a real BF16 matrix operation. Started the server on loopback with custom nodes disabled.
- Added `itov server start`, `itov job run`, and `itov job wait`, plus a deterministic neutral input-image helper.
- Added durable submission intent, explicit unknown/rejected/failed/timed-out states, resumable observation, structured server errors, per-job OS locking, and exact history-based artifact downloads with SHA-256 verification and overwrite protection.
- Verified a real neutral image-copy workflow with pixel-identical output, timeout/resume using the same prompt ID, and a real execution failure from an invalid image. Retained passing and failing evidence in [the runtime qualification record](docs/evidence/stage-02-runtime-20260921.json).
- Passed all 101 tests against source on Python 3.13.9 and all 101 against the built wheel on Python 3.11.14. Lint, formatting, wheel/source-distribution builds, and packaged-source byte parity passed; retained [automated verification evidence](docs/evidence/stage-02-verification-20260921.json).
- Documented launch, observation, and cancellation semantics in [runtime and job guidance](docs/runtime-and-jobs.md). Job Ctrl+C detaches the observer; targeted server-side cancellation is not implemented.
- Model inference, video generation, custom-node qualification, and the manifest/ledger stages remain open.

### 2026-09-21 — Initial development foundation

- Added the uv-managed ITOV Python package and CLI commands for workspace initialization, environment diagnostics, and exported ComfyUI API workflow validation.
- Added versioned TOML configuration, configuration-relative paths, portable-runtime detection, Unicode path support, and protection against overwriting an existing workspace configuration.
- Added read-only ComfyUI metadata access with bounded response sizes, timeouts, explicit HTTP errors, and strict JSON parsing.
- Added graph and node-schema checks, a neutral image-copy example, and Git exclusions for runtimes, model weights, generated media, and development caches.
- Reviewed the original design documents and recorded implementation defects, current compatibility findings, and the staged build plan in [the development review](docs/development-review.md). The eleven original documents were preserved.
- Verified 74 tests against source on Python 3.13.9 and 74 against the built wheel on Python 3.11.14. Lint, formatting, source-distribution and wheel builds passed. Retained [verification evidence](docs/evidence/stage-01-verification-20260921.json).
- Retained the [failed runtime preflight](docs/evidence/stage-01-doctor-20260921.json): no extracted ComfyUI runtime, embedded interpreter, or listening server at the configured address. No real workflow execution or rendering acceptance was established in this stage.

### 2026-09-21 — GitHub publication repair

- Removed the 1.86 GB ComfyUI installer from both unpublished commits while preserving the installer locally and retaining a recovery bundle of the original history.
- Added an ignore rule for local ComfyUI archives and successfully published the document history to `deadcoast/itov`.
- Configured `main` to track `origin/main` and established the remote default-branch reference. Verified matching local and remote commits and a clean working tree at the time of repair.

### 2026-09-20 — Design documentation

- Added the initial project research and design material, later organized into the eleven Markdown files under `docs/`.
