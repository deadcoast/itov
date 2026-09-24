# Development TODO

Updated 2026-09-23 after B-02 duplicate/identity/caption review, frozen selection and source/installed verification.

**Product status: incomplete.** ITOV has useful low-level protocols and narrowly exercised media/training paths. It does not yet provide a cohesive, broadly qualified generation, training, evaluation and discovery application. Earlier stage checkmarks describe prototype increments, not completion of those product capabilities.

The mandatory independent-human review gate is shelved. The assistant owns testing, visual inspection, evidence collection and reasoned quality decisions. Failed or uncertain results remain failed or uncertain. The current curated candidate has object-count/regression failures and unresolved trigger specificity; it is not accepted for production.

Next focus: **B-03: supported training configuration and measured trials**. A-01 through A-06 and B-01/B-02 are delivered and recorded in [CHANGELOG.md](CHANGELOG.md). [Dataset review](docs/dataset-review.md) now records all-pair content/perceptual observations, attributed work/creator groups, caption judgments and a frozen local selection bound to its imported provenance. [B-02 verification](docs/evidence/phase-b02-verification-20260923.json) covers source/installed tests, actual fresh-workspace reproduction and freeze interruption/retry, 29 matching historical public commands per implementation and preservation of 397 historical/original-pilot files. The selected two training works and one validation work do not establish corpus adequacy or improved learning. [Image inspection](docs/candidate-inference-review-20260923.md) still retains a candidate-only count/material failure; the candidate remains rejected. Execution remains cooperative Windows/single-local-GPU ownership. The [source audit](docs/development-audit-20260922.md) explains why the remaining tasks are necessary. The [previous TODO](docs/history/TODO-20260922-stage-prototypes.md) is preserved as a historical snapshot and is no longer the active plan.

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
| B. Curated data and durable training | **Active; B-01/B-02 delivered, B-03 next** | Reproducible data preparation and inspectable training experiments with useful restart/checkpoint behavior | Rebuild from declared inputs; no split leakage; checkpoint/restart checks; actual model experiments with retained failures |
| C. Autonomous evaluation and improvement | Planned; depends on A and B | Repeatable, evidence-backed decisions about quality, activation and regressions | Frozen independent cases, complete deployed-runtime coverage, calibrated checks, assistant inspection and a recorded candidate disposition |
| D. End-to-end application and operator workflow | Planned; depends on A–C | Usable image/video/audio workflows and coherent diagnostics rather than disconnected command fragments | Representative end-to-end sessions, interruption/recovery, clean installation and documented known limits |
| E. Discovery, lookup and scheduled curation | Backlog; original Stage 12 | Controlled acquisition, searchable lineage and repeatable unattended cycles | Bounded source adapters, snapshot-consistent queries, schedule ownership, recovery and qualified promotion/retirement policy |

## Phase A — execution and integration foundations

Delivered A-01 through A-06 have moved to the changelog. The [state/recovery contract](docs/training-result-states.md), [deployed evaluation runbook](docs/deployed-evaluation.md), [shared ownership contract](docs/execution-ownership.md), [candidate inference runbook](docs/candidate-inference.md), [record/freshness contract](docs/assessment-records.md) and [operator runbook](docs/operator-runbook.md) describe their supported boundaries. Historical records remain unchanged. These deliver the six bounded Phase A tasks; they do not establish model-quality acceptance, arbitrary runtime/device support or the end-to-end product requirements in B–E.

## Phase B — curated data and durable training

B-01 and B-02 have moved to the changelog. The [import/recovery contract](docs/dataset-import.md) covers declared inputs, full decode/transform receipts and complete-bundle publication. The [review/freeze contract](docs/dataset-review.md) retains all 28 pilot pairs, exclusions, unresolved attribution and exact selected captions/splits. Stable provider/local identifiers constrain work/creator leakage; heuristic distances do not prove perceptual independence. The narrower tabletop target and original mixed-style confound are documented. Live acquisition remains E-02; this three-work local selection does not establish a useful corpus or model quality.

| ID | Status | Work | Acceptance evidence |
| --- | --- | --- | --- |
| B-03 | **Next; B-01/B-02 delivered** | Replace the fixed 512px, rank-4/8, round-robin single-example loop with a documented training configuration covering supported batch/accumulation, sampling, learning-rate schedule and validation cadence. Add only combinations the worker can validate and exercise. | Effective config and sample order are recorded; gradient/precision checks, resource observations and actual bounded trials support each introduced option. |
| B-04 | Open; B-03 | Add durable checkpoints including optimizer, RNG, scheduler and dataset/step position, with explicit restart compatibility and failure handling. | Interrupted-vs-uninterrupted experiment verifies resume semantics and declared tolerances; stale or partial checkpoints are rejected without overwriting evidence. |
| B-05 | Open; B-03/B-04 | Manage experiments and checkpoint selection by an explicit hypothesis, budget and evaluation protocol. Preserve per-checkpoint outcomes; separate training loss from quality selection. | Reproduce a bounded experiment from its manifest and select/reject checkpoints against frozen cases. Unsuccessful experiments remain visible. |

## Phase C — autonomous evaluation and improvement

| ID | Status | Work | Acceptance evidence |
| --- | --- | --- | --- |
| C-01 | Open; A-02/B-05 | Build a representative frozen evaluation corpus beyond two prompts/two seeds. Cover counts, attributes, layout, textures, trigger specificity, strength range and unrelated-task regressions with explicit expected outcomes. | Coverage manifest, held-out case policy and baseline results exist before tuning; all failures remain in the evaluation set. |
| C-02 | Open; C-01 | Add repeatable image checks and optional evaluator interfaces with recorded versions, inputs and uncertainty. Calibrate on known passing/failing examples; combine measurements with direct assistant inspection. | Report false accepts/rejects and unavailable judgments. No arbitrary composite score or changed-pixel threshold substitutes for observed quality. Human participation is optional. |
| C-03 | Open; A-02/C-01/C-02 | Evaluate the actual deployed artifact across all conditions in the target runtime. Compare Diffusers and ComfyUI only under documented sampler/settings differences or controlled parity experiments. | Complete deployed-runtime matrix, loader mapping, artifact decoding and identity bindings; failed/uncertain runtime quality blocks acceptance on its evidence. |
| C-04 | Open; B/C-01–C-03 | Investigate current one-pear and divided-panel failures and the strong adapter effect without the trigger. Run predeclared, bounded data/conditioning/training/strength experiments and retain unfavorable seeds. | Case-level before/after evidence identifies what improved, regressed or stayed unresolved. Record an assistant accept/reject/inconclusive decision with method and limitations. |
| C-05 | Open; C-03/C-04 | Complete candidate lifecycle behavior: evaluation summary, deployment validation, policy preview, activation, retirement and rollback with consistent lineage. | Demonstrate stale decision refusal, interrupted activation/recovery and rollback preserving unrelated entries. Current candidate remains rejected until evidence supports a new decision. |

## Phase D — end-to-end application and operator workflow

| ID | Status | Work | Acceptance evidence |
| --- | --- | --- | --- |
| D-01 | Open; A–C | Integrate generation, training, evaluation and catalog actions into a discoverable CLI workflow with inspection/status commands and an installed-package runbook. | Run from a fresh configured workspace without development-only helpers or hidden path assumptions; retain diagnostics for missing optional dependencies. |
| D-02 | Open; D-01 | Develop image-to-video and audio/A/V beyond the short proof runs: duration/configuration support, exact source lineage, cancellation/recovery and downstream artifact contracts. | Representative longer media tasks, full playback/frame/audio inspection, preserved error cases and measured resources. The existing unrequested-hand case remains a regression input. |
| D-03 | Open; D-02 | Implement objective audio/visual quality checks appropriate to the selected models and inspect listening/semantic synchronization. Reconcile the original voice/LTX design separately before adding its unimplemented capabilities. | Task-specific scorecards, actual audio/video inspection and declared limitations. Mux timing alone does not establish semantic or lip synchronization. |
| D-04 | Open; A-03/D-02 | Extend workload measurement/admission and cancellation across supported media instead of generalizing the two-worker audio trial. | Repeated identity-bound observations, pressure/refusal cases, cross-command contention and actual overlap where supported. No unmeasured speedup/capacity claim. |
| D-05 | Open; D-01–D-04 | Finish clean-install/update behavior, optional ML provisioning, configuration migration, backups/restores and operator documentation. Profile and address repeated I/O/latency bottlenecks. | Installed-package end-to-end verification and recovery exercises, measured command costs and a candid supported-capability matrix. |

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
