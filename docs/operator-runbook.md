# ITOV operator runbook

This is the supported command sequence for the current Windows, single-local-NVIDIA-GPU implementation. It covers a reproducible image-I/O session, model inference, training assessment and deployed evaluation, with one status/recovery contract. It does not install ComfyUI/models, acquire a training corpus or establish useful model quality. Those remain explicit prerequisites and later development work. The current still-life candidate remains **rejected**.

## Read a response

For B-03 training configuration, use the [optimization runbook](training-configuration.md). It explains v3 specifications, the effective sample/rate plan, supported settings, partial step evidence and the separate technical/quality outcomes.

For C-01 evaluation coverage, use the [corpus runbook](evaluation-corpus.md). Freeze broader cases and strengths independently of training, execute a base-model baseline, then record every image observation. Pending review returns 1; a successfully recorded baseline returns 0 even when images fail. It cannot promote a candidate.

For C-02, use [`checks packet/inspect/calibrate/replay`](image-checks.md) after complete deployed evaluation. Inspect every image and record complete references; supply an optional evaluator response only when available. Successful recording returns 0 while preserving false accepts/rejects and uncertainty. The initial screen [missed all six observed bordered images](image-check-calibration-20260924.md); its passes cannot establish quality. The [C-03 full matrix](deployed-candidate-review-20260924.md) is complete and the candidate is rejected; future candidate reviews still require every condition.

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

## 1. Install, configure and inspect

Use an explicit ITOV wheel artifact and an existing local ComfyUI installation.
The wheel does not include ComfyUI, models, training data or optional ML packages.
The current version is 0.13.1, unreleased; obtain the wheel from the verified build
for this checkout. Build maintainers use `uv build`; operating the installed wheel
does not require the source tree.

From PowerShell, replace the installation/workspace paths below with your
actual paths. The workspace must be new. Keep `$cfg` absolute when changing
directories. This sequence uses `uv` to create a separate core environment:

```powershell
$wheel = 'D:\Packages\itov-0.13.1-py3-none-any.whl'
$tool = 'D:\Tools\itov-core'
$work = 'D:\Work\itov-session'
$comfy = 'D:\AI\ComfyUI_windows_portable\ComfyUI'
$comfyPython = 'D:\AI\ComfyUI_windows_portable\python_embeded\python.exe'
uv venv --python 3.11 $tool
uv pip install --python "$tool\Scripts\python.exe" $wheel
if ($LASTEXITCODE -ne 0) { throw 'Inspect installation failure before continuing' }
$env:PATH = "$tool\Scripts;$env:PATH"
$cfg = "$work\itov.toml"
itov workspace guide setup --config $cfg
itov init $work --comfyui-root $comfy --comfyui-python $comfyPython --url http://127.0.0.1:8188
if ($LASTEXITCODE -ne 0) { throw 'Configuration was not initialized; preserve existing files' }
itov doctor --config $cfg --offline
itov workspace status --config $cfg
itov server start --config $cfg --print-command
```

Inspect every result before continuing; the command exit contract above applies.
Use `itov workspace guide TOPIC --config $cfg` to discover the sequence for
generation, models, training, evaluation, catalog or recovery. Named inputs in
guides must be explicitly supplied. Guidance never submits work or changes state.
In this checkout, `uv run --inexact --locked itov` is an alternative launcher;
preserve its existing environment and use `$env:UV_CACHE_DIR = "$PWD\.uv-cache"`.

`doctor` identifies missing runtime files/tools; its failed checks are not waived
by initialization. FFmpeg/ffprobe are required for supported media decoding.
Optional-package failures can be retained before provisioning an environment:

```powershell
itov workspace dependencies dataset --config $cfg --save
itov workspace dependencies training --config $cfg --save
# Once provisioned, select the exact separate interpreter explicitly:
itov workspace dependencies training --python 'D:\Tools\itov-train\Scripts\python.exe' --config $cfg --save
```

Exit 1 is expected for missing optional packages in a core-only environment.
The saved receipt includes each missing/wrong package or interpreter error. This
metadata probe imports no image/ML library and establishes no CUDA readiness.
Dataset operations require Pillow 12.3.0 in the selected image interpreter;
training uses the pins in the [training contract](training-and-promotion.md).

Start the server in a separate terminal, using the same installed executable and
absolute configuration path. `server start` stays in the foreground; Ctrl+C stops
that server. Select another free loopback port during init if 8188 is already used.

```powershell
itov server start --config 'D:\Work\itov-session\itov.toml'
```

Back in the operator terminal:

```powershell
itov doctor --config $cfg
nvidia-smi -L
# Set this from the exact UUID printed for the intended local GPU.
$gpu = 'GPU-REPLACE-WITH-OBSERVED-UUID'
itov device status --gpu $gpu --json
```

A held lease is a reason to inspect/resume its owner. ITOV coordinates cooperating
same-user commands; unrelated GPU clients can bypass the registry. See
[execution ownership](execution-ownership.md).

## 2. Complete and replay a neutral image job

The packaged starter publishes a deterministic 64×64 PNG, a stock image-copy
workflow and a neutral catalog declaration in the configured workspace. Unchanged
retries are safe; changed files are preserved and refused. It needs no checkout
helper, downloaded image or model. This establishes image I/O, not model quality.

```powershell
itov workspace starter --config $cfg
if ($LASTEXITCODE -ne 0) { throw 'Inspect preserved starter inputs before continuing' }
$workflow = "$work\workflows\itov-starter.api.json"
itov workflow validate $workflow --config $cfg --live
if ($LASTEXITCODE -ne 0) { throw 'Workflow/runtime validation failed' }
$job = itov job run $workflow --config $cfg --wait-timeout 120 --json | ConvertFrom-Json
$job._cli
itov workspace status --kind jobs --config $cfg
itov workspace inspect $job.record_path --config $cfg
```

Read the outcome before proceeding. A short `--wait-timeout 0.01` can expose
partial progress, but fast/cached jobs may finish first. Timeout never cancels a
server job. Preserve the printed record and observe the same request:

```powershell
$done = itov job wait $job.record_path --config $cfg --json | ConvertFrom-Json
$done.artifacts
```

A successful wait lists downloaded paths and hashes. Another wait with intact
artifacts verifies locally without HTTP or another POST. Malformed workflows
retain their validation/protocol causes. For an uncertain accepted request,
inspect history and use `job wait RECORD --prompt-id ID` only with proven identity.
An empty queue, missing history or elapsed time cannot prove a POST was never
accepted. Owned jobs must use their owning batch/inference/evaluation or parallel
controller; `workspace inspect` supplies those commands.

## 3. Plan and execute a batch

Continue in this **fresh workspace with an empty catalog**. The starter declaration
is not a merge: preserve any existing catalog and review its entries first.

```powershell
$initial = itov catalog init --config $cfg --json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Inspect existing catalog before continuing' }
$catalog = "$work\templates\itov-starter.catalog.json"
itov catalog validate $catalog --config $cfg --check-files
if ($LASTEXITCODE -ne 0) { throw 'Catalog validation failed' }
itov catalog import $catalog --config $cfg --expected-head $initial.head
if ($LASTEXITCODE -ne 0) { throw 'Catalog import failed' }
$request = itov workspace request itov-starter --count 2 --save --config $cfg --json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Request creation failed' }
$plan = itov batch plan $request.saved_path --config $cfg --save --json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Planning failed' }
itov workspace inspect $plan.path --config $cfg
$qualified = itov batch qualify $plan.path --config $cfg --save --json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Qualification failed' }
itov batch run $plan.path --config $cfg --qualification $qualified.path
itov batch status $plan.path --config $cfg
itov batch resume $plan.path --config $cfg
itov workspace status --kind batch --config $cfg
```

For an existing workspace, start with `catalog show`, use a request pinned to its
current HEAD, and preserve prior inputs/plans. `workspace request` supports neutral
presets without seed/LoRA bindings. Model requests use their explicit specifications
and [batch request contract](batch-planning.md).

Planning submits nothing. Qualification pins runtime/assets. Execution reserves
ownership/seeds before submission. `resume` collects accepted work and can submit
the unsubmitted remainder after fresh checks; completed resume revalidates outputs
without HTTP. Failed/abandoned plans never silently become fresh attempts.

`workspace status` paginates known record directories without scanning assets or
verification trees. `workspace inspect` checks document integrity and reports
recorded state. Neither revalidates current weights, outputs or model quality.
Follow the suggested domain status/replay command for that validation. See the
[workspace contract](workspace-workflow.md) for inventory limits and exit meanings.

## 4. Generate with models or a trained candidate

Model assets must already match their declared hashes. The v1 SDXL, Wan video and Stable Audio examples use `prepare`, explicit reviewed catalog import, `plan --save`, then the batch commands above. Use `video verify SPEC OUTPUT.mp4`, `audio verify SPEC OUTPUT`, and `av mux SPEC` for their media contracts. [Image](image-inference.md), [video](image-to-video.md), [audio/A/V](audio-and-av.md) and [VRAM](vram-profiling.md) detail provisioning and bounded qualification. The A/V examples reference retained jobs; new sessions must declare their own job/record/artifact hashes.

For [extended video/audio](extended-media.md), use the v2 examples and the same explicit catalog/qualification sequence. `video bind-source --save` binds a completed image job; `av spec --save` selects completed media records and a source-audio offset. `av replay` verifies an existing bundle without creating one. `batch cancel` records a durable request to finish accepted work and retire remaining picks; optional `--interrupt-running` requires the reviewed atomic per-job endpoint. Keep the owner running or resume the same plan to settle it. A saved request is not terminal cancellation; abandoned plans still return exit one and retain seeds.

Version-two SDXL inference stages explicit checkpoint/adapter bindings without catalog activation. Set `$inferenceSpec` to your declared specification; it must pin your own asset and training-plan hashes:

```powershell
itov inference capabilities
itov inference prepare $inferenceSpec --config $cfg
$inference = itov inference plan $inferenceSpec --config $cfg --save --json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Inference planning failed' }
itov inference run $inference.saved_path --config $cfg
itov inference status $inference.saved_path --config $cfg
itov inference resume $inference.saved_path --config $cfg
itov inference replay $inference.saved_path --config $cfg --save
```

A new candidate needs its exact training-plan file hash, candidate ID and export hash in a new specification. Change declarations, never generated graphs or saved plans. Seeds remain reserved, so a deliberate new generation uses new seeds. The [candidate contract](candidate-inference.md) specifies supported strengths, ordered LCM/candidate layers and sampler compatibility. A rejected candidate may be investigated experimentally without accepting or promoting it.

## 5. Train, assess and compare the deployed artifact

Training requires declared local source images/captions, prepared dataset, provenance/curation, frozen quality cases, checkpoint/configuration/tokenizer files and the pinned optional training environment. Use [transactional dataset import](dataset-import.md) for new local or retained Met inputs; it preserves failed attempts and publishes a verified complete bundle. Acquisition remains later work. [Version-four checkpoints](training-checkpoints.md) add explicit compatible continuation from committed optimizer state. Provision using the [training](training-and-promotion.md) and [curation](curated-quality-review.md) contracts. Start with the installed training guide; it names the explicit declarations, interpreters and saved outputs needed at each step:

```powershell
itov workspace guide training --config $cfg
itov workspace dependencies training --python $trainingPython --config $cfg --save
itov workspace dependencies dataset --python $imagePython --config $cfg --save
# After data inspection/freezing/import and writing the bound training specification:
$training = itov training plan $trainingSpec --config $cfg --save --json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Training planning failed' }
itov training run $training.saved_path --config $cfg --gpu $gpu
itov workspace inspect $training.saved_path --config $cfg
itov training status $training.saved_path --config $cfg
itov evaluation assess $training.saved_path --config $cfg --save
itov training candidate $training.saved_path --config $cfg --save
```

Set `$trainingPython`, `$imagePython` and `$trainingSpec` to the provisioned interpreters and explicit specification; the training spec also pins its interpreter. For new reviewed data, follow [dataset inspection and freezing](dataset-review.md), import the frozen declaration, and bind Met curation with `dataset curate CURATION --freeze FREEZE --save`. The three-work pilot is a bounded data-method result, not model acceptance. No historical sample/specification is automatically selected for a new workspace.

An unchanged plan with an existing attempt refuses to train again. For existing completed work, start at `training status` using its saved path. `artifacts_validated` establishes technical artifact checks, not learned quality. The printed result/log paths and failure boundary identify a failed attempt. `training recover` only reconciles a stopped attempt; it does not resume optimization or launch another worker. For v4, inspect `training checkpoints PLAN`, then explicitly select a complete manifest with `training resume-plan PLAN --checkpoint CHECKPOINT_JSON --save` and run that new plan. Partial checkpoints and changed execution inputs are refused; the old attempt remains preserved.

For bounded checkpoint comparisons, use [experiment manifests](training-experiments.md): `experiment plan SPEC --save` declares hypotheses, endpoints, repetitions, budget and frozen review protocol; `experiment run MANIFEST --member ID --gpu UUID` executes one declared attempt. `experiment status` preserves each outcome, and `experiment packet --save` creates a complete pending case review. `experiment decide MANIFEST --review REVIEW --save` records loss-independent selection or rejection; `experiment replay --decision DECISION` checks the saved evidence. Selection is only for further evaluation. No failed repetition can be omitted, and no selected checkpoint is automatically activated.

For numerical comparisons, declare [v2 tolerances](experiment-variance.md) before
execution, then run `experiment variance MANIFEST --save` and
`experiment variance-replay MANIFEST --report REPORT`. Inspect exact equality,
every repetition pair and failed/unavailable attempts before attributing a visual
change to training. A tolerance pass is not a quality decision.

For deployed evaluation, create an evaluation specification referring to the exact training plan and its file hash. Use `workspace guide evaluation` and set `$evaluationSpec` to your own frozen-corpus declaration; bind the exact training-plan path and hash:

```powershell
$comparison = itov evaluation plan $evaluationSpec --config $cfg --save --json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Evaluation planning failed' }
itov evaluation run $comparison.saved_path --config $cfg
itov evaluation status $comparison.saved_path --config $cfg
itov evaluation resume $comparison.saved_path --config $cfg
itov evaluation replay $comparison.saved_path --config $cfg --save
```

Inspect all base/trigger/adapter conditions and seeds. Retain count/material/regression failures and uncertainty. A saved technical report has `quality_acceptance: not_established`. The packet writes a pending `.review.json` template; the assistant records observations, evidence hashes, method, limitations and an actual verdict. It must not turn failed checks into approvals. Complete the [deployed decision](deployed-review.md), then use [candidate summary, deployment and preview](candidate-lifecycle.md) to inspect lifecycle eligibility. Only an eligible saved preview can be explicitly applied. Legacy training-only `promotion apply` refuses activation. The current candidate remains rejected.

## Recovery choices

For a complete version-two deployed comparison, use the [C-03 review sequence](deployed-review.md): `evaluation mapping PLAN --save`, `evaluation review-packet PLAN --mapping CERTIFICATE --save`, inspect every image/comparison and fill the saved template, then `evaluation decide PACKET --review REVIEW --save`. `evaluation decision-replay DECISION` repeats all bindings and the disposition offline. A valid recorded rejection returns exit 0; read `disposition`, not the command exit alone. The C-05 `candidate` commands consume this decision and preserve rejection through explicit policy checks; they do not use a legacy training-only approval.

| Observation | Safe next operation | Required evidence |
| --- | --- | --- |
| `timed_out`, `detached`, `observation_failed` | `job wait RECORD` or owning family `resume PLAN` | Same durable request/graph; no retry of an unknown POST |
| `submission_unknown` | Inspect history, then owning `wait`/`resume --prompt-id ID` | Matching request and graph provenance |
| `collection_failed`, `artifact_invalid` | Preserve bad artifacts; inspect owning record; retry collection with wait/resume where supported | Proven terminal success; differing existing artifacts are never overwritten |
| Batch/evaluation/inference failed remainder | `abandon PLAN` | Every submitted request has a known terminal outcome; seeds stay reserved |
| Training running/validating after controller exit | `training recover PLAN` | Confirmed dead controller, worker and native job; fresh result/input checks before final validation |
| Held device after a crash | `device recover --gpu UUID --lease LEASE_ID` | Exact lease and positively confirmed dead owner/terminal work; empty queue is insufficient |
| Pending catalog transaction | `catalog recover` | Journal and immutable snapshot consistency; ordinary reads do not repair |
| Pending candidate lifecycle transaction | `candidate recover` | Exact lineage and fresh approval before HEAD publication; stale uncommitted intent can be explicitly archived with `--abandon` |
| Managed parallel controller crash | `parallel recover PLAN` | Confirmed owned-worker termination; retires uncertain work without resubmission |

Never repair a workflow by hand-editing run records, deleting a device journal, releasing reserved seeds or changing a saved plan. Follow the owning command's reported causes. Offline completed replay checks existing artifacts/inputs; it does not rerender a model or recertify quality.

## Verification boundary

[A-06 verification](evidence/phase-a06-verification-20260923.json) records source and installed CLI checks, fixture timeout/failure recovery, real Windows controller exit/recovery with fixture weights, and offline replay of retained model results. No new model training/rendering or broader model-quality acceptance is claimed for this CLI integration task. The [D-01 verification](d01-workflow-verification-20260925.md) adds clean installed neutral image I/O, timeout recovery, package parity and retained optional dependency failures; the current contract is [workspace workflow](workspace-workflow.md). Later Phase D and E work remains open.
