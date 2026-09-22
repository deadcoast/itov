# Training completion, validation and recovery

The controller and `evaluation assess` share the read-only validator in `src/itov/training_results.py`. A stopped worker or a hash-matching file does not by itself establish a valid training result. Candidate quality decisions remain separate from execution and technical validation.

## Supported commands

```powershell
uv run --inexact --locked itov training run workspace/state/training/plans/PLAN_ID.json --gpu GPU_UUID --json
uv run --inexact --locked itov training status workspace/state/training/plans/PLAN_ID.json --json
uv run --inexact --locked itov evaluation assess workspace/state/training/plans/PLAN_ID.json --save --json
```

Default text output and JSON expose the current status, saved status, worker completion, artifact validation, failed boundary, relevant files and next action. `training status` is read-only and does not launch a worker, contact ComfyUI, import ML libraries or modify an old record.

## State meanings

New attempts write version 2 run records. Worker result documents and existing assessment/candidate formats retain their versions and meanings.

| Run status | Meaning | Next action |
| --- | --- | --- |
| `running` | The controller owns execution; completion is not established. | Observe the controller, or recover after confirmed exit. |
| `validating` | The worker has exited; result/artifact validation or final record publication is pending. | Observe the controller, or explicitly recover after confirmed exit. |
| `artifacts_validated` | The result, declared artifacts and required diagnostic coverage passed, with final execution-input revalidation. | Run technical assessment, then separate candidate evaluation. |
| `failed` | A recorded operation failed, or fresh status inspection found invalid/stale evidence. | Inspect the named boundary and artifacts. Preserve the attempt. Use a new plan for corrected training. |

`worker_completion=completed` means process exit was observed. It does not assert that the worker reported success or produced valid weights. `artifact_validation` distinguishes `not_run`, `pending`, `validating`, `passed` and `failed`. `candidate_assessment=not_performed_by_training` explicitly describes this command's scope; it does not erase or summarize separately saved reviews.

A status response has `scope=training_status_observation`. Its `record_id` identifies the **saved run record**, not a hash of the augmented response. `recorded_status` preserves the saved status while `status` reports the current observation. Version 1 historical `succeeded` records are read through the same validator: a valid one is observed as `artifacts_validated`, and an invalid one as `failed`. Neither path rewrites historical bytes. Old failed records without boundary metadata retain their original error and unknown worker state.

## Validation and failed boundaries

| Boundary | Checks |
| --- | --- |
| `worker_execution` | Owned process termination, timeout/resource interruption, or an explicit worker failure. |
| `result_publication` | A complete readable, hash-sealed `result.json` exists. Missing or truncated publication fails here. |
| `result_binding` | The result belongs to this plan and, when recorded, matches its exact result ID. |
| `result_schema` | Supported result version, complete declared fields, integer metadata and no worker claim of quality acceptance. |
| `input_freshness` | Prepared dataset identity and referenced input bytes. Run/finalization recovery also revalidate the model, executable, environment and pinned source files. |
| `weights` | File/hash/size, valid supported safetensors, matching rank, complete down/up matrix pairs, contiguous complete payload and finite values. |
| `optimizer_evidence` | Adapter-only/reload declarations, changed-tensor evidence, exact optimizer-step count and complete nonnegative loss records. |
| `heldout_matrix` | Every held-out sample, prescribed noise seed and loss before and after training. |
| `preview_matrix` | Required paired previews, exact prompt/seed, distinct pair paths and referenced file hashes. |
| `quality_matrix` | For v2 specifications, every frozen case/seed/condition, exact prompt bindings, distinct paths and referenced image hashes. |
| `record_publication` | Publishing a durable controller transition failed. Inspect status before recovery. |

Preview/matrix file checks establish their declared bindings and hashes, not full image decoding or visual quality. The worker's optimizer/reload declarations remain evidence supplied by that worker. Full model-to-loader compatibility and quality acceptance require the separate evaluation workflow. Status/assessment replay checks saved result and dataset/evaluation evidence; it does not require the original trainer source or ML environment to remain installed. Fresh execution and finalization recovery do require those pinned execution inputs.

CLI exit `0` means the requested observation/operation completed without a reported failure; a running status is not completion. Exit `1` reports a failed training observation/attempt. Exit `2` reports an operational refusal or malformed/stale assessment input; validation errors include `failure_boundary`. An interrupted final write can therefore return `2` while leaving the durable run at `validating`.

## Explicit recovery

```powershell
uv run --inexact --locked itov training recover workspace/state/training/plans/PLAN_ID.json --json
```

Recovery requires the exact controller identity to be dead, no live processes in its native job, and confirmed worker exit. An uncertain identity, live worker or different held device lease is refused. The matching abandoned device lease is recovered only after those checks. Recovery never starts a worker or submits another training run.

- Interrupted `running` attempts become failed; execution/checkpoint resume is not implemented.
- Interrupted version 2 `validating` attempts can become `artifacts_validated` after the complete shared validation and fresh execution-input checks. Invalid or incomplete artifacts become a boundary-specific failure.
- Already terminal attempts cannot be recovered or silently rerun. `status` and `evaluation assess` can recheck them without changing their records.
- A missing or malformed `run.json` is an operational error requiring inspection. Recovery does not guess a current record from partial journals.

Each new controller transition is saved under `runs/PLAN_ID/records/RECORD_ID.json` before `run.json` is atomically replaced. Recovery also retains its original record there. Result files, weights, images and prior transition files are never overwritten by recovery. Publication across all these files is not a single atomic transaction; the saved pending state is the recovery boundary.

## Regression evidence

The retained Stage 11B attempt `a0a56da93c29eb34383495f5d281f806f84973b3d531051afb52922e9578941d` points its weights reference at a PNG. Before A-01, status returned `succeeded` with exit `0`, while assessment failed. With the shared validator, status returns `failed`, `recorded_status=succeeded`, `worker_completion=completed`, `artifact_validation=failed` and `failure_boundary=weights`, with exit `1`. The old result/run documents remain unchanged.

The [A-01 verification receipt](evidence/phase-a01-verification-20260922.json) separates automated fixtures, native owned-process interruption/recovery, installed-package checks and actual retained-artifact replay. No new model training, quality improvement or production acceptance follows from these checks. The curated candidate's existing rejection remains in force.
