# Device ownership and bounded parallel audio

ITOV 0.10.0 adds Windows device ownership and an explicit two-worker audio qualification command. It launches and owns both ComfyUI processes, isolates their storage, reserves all seeds in one workspace transaction, and checks measured GPU and host-memory requirements before submitting. This gate covers the pinned stock Stable Audio Open workload. Image/video concurrency, larger pools, other operating systems and arbitrary models remain unqualified.

## Ownership and worker isolation

Managed controllers sharing a Windows user account use one GPU-UUID registry at `%USERPROFILE%\AppData\Local\ITOV\device-leases\UUID\`. The stable `ownership.lock` holds an OS file lock for the entire worker lifetime. `current.json` records the controller, workspace, plan, lease UUID, native job name and each worker's PID plus process creation time. Atomic publication and canonical hashes detect inconsistent records; hashes do not authenticate records against an operator who rewrites them.

Each child is created suspended and atomically attached to a Windows Job Object through `PROC_THREAD_ATTRIBUTE_JOB_LIST`. Its identity is saved before its primary thread resumes. The job has `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`; closing the controller's last handle terminates its workers even if the controller dies between process creation and journal registration. Normal shutdown terminates only that owned job, waits for its active process count to reach zero and waits for every retained process handle to signal before releasing the lease. See Microsoft's [Job Objects documentation](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects) and [process attribute API](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute).

Workers default to loopback ports 8191 and 8192. Each has separate input/output, user data, SQLite asset index, telemetry and scratch/temp paths under `workspace/state/parallel/workers/0/` or `1/`. Log files are exclusive to the lease under `state/parallel/logs/LEASE_ID/`. Stock runtime files and model weights remain shared and unchanged. Worker launch is hidden on Windows.

The original workspace owns one catalog, execution database and seed registry. All jobs receive distinct plan/index-derived request IDs and collected artifact directories. A whole-workspace dispatcher lock and catalog check still apply. Worker roots do not create separate seed catalogs. The configured original server must be reachable and idle; its existing process is left running.

**Ownership scope:** A-03 extends the same device registry to ordinary ITOV jobs, sequential batches and deployed evaluations, and reconciles workspace admission with training/parallel controllers. See [shared ownership and external-server recovery](execution-ownership.md). Arbitrary ComfyUI clients, other users and external GPU applications do not acquire this lease. Their existing GPU allocations are included in fresh device-pressure checks, but their future work can race those checks. `server start` remains a foreground external-server launcher. This is not operating-system GPU exclusivity or a hard capacity reservation.

## Prepare and calibrate

Use the existing [audio preparation/import/planning flow](../guides/audio-and-av.md) with explicit unused seeds. Import all required candidates before saving plans, so the plans share the final catalog head. Prepare two four-job plans for calibration and one two-job plan for qualification. All jobs must have the same exact workload except sampler seeds and output prefixes. The bounded gate accepts stock audio nodes with one sampler and one audio output per job.

Keep the configured original server idle, then run:

```powershell
uv run --locked itov parallel calibrate workspace/state/plans/CALIBRATION_PLAN_1.json --json
uv run --locked itov parallel calibrate workspace/state/plans/CALIBRATION_PLAN_2.json --json
```

Each command starts two fresh workers and executes four actual jobs **serially**: worker 0 cold/warm, followed by worker 1 cold/warm. Both workers are stopped before returning. Repeating the command with the second plan supplies two independent cold/warm sessions for each worker. The printed `evidence` path names an immutable calibration document under `state/parallel/calibrations/`.

Calibration is an explicit model trial, not a prior capacity prediction. It requires current available physical and commit memory to exceed twice the pinned weight bytes plus 4 GiB, and at least 2 GiB of free device memory. It permanently reserves its seeds. A failed trial retains its job records, telemetry, logs and reservations.

Calibration binds the [Stage 9A exact identity](vram-profiling.md#identity-and-policy), including the worker's actual paths, port and launch arguments. Existing sequential profiles cannot replace these per-worker measurements. Changing ports, runtime identity, model bytes, graph content or observer code requires new calibration; evidence expires after seven days. Two copies of one session do not satisfy repetition.

The host snapshot retains Python's reported Windows release label. Python 3.11 reports this Windows 11 host as `10`, while Python 3.13 reports `11`; both report kernel `10.0.26200`. Calibration comparison permits only that marketing-name alias when the numeric version, service-pack/edition, machine name and architecture all match. A different kernel build or runtime remains a mismatch. The [initial package check](../evidence/stage-09b-initial-verification-20260921.json) retains the original refusal and both observed identities.

## Parallel admission and execution

```powershell
uv run --locked itov parallel qualify workspace/state/plans/TWO_JOB_PLAN.json --calibration workspace/state/parallel/calibrations/FIRST_ID.json --calibration workspace/state/parallel/calibrations/SECOND_ID.json --json
```

Optional `--config`, `--ports PORT_0 PORT_1` and `--wait-timeout SECONDS` apply to calibration and qualification. Exactly two distinct nonprivileged ports are required, separate from the configured server.

The runner starts fresh owned workers, qualifies their model/source bindings and checks each worker's repeated profiles. It then combines their measured additional GPU envelopes:

```text
GPU required = current whole-device use
             + sum(worker additional envelopes)
             + ceil(20% of that sum) + 2 GiB
GPU capacity = min(NVIDIA total, CUDA total)

worker host envelope = maximum across calibration sessions of:
                       peak working set, peak committed memory
host required = sum(worker host envelopes)
              + ceil(20% of that sum) + 4 GiB
```

Both current available physical memory and available commit must meet the host requirement. The full lifetime peaks are retained without subtracting current worker allocations; this is deliberately conservative. Windows supplies those counters through [PROCESS_MEMORY_COUNTERS_EX](https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-process_memory_counters_ex), and available physical/commit memory through [GlobalMemoryStatusEx](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/nf-sysinfoapi-globalmemorystatusex). Margins are explicit policy choices, not statistical confidence bounds. Sampling cannot guarantee the absence of a later transient peak.

The first admission check precedes seed reservation. A second fresh check immediately precedes the two POST requests; refusal there keeps the claimed seeds. Both decisions are retained under `state/parallel/decisions/`. Catalog state and qualification are rechecked before submission. Two threads synchronize the POST requests, and observations/downloads run concurrently. Accepted or uncertain requests are never automatically submitted again.

Qualification requires two successful owned audio artifacts, complete measurements and at least 100 ms of overlap between observed prompt execution intervals. The immutable result under `state/parallel/qualifications/` records the final admission, both process measurements and measured overlap. Successful jobs without that overlap remain completed jobs but produce `qualified: false` and exit code 1. This measures prompt execution overlap; it does not establish simultaneous GPU kernels, throughput improvement, general media quality or human listening acceptance. Configuration/admission exceptions use exit code 2 and preserve the decision when available.

## Completed verification and interrupted recovery

```powershell
uv run --locked itov parallel resume workspace/state/plans/COMPLETED_PLAN.json --json
uv run --locked itov device status --gpu GPU-UUID
uv run --locked itov parallel recover workspace/state/plans/INTERRUPTED_PLAN.json --json
```

Completed `parallel resume` revalidates local owned artifacts without HTTP calls or worker startup. Its scope is artifact reverification, not a new capacity or overlap qualification. Ordinary `batch run/resume/abandon` refuses managed parallel receipts and directs callers to the dedicated commands.

An interrupted command is not restarted. Recovery requires the recorded native job to be empty and every recorded worker identity to be confirmed dead. PID reuse is distinguished through creation time; access denial or an unknown handle state is not treated as death. Recovery marks the run abandoned while preserving every job record, uncertain outcome and seed reservation. New work requires a new plan with unused seeds.

After abrupt controller exit, the OS lock is released but the durable lease remains held. Never delete that journal or reclaim it by age. If failure occurred before the workspace claim, inspect the exact lease and recover it explicitly:

```powershell
uv run --locked itov device recover --gpu GPU-UUID --lease EXACT_LEASE_UUID
```

This requires a dead controller, empty job and dead recorded workers while holding the registry lock. A mismatched lease UUID, live owner, unknown process state or incomplete registry refuses recovery. Released journals remain archived by lease UUID. These checks qualify local Windows process failure behavior; they do not establish power-loss, network-filesystem, hostile-operator or cross-user safety.

## Evidence

The [initial failed calibration](../evidence/stage-09b-initial-calibration-20260921.json) retained a ComfyUI logging failure, then confirmed worker termination and retired the run without releasing seeds. Its hidden-process stream wrapper originally allowed the stock logger's replacement of `sys.stdout` to close the underlying buffer. Keeping the original stream owners alive corrected the failure; a native regression reproduces that replacement and garbage collection.

The [corrected calibration](../evidence/stage-09b-calibration-20260921.json) records eight real pretrained audio jobs across four fresh workers. Maximum committed host memory was 8,096,665,600 bytes for worker 0 and 8,076,214,272 for worker 1. These produce a 23,702,423,143-byte host requirement under the unchanged policy.

The [first actual parallel admission](../evidence/stage-09b-initial-parallel-20260921.json) correctly refused: available commit was 22,614,253,568 bytes, a shortfall of 1,088,169,575 bytes (about 1.01 GiB). GPU admission had headroom. A real competing process using a different workspace was refused by the shared device lock. The trial made no execution claim or POST, stopped both owned workers and released the lease. The prepared plan's seeds remained unused at that refusal.

A supported [idle-server cache-release request](../evidence/stage-09b-cache-release-20260921.json) preserved the existing server process, queue and history but did not free measurable commit memory. After the user freed memory, the [actual parallel trial](../evidence/stage-09b-parallel-20260921.json) passed both admission checks with unchanged calibration and policy. Final available host commit was 30,357,254,144 bytes against the 23,702,423,143-byte requirement; GPU policy required 12,800,596,378 bytes against 34,162,016,256 bytes of capacity.

Both cold-process audio jobs completed with **4.087163999 seconds of observed prompt execution overlap**. Each distinct FLAC fully decoded to 176128 stereo samples at 44.1 kHz. Retained samples: [worker 0](../evidence/stage-09b-output-01.flac) and [worker 1](../evidence/stage-09b-output-02.flac). Measured host peaks stayed below the calibration envelopes. Both owned workers were confirmed dead, the shared lease returned idle, and original job records/server history remained unchanged. Source and installed Python 3.11 CLI replay made zero runtime HTTP requests; [completion evidence](../evidence/stage-09b-completion-20260921.json) records these checks.

The unchanged implementation already passed [693 source and 693 installed-wheel tests](../evidence/stage-09b-verification-20260921.json); the live follow-up verifies the remaining bounded model gate. Native ownership/crash tests, HTTP lost-acknowledgement fixtures and real GPU inference provide different evidence scopes; none substitutes for the others. Prompt overlap does not prove simultaneous GPU kernels or a speedup. Human listening, semantic quality, arbitrary models and broader concurrency remain unqualified.

The completed plan now owns its seeds and must not be submitted again. Reverify its artifacts in this existing checkout:

```powershell
$prepared = Get-Content docs/evidence/stage-09b-preflight-20260921.json -Raw | ConvertFrom-Json
uv run --locked itov parallel resume ($prepared.plans[2].path) --json
```

Replay requires the retained local workspace and artifacts. New trials require a new plan with unused seeds and fresh matching admission; recalibrate when evidence expires or its exact bindings change.
