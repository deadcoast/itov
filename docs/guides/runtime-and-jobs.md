# Runtime qualification and single-worker execution

This contract covers runtime launch and single-workflow submission/observation. Its 2026-09-21 qualification below establishes neutral image I/O. Later [image](image-inference.md), [video](image-to-video.md) and [training](../training/training-and-promotion.md) trials have separate bounded evidence; general model quality and custom-node support remain unqualified. Current [ownership](../contracts/execution-ownership.md) rules apply to new submissions.

## Qualified local runtime

The runtime came from the official [ComfyUI v0.37.0 release](https://github.com/Comfy-Org/ComfyUI/releases/tag/v0.37.0), using `ComfyUI_windows_portable_nvidia.7z`.

| Field | Observed value |
| --- | --- |
| Archive bytes | 1,925,204,508 |
| Published and verified SHA-256 | `7805f634fab51f63a238aaf0cfe2a9833bb7c86ddfc8400a60919f44460d7d65` |
| ComfyUI | 0.37.0 |
| Embedded Python | 3.13.14 |
| PyTorch | 2.13.0+cu130 |
| CUDA runtime | 13.0 |
| Device | NVIDIA GeForce RTX 5090, compute capability 12.0 |
| Torch architecture coverage | Includes `sm_120` |
| CUDA execution probe | A 256 × 256 BF16 matrix multiplication completed with finite results after synchronization |
| Server node registry | 959 classes, custom nodes disabled |
| Attention at startup | PyTorch attention; SageAttention and Triton are not acceptance claims |

The official release API, rather than a cached latest-release webpage, supplied the pinned version and checksum. Archive members were checked for containment before extraction. The old CUDA 12.6 archive was preserved. Archive and extracted runtime remain local and ignored by Git.

For a fresh machine, obtain the matching package from that release, verify the checksum, and extract its `ComfyUI_windows_portable` directory under `AI/ComfyUI/`. Do not overwrite an existing runtime. Re-check [official installation guidance](https://docs.comfy.org/installation/comfyui_portable_windows) when selecting a different release. The Python used by `uv run` remains separate from the runtime's embedded Python.

## Starting the server

```powershell
uv run --locked itov server start
```

The command resolves paths from `workspace/itov.toml`, passes explicit workspace input/output directories, disables automatic browser launch, and uses loopback HTTP only. It runs in the foreground; Ctrl+C stops that server. `--print-command` prints the argument list without starting a process. `--custom-nodes` enables installed custom nodes, which need their own compatibility checks.

The qualification session started a hidden server at `http://127.0.0.1:8188`. Its output is in `workspace/logs/comfyui-stage02.stdout.log` and `workspace/logs/comfyui-stage02.stderr.log`; its process ID was recorded in `workspace/state/comfyui-stage02.pid`. These identify that session only. Do not assume a saved PID still identifies the same process later.

## Job states and limits

`itov job run WORKFLOW` validates the exported API graph against the running server's node registry, writes a durable intent record, and submits once. The record contains a request ID, workflow bytes digest, parsed workflow, server URL, validation result, acknowledged prompt ID, execution history, and downloaded artifact provenance.

| State | Meaning and next action |
| --- | --- |
| `validation_failed` | Local graph/schema checks failed. No submission occurred. |
| `rejected` | ComfyUI returned an explicit HTTP 400 validation error; server details are retained. |
| `submission_unknown` | The request may have reached ComfyUI, but no usable acknowledgement arrived. Automatic resubmission is refused. |
| `queued`, `observing` | An acknowledged prompt is being monitored. |
| `timed_out`, `detached`, `observation_failed` | Waiting ended; the server job may continue. Use `job wait RECORD` to resume without submission. |
| `failed` | Execution history reports an error or interruption. The server's error record is retained. |
| `collecting`, `collection_failed` | Execution succeeded but output retrieval is incomplete. Resume retries observation/retrieval without submitting again. |
| `succeeded` | Persistent output artifacts were retrieved and hashed. Resuming checks local artifact hashes before returning this state again. |

Job Ctrl+C handling detaches the observer; it does not call the server's interrupt endpoint. This avoids cancelling unrelated work. Standalone jobs retain this observation-only behavior. Sequential plans separately support [durable batch cancellation](extended-media.md), including optional per-job interruption when the reviewed atomic endpoint is available.

HTTP operations default to a three-second socket timeout. Execution observation defaults to 120 seconds, adjustable with `--wait-timeout`; artifact transfer follows successful execution and uses the HTTP timeout. Each artifact is limited to 512 MiB. Persistent `type=output` files are retrieved through `/view` using exact history descriptors. Input references and temporary previews are excluded. Jobs producing only text or previews do not qualify as delivered media.

Artifacts are published without replacing a differing existing file. Partial downloads are removed, Content-Length is checked when supplied, and resume can retrieve a missing artifact. Job records are replaced atomically. An OS-backed lock prevents two local processes from operating on the same record and releases on process exit; no PID signalling or age-based lock deletion is used. Batch dispatch adds separate [workspace ownership and reservation records](../contracts/batch-execution.md). Use `batch resume PLAN` for batch-owned jobs, including their pre-submission `prepared` state and uncertain-acknowledgement reconciliation.

## Real qualification results

- The live preflight passed with the configured local runtime and CUDA device.
- `LoadImage → SaveImage` completed and returned an exact history artifact; the 64 × 64 output matched the neutral input pixel-for-pixel.
- A second job deliberately stopped waiting immediately, then resumed with the same prompt ID and completed without resubmission.
- A deliberately invalid PNG passed filename selection but failed during real execution. ITOV reported `failed`, retained the ComfyUI exception history, and reported no delivered artifact.

The [runtime evidence](../evidence/stage-02-runtime-20260921.json) retains source/checksum details, runtime observations, job IDs, output hashes, and the expected negative case. The initial failed stage-one preflight remains preserved separately. None of these checks establish checkpoint quality, video generation, performance claims from the original documents, or custom-node compatibility.
