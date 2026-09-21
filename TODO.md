# Development TODO

Updated 2026-09-21. This is the working task list for continued development. The [build plan](docs/development-review.md) records design decisions and acceptance evidence; [CHANGELOG.md](CHANGELOG.md) records delivered increments. Original documents under `docs/design_spec/` are design inputs, not proof that their examples work.

Current checkpoint: stage 7's bounded silent-video implementation and verification are complete. Next development stage: 8, audio model/API selection and timing contracts. The recorded image/video quality defects remain open alongside that work.

## Working rules

- Keep one active development stage. Finish its implementation and relevant verification before advancing.
- Add newly discovered requirements, defects, and external dependencies below with a concrete next action.
- Check a task only when its stated evidence exists. Source tests, installed-package checks, actual model execution, visual review, and human acceptance are separate.
- Preserve failed evidence and existing user changes. Keep downloaded models and generated workspace state out of Git.
- Update this TODO, the build plan, and the changelog at each completed increment.

## Development stages

| Stage | Status | Deliverable and acceptance boundary |
| --- | --- | --- |
| 1. Workspace and workflow preflight | Complete | Configurable CLI, diagnostics, API graph validation; [evidence](docs/evidence/stage-01-verification-20260921.json). |
| 2. Runtime and individual jobs | Complete for neutral workflow | Local CUDA runtime, submission, observation, recovery, exact artifact retrieval; [evidence](docs/evidence/stage-02-runtime-20260921.json). |
| 3. Catalog and revision ledger | Complete for local revisions | Versioned schemas, immutable snapshots, locking and explicit recovery; [evidence](docs/evidence/stage-03-verification-20260921.json). |
| 4. Deterministic batch and rotation planning | Complete | Replayable plans, selection/cooldowns, explicit seed and loader bindings; [evidence](docs/evidence/stage-04-verification-20260921.json). |
| 5. Qualified sequential execution | Complete for documented cases | Whole-batch ownership, seed reservations, one-at-a-time execution and uncertain-outcome recovery; [evidence](docs/evidence/stage-05-execution-20260921.json). |
| 6. Pinned image inference | Complete for selected baseline | User-selected official SDXL 1.0 + LCM LoRA; four real 1024×1024 outputs; [evidence](docs/evidence/stage-06-inference-20260921.json). Exact prompt compliance and general quality remain open. |
| 7. Image-to-video | Complete for the bounded baseline | Two real Wan 2.2 TI2V 5B clips, pinned input/model files, sequential execution, full media validation, resume and resource observations; [evidence](docs/evidence/stage-07-video-20260921.json). General quality remains open. |
| 8. Audio and audiovisual output | **Next** | Select actual upstream audio API/model, define duration/sample-rate/timing contracts, generate and validate separate audio, mux and verify synchronization. |
| 9. Measured VRAM and parallel admission | Planned; requires representative 7/8 runs | Reconcile Part 11, measure cold/warm workloads and uncertainty, validate refusal/admission and isolated ownership before parallel GPU jobs. |
| 10. Trigger and scene constraints | Planned | Reconcile Part 12 aliases, scoring and phrase/template schemas against the real catalogs; retain source provenance and explicit constraints. |
| 11. Training, evaluation and promotion | Planned | Replace design skeletons with selected upstream APIs, dataset provenance, independent acceptance and explicit catalog promotion. |
| 12. Discovery, lookup, scheduling and curation | Planned | Reconcile Parts 7/8 and 12.1–12.4; build on accepted media contracts and durable ownership rather than filename guesses. |

## Stage 7 completed tasks

- [x] Read the current build plan and confirm stage-six execution/package evidence exists.
- [x] Inspect installed stock Wan/video node implementations and current disk capacity.
- [x] Record the upstream workflow, immutable model revisions, exact byte lengths and SHA-256 hashes.
- [x] Prepare strict, versioned image-to-video specifications and deterministic catalog/plan generation.
- [x] Pin the source image and each model dependency; refuse changed bytes and ambiguous stock loader search paths.
- [x] Extend qualification only for the required stock nodes and their source modules, preserving existing image receipts.
- [x] Validate MP4 artifacts with exact frame count, dimensions, frame rate, duration, successful full decode and observable frame variation.
- [x] Acquire and hash-verify model files, preserving all existing assets.
- [x] Execute two neutral seeded clips through the sequential runner, inspect representative frames and retain timing/GPU observations.
- [x] Verify completed resume, prior job preservation and no duplicate prompt ownership.
- [x] Require top-level PNG names after the real nested-input preflight failure; retain the failure and retire only its unsubmitted preset.
- [x] Support explicit retirement of failed media collection only with fresh owned terminal server evidence; retain seeds and artifacts.
- [x] Pass focused regressions, source/package checks, update documentation/changelog, and retain successful and failed evidence. Final source and installed-wheel suites: 474 passed each; 23 ITOV modules match the built wheel.

## Next stage 8 tasks

- [ ] Select a neutral audio baseline from an actual upstream model/API; record required assets, hashes, disk capacity and runtime dependencies.
- [ ] Define sample rate, channel layout, target duration, trimming/padding policy and synchronization tolerances against the accepted video contract.
- [ ] Add explicit audio input/output binding and owned artifact validation without changing existing silent-video behavior.
- [ ] Implement explicit muxing with provenance for both inputs and decoded duration/synchronization checks.
- [ ] Exercise real audio generation, paired video/audio output, failure preservation and resume; retain source/package and runtime evidence separately.
- [ ] Update this TODO, development review and changelog before advancing to stage 9.

## Required inputs and dependencies

| ID | Requirement | Status / next action |
| --- | --- | --- |
| REQ-01 | Reference image baseline | Satisfied: official SDXL 1.0 + LCM selected by user; retain the existing stage-six images and model pins. |
| REQ-02 | Video model files | Satisfied: three files, immutable revision and hashes in [video-assets.json](examples/video-assets.json); 18.145 GB downloaded and verified. |
| REQ-03 | Stock runtime schema | Satisfied for this baseline: live schemas, exact module checks, nested choices and real execution verified. |
| REQ-04 | Neutral source image | Satisfied: pinned stage-six still life copied immutably to a top-level workspace input filename. |
| REQ-05 | Disk capacity | Complete-baseline capacity plus reserve checked before download; about 55.8 GB was free at stage start. Recheck before future assets. |
| REQ-06 | Video decoding tools | FFmpeg/ffprobe used for bounded full-decode checks; versions and results retained in stage-seven evidence. |
| REQ-07 | GPU capacity evidence | Two actual video runs sampled; maximum observed whole-device usage was 31,507 MiB of 32,607 MiB. This includes caches/other allocations and can miss peaks; it does not calibrate a predictor or authorize concurrency. Stage 9 remains open. |
| REQ-08 | Media quality acceptance | Open: stage-six count/shape errors; stage-seven clip 1 adds an unrequested hand. Preserve examples and define independent quality acceptance. |
| REQ-09 | Audio baseline and timing | Pending stage 8: select upstream model/API and pin assets; define sample rate, duration, alignment and mux validation before implementation. |

## Follow-up requirements and known limits

- [ ] Investigate the unrequested hand in stage-seven clip 1 using defined scene/motion constraints and independent quality criteria; retain the failing output.
- [ ] Define reference scenes and measurable quality criteria before claiming production image/video quality.
- [ ] Reconcile the design documents' named model files, custom nodes, tuning and speed claims with current upstream evidence; do not install their embedded scripts verbatim.
- [ ] Qualify other model/LoRA combinations individually; one successful baseline does not establish arbitrary compatibility.
- [ ] Extend video qualification beyond two 1.375-second clips: longer sequences, representative resolutions and full playback review, with explicit quality criteria.
- [ ] Design explicit workspace backup/restore and test recovery. Current process-crash checks do not establish power-loss, network-filesystem or partial-backup safety.
- [ ] Keep the existing user-deleted `.cipher-review-temp/` files outside this increment; any repository hygiene cleanup must preserve that unrelated work.
