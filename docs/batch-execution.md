# Qualified sequential batch execution

ITOV executes immutable plans one job at a time, introduced in 0.5.0 and extended for pinned image inference in 0.6.0. A qualification receipt binds a plan to observed live node schemas, runtime identity, input bytes, and supported stock loader paths. Submission is opt-in; `batch plan`, `verify`, and `qualify` never POST a prompt.

Version 0.7.0 adds the separately identified `stock-wan22-v1` profile for [pinned silent image-to-video](image-to-video.md). Existing image receipts retain the `stock-local-v1` shape. Wan qualification additionally binds the required stock extras modules and pinned diffusion/text-encoder/VAE/input files, rejects ambiguous loader aliases, and requires an MP4/H.264 output contract. V3 nested choices are validated through their dotted API inputs.

## Commands

Start the configured server with `uv run --locked itov server start`. With an existing saved plan:

```powershell
uv run --locked itov batch qualify workspace/state/plans/PLAN_ID.json --save
uv run --locked itov batch run workspace/state/plans/PLAN_ID.json --qualification workspace/state/qualifications/QUALIFICATION_ID.json
uv run --locked itov batch status workspace/state/plans/PLAN_ID.json
uv run --locked itov batch resume workspace/state/plans/PLAN_ID.json
```

Use the IDs printed by planning and qualification. Every command accepts `--config` and `--json`. Qualification and execution accept `--timeout` (per HTTP request, at most 60 seconds). Run/resume also accept `--wait-timeout` (per job, at most 86400 seconds) and `--poll-interval` (at most 60 seconds). A wait timeout or Ctrl+C detaches observation; it does not cancel work on ComfyUI. Inspect the printed prompt IDs and `state/jobs/REQUEST_ID.json` records for artifacts and execution errors.

Exit codes: qualification/run/resume return 0 for success, 1 for a paused or failed execution, and 2 for invalid inputs or an operation that could not start. A successful `status` or `abandon` command returns 0 even if the reported batch did not succeed. No package release or automatic Git commit is implied.

## Qualification profile: `stock-local-v1`

The profile requires a loopback HTTP runtime whose reported argument vector exactly matches `itov server start`, including custom nodes disabled and explicit workspace input/output directories. `extra_model_paths.yaml`, alternate directory flags, custom nodes, arbitrary loader adapters, annotated input paths, external text embeddings, and dynamic output prefixes are outside this profile.

Supported stock classes are `LoadImage`, `SaveImage`, `CheckpointLoaderSimple`, `LoraLoader`, `LoraLoaderModelOnly`, `CLIPTextEncode`, `EmptyLatentImage`, `KSampler`, `VAEDecode`, and `VAEEncode`. Their live registry entries must identify the `nodes` module. All expanded graphs must pass live schema validation. Every `KSampler.seed` must have an explicit plan binding and equal that job's reserved seed.

The receipt records:

- Plan ID, profile/version, server URL, runtime argument vector, ComfyUI/Python/Torch versions, and stable device identity fields.
- The hash of the used live node schemas and hashes of `main.py`, `nodes.py`, and `folder_paths.py`.
- Hashes and sizes of input files and checkpoint files reached through the default stock paths. LoRA loader names must resolve under `models/loras` to the exact planned catalog asset bytes, including nested paths. A loader name cannot represent two different planned assets.
- A deterministic qualification ID over the canonical receipt body, excluding that ID. Saved receipts are immutable canonical JSON plus LF under `state/qualifications`.

Before **each new POST**, ITOV replays the plan against the current clean catalog, rehashes assets, reads live metadata, and requires the receipt to match. The final catalog head check and POST share the catalog writer lock. A busy queue pauses new submission. A current job that was already accepted may still be observed and collected after catalog or input changes; the next submission remains blocked.

These are local preflight observations, not a runtime attestation or a model-compatibility certificate. The operator must keep runtime files, input/model bytes, search-path configuration, and the server under exclusive control during execution. Restart ComfyUI after changes to model bytes or search paths: existing node/model caches cannot be attested through these metadata endpoints. Changes between the final file check and server use, and a different client racing the queue check, are outside this guarantee. Other clients and standalone `job run` do not participate in the batch lease.

Stage five qualified the neutral image-copy workflow before any weights were installed. Stage six subsequently qualified four real jobs using the pinned SDXL base checkpoint and LCM SDXL LoRA; see [image-inference evidence](image-inference.md#local-acceptance-evidence). Loader resolution unit tests still use plain-byte files and protocol fixtures, and do not establish inference by themselves.

## Ownership, seeds, and history

`state/batches/execution.lock` is a stable OS-owned dispatcher lock. ITOV never deletes a lock marker or probes PIDs. `state/batches/execution.sqlite3` stores complete plan and qualification bytes, ordered job ownership, permanent seed reservations, and timestamped observation events. SQLite explicit transactions use foreign keys, full synchronous writes, and the rollback journal. One transaction claims the complete batch and all non-null unsigned 64-bit seeds, or none of them. Seeds are stored as decimal text to preserve the full range.

Reservations are workspace-wide across this batch executor, including failed and abandoned batches. They do not cover standalone jobs, other workspaces, or external clients. A collision rejects the entire claim; execution never silently changes a planned seed. Choose a different request seed or preset seed base and generate a new plan. Cooldowns still apply within the plan; the executor does not add cross-batch rotation selection rules.

Job request IDs are deterministic UUIDv5 values derived from the plan ID and zero-based index. Each job record retains its owner, exact graph, workflow hash, prompt ID, execution history, and artifact hashes. Observation events are separate from the version-one hash-chained **catalog revision** ledger; they are transactional execution records, not cryptographically sealed history.

The next job starts only after the previous job succeeds and every persistent output has been downloaded from its exact history descriptor and hashed. Existing differing output bytes are preserved with an error. Repeating run/resume for a completed plan verifies local artifacts and does not submit the plan again. To intentionally render again, create a distinct plan; seed reservations still apply.

Stock Windows ComfyUI reports nested output subfolders with backslashes. ITOV accepts both separator forms for safe relative subfolders and preserves the exact descriptor when requesting `/view`; parent traversal, rooted paths, and drive paths remain rejected.

## Resume and uncertain acceptance

| Durable state | Resume behavior |
| --- | --- |
| Reserved, no job file | Create that owned record in `prepared` state. |
| Prepared record published before reservation observation | Adopt the matching prepared record; requalify before submission. |
| Prepared | Requalify, check idle queue/current catalog, save `submitting`, then issue one POST. |
| Submitting / submission unknown | Search running/pending queue and the latest 200 history entries for the exact request ID and matching graph under the numeric-normalization rule below. Never POST again. |
| Known prompt ID | Observe that prompt and validate returned batch ownership; collect verified outputs. |
| Succeeded | Verify downloaded artifacts; recollect missing artifacts from existing history without resubmission. Differing files remain untouched. |
| Rejected / execution failed | Stop the batch; leave remaining jobs unsubmitted and retain reservations. |
| Missing, inconsistent, or regressed ownership | Preserve the evidence and stop. Never recreate a previously prepared/started job. |

A matching server record is positive acceptance evidence. From 0.6.0, graph matching permits ComfyUI's lossless integer/float normalization of scalar input values (for example, `cfg: 7` becoming `7.0`). All other graph values, connection arrays, metadata, and owner IDs retain strict equality; booleans and rounded large integers do not qualify. Original submitted bytes remain in the plan/job record. An empty queue, missing history, or server restart never proves a POST was not accepted. If the relevant entry has aged out of the recent-history query, an explicit ID can be checked:

```powershell
uv run --locked itov batch resume workspace/state/plans/PLAN_ID.json --prompt-id KNOWN_PROMPT_ID
```

The supplied ID must still have matching server provenance; the option cannot force an attachment. Multiple matching prompts or a graph mismatch remain uncertain. If a crash occurred after saving `submitting` but before actually sending the request, automatic resume deliberately remains uncertain when no evidence exists. There is no force-retry shortcut.

Paused batches retain persistent workspace ownership even after the process exits. Resolve/observe accepted jobs with `resume`. To retire a remainder after a stale catalog or another deliberate change:

```powershell
uv run --locked itov batch abandon workspace/state/plans/PLAN_ID.json
```

Abandon refuses active or uncertain jobs. It only retires remaining unsubmitted picks after all submitted work has a known terminal outcome; it never cancels server jobs or releases reserved seeds. From 0.7.0, a `collection_failed` job can be retired only after fresh server checks establish matching request/graph ownership and terminal success. This supports preserving an invalid video while retiring its remainder; missing or ambiguous history still refuses. An abandoned plan cannot later be submitted. A missing database with an existing initialization marker is an error, not an empty reservation store. Preserve the complete workspace state for inspection/consistent recovery; partial backup restoration and manual record edits are not supported recovery procedures.

## Evidence and remaining gates

The [real execution record](evidence/stage-05-execution-20260921.json) retains a four-job neutral batch, a two-job real-server run with an injected lost acknowledgement and safe reconciliation, and a one-job timeout/resume with the same prompt ID. All seven collected images were pixel-identical to the 64×64 input. Repeating the completed primary batch made zero runtime requests. Existing standalone job records and the catalog head remained unchanged.

The [source/package verification](evidence/stage-05-verification-20260921.json) records automated checks, including controlled process exits at preparation/submission/acknowledgement boundaries, interrupted transaction rollback, competing dispatcher exclusion, seed collisions, stale inputs/catalogs, wrong ownership, and artifact preservation. These do not qualify sudden power loss, remote filesystems, backup restore, other operating systems, pretrained model inference, video/audio generation, performance, or parallel GPU execution.

The separate [stage-six inference evidence](evidence/stage-06-inference-20260921.json) establishes sequential execution with the selected pretrained checkpoint and LoRA. It retains the initial observation/collection failures and successful recovery using the already accepted prompt, plus the four final images. Its [source/package verification](evidence/stage-06-verification-20260921.json) includes numeric-normalization and Windows descriptor regressions. The broader storage, model, quality, performance, and concurrency limits above remain open.

The [stage-seven video evidence](evidence/stage-07-video-20260921.json) records two real Wan 2.2 5B clips and completed resume without new prompts. Video collection and completed resume additionally verify full local decoding and the pinned media contract. Source tests inject invalid-video collection, successful resume, safe retirement, and missing-history refusal. These establish the bounded silent-video path; audio, long-video quality and concurrent GPU execution remain unqualified.
