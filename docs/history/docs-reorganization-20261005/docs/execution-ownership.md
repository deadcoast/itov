# Execution ownership across command families

A-03 makes ordinary jobs, sequential batches, deployed evaluations, training and managed parallel trials participate in the same workspace exclusion rules and same-user device registry. A completed command or an empty server queue does not by itself prove that an uncertain request is safe to retire.

A-04's version-two candidate/stack inference uses this same sequential dispatcher, durable job ownership, device lease and ordinary seed namespace. The inference commands add no ownership bypass.

The supported new-submission profile is Windows, one local NVIDIA GPU, and a loopback HTTP ComfyUI server reporting that GPU as CUDA device 0. The UUID comes from local NVIDIA telemetry; the reported server device name/index/type must match. Remote servers, multiple GPUs, CPU-only servers and other operating systems are refused by this client ownership profile. This is a conservative scope restriction, not a claim that GPU memory is reserved by Windows.

## Workspace and device boundaries

Every execution family holds the stable `state/batches/execution.lock` while dispatching or recovering owned workspace state. Admission checks unfinished batch/evaluation claims, standalone job records and running/validating training attempts. An interrupted training controller or detached standalone request therefore blocks new work in that workspace even after its OS lock has been released. Unknown states and missing initialized execution databases are refused. Retired batches keep their job records and seed reservations without blocking new work.

The existing device registry at `%USERPROFILE%\AppData\Local\ITOV\device-leases\GPU_UUID\` is shared across workspaces. Its OS lock prevents concurrent dispatch, and its canonical journal retains unfinished ownership after controller exit. Do not relocate, delete or reset that registry to bypass a refusal. An inaccessible registry fails before POST or native worker startup. Normal execution needs write access to this same-user registry as well as the workspace.

| Owner | Device lifetime | What can stop it |
| --- | --- | --- |
| Ordinary job | From durable submission intent until proven terminal server outcome | Observation/recovery only; ITOV never interrupts its externally controlled server |
| Sequential batch / deployed evaluation | One lease across its submitted requests for the controller session; unresolved requests retain it after detachment | Resume observes accepted requests; remaining submissions still require fresh bindings |
| Training / managed parallel workers | Native controller and its Job Object worker lifetime | The controller terminates only its owned Job Object, confirms worker exit, then releases the lease |

Pausing between jobs with no unresolved submitted work can release the device while the batch still retains its workspace claim. Another workspace may then use the device; the paused plan must reacquire ownership before its next POST. Completed artifact observation can run without acquiring a device lease or contacting the server, including while another workspace owns the GPU.

## External server policy

`job run`, `batch run/resume` and `evaluation run/resume` treat the configured server as **externally controlled**. The existing `server start` command is a foreground launcher; it does not turn that server into a managed training/parallel worker. New job records explicitly include `device_lease.server_control: external`, GPU UUID, lease ID and operation ID. `device status` exposes `kind: external_server_requests`, exact graph text, request IDs, acknowledged prompt IDs and terminal observations.

The client writes submission intent into the device journal **before** POST. A lost acknowledgement, timeout, Ctrl+C or controller crash retains that lease until its outcome is positively established. A second workspace, ordinary job, training controller or parallel trial using this registry cannot bypass it. Before each new submission, the controller verifies the local device mapping, obtains ownership and checks that the server queue is idle.

Arbitrary ComfyUI/UI clients, other users, other registry installations and external GPU applications do not participate. They can submit after an idle-queue check or allocate GPU memory during a lease. ITOV neither cancels their requests nor clears their queue/history nor terminates their server. This is cooperative exclusion among the covered ITOV commands, not OS-wide exclusivity, memory admission qualification or protection against a modified/malicious peer.

## Observation and recovery

```powershell
uv run --inexact --locked itov job run workflow.api.json --wait-timeout 120 --json
uv run --inexact --locked itov job wait workspace/state/jobs/REQUEST_ID.json --json
uv run --inexact --locked itov device status --gpu GPU-UUID
```

Standalone `job wait` now reconciles an uncertain submission using the same request-ID/exact-graph proof as owned batches. If recent history no longer contains it, supply the known prompt explicitly:

```powershell
uv run --inexact --locked itov job wait workspace/state/jobs/REQUEST_ID.json --prompt-id KNOWN_PROMPT_ID --json
```

The supplied ID must match actual server provenance; it is not an override. `job wait` refuses plan-owned records and directs them to `batch resume`, `evaluation resume` or `parallel resume/recover`. This preserves each family's dispatcher and recovery rules. A matched acknowledged prompt is observed and collected; it is never reposted. Artifact failures retain their evidence even when terminal server execution permits releasing the device.

For an abandoned controller, inspect the lease and use its exact ID:

```powershell
uv run --inexact --locked itov device recover --gpu GPU-UUID --lease EXACT_LEASE_UUID --json
```

Native leases retain the existing dead-controller, empty-native-job and dead-worker requirements. External-request leases require a confirmed dead controller and matching terminal history for every unresolved request. Missing history, an unavailable server, a different graph, a live/unknown process, or active server execution refuses recovery. An empty queue or server restart is not proof. A crash after durable intent but before POST may remain uncertain indefinitely when no positive evidence exists; there is no force-retry or age-based clearing path.

Explicit device recovery archives the journal and releases device exclusion; it does not rewrite job/training records, drop seeds, mark a batch successful or restart work. Use the owning family's observation/recovery command to reconcile its workspace state. Ordinary resume may reattach the same operation under the OS lock after the previous dispatcher detached; a different operation cannot adopt it.

Historical job records without device bindings remain readable and observable. Existing unfinished workspace records participate in admission, but old requests do not acquire retroactive cross-workspace GPU ownership. No historical receipt or model artifact is rewritten to claim the new guarantee. Changed controller source also changes new training plan identities; previously frozen attempts remain historical evidence.

## Verification and limits

[A-03 verification](evidence/phase-a03-verification-20260923.json) separates protocol fixtures, actual native process tests, installed-package checks and the local ComfyUI trial. Cross-family tests cover the shared workspace lock, detached requests in another workspace, native owner contention and interrupted training/standalone records. Native tests create real suspended children, retain identity before resume, kill only the owned Job Object and verify an unrelated process survives. Crash tests preserve intent/acknowledgement/collection boundaries and require positive recovery evidence.

The actual installed trial preserves a controlled unrelated-client history entry, times out after one accepted SDXL request, refuses a competing workspace and the managed device-lease primitive, refuses early recovery without terminal evidence, then observes the same prompt and releases ownership. No cross-model concurrency, capacity increase, new training quality or product-wide completion is claimed. The existing candidate remains rejected; A-04 inference-stack integration and the broader phases remain open.
