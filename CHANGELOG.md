# Changelog

Record user-visible changes, verification, and incomplete acceptance gates here as development progresses. Entries under Unreleased describe repository work, not a published package release.

## Unreleased

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
