# Development TODO

Updated 2026-09-24 after C-01 frozen evaluation coverage, base-model observations and source/installed verification.

**Product status: incomplete.** ITOV has useful low-level protocols and narrowly exercised media/training paths. It does not yet provide a cohesive, broadly qualified generation, training, evaluation and discovery application. Earlier stage checkmarks describe prototype increments, not completion of those product capabilities.

The mandatory independent-human review gate is shelved. The assistant owns testing, visual inspection, evidence collection and reasoned quality decisions. Failed or uncertain results remain failed or uncertain. The current curated candidate has object-count/regression failures and unresolved trigger specificity; it is not accepted for production.

Next focus: **C-02: calibrated image checks and evaluator interfaces**. C-01 delivers a [frozen twelve-case corpus](docs/evaluation-corpus.md), three seeds per case, explicit held-out policy and a [72-image base-model baseline](docs/evaluation-corpus-baseline-20260924.md) before further tuning. Observations retain 7 passing, 52 failing and 13 uncertain images. The 288-image adapter strength comparison is planned but unexecuted; complete candidate evaluation remains C-03. [C-01 verification](docs/evidence/phase-c01-verification-20260924.json) distinguishes source/installed checks, actual rendering, recovered Windows record-write failure and direct inspection. No model was accepted or promoted.

A-01 through A-06 and B-01 through B-05 are delivered within their documented scope and recorded in [CHANGELOG.md](CHANGELOG.md). [Experiment manifests](docs/training-experiments.md) preregister hypotheses, independent checkpoint endpoints, repetitions, budgets and frozen case decisions. [B-05 verification](docs/evidence/phase-b05-verification-20260924.json) covers 1,299 source and 1,299 installed tests, four actual attempts and twelve optimizer updates. Both endpoints and all four repetitions were [rejected on quality evidence](docs/training-experiment-trial-20260924.md). **Exact numerical reproduction failed** despite matching sample/noise/rate order and RNG; all nine adapter images differed per endpoint. The workflow reproduces the declared execution and records unsuccessful outcomes; it does not establish numerical determinism or a clean causal duration effect. Investigation is retained under C-04. The selected two training works and one validation work do not establish corpus adequacy or improved learning. The previous candidate remains rejected. Execution remains cooperative Windows/single-local-GPU ownership. The [source audit](docs/development-audit-20260922.md) explains why the remaining tasks are necessary. The [previous TODO](docs/history/TODO-20260922-stage-prototypes.md) remains a historical snapshot, not the active plan.

## How work is tracked

- Keep one phase active and work dependency-first. Record newly found defects under the affected task.
- A task needs a usable implementation, meaningful failure/recovery checks and the evidence specified below before it moves to the changelog. A successful example or a test count alone does not finish a capability.
- Report implementation status, actual runtime behavior and measured/observed quality separately. State unresolved defects before describing the next stage.
- Preserve failed runs, source assets, user changes and historical evidence. Use new identities for changed datasets, experiments and reports.
- Integrate delivered behavior into supported commands and tracked documentation. Local investigation scripts are temporary tooling, not the finished feature.
- Continue ordinary development and testing autonomously. Ask for information only where a decision genuinely depends on the user's intent or unavailable input.

## Phase map

| Phase | Status | Product outcome | Exit evidence |
| --- | --- | --- | --- |
| A. Execution and integration foundations | **Delivered within the documented supported scope** | One coherent path from declared inputs through owned execution, validated artifacts and recoverable state | Supported commands exercise success, bad artifacts, interruption, stale inputs and replay across the affected execution paths |
| B. Curated data and durable training | **Delivered within the documented bounded scope; numerical determinism unqualified** | Reproducible data preparation and inspectable training experiments with useful restart/checkpoint behavior | Declared data rebuild, split checks, checkpoint/restart evidence and repeated model experiments; failed exact reproduction and quality outcomes retained |
| C. Autonomous evaluation and improvement | **Active; C-01 delivered, C-02 next** | Repeatable, evidence-backed decisions about quality, activation and regressions | Frozen independent cases, complete deployed-runtime coverage, calibrated checks, assistant inspection and a recorded candidate disposition |
| D. End-to-end application and operator workflow | Planned; depends on A–C | Usable image/video/audio workflows and coherent diagnostics rather than disconnected command fragments | Representative end-to-end sessions, interruption/recovery, clean installation and documented known limits |
| E. Discovery, lookup and scheduled curation | Backlog; original Stage 12 | Controlled acquisition, searchable lineage and repeatable unattended cycles | Bounded source adapters, snapshot-consistent queries, schedule ownership, recovery and qualified promotion/retirement policy |

## Phase A — execution and integration foundations

Delivered A-01 through A-06 have moved to the changelog. The [state/recovery contract](docs/training-result-states.md), [deployed evaluation runbook](docs/deployed-evaluation.md), [shared ownership contract](docs/execution-ownership.md), [candidate inference runbook](docs/candidate-inference.md), [record/freshness contract](docs/assessment-records.md) and [operator runbook](docs/operator-runbook.md) describe their supported boundaries. Historical records remain unchanged. These deliver the six bounded Phase A tasks; they do not establish model-quality acceptance, arbitrary runtime/device support or the end-to-end product requirements in B–E.

## Phase B — curated data and durable training

B-01 through B-05 have moved to the changelog. The [import/recovery contract](docs/dataset-import.md) covers declared inputs, full decode/transform receipts and complete-bundle publication. The [review/freeze contract](docs/dataset-review.md) retains all 28 pilot pairs, exclusions, unresolved attribution and exact selected captions/splits. Stable provider/local identifiers constrain work/creator leakage; heuristic distances do not prove perceptual independence. [Configured training](docs/training-configuration.md) supports micro-batch/accumulation pairs 1/1, 1/2 and 2/1, sequential/shuffled epochs, constant/warmup-decay rates and explicit validation cadence within the existing 512px/rank-4/8 bounds. [V4 checkpoints](docs/training-checkpoints.md) add complete optimizer/RNG bundles and compatible continuation at committed update boundaries. [Experiments](docs/training-experiments.md) bind endpoint repetitions and loss-independent quality decisions to an explicit budget and protocol. Historical v3 step events remain diagnostics. Live acquisition remains E-02; this three-work selection and its short trials do not establish a useful corpus, numerical determinism or model quality.

The B-05 campaign executed its declared repetitions and rejected every checkpoint against frozen cases. Its exact numerical reproduction check failed and remains visible. The delivered scope is experiment management, bounded repeated execution and evidence-backed checkpoint disposition, not deterministic GPU training or a successful learned model.

## Phase C — autonomous evaluation and improvement

C-01 has moved to the changelog. Its [corpus workflow](docs/evaluation-corpus.md) preserves legacy failures, freezes all seven coverage axes and records complete base-model observations. Broader cases expose collapsed objects, utensil/fruit substitutions, repetition, framing and visibility failures before adapter application. Declared coverage and caption exclusion do not prove semantic independence or corpus sufficiency. The seven held-out prompts remain excluded from subsequent training/tuning; baseline exposure and future contamination must remain explicit.

| ID | Status | Work | Acceptance evidence |
| --- | --- | --- | --- |
| C-02 | Open; C-01 | Add repeatable image checks and optional evaluator interfaces with recorded versions, inputs and uncertainty. Calibrate on known passing/failing examples; combine measurements with direct assistant inspection. | Report false accepts/rejects and unavailable judgments. No arbitrary composite score or changed-pixel threshold substitutes for observed quality. Human participation is optional. |
| C-03 | Open; A-02/C-01/C-02 | Evaluate the actual deployed artifact across all conditions in the target runtime. Compare Diffusers and ComfyUI only under documented sampler/settings differences or controlled parity experiments. | Complete deployed-runtime matrix, loader mapping, artifact decoding and identity bindings; failed/uncertain runtime quality blocks acceptance on its evidence. |
| C-04 | Open; B/C-01–C-03 | Investigate one-pear/divided-panel failures, the strong adapter effect without the trigger, and B-05's numerical variation despite matching order/RNG. Measure repetition variance before attributing changes to training choices. Run predeclared, bounded data/conditioning/training/strength experiments and retain unfavorable seeds. | Case-level before/after evidence and declared numerical tolerances identify improvement, regression, repetition variance and uncertainty. Record an assistant accept/reject/inconclusive decision with method and limitations; preserve failed exact-reproduction evidence. |
| C-05 | Open; C-03/C-04 | Complete candidate lifecycle behavior: evaluation summary, deployment validation, policy preview, activation, retirement and rollback with consistent lineage. | Demonstrate stale decision refusal, interrupted activation/recovery and rollback preserving unrelated entries. Current candidate remains rejected until evidence supports a new decision. |

## Phase D — end-to-end application and operator workflow

| ID | Status | Work | Acceptance evidence |
| --- | --- | --- | --- |
| D-01 | Open; A–C | Integrate generation, training, evaluation and catalog actions into a discoverable CLI workflow with inspection/status commands and an installed-package runbook. | Run from a fresh configured workspace without development-only helpers or hidden path assumptions; retain diagnostics for missing optional dependencies. |
| D-02 | Open; D-01 | Develop image-to-video and audio/A/V beyond the short proof runs: duration/configuration support, exact source lineage, cancellation/recovery and downstream artifact contracts. | Representative longer media tasks, full playback/frame/audio inspection, preserved error cases and measured resources. The existing unrequested-hand case remains a regression input. |
| D-03 | Open; D-02 | Implement objective audio/visual quality checks appropriate to the selected models and inspect listening/semantic synchronization. Reconcile the original voice/LTX design separately before adding its unimplemented capabilities. | Task-specific scorecards, actual audio/video inspection and declared limitations. Mux timing alone does not establish semantic or lip synchronization. |
| D-04 | Open; A-03/D-02 | Extend workload measurement/admission and cancellation across supported media instead of generalizing the two-worker audio trial. | Repeated identity-bound observations, pressure/refusal cases, cross-command contention and actual overlap where supported. No unmeasured speedup/capacity claim. |
| D-05 | Open; D-01–D-04 | Finish clean-install/update behavior, optional ML provisioning, configuration migration, backups/restores and operator documentation. Profile and address repeated I/O/latency bottlenecks. | Installed-package end-to-end verification and recovery exercises, measured command costs and a candid supported-capability matrix. |

C-01 retained a Windows `WinError 5` while replacing an owned job record after server acceptance. Public resume reconciled that request and finished without an extra completed render. The contending process is undetermined; transient sharing-failure hardening and repeated validation cost remain D-05 work. Preserve the [paused/resumed evidence](docs/evidence/phase-c01-verification-20260924.json).

## Phase E — discovery and scheduling backlog

- [ ] E-01: Reconcile original Parts 7–10 and 12.1–12.4 against the implemented contracts before importing their example algorithms or performance claims.
- [ ] E-02: Add bounded source acquisition, rights/provenance retention, download continuation and quarantine with per-provider failure handling.
- [ ] E-03: Build snapshot-consistent reverse lookup over assets, compatibility, triggers, lineage and candidate decisions; read-only queries must report stale/missing state.
- [ ] E-04: Implement phrase-bank constraints and versioned curation with explicit infeasibility/relaxation reports and reproducible sampling.
- [ ] E-05: Add owned scheduled cycles with budgets, idempotency, interruption recovery and policy-driven candidate handling; ordinary development does not require a human review gate.

## Existing evidence and unresolved dependencies

The changelog retains the implemented protocols, scoped test runs, real media/training trials and corrections from the old stage plan. The prototype evidence is useful regression material. It does not close the phases above.

Continue using the existing uv environments, pinned model files, ComfyUI installation and repository-local caches. Keep the large installer, downloaded models and generated workspace out of Git. Recheck current device/host memory before new model work. Preserve SCM 0.5.0 and unrelated workspace changes.

The public-domain dataset choice is settled. An independent human review is no longer a dependency. Open requirements are engineering work and better evaluation/data evidence: original REQ-08/10/15 (media quality/activation), REQ-11/12/14/19 (resource/runtime scope), REQ-17 (phrase balancing), and REQ-18 (curated quality) map to the phases above. Earlier requirements marked satisfied only for a prototype retain that narrower evidence scope.
