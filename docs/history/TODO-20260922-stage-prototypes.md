# Development TODO

Updated 2026-09-22. This is the working task list for continued development. The [build plan](docs/development-review.md) records design decisions and acceptance evidence; [CHANGELOG.md](CHANGELOG.md) records delivered increments. Original documents under `docs/design_spec/` are design inputs, not proof that their examples work.

Current checkpoint: Stage 11B implementation and the bounded curated pilot are verified: eight public-domain still lifes, a corrected 128-step run, 16 fixed comparisons, a stock ComfyUI pair, 872 source tests and 872 installed-wheel tests. The [independent review packet](docs/evidence/stage-11b-review/README.md) is ready. Human acceptance, trigger specificity and retained quality failures remain open; the candidate is unpromoted. Stage 12 has not started.

## Stage 11B active tasks

- [x] Record per-artwork source metadata, permission basis, selection/caption notes, preprocessing and disjoint train/validation groups; fully decode and visually inspect selected images. Eight-work public-domain Met pilot, six train/two artist-disjoint validation.
- [x] Bind immutable curation and held-out/regression evaluation cases into training before execution. Compare base/adapter with and without the trigger at identical seeds.
- [x] Build complete review packets and strict review coverage checks; require an independent human attestation and preserve rejected or pending outcomes.
- [x] Train a bounded curated candidate and retain all technical results, exported weights, comparison images and runtime compatibility evidence. Corrected 128-step run, 16 matrix images and two ComfyUI jobs passed technical checks; main catalog unchanged. Initial memory refusal and invalid weight-reference result retained.
- [x] Verify malformed/stale evidence rejection, source and installed-package behavior; update evidence, documentation and changelog. Passed 872 source and 872 installed-wheel tests, lint/format/build, 42-module parity, exact README packaging, actual JSON/text offline CLI checks and preserved SCM 0.5.0. [Verification](docs/evidence/stage-11b-verification-20260922.json).
- [ ] Obtain the user's independent quality review of the concrete packet. This cannot be replaced by assistant inspection or automated tests; promotion stays blocked until acceptance.
- [ ] Resolve the recorded quality failures before any passing promotion decision: one regression seed produces divided panels/extra objects; the stock ComfyUI candidate shows one pear instead of two; trigger specificity is unestablished. Preserve these cases and gather human observations before planning a new iteration.

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
| 8. Audio and audiovisual output | Complete for the bounded baseline | Two real Stable Audio Open stereo FLACs and two owned H.264/AAC pairs; full decode, trim/pad, timing, source-frame preservation and repeat verification. [Evidence](docs/evidence/stage-08-audio-20260921.json). Listening and semantic synchronization remain open. |
| 9. Measured VRAM and parallel admission | **Complete for the bounded Windows/audio path** | Eight real calibration jobs and two overlapping audio jobs; managed same-user GPU leases, isolated workers, native recovery, aggregate admission and offline replay verified. Initial host-memory refusal retained. [Ownership and evidence](docs/parallel-execution.md). |
| 10. Trigger and scene constraints | Complete for bounded offline validation | Versioned lexical contracts, deterministic collision/scene reports, report-only aliases, source provenance and actual catalog/plan checks. [Scope/evidence](docs/triggers-and-scenes.md). Model activation and quality remain open. |
| 11. Training, evaluation and promotion | **11A complete for smoke scope; 11B implemented, independent quality gate open** | Curated eight-work pilot, 128-step training, fixed 16-image comparisons, stock ComfyUI pair and pending independent review packet delivered. Known prompt/regression failures retained; no promotion. [Quality workflow](docs/curated-quality-review.md). |
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

## Stage 8 completed tasks

- [x] Select a neutral audio baseline from an actual upstream model/API; record required assets, hashes, disk capacity and runtime dependencies. Stable Audio Open 1.0 + T5, 5.746 GB verified; existing stock runtime.
- [x] Define sample rate, channel layout, target duration, trimming/padding policy and synchronization tolerances against the accepted video contract. See [audio/A/V contracts](docs/audio-and-av.md).
- [x] Add explicit audio input/output binding and owned artifact validation without changing existing silent-video behavior.
- [x] Implement explicit muxing with provenance for both inputs and decoded duration/synchronization checks.
- [x] Exercise real audio generation, paired video/audio output and completed replay. Synthetic failure-injection tests cover collection pause/resume and retained mux attempts. Keep those boundaries explicit in the separate runtime and source/package evidence.
- [x] Pass 543 tests against source and the installed wheel, lint/format/build checks, 26-module byte parity, installed audio verification/mux replay and prior-video resume. Update this TODO, development review and changelog before advancing to stage 9.

## Stage 9A measurement and admission

- [x] Reconcile Part 11's fixed reserves, LoRA-strength exponent, attention ratios and block-swap savings with installed stock loaders. Unsupported formulas remain unused and unverified.
- [x] Define immutable measurement records keyed by exact graph/model/source hashes, dimensions/duration, precision selections, runtime/driver, allocator, cache state and device identity.
- [x] Capture cold/warm image, video and audio workloads in repeated fresh processes. Keep allocator peaks separate from sampled global device memory; retain uncertainty and failed evidence.
- [x] Isolate observer user data, asset database and temp cleanup. Preserve the initial measurements and repeat them after the identity change.
- [x] Reproduce stock VAE choice-order instability across fresh processes; normalize only the explicitly selected VAE filename choices and repeat video calibration. Preserve the original refusal.
- [x] Refuse missing, stale, failed, mismatched or insufficient evidence; require a successful last-execution measurement for a used process. Keep policy margins explicit and execution sequential.
- [x] Bind profile guards atomically with seed reservations. Test pre-claim refusal, resume persistence, missing bindings, queue/cache pressure and changed evidence.
- [x] Execute two fresh guarded audio jobs and verify completed resume with zero runtime requests. Refuse incomplete evidence without claiming seeds and refuse two-worker admission.
- [x] Finish final video headroom assessment: repeated identities match; admission refuses 38.391 GiB required against 31.816 GiB capacity. No seeds claimed or jobs submitted by that check.
- [x] Pass 648 source tests and 648 installed-wheel tests, lint/format/build checks, 29-module byte parity, installed guarded resume and prior audio/video/mux regressions. Update evidence, TODO, build plan and changelog. [Verification](docs/evidence/stage-09-verification-20260921.json).

## Stage 9B completed tasks

- [x] Define same-user device leases keyed by GPU UUID, including cross-workspace ownership and conservative unknown-owner recovery. Actual Windows handles bind PID plus creation time; no `os.kill(pid, 0)`.
- [x] Isolate each worker's port, input/output, user/database/temp and telemetry paths; retain whole-workspace catalog/seed integrity and distinct collected artifact ownership.
- [x] Test simultaneous contention, atomic job membership, controller death before/after worker registration, confirmed shutdown and sticky lease recovery with actual Windows processes. Test lost acknowledgement and duplicate prevention with concurrent HTTP fixtures; interrupted workers are explicitly retired, never restarted automatically.
- [x] Add measured host working-set/commit envelopes, available physical/commit checks and aggregate whole-device GPU pressure. Document that other users, unmanaged clients and ordinary sequential commands bypass this managed lease.
- [x] Execute two fresh four-job serial calibrations of pinned neutral audio, providing two cold/warm sessions per worker. Retain the initial logging failure, confirmed recovery and all four reserved seeds; repeat with fresh seeds after the fix.
- [x] Exercise actual cross-workspace contention and conservative parallel admission refusal: 23,702,423,143 host bytes required versus 22,614,253,568 available commit. No execution claim or POST; owned workers stopped and shared device lease returned idle.
- [x] Attempt supported idle-server cache release; retain unchanged history and measured memory. It did not free measurable commit headroom. Do not lower policy margins or stop unrelated applications to force admission.
- [x] Pass 693 source and 693 installed-wheel tests, lint/format/build, 33-module byte parity, installed calibration validation/replay and prior media regressions. Preserve the initial Windows-label mismatch and its narrow correction. [Verification](docs/evidence/stage-09b-verification-20260921.json).
- [x] After the user freed memory, admit the prepared two-job plan with 30,357,254,144 bytes of available host commit against the unchanged 23,702,423,143-byte requirement. Preserve the original refusal; no margin changes.
- [x] Qualify two real audio jobs with 4.087163999 seconds of prompt execution overlap, distinct fully decoded FLACs and zero-HTTP completed replay from both source and installed wheel. Confirm owned workers dead, lease idle and prior jobs/original server history unchanged. [Runtime](docs/evidence/stage-09b-parallel-20260921.json) and [completion](docs/evidence/stage-09b-completion-20260921.json).

## Stage 10 completed tasks

- [x] Reconcile Part 12 trigger aliases, Part 12.2 constraints and scene-template definitions against the existing catalog and plan schemas. The source has incompatible schemas/classes/exit codes, incomplete helpers, unreachable reserved-pair blocking and unproved activation-token rewriting. Part 12.2 is a later phrase-bank solver, not an existing scene schema.
- [x] Define explicit, versioned validation contracts and deterministic diagnostics before implementing scoring or automatic behavior. No activation rewriting, automatic scoring, relaxation or promotion; supplied vocabulary hashes and normalization identity remain bound.
- [x] Implement the bounded offline validation path and exercise accepted/rejected examples. Two image and two audio planned jobs passed; a deliberate scene violation produced four errors. Zero HTTP; 146 catalog/workflow/database/job files preserved. [Evidence](docs/evidence/stage-10-offline-20260921.json). The current LCM entry has no declared triggers; collision behavior is covered by metadata fixtures.
- [x] Verify source/package commands and update evidence, this stage map and the changelog before advancing to training or promotion. Passed 763 source and 763 installed-wheel tests, lint/format/build and 36-module parity. Source/installed CLI checks passed with zero HTTP; completed replay retained jobs/seeds and appended only 12 expected audit events. Preserve the initial harness assumption failure separately. [Verification](docs/evidence/stage-10-verification-20260921.json).

## Stage 11A completed; next: Stage 11B independent quality

- [x] Reconcile the incomplete voice/LTX training and evaluation sketches with current upstream APIs. Select the user-approved SDXL UNet LoRA smoke baseline; preserve original design inputs.
- [x] Define and verify a dataset manifest: declared source permissions, purpose, byte hashes, preprocessing and train/validation groups. User approved neutral procedural images; shared-generator splits cannot establish natural-data generalization.
- [x] Specify the smoke scene, five promotion review criteria and paired held-out diagnostics. Retain incorrect object count/composition as failed quality evidence; this does not close independent quality/activation review.
- [x] Pin Diffusers 0.38.0, PEFT 0.21.0 and Accelerate 1.15.0 in a separate workspace environment, reusing existing Torch read-only. Pin Transformers 4.57.6, hub 0.36.0 and tokenizers 0.22.2 after the observed CLIP incompatibility. Pin local SDXL configuration; no checkpoint download.
- [x] Verify bounded training plans and native Windows process/device ownership, retained failures, no automatic retry and explicit dead-owner recovery.
- [x] Run eight rank-four optimizer steps at 512px, retain 1,120 finite changed tensors, paired held-out loss and four baseline/candidate preview images. Actual Torch peaks: 8,344,747,008 allocated and 9,588,178,944 reserved bytes; start floors remain experimental policy.
- [x] Keep trained outputs as candidates with immutable lineage. Require reviewed promotion tied to assessment/export identity; every smoke plan is refused. Main catalog remains unchanged.
- [x] Detect ignored raw Diffusers weights in ComfyUI through identical decoded pixels. Convert only tensor names, preserve payload bytes, map all 560 targets and repeat the actual fixed-seed pair with changed pixels. Retain the failed pair.
- [x] Verify source/package and actual training/evaluation evidence separately, then update this TODO, the build plan and changelog. Final results: 837 source and 837 installed-wheel tests, lint/format/build, 40-module parity, preserved SCM 0.5.0 and actual JSON/text CLI checks. Offline revalidation preserved all 146 prior files and the main catalog. [Verification](docs/evidence/stage-11-verification-20260921.json).
- [ ] Stage 11B acceptance: curated data, independent scene specifications, four-condition comparisons and regression criteria are delivered; genuine human review and resolution of retained failures remain open before production promotion. The earlier synthetic candidate is permanently smoke-purpose evidence.

## Required inputs and dependencies

| ID | Requirement | Status / next action |
| --- | --- | --- |
| REQ-01 | Reference image baseline | Satisfied: official SDXL 1.0 + LCM selected by user; retain the existing stage-six images and model pins. |
| REQ-02 | Video model files | Satisfied: three files, immutable revision and hashes in [video-assets.json](examples/video-assets.json); 18.145 GB downloaded and verified. |
| REQ-03 | Stock runtime schema | Satisfied for this baseline: live schemas, exact module checks, nested choices and real execution verified. |
| REQ-04 | Neutral source image | Satisfied: pinned stage-six still life copied immutably to a top-level workspace input filename. |
| REQ-05 | Disk capacity | Complete-baseline capacity plus reserve checked before download. About 106.9 GB was free before the stage-eight 5.746 GB download. Recheck before future assets. |
| REQ-06 | Video decoding tools | FFmpeg/ffprobe used for bounded full-decode checks; versions and results retained in stage-seven evidence. |
| REQ-07 | GPU capacity evidence | Stage 9A adds repeated in-process observations for four exact workloads and guarded sequential checks. [Measurements](docs/evidence/stage-09-vram-20260921.json). Sampled peaks and explicit margins do not guarantee capacity or authorize concurrency. |
| REQ-08 | Media quality acceptance | Open: stage-six count/shape errors; stage-seven clip 1 adds an unrequested hand. Preserve examples and define independent quality acceptance. |
| REQ-09 | Audio baseline and timing | Implemented and exercised: two pinned Stable Audio Open generations, exact stereo FLAC samples, two 1.375-second H.264/AAC pairs and completed replay. [Runtime evidence](docs/evidence/stage-08-audio-20260921.json). |
| REQ-10 | Audio quality and upstream warnings | Open: human listening, loudness and semantic scene alignment are unqualified. Retain TorchSDE boundary warnings from the actual sampler and evaluate them before expanding its acceptance scope. |
| REQ-11 | Capacity measurement authority | Implemented for stage 9A: fresh-process/warm labels, exact identity, sampling gaps, non-Torch/global usage, seven-day expiry and explicit uncertainty margins. Broader prediction remains unqualified. |
| REQ-12 | Parallel ownership and host memory | Qualified for two same-user managed Windows audio workers: native contention/crash recovery, repeated calibration, real refusal/admission, overlapping inference and offline replay. Broader concurrency remains unqualified. [Evidence/scope](docs/parallel-execution.md). |
| REQ-13 | Cross-process schema stability | Corrected for the observed stock VAE choice-order defect; available choices/defaults and selected model bytes remain bound. Other runtime/schema changes still require new profiles. |
| REQ-14 | Parallel trial host capacity | Satisfied for the retained trial after the user freed memory. Both physical/commit checks passed with unchanged margins; worker host peaks stayed within calibration. Fresh checks remain mandatory for future runs. |
| REQ-15 | Trigger vocabulary and activation authority | Open: Stage 10 examples are operator demonstration policy; the real LCM declares no triggers. Obtain authoritative per-model vocabulary/trigger declarations and independent activation evidence before claiming trained-token coverage or allowing any activation rewrite. |
| REQ-16 | Training baseline and dataset lineage | Satisfied for the user-approved smoke scope: pinned SDXL UNet LoRA, eight train/two held-out procedural images, separate compatible environment, eight-step owned trial and paired diagnostics. No production dataset authority or generalization is established. |
| REQ-17 | Phrase-bank balancing contract | Deferred to Stage 12: reconcile Part 12.2 axis names and count/for-each grammar before implementing corpus solving, soft relaxation or scoring. Scene lint does not implement that solver. |
| REQ-18 | Curated training data and model acceptance | Stage 11B active: user-selected public-domain still-life pilot prepared with source metadata, six train/two artist-disjoint validation works, fixed four-condition review suite and strict review coverage. Independent human quality decision remains required; no production promotion. |
| REQ-19 | Trainer/runtime compatibility | Qualified for the recorded SDXL environment and stock ComfyUI loader after retained CLIP, offline reload, VAE dtype and tensor-name failures. Requalify changed libraries, base models or export formats; package versions are not a hermetic binary dependency lock. |

## Follow-up requirements and known limits

- [ ] Investigate the unrequested hand in stage-seven clip 1 using defined scene/motion constraints and independent quality criteria; retain the failing output.
- [ ] Define reference scenes and measurable quality criteria before claiming production image/video quality.
- [ ] Listen to the retained stage-eight audio and A/V samples against explicit quality criteria; no human listening or semantic/lip-sync acceptance has been recorded.
- [ ] Reconcile the design documents' named model files, custom nodes, tuning and speed claims with current upstream evidence; do not install their embedded scripts verbatim.
- [ ] Qualify other model/LoRA combinations individually; one successful baseline does not establish arbitrary compatibility.
- [ ] Before general concurrency, reconcile ordinary ITOV commands and external clients with managed device ownership; qualify additional users/platforms and larger worker pools separately.
- [ ] Extend video qualification beyond two 1.375-second clips: longer sequences, representative resolutions and full playback review, with explicit quality criteria.
- [ ] Design explicit workspace backup/restore and test recovery. Current process-crash checks do not establish power-loss, network-filesystem or partial-backup safety.
- [ ] Keep the existing user-deleted `.cipher-review-temp/` files outside this increment; any repository hygiene cleanup must preserve that unrelated work.
