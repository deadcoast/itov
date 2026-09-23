# Deployed SDXL evaluation

A-02 adds a supported route from a technically valid trained candidate to a complete ComfyUI comparison. `evaluation plan`, `run`, `status`, `resume`, `replay` and `abandon` use the same durable sequential job protocol as batches. No graph edits or local qualification helper are needed. This is a bounded technical evaluation capability; ITOV and Phase A remain incomplete.

## Inputs and planning

Use a successful version 2 training plan with a frozen curated dataset and quality suite. The current suite contract allows two to four cases, two seeds per case, and requires held-out and regression coverage. Every case/seed produces four conditions in fixed order: `base_plain`, `base_trigger`, `adapter_plain`, `adapter_trigger`. Seeds intentionally repeat across conditions. Training assessment and the existing candidate export validation still apply.

[The pilot specification](../examples/still-life.evaluation.json) pins this workspace's retained curated training plan. A fresh workspace must provision and validate its own training inputs and supply their plan path/hash. Paths inside the specification are relative to the configured workspace; the specification argument itself is a normal CLI path.

```json
{
  "version": 1,
  "id": "my-deployed-comparison-v1",
  "training_plan": {"path": "state/training/plans/PLAN_ID.json", "sha256": "PLAN_FILE_SHA256"},
  "sampler": {"steps": 20, "cfg_milli": 7000, "sampler_name": "dpmpp_2m", "scheduler": "karras"},
  "width": 512,
  "height": 512,
  "strength_milli": 1000
}
```

The supported graph uses the training checkpoint, stock `LoraLoaderModelOnly`, one image per job, explicit `dpmpp_2m`/`karras`, 1–50 steps, CFG 0.001–15, adapter strength 0.001–1 and dimensions 512–1024 in multiples of 64. Only the 512px/20-step/CFG-7/strength-1 pilot has actual model evidence. Other accepted numeric settings have validation/protocol coverage, not a broad quality or capacity qualification. FFmpeg must be on PATH for bounded PNG decoding; the core CLI does not import an ML framework.

Start the configured stock server with `itov server start`, or inspect its exact argument list with `itov server start --print-command`. Custom nodes must be disabled and the server arguments must match the configured runtime command exactly. Do not replace loaded runtime/model files during a comparison; restart the server before planning after such changes.

```powershell
uv run --inexact --locked itov evaluation plan examples/still-life.evaluation.json --config workspace/itov.toml --save --json
```

`plan --save` exports the validated candidate if necessary and stages an immutable copy as `models/loras/itov_evaluation_EXPORT_SHA256.safetensors` in ComfyUI. An existing different file is refused, never overwritten. It then checks live node schemas, runtime arguments and asset bindings and saves `workspace/state/evaluation/plans/PLAN_ID.json`. It submits no jobs and does not activate or import the candidate into a catalog. A failure may leave a valid unused candidate/deployment; no cross-file atomic transaction is claimed. Without `--save`, planning requires the candidate already to be staged and prints a plan without publishing it.

Each plan binds the training plan reference, candidate/export, checkpoint, frozen suite, exact positive/negative text, roles/seeds, strength, sampler, complete graph bytes, literal output prefixes, deployed loader name and content hashes. Runtime identity includes the server URL/argv, reported ComfyUI/Python/PyTorch versions, device name/type/index, used node schemas, the executable, `main.py`, `nodes.py`, `folder_paths.py`, eight declared execution/LoRA/sampler source files and FFmpeg identity. Before each new POST these inputs are checked again. The receipt does not attest every dependency, in-memory code, a loaded-model cache or every adapter target mapping. Hashes are consistency checks, not signatures.

## Run, observe and resume

Substitute the saved plan path printed above:

```powershell
uv run --inexact --locked itov evaluation run workspace/state/evaluation/plans/PLAN_ID.json --wait-timeout 300 --json
uv run --inexact --locked itov evaluation status workspace/state/evaluation/plans/PLAN_ID.json
uv run --inexact --locked itov evaluation resume workspace/state/evaluation/plans/PLAN_ID.json --wait-timeout 300 --json
uv run --inexact --locked itov evaluation replay workspace/state/evaluation/plans/PLAN_ID.json --save --json
```

`run` reserves the matrix before sequential submission. Job records and artifacts use the existing owned-request paths; the execution database retains every case/seed reservation under an evaluation-plan namespace. Repeated paired seeds do not consume or bypass ordinary generation seed reservations. A distinct comparison can intentionally reuse the same cases/seeds under a new specification/plan identity.

A timeout or Ctrl+C stops the controller's wait; accepted server work can still run. `resume` first observes an accepted or uncertain request using its durable request ID and exact submitted graph. It never retries a POST whose outcome is unknown. If recent history no longer includes an uncertain submission, `resume --prompt-id ID` can inspect an explicitly identified owned prompt; uncertainty otherwise remains paused. Changed inputs block the next submission but do not prevent collecting already accepted work. Missing ownership records and backwards state changes are refused.

`status` reads local durable state and revalidates any successful artifacts without HTTP or job-record changes. It reports the recorded execution state separately from `artifact_invalid`, every case/seed/role, request/prompt identity, paths and errors. `run`/`resume` may collect missing artifacts from the proven server job; `status` never repairs them. Completed resume with intact artifacts needs no HTTP and submits nothing. Saved observations are still allowed to update the execution journal.

Every evaluation output must be exactly one owned PNG with the declared dimensions, pinned file hash, successful complete FFmpeg RGB decoding and a recorded decoded-pixel hash. Corrupt/truncated files stop progress before the next job. Decoder identity is pinned. Image validity and changed pixels do not establish prompt adherence or useful training.

`replay --save` requires the complete valid matrix, current training/candidate inputs, unchanged declared runtime/model files and the same decoder. It performs no HTTP and writes an immutable `state/evaluation/reports/REPORT_ID.json` containing all bindings, image paths, hashes and owned job references. Its `technical_pass` is separate from `quality_acceptance: not_established`. Inspect the actual images and retain case-level quality findings before making any disposition. Replay does not activate, promote, certify loader-target coverage or establish Diffusers/ComfyUI sampler parity.

CLI exits are 0 for a saved/printed plan, complete valid status/run/replay, and 1 for incomplete, paused, failed, abandoned or artifact-invalid reports. Malformed inputs, stale bindings and operational refusals before an execution report return 2. Default text prints counts and case-level progress; `--json` retains all bindings and diagnostics.

## Retiring a comparison and ownership limits

```powershell
uv run --inexact --locked itov evaluation abandon workspace/state/evaluation/plans/PLAN_ID.json --json
```

Abandonment retires unsubmitted rows only after all submitted work has a known terminal outcome. A failed collection additionally requires live owned terminal-success evidence. Active/unknown submissions cannot be abandoned; resume observation first. Abandonment never cancels another job, removes files, releases seed history or permits this plan to start again. Preserve the failed evidence and choose a new specification ID for an intentional new attempt.

Evaluation shares the sequential batch database and whole-workspace lock. A-03 adds [cross-family workspace/device admission and an explicit external-server policy](execution-ownership.md): pending requests retain a same-user device lease until positively observed terminal. An unmanaged client can still submit outside this cooperative protocol. No parallel model execution, external cancellation guarantee or arbitrary LoRA stack is introduced here; inference-stack integration remains A-04.

The installed-package trial and source/protocol checks are recorded in [A-02 verification](evidence/phase-a02-verification-20260923.json). The current candidate remains rejected on quality; complete transport/runtime coverage does not close Phase C.
