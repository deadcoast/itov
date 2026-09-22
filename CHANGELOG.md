# Changelog

Record user-visible changes, verification, and incomplete acceptance gates here as development progresses. Entries under Unreleased describe repository work, not a published package release.

## Unreleased

### 2026-09-21 — Measured VRAM and guarded sequential admission

- Advanced ITOV to 0.9.0 with `vram server`, `vram capture`, `vram check`, and optional `batch run/resume --vram-profile` guards. Measure allocator peaks inside ComfyUI and retain distinct global device samples, exact workload/runtime identity and cold/warm session evidence.
- Require repeated recent successful profiles, explicit uncertainty/reserve margins, idle queues and a proved cache state. Missing, stale, failed or mismatched evidence is refused. Part 11's unsupported memory formulas and fallback costs remain unused; all parallel-worker requests are refused.
- Bind immutable guards in the seed-reservation transaction, recheck before each new submission, retain guards on resume, and refuse missing/replaced bindings. Actual guarded audio execution completed two fresh jobs; incomplete evidence claimed no seeds, and completed replay made zero runtime requests.
- Isolated observer user data, SQLite index and temp cleanup. Retained the initial startup failure and preliminary measurements, then repeated captures. Fixed a stock VAE choice-order mismatch for explicitly selected, pinned VAE files; retained the original refusal and repeated both video sessions.
- Final profiles contain 16 real cold/warm jobs across audio, SDXL base, SDXL+LCM and Wan video. Fresh image/audio admission passed; the final video check refused headroom at 38.391 GiB required against 31.816 GiB capacity. Successful calibration does not override conservative admission or establish a capacity guarantee.
- Passed 648 tests against source on Python 3.13.9 and 648 against the installed wheel on Python 3.11.14, plus lint/format, both package builds, 29-module byte parity, all eight final profile validations, completed guarded resume and prior audio/video/mux checks. [Verification evidence](docs/evidence/stage-09-verification-20260921.json) retains failures and corrections; the separately developed SCM 0.5.0 installation was preserved.
- Added [VRAM commands, measurement policy and evidence](docs/vram-profiling.md), and updated the TODO/build plan with stage 9B device ownership, worker isolation, host-memory and parallel recovery tasks. Current acceptance is bounded measurement and guarded sequential execution; general prediction, parallel GPU work and media-quality acceptance remain open.

### 2026-09-21 — Bamboozle missing-ledger recovery and prepared-operation integrity

- Advanced SCM dev tools to 0.5.0. Added `bamboozle recover ENCODED --original ORIGINAL`, which previews by default and creates only the missing ledger with `--apply`. Recovery requires the supplied original and dictionary to reproduce the encoded bytes exactly, rejects existing metadata and edited pairs, and rechecks file fingerprints around publication.
- Added recovery publication reporting with `ledger_saved`, a retained `recovered: true` ledger flag, and missing-ledger guidance. Recovery establishes consistency with the supplied original; it does not authenticate historical provenance or recover an original lost during an in-place operation.
- Reproduced and fixed mutable prepared conversions saving unreviewed text with a mismatching ledger. Prepared operations now expose read-only inputs and snapshots, return detached ledger data, and track lifecycle independently of the report. Report edits cannot redirect publication or make a completed plan reusable. Normal mapping access and legacy conversion commands remain available.
- Passed all 201 focused tests, including 32 new recovery and plan-integrity regressions, plus Ruff lint/format and whitespace checks. Built source and wheel packages, verified seven packaged/installed files against source, and passed 14 installed command exercises beginning with an injected ledger-write failure after encoding.
- Operated the live Windows terminal through recovery preview, ledger creation, verification, decode preview/save, and quit. Recovery preserved the original and encoded bytes and modification times; strict restoration and terminal restoration matched the original bytes. Restored the editable installation and retained [verification evidence](docs/evidence/bamboozle-recovery-20260921.json), including the corrected test-key and terminal-fixture-path mistakes. Cross-process transactions, crash durability, and generated-code correctness remain outside this qualification.

### 2026-09-21 — Bamboozle restoration and preview improvements

- Advanced SCM dev tools to 0.4.0. Decode, Verify, and reverse Preview now use the dictionary saved in a valid ledger by default, allowing restoration after a custom dictionary is changed or removed. Explicit dictionaries must still match; malformed ledgers never silently fall back. Terminal and JSON reports identify the selected dictionary source and hash.
- Prevent decoding over a separate destination with its own cipher ledger, including with `--force`, and reject destination ledgers created between preview and save. Existing in-place restoration and version-1 ledger integrity limits remain supported.
- Added `--context N` for concise or expanded diffs; using it with Encode or Decode always previews without writes. Corrected CR-only newline markers and Unicode separator handling in diffs, while retaining exact source line comparisons and saved bytes.
- Added Refresh to the terminal preview so changed files can be reloaded and reviewed before saving. Updated both usage guides and the legacy flag interface.
- Passed all 169 focused tests, Ruff lint/format, and whitespace checks. Built source and wheel packages, checked seven packaged/installed files against source, passed 14 installed-command exercises, and operated the live Windows terminal through edit-during-preview, refresh, and save. Retained [verification evidence](docs/evidence/bamboozle-operations-20260921.json), including the reproduced prior defects and corrected initial lint finding. Checks cover local conversion and operations; ledger hashes remain consistency checks, and output/ledger updates are not a crash-atomic pair.

### 2026-09-21 — Pinned audio and owned audiovisual composition

- Advanced ITOV to 0.8.0 with `audio prepare`, `audio plan`, `audio verify`, and `av mux`. Added a pinned Stable Audio Open 1.0/T5 baseline using installed stock ComfyUI nodes; 5.746 GB of model files were downloaded and hash-verified locally.
- Added bounded stereo FLAC contracts, checkpoint/encoder pins, stock audio module/schema qualification, explicit seeds and full decoded sample validation. Failed collection preserves ownership/artifacts and pauses later jobs; completed resume validates audio without new submissions.
- Added composition from exact completed job records and artifact hashes. Audio starts at zero, resamples to 48 kHz, trims or pads to the video's duration, and retains its aligned PCM WAV. Immutable H.264/AAC outputs preserve every decoded video frame and verify stream duration plus contiguous audio timestamps. Repeated composition revalidates the existing output; failed attempts and differing files are preserved.
- Completed two actual 176128-sample stereo generations and two 1.375-second audiovisual pairs, with no duplicate prompts, no changed prior job records and successful completed replay. Retained [audio, video and runtime evidence](docs/audio-and-av.md#evidence-and-limits), including upstream sampler warnings.
- Passed 543 tests against source on Python 3.13.9 and 543 against the installed wheel on Python 3.11.14, plus lint, formatting, both package builds, 26-module byte parity and installed-package audio/mux/prior-video checks. [Verification evidence](docs/evidence/stage-08-verification-20260921.json) retains the initial receipt-serialization failures and their correction. Listening quality, semantic/lip synchronization and parallel GPU acceptance remain open.
- Updated the TODO and build plan with stage-nine measurement tasks, unresolved listening/semantic synchronization criteria, upstream warning review and capacity-measurement requirements. Original specifications and concurrent Bamboozle work remain separate.

### 2026-09-21 — Bamboozle core and terminal polish

- Advanced SCM dev tools to 0.3.0. Added a reusable `CipherEngine` that copies and validates its dictionary, reuses compiled matching rules, and collects independent counts during conversion. Existing string-returning helpers and CLI commands remain available.
- Fixed partial matches inside Unicode identifiers, including combining marks and connector characters. Conversion errors now identify a line and column; file fingerprinting reads bounded chunks, and the core API rejects invalid option combinations before accessing files.
- Corrected a reproduced cleanup failure that reported output as unsaved after publication. Preserve both publication and cleanup diagnostics when both fail, prevent reuse of partially finalized previews, and recheck the ledger after output publication before metadata changes. Output and ledger remain separate operations without an exclusive cross-process lock.
- Added `bamboozle --version` and retry-in-place for missing file paths in the terminal menu. `--json` now requires an explicit command. Updated engine, Unicode, error-reporting, and compatibility guidance.
- Passed all 138 focused cipher/CLI tests, including 27 new regressions. Built the source distribution and wheel, verified six packaged/installed files against source, passed 11 installed command exercises, and operated the real Windows terminal through missing-path recovery, preview, cancellation, and quit. Restored the editable installation in the existing environment. [Verification evidence](docs/evidence/bamboozle-core-20260921.json) records the original failures and local checks; generated-code correctness and crash durability remain unqualified.

### 2026-09-21 — Pinned image-to-video and persistent development TODO

- Added [TODO.md](TODO.md) with the current stage map, checked deliverables, required assets/tools, discovered defects and concrete next-stage tasks. Stage 7 is complete for the bounded silent-video baseline; stage 8 audio contracts are next.
- Advanced ITOV to 0.7.0 with `video prepare`, `video plan`, and `video verify`, a pinned Wan 2.2 TI2V 5B stock workflow, immutable PNG/model bindings, and deterministic seeded plans. Added a three-file, 18.145 GB video download manifest and complete-baseline capacity checks; weights remain local and Git-ignored.
- Added the `stock-wan22-v1` qualification profile with exact stock module identity/source checks and refusal of ambiguous loader aliases. Preserved existing image receipts. Added ComfyUI V3 selected-branch input validation for native MP4/H.264 encoding.
- Require exact video dimensions, frame rate/count, duration, full RGB decode, constant timestamps and frame variation before the next batch job. Completed resume revalidates media. Failed collection may be retired only with fresh owned terminal server evidence, preserving artifacts and permanent seed reservations.
- Completed two actual 640×640 Wan clips, each 33 frames at 24 fps. Verified one prompt per request, distinct artifacts, completed resume, and unchanged prior job records. Retained [clips, frames, runtime observations and evidence](docs/image-to-video.md#evidence-and-limits). Fixed the initial top-level-input preflight failure before any render submission and preserved its evidence.
- Passed 474 tests against source on Python 3.13.9 and 474 against the installed wheel on Python 3.11.14, plus lint, formatting, package builds, 23-module byte parity, installed-wheel resume and real MP4 verification. The [verification record](docs/evidence/stage-07-verification-20260921.json) retains initial environment/test failures and their corrections.
- Representative-frame inspection found an unrequested hand in the first clip. Quality acceptance, audio, long clips, calibrated VRAM prediction and parallel GPU execution remain open. Updated the build plan and usage guides while preserving original specifications and unrelated user work.

### 2026-09-21 — Bamboozle terminal interface

- Added `bamboozle encode`, `decode`, `preview`, `verify`, and `validate`, plus a guided no-argument terminal menu with pasted paths, a diff before Save, output-path selection, explicit overwrite confirmation, and clean cancellation/EOF/Ctrl+C behavior. Added a repository-aware PowerShell launcher and directory/module entry points.
- Prepared conversions now retain the exact reviewed text and file fingerprints. Save rejects changes to the input, mapping, ledger, or output after preview. New commands preserve existing destinations unless `--force` is supplied; publishing a new file also preserves a destination created concurrently.
- Packaged SCM dev tools 0.2.0 with its dictionary and both `bamboozle` and legacy `scm-cipher` entry points. Retained the legacy flag interface and the user's existing author metadata. Installed the final tool as an editable package in the existing project environment.
- Passed all 111 focused cipher/CLI tests, Ruff lint and formatting, and whitespace checks. Built the source distribution and wheel, verified five packaged/installed files against source, and passed eight installed-wheel command exercises from an unrelated working directory. Corrected an initial package build that included `setup.py` as a runtime module before installing the final wheel.
- Operated the real Windows terminal through preview, encode/save, verification, decode/save, and quit; the restored bytes matched the original and successful decode removed its ledger. Also checked the installed command's no-argument menu, preview, invalid-choice recovery, and cancellation. Retained [verification evidence](docs/evidence/bamboozle-terminal-20260921.json). These checks cover local CLI and package behavior; generated-code correctness and ComfyUI acceptance remain separate.

### 2026-09-21 — Pinned SDXL and LCM image inference

- Advanced development to 0.6.0 with `inference prepare` and `inference plan`, versioned stock SDXL base/LCM workflows, explicit seeds, immutable catalog candidates, and checkpoint/LoRA hash verification. Preparation preserves existing entries and submits no jobs.
- Added example specifications and an optional model downloader pinned to immutable upstream revisions, exact byte lengths, and SHA-256 hashes. Existing differing files are preserved; weights and workspace copies remain Git-ignored.
- Completed four actual sequential 1024×1024 inference jobs on the local RTX 5090: two SDXL base and two SDXL+LCM. Collected distinct decoded outputs with verified ownership/artifact hashes and retained prior job records. See [execution evidence and images](docs/image-inference.md#local-acceptance-evidence).
- Fixed two defects revealed by real inference: lossless integer/float input normalization in ComfyUI history and Windows backslashes in nested output descriptors. Kept strict ownership/path checks, retained both original failures, and resumed the same accepted prompt without resubmitting it.
- Passed 400 tests against source on Python 3.13.9 and 400 against the installed wheel on Python 3.11.14, plus lint, formatting, package builds, and byte parity for 21 modules. [Verification evidence](docs/evidence/stage-06-verification-20260921.json) distinguishes fixtures, packaging, and real inference.
- Recorded visual object-count/shape errors despite recognisable subjects. General media quality, additional model compatibility, calibrated VRAM prediction, video/audio integration, and parallel GPU execution remain open. Updated the build plan and usage guidance; original design specifications remain unchanged.

### 2026-09-21 — Bamboozle previews and integrity verification

- Expanded the standalone cipher with read-only `--dry-run` and `--diff`, versioned JSON reports, substitution/literal counts, and a dictionary-only `--mode validate` command. Omitted output paths now use the established `_safe` and `_ready` filename conventions.
- Added version-2 ledgers with original/encoded byte hashes and a canonical dictionary hash. `--mode verify` checks both encoded content and restored-original bytes without writes; reverse `--strict` requires the unchanged encoded file. Ordinary reverse continues to accept edited files and reports the integrity boundary.
- Retained version-1 and ledger-free reverse compatibility, added `--keep-ledger` for repeated restoration to separate outputs, and reject accidental double encoding when an input already has a ledger. JSON failures state whether output publication already succeeded.
- Updated the Bamboozle usage guides with commands, report fields, compatibility rules, and the distinction between consistency checks and authentication.
- Passed all 74 focused tests, including the prior 48 regressions and 26 new cases covering preview non-mutation, actual CLI subprocesses, strict/edited/legacy reversal, malformed hashes, canonical dictionary hashing, default paths, repeated restoration, and structured failure reporting. Focused Ruff lint/format and `git diff --check` passed. Verification covers local text conversion on Windows Python 3.13; it does not establish Python refactoring correctness or installed SCM package acceptance.

### 2026-09-21 — Cipher conversion repair

- Continued from the user's startup syntax fix. Replaced sequential substitutions with a single pass so generated replacements and protected native terms are never rewritten during the same conversion.
- Added dictionary and marker validation, explicit rejection of unsupported case and ambiguous mappings, and an exact forward/reverse round-trip check before publishing forward output.
- Resolved the default dictionary beside the script, preserved UTF-8 BOMs and line endings, and used complete temporary writes before replacing output files. Errors return a nonzero status; failures after output publication explicitly identify that the output was saved.
- Replaced the shared directory ledger with one ledger beside each encoded output. Reverse conversion checks its recorded dictionary and removes it only after saving output; legacy directory ledgers remain untouched. Updated both usage guides.
- Passed 48 focused regression tests on local Windows Python 3.13, including real CLI subprocesses, native literals, cascading substitutions, dictionary errors, multiple files/directories, in-place conversion, and injected output/ledger failures. Focused Ruff lint/format and `git diff --check` passed. The first file-test run had 34 passes and 12 setup errors because the existing `.test-tmp` directory denied access; all tests passed using a fresh repository-local temporary directory. This verification covers local text conversion, not edited-code correctness, installed SCM packaging, or ComfyUI execution.

### 2026-09-21 — Qualified sequential batch execution

- Advanced development to 0.5.0 and implemented opt-in `batch qualify`, `run`, `status`, `resume`, and `abandon` commands.
- Added immutable stock-runtime qualification receipts with live schema checks, controlled launch arguments, runtime/input/model hashes, exact planned LoRA loader resolution, safe output prefixes, and explicit sampler seed coverage. Recheck qualification before each new submission.
- Added transactional whole-batch ownership and permanent workspace seed reservations, deterministic per-job IDs, execution observations, and an OS-owned dispatcher lock. Only verified output collection permits the next job.
- Added safe acknowledgement reconciliation using exact server request IDs and graphs, timeout/crash resume without automatic resubmission, missing/regressed ownership refusal, and conservative abandonment that keeps seeds and refuses unresolved work.
- Qualified seven actual neutral ComfyUI jobs across a four-job sequential run, a two-job lost-acknowledgement recovery run, and a timeout/resume run. All outputs were pixel-identical; completed resume made zero runtime requests. Retained [real execution evidence](docs/evidence/stage-05-execution-20260921.json).
- Passed all 281 tests against source on Python 3.13.9 and all 281 against the installed wheel on Python 3.11.14. Lint, formatting, both package builds, packaged/installed byte parity for all 20 modules, and installed-wheel resume of the real completed batch passed. Retained the initial pre-fix wheel parity failure and stale uv wheel-cache regression failure, followed by the corrected artifact installation and passing checks, in [verification evidence](docs/evidence/stage-05-verification-20260921.json).
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
