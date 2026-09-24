# ITOV operator runbook

This is the supported command sequence for the current Windows, single-local-NVIDIA-GPU implementation. It covers a reproducible image-I/O session, model inference, training assessment and deployed evaluation, with one status/recovery contract. It does not install ComfyUI/models, acquire a training corpus or establish useful model quality. Those remain explicit prerequisites and later development work. The current still-life candidate remains **rejected**.

## Read a response

All result commands print text by default. Add `--json` for exactly one JSON object on stdout, including argument/configuration errors. JSON retains the existing domain fields and adds `_cli` version 1:

| Field | Meaning |
| --- | --- |
| `command` | Command family and action |
| `outcome`, `exit_code` | Consistent command result, described below |
| `next_action` | What the operator should do next |
| `actions` | Suggested commands as shell-independent `argv` arrays beginning with `itov`, plus a label and a condition (`when`) |
| `artifacts` | Labeled absolute file/directory references; a reference alone does not assert existence or validity |
| `causes` | Failure locations and retained error, validation, server or policy details |

Suggestions are not executed automatically. Text shows the same information and quotes commands for PowerShell. Use the installed `itov` executable, or prefix its arguments with `uv run --inexact --locked itov` in this checkout. JSON consumers should use the process exit code or `_cli`, since legacy `ok`, `status` and `technical_pass` fields describe different domain checks.

| Exit | Outcome | Meaning |
| --- | --- | --- |
| 0 | `ok` | The requested operation passed its declared checks; planning, technical assessment and an idle registry do not imply media quality |
| 1 | `incomplete` | Not started, running, paused, detached, timed out, held, abandoned or pending catalog recovery |
| 1 | `failed` | Diagnostic, artifact, observation or execution checks failed; collection/observation failure may be recoverable |
| 1 | `refused` | A reported policy/admission refusal or server rejection, including rejected promotion |
| 2 | `error` | Invalid arguments/configuration/files, stale bindings, ownership/protocol refusal or another caught operational exception prevented a normal report |
| 130 | `interrupted` | Ctrl+C reached the CLI; inspect durable state before doing anything else |

The domain's recorded state remains unchanged. `training status` on running/validating work, unfinished `batch status`, `batch abandon` and retired `parallel recover` now return **1**, even when observation/retirement itself succeeded. `device status` on a held lease returns 1. A controller that catches Ctrl+C and saves `detached`/`paused` returns incomplete/1; an uncaught CLI interrupt returns 130. This distinction preserves the controller's durable report.

Errors/interruption use stderr in text mode; ordinary reports, including failed/refused reports, use stdout. JSON errors use stdout. `--help` and `--version` retain argparse behavior. `server start` and `vram server` remain foreground child processes with their own output/exit status; `--print-command` still prints the raw JSON argument list and starts nothing.

`_cli` is presentation metadata. It is never written into a plan, job record, review packet or sealed report. Use `--save` to publish an immutable artifact; do not redirect an augmented CLI response into a saved-plan path. Existing domain schemas and content IDs remain unchanged.

## 1. Configure and inspect

From the checkout, use the existing environment and repository-local cache:

```powershell
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
uv sync --inexact --locked
$cfg = 'workspace/itov.toml'
# Run init only for a new workspace. It refuses existing configuration.
uv run --inexact --locked itov init
uv run --inexact --locked itov doctor --config $cfg --offline
uv run --inexact --locked itov server start --config $cfg --print-command
```

The default runtime is `AI/ComfyUI/ComfyUI_windows_portable/ComfyUI`; `init --comfyui-root PATH --comfyui-python PATH` selects another explicit installation. `doctor` identifies missing tools/runtime files; its failed checks are not waived by successful initialization. FFmpeg/ffprobe must be available for the supported media decoding paths. Optional training uses the separately pinned environment in the [training contract](training-and-promotion.md).

Start the configured stock server in a separate terminal and leave it in the foreground:

```powershell
uv run --inexact --locked itov server start --config workspace/itov.toml
```

Back in the operator terminal:

```powershell
uv run --inexact --locked itov doctor --config $cfg
nvidia-smi -L
# Set this from the exact UUID printed for the intended local GPU.
$gpu = 'GPU-REPLACE-WITH-OBSERVED-UUID'
uv run --inexact --locked itov device status --gpu $gpu --json
```

A held lease is a reason to inspect/resume its owner, not to delete state. ITOV coordinates cooperating same-user commands; unrelated GPU clients can bypass this registry. See [execution ownership](execution-ownership.md).

## 2. Complete and replay a neutral image job

The checkout helper creates a 64×64 PNG and refuses overwrite. Skip that line if the input already exists. It is a source-tree helper, not an installed CLI dependency: installed users may provide their own `example.png` in the configured input directory and the API workflow in `examples/image-copy.api.json`.

```powershell
uv run --inexact --locked python scripts/create_preflight_image.py workspace/input/example.png
uv run --inexact --locked itov workflow validate examples/image-copy.api.json --config $cfg --live
$job = uv run --inexact --locked itov job run examples/image-copy.api.json --config $cfg --wait-timeout 120 --json | ConvertFrom-Json
$job._cli
$job.record_path
```

Read the outcome before proceeding. A short `--wait-timeout 0.01` can expose partial progress, but fast/cached jobs may finish before any chosen timeout. Timeout never cancels the server job. Preserve the printed record and observe the same request:

```powershell
uv run --inexact --locked itov job wait $job.record_path --config $cfg
$done = uv run --inexact --locked itov job wait $job.record_path --config $cfg --json | ConvertFrom-Json
$done.artifacts
```

A successful wait lists downloaded paths and hashes; subsequent wait with intact artifacts verifies locally without HTTP or another POST. A malformed workflow returns an error or validation failure with the specific cause. If acceptance is unknown, inspect matching server history and, only with its proven identity, use `job wait RECORD --prompt-id ID`. An empty queue, missing history or elapsed time cannot establish that a POST was never accepted.

## 3. Plan and execute a batch

For a **fresh neutral catalog** in the configured workspace, the source helpers create explicit input declarations without changing execution state:

```powershell
uv run --inexact --locked python scripts/create_catalog_example.py --config $cfg
$initial = uv run --inexact --locked itov catalog init --config $cfg --json | ConvertFrom-Json
uv run --inexact --locked itov catalog validate workspace/templates/neutral.catalog.json --config $cfg --check-files
uv run --inexact --locked itov catalog import workspace/templates/neutral.catalog.json --config $cfg --expected-head $initial.head
uv run --inexact --locked python scripts/create_batch_example.py --config $cfg
$plan = uv run --inexact --locked itov batch plan workspace/templates/neutral.batch.json --config $cfg --save --json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Planning failed; inspect its response' }
$qualified = uv run --inexact --locked itov batch qualify $plan.path --config $cfg --save --json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Qualification failed; inspect its response' }
uv run --inexact --locked itov batch run $plan.path --config $cfg --qualification $qualified.path
uv run --inexact --locked itov batch status $plan.path --config $cfg
uv run --inexact --locked itov batch resume $plan.path --config $cfg
```

Do not import a neutral replacement over an existing production catalog. For an existing workspace, use `catalog show`, review its current entries and use a request pinned to that head instead. Helpers refuse overwrites; a repeat session uses its saved declarations/plan. Installed users can supply the documented [catalog](catalog-and-ledger.md) and [batch request](batch-planning.md) directly.

Planning submits nothing. Qualification pins runtime/assets. Execution reserves ownership/seeds before submission. `status` is read-only; `resume` collects already accepted work and can submit the unsubmitted remainder after fresh checks. Completed resume revalidates outputs without HTTP. A failed/abandoned plan never silently becomes a fresh attempt.

## 4. Generate with models or a trained candidate

Model assets must already match their declared hashes. The v1 SDXL, Wan video and Stable Audio examples use `prepare`, explicit reviewed catalog import, `plan --save`, then the batch commands above. Use `video verify SPEC OUTPUT.mp4`, `audio verify SPEC OUTPUT`, and `av mux SPEC` for their media contracts. [Image](image-inference.md), [video](image-to-video.md), [audio/A/V](audio-and-av.md) and [VRAM](vram-profiling.md) detail provisioning and bounded qualification. The A/V examples reference retained jobs; new sessions must declare their own job/record/artifact hashes.

Version-two SDXL inference stages explicit checkpoint/adapter bindings without catalog activation:

```powershell
uv run --inexact --locked itov inference capabilities
uv run --inexact --locked itov inference prepare examples/still-life-candidate.inference.json --config $cfg
$inference = uv run --inexact --locked itov inference plan examples/still-life-candidate.inference.json --config $cfg --save --json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Inference planning failed' }
uv run --inexact --locked itov inference run $inference.saved_path --config $cfg
uv run --inexact --locked itov inference status $inference.saved_path --config $cfg
uv run --inexact --locked itov inference resume $inference.saved_path --config $cfg
uv run --inexact --locked itov inference replay $inference.saved_path --config $cfg --save
```

This example pins the retained local still-life candidate; it is not portable training input. A new candidate needs its exact training-plan file hash, candidate ID and export hash in a new specification. Change declarations, never generated graphs or saved plans. Seeds remain reserved, so a deliberate new generation uses new seeds. The [candidate contract](candidate-inference.md) specifies supported strengths, ordered LCM/candidate layers and sampler compatibility. A rejected candidate may be investigated experimentally without accepting or promoting it.

## 5. Train, assess and compare the deployed artifact

Training requires declared local source images/captions, prepared dataset, provenance/curation, frozen quality cases, checkpoint/configuration/tokenizer files and the pinned optional training environment. Use [transactional dataset import](dataset-import.md) for new local or retained Met inputs; it preserves failed attempts and publishes a verified complete bundle. Acquisition and training checkpoint restart remain later work. The following commands inspect the historical version-one pilot; provision using the [training](training-and-promotion.md) and [curation](curated-quality-review.md) contracts:

For new reviewed data, first follow [dataset inspection and freezing](dataset-review.md). Inspect every image/caption and pair finding, freeze the selection, import its generated declaration, and bind Met curation with `dataset curate CURATION --freeze FREEZE --save`. The printed v2 curation declaration can be pinned in the existing training qualification. The three-work reviewed pilot is a data-method result, not accepted model training evidence.

```powershell
uv run --inexact --locked itov dataset validate workspace/training/data/met-still-life-v1/dataset.json --config $cfg
uv run --inexact --locked itov dataset prepare workspace/training/data/met-still-life-v1/dataset.json --config $cfg
uv run --inexact --locked itov dataset curate workspace/training/data/met-still-life-v1/curation.json --config $cfg --save
$training = uv run --inexact --locked itov training plan examples/sdxl-still-life.training.json --config $cfg --save --json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Training planning failed' }
uv run --inexact --locked itov training run $training.saved_path --config $cfg --gpu $gpu
uv run --inexact --locked itov training status $training.saved_path --config $cfg
uv run --inexact --locked itov evaluation assess $training.saved_path --config $cfg --save
uv run --inexact --locked itov training candidate $training.saved_path --config $cfg --save
uv run --inexact --locked itov evaluation packet $training.saved_path --config $cfg --save
```

An unchanged plan with an existing attempt refuses to train again. For existing completed work, start at `training status` using its saved path. `artifacts_validated` establishes technical artifact checks, not learned quality. The printed result/log paths and failure boundary identify a failed attempt. `training recover` only reconciles a stopped attempt; it does not resume optimization or launch another worker.

For a new experiment, create an evaluation specification referring to that exact training plan and its file hash. The retained `examples/still-life.evaluation.json` already binds the local historical trial, so it can replay that experiment rather than automatically selecting newly trained weights:

```powershell
$comparison = uv run --inexact --locked itov evaluation plan examples/still-life.evaluation.json --config $cfg --save --json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Evaluation planning failed' }
uv run --inexact --locked itov evaluation run $comparison.saved_path --config $cfg
uv run --inexact --locked itov evaluation status $comparison.saved_path --config $cfg
uv run --inexact --locked itov evaluation resume $comparison.saved_path --config $cfg
uv run --inexact --locked itov evaluation replay $comparison.saved_path --config $cfg --save
```

Inspect all base/trigger/adapter conditions and seeds. Retain count/material/regression failures and uncertainty. A saved technical report has `quality_acceptance: not_established`. The packet writes a pending `.review.json` template; the assistant records observations, evidence hashes, method, limitations and an actual verdict. It must not turn failed checks into approvals. Use `promotion prepare TRAINING_PLAN --review REVIEW --save` to inspect policy; explicit `promotion apply` additionally binds the reviewed decision and current catalog head. This runbook stops at the current candidate's rejection.

## Recovery choices

| Observation | Safe next operation | Required evidence |
| --- | --- | --- |
| `timed_out`, `detached`, `observation_failed` | `job wait RECORD` or owning family `resume PLAN` | Same durable request/graph; no retry of an unknown POST |
| `submission_unknown` | Inspect history, then owning `wait`/`resume --prompt-id ID` | Matching request and graph provenance |
| `collection_failed`, `artifact_invalid` | Preserve bad artifacts; inspect owning record; retry collection with wait/resume where supported | Proven terminal success; differing existing artifacts are never overwritten |
| Batch/evaluation/inference failed remainder | `abandon PLAN` | Every submitted request has a known terminal outcome; seeds stay reserved |
| Training running/validating after controller exit | `training recover PLAN` | Confirmed dead controller, worker and native job; fresh result/input checks before final validation |
| Held device after a crash | `device recover --gpu UUID --lease LEASE_ID` | Exact lease and positively confirmed dead owner/terminal work; empty queue is insufficient |
| Pending catalog transaction | `catalog recover` | Journal and immutable snapshot consistency; ordinary reads do not repair |
| Managed parallel controller crash | `parallel recover PLAN` | Confirmed owned-worker termination; retires uncertain work without resubmission |

Never repair a workflow by hand-editing run records, deleting a device journal, releasing reserved seeds or changing a saved plan. Follow the owning command's reported causes. Offline completed replay checks existing artifacts/inputs; it does not rerender a model or recertify quality.

## Verification boundary

[A-06 verification](evidence/phase-a06-verification-20260923.json) records source and installed CLI checks, fixture timeout/failure recovery, real Windows controller exit/recovery with fixture weights, and offline replay of retained model results. No new model training/rendering or broader model-quality acceptance is claimed for this CLI integration task. Phase B and the later application/evaluation phases remain open.
