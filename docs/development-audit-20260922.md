# Development audit and scope correction

This source review responds to the user's assessment that completion reporting and the TODO overstated how developed ITOV is. **ITOV remains a partial application composed of low-level integrations and bounded prototypes.** Existing protocols and successful tests provide useful evidence, but substantial integration, training methodology, quality evaluation and operator work remains.

The mandatory independent-human gate was an assistant-added workflow restriction. The user shelved it on 2026-09-22. The assistant is responsible for continuing tests and inspection, recording its method and limitations, and rejecting or deferring candidates on the evidence. This change does not turn current failed images into passing results.

## Source-backed findings

| Priority | Finding and consequence | Source/evidence inspected | Work in the new TODO |
| --- | --- | --- | --- |
| High | Training `run` verifies a result ID, claimed success and referenced file hash, then records `succeeded`. Safetensors/complete output validation happens later in `assess`. The retained PNG-as-weights result demonstrates why process completion and valid training output need separate states. | `src/itov/training.py:run`, `src/itov/evaluation.py:assess`; Stage 11B attempt 02 | A-01 |
| High | The public inference specification supports two fixed profiles and permits a LoRA only for the LCM profile. Curated-candidate stock-runtime testing manually changes graph dictionaries and copies weights in an ignored local helper. That is not a finished trained-candidate integration. | `src/itov/inference.py:PROFILES/validate_spec/describe`; `workspace/state/verification/qualify_stage11b_comfy.py` | A-02/A-04 |
| High | Job, sequential-batch, training and parallel execution have separate controllers and ownership boundaries. Managed device leasing does not cover ordinary existing-server jobs. Product-wide exclusion, cancellation and recovery cannot be inferred from the managed audio trial. | `src/itov/jobs.py`, `batch_execution.py`, `training.py`, `parallel.py`; `docs/parallel-execution.md` | A-03/D-04 |
| High | Dataset preparation is a fixed eight-work helper, creates its output directory before processing and lacks a complete transaction/resume workflow. The core curation validator checks supplied metadata/hashes and declared transforms, not perceptual duplicates or actual semantic suitability. | `scripts/prepare_met_still_life.py`, `src/itov/curation.py`, `training_data.py` | B-01/B-02 |
| High | Training is one pinned SDXL profile: 512px, rank 4/8, at most 256 steps, one cached sample per step in fixed round-robin order and fixed AdamW. It has no saved optimizer/RNG checkpoint, restart path, scheduler selection, accumulation or checkpoint selection workflow. These choices bound a pilot; they do not constitute a developed trainer. | `src/itov/training.py:validate_spec`, `training_worker.py:train` | B-03–B-05 |
| High | Quality evaluation has two local cases/two seeds in the actual pilot, fixed four-condition renders and review declarations. There is no calibrated automatic quality estimator, representative corpus or integrated deployed-runtime matrix. The stock ComfyUI pair still fails the requested count; a regression seed contains extra panels/objects. | `examples/still-life.quality.json`, `src/itov/quality.py`, Stage 11B review images and runtime evidence | C-01–C-04 |
| Medium | `quality.packet` calls `assess`, `candidate` calls `assess` again, and qualification/data validation repeats across both. Multiple paths operate on untyped dictionaries. This creates coupling and repeated reads; runtime cost needs profiling rather than an invented performance number. | `src/itov/quality.py:packet/validate_matrix`, `evaluation.py:candidate/assess` | A-05 |
| Medium | Several important real-world qualification steps live only in ignored workspace scripts. An installed wheel passing source tests does not show that a fresh user can reproduce those operations through supported commands. | Stage 11/11B helper scripts and their retained command evidence; CLI parser | A-02/A-06/D-01/D-05 |
| High | Earlier stage-level "complete" labels aggregate protocol checks and a few examples while broader model quality, resource coverage, voice training, lookup, acquisition and scheduling remain absent or unqualified. The task accounting obscured that gap. | Previous TODO, development-review stage map, original Parts 5/7/8/12.1–12.4 | New phase plan; D/E |

This is a targeted source audit of the execution, inference, dataset, trainer and review paths. It is not an exhaustive audit of every line or a claim that every low-level component is defective. Hash-bound artifacts, uncertain-outcome handling, catalog compare-and-swap and preserved failure records are useful foundations to retain while developing the missing methods.

## Current capability classification

| Area | Current evidence | Remaining product status |
| --- | --- | --- |
| Workspace, catalog and deterministic planning | Implemented contracts, local revision/recovery and replay tests | Foundation; integrate lifecycle, migrations, backup/restore and operator workflow |
| Runtime jobs and sequential execution | Owned request records and bounded live success/recovery examples | Partial integration; shared ownership/cancellation and broader workloads remain |
| Image, video, audio and A/V | Pinned models with small real trials and artifact checks | Prototype capability; semantic quality and representative scenarios remain |
| VRAM and concurrency | Exact-workload measurements and bounded two-worker audio trial | Narrow qualification; general admission/concurrency remains |
| Trigger/scene logic | Lexical rules and deterministic reports | Prototype constraints; model activation and conditioning method remain |
| Training/data | Synthetic and eight-work curated pilots; one fixed SDXL worker | Prototype trainer; durable experiments, data pipeline and checkpoint methods remain |
| Evaluation/promotion | Artifact checks, comparison records and catalog policy transactions | Partial method; autonomous evidence review is supported, calibrated quality and full lifecycle integration remain |
| Discovery/query/scheduling/phrase curation | Design inputs | Unimplemented product areas |

## Completion accounting and next work

The old TODO is retained verbatim at [the historical snapshot](history/TODO-20260922-stage-prototypes.md). Its completed checkboxes describe work performed at the time; the stage-level completion interpretation is superseded by this audit. [CHANGELOG.md](../CHANGELOG.md) records the delivered prototype increments and this correction. [TODO.md](../TODO.md) is the new active plan, containing open tasks with dependencies and observable exit criteria.

Start with **A-01: training result state and artifact validation**. Then integrate deployed-runtime evaluation (A-02) and reconcile ownership (A-03). Training/data expansion and measured quality work follow those execution foundations. A status report must identify what is still missing even when the focused implementation or package checks pass.

## Verification of this correction

The reviewer-policy change passed 77 focused tests and 880 source/880 installed-wheel tests. [The verification receipt](evidence/review-policy-verification-20260922.json) also records lint/format/build, 42-module parity, exact README packaging, actual offline v3 rejection, preservation of the catalog/model bytes and retained historical files. [The assistant reassessment](evidence/review-policy-reassessment-20260922.json) is an actual rejection based on inspected images, not a fabricated approval. These results verify this correction; they do not resolve the architectural or model-method gaps listed above.
