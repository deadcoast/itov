# Catalog contracts and ledger integrity

Stage three defines the version-one data contract used by executable ITOV. The original Parts 3, 4, 8, 9, and 10 remain design references. Their incompatible JSON/CSV variants are not silently imported, sealed, or repaired. The catalog records whole revisions and now includes version-two candidate lifecycle events. Render picks, permanent seed reservations and observations live separately in the SQLite execution store; [candidate lifecycle](../evaluation/candidate-lifecycle.md) implements explicit reviewed transitions. Unattended promotion remains outside this contract. Stage four adds [rotation planning](batch-planning.md) over these snapshots.

## Operator workflow

Create the neutral example in an initialized workspace. The helper refuses to overwrite either destination and pins the workflow's actual bytes, including its checkout line endings:

```powershell
uv run --locked python scripts/create_catalog_example.py
uv run --locked itov catalog validate workspace/templates/neutral.catalog.json --check-files
uv run --locked itov catalog init
uv run --locked itov catalog show --json
```

Review the catalog and copy the head from `show` into the import command:

```powershell
uv run --locked itov catalog import workspace/templates/neutral.catalog.json --expected-head HEAD_FROM_SHOW
uv run --locked itov catalog verify --check-files --json
```

`init` creates an empty catalog once. `import` checks every referenced file's SHA-256 and the structural validity of each API workflow before publishing anything. A stale expected head fails, even if the submitted catalog happens to match current contents. Reimporting identical content against the current head verifies assets again and creates no duplicate event. `validate` alone only checks the schema and relationships; it needs neither a workspace nor a server. `show` returns the current committed snapshot, and `--json` includes its full catalog and ledger. None of these commands submits ComfyUI work.

`--config` selects a workspace as for other ITOV commands. Paths inside a catalog are relative to that workspace, never relative to the incoming catalog file. `verify --expected-head HASH` also checks an independently retained snapshot anchor. Exit codes are 0 for success, 1 for an otherwise valid store with a pending transaction, and 2 for invalid input, stale state, corrupted data, missing/mismatched files, or I/O errors.

## Catalog schema v1

All keys shown below are required and unknown keys fail validation. Integers are actual JSON integers (booleans and floating-point values are rejected), between 0 and 2^64−1 unless a positive minimum is stated. IDs use lowercase ASCII letters, digits, underscores, periods, and hyphens, start with a letter or digit, and are at most 128 characters. IDs must be unique within each collection. Text lists reject duplicates and control characters.

The top-level object has `version: 1`, `presets: []`, `loras: []`, and `compatibility: {hard_conflicts: [], soft_conflicts: [], synergies: [], preset_pairings: []}`. An empty catalog is valid.

| Preset field | Contract |
| --- | --- |
| `id`, `category` | IDs; categories are operator-defined |
| `tags` | Array of nonempty strings |
| `workflow` | Asset reference: `{path, sha256}` |
| `base_model` | Model-family ID, or null for a workflow with no model |
| `rotation_weight_milli` | Positive integer; 1000 represents 1.0 |
| `seed` | Null, or `{base, step}` with a nonnegative base and positive step; stage-four requests declare the corresponding workflow bindings |

Sampler, motion, prompts, and post-processing settings belong to the referenced real ComfyUI API graph. The catalog does not introduce a competing synthetic workflow representation. Stage-four planning supports explicit seed and built-in LoRA loader bindings; actual model-specific runtime qualification remains later work.

| LoRA field | Contract |
| --- | --- |
| `id`, `category`, `slot` | IDs; no hard-coded artistic categories or slot names |
| `asset` | Asset reference: `{path, sha256}` |
| `base_models` | Nonempty array of unique model-family IDs |
| `strength_milli` | `{min, recommended, max}` integers with `min <= recommended <= max`; 650 represents 0.65 |
| `rotation_weight_milli` | Positive integer |
| `trigger_words` | Array of nonempty strings |
| `status` | `candidate`, `active`, `flagged`, or `quarantined` |

These fields record operator assertions. Neither `active`, a declared model family, nor passing file hashes establishes model compatibility, quality, licensing, or rendering acceptance. File verification does not deserialize weights. No numerical tuning recommendation or total stack budget is inferred from the original examples.

| Compatibility field | Contract |
| --- | --- |
| `hard_conflicts`, `soft_conflicts` | Arrays of two distinct existing LoRA IDs; unordered pairs cannot repeat, even across the two lists |
| `synergies` | Array of `{loras, weight_milli}`; at least two distinct existing IDs, positive weight, no duplicate combination or hard-conflict subset |
| `preset_pairings` | Array of `{preset, loras}`; unique existing preset, at least one distinct existing LoRA, and each LoRA declares the preset's base model |

Pairings are preference pools, not complete stacks: they may include alternatives in the same slot or mutually conflicting alternatives. The stage-four selector resolves conflicts, statuses, slots, and budgets. Synergy and base-model metadata are declarations, not measured compatibility.

Asset paths use `/` separators, have no absolute paths, empty/dot/parent components, Windows stream syntax, device names, wildcard characters, or trailing dots/spaces. LoRA paths must be unique ignoring case. Hashes are 64 lowercase hexadecimal characters. File checks reject redirects outside the workspace. Input, snapshot, and journal JSON documents are each limited to 32 MiB; large model files are hashed incrementally.

## Canonical encoding and ledger schema v1

The encoding is explicitly ITOV-specific, not a claim to implement RFC 8785. Objects use sorted keys, arrays retain their order, strings use UTF-8 without ASCII escaping or Unicode normalization, and separators are `,` and `:` without whitespace. Floating-point values are forbidden. Integer thousandths avoid rounding or platform-specific decimal conversion. Duplicate input keys, non-finite numbers, and lone Unicode surrogates are rejected. File hashes cover actual bytes; catalog hashes cover canonical bytes without a trailing newline.

Each ledger row contains exactly:

| Field | Contract |
| --- | --- |
| `version` | Integer 1 |
| `sequence` | Contiguous integer starting at 1 |
| `event_id` | Unique canonical UUID |
| `created_at` | UTC timestamp `YYYY-MM-DDTHH:MM:SS.ffffffZ`; sequence determines ordering |
| `action` | `initialize` for row 1, then `catalog_import` |
| `catalog_sha256` | Hash of the canonical catalog for that revision |
| `previous_hash` | Prior row hash; 64 zeros for the first row |
| `row_hash` | SHA-256 defined below |

C-05 additionally supports version-two lifecycle rows after initialization. They have the same fields plus `operation: {path, sha256}`, which references an immutable lifecycle preview. Their actions are `candidate_activate`, `candidate_retire` and `candidate_rollback`. Existing version-one rows and snapshot version one remain unchanged. `candidate status/replay` also validate the bound preview, predecessor snapshot and exact one-entry delta; ordinary ledger verification checks the reference schema and its inclusion in the hash chain. See the [lifecycle contract](../evaluation/candidate-lifecycle.md).

The row body comprises all row fields except `previous_hash` and `row_hash`, including `operation` for version two. Every writer and verifier uses the same domain prefix (the body carries the version):

```text
SHA256(b"ITOV-LEDGER-v1\0" + bytes.fromhex(previous_hash) + canonical_bytes(body))
```

The [frozen vectors](../../tests/fixtures/ledger-v1-vector.json) cover both zero and nonzero predecessors. The snapshot contains `{version: 1, catalog, ledger}`. Its file is canonical JSON followed by one LF byte; the snapshot head is the SHA-256 of that entire file. Readers validate its content hash, schema, every chain link and row hash, and the current catalog's match with the ledger tail. Missing, reordered, duplicated, or altered rows fail these checks when their retained hashes/anchor disagree.

## Commit protocol and recovery

Workspace storage:

```text
state/catalog/
  catalog.lock       stable OS lock file; never delete to clear ownership
  HEAD               snapshot SHA-256 followed by LF
  objects/HASH.json  retained immutable catalog + ledger generations
  pending.json       complete redo intent, present only during an unfinished transaction
```

Writers acquire one OS-backed lock covering validation of current state through commit. The shared lock utility uses Windows byte-range locking or POSIX flock, bounded waiting, and ownership released by process exit. It does not probe or signal PIDs, steal based on age, or unlink an existing lock.

Under that lock, a writer validates the expected head and asset bytes, then:

1. Writes and fsyncs complete redo intent to a same-directory temporary file, then publishes `pending.json` without overwriting an existing intent.
2. Writes and fsyncs the new complete snapshot, then publishes its hash-named object without overwriting existing data.
3. Atomically replaces `HEAD` with the new snapshot digest: this is the commit point.
4. Removes the completed pending intent. All prior snapshots remain available.

Readers acquire the same lock for the short `HEAD` read to avoid Windows file-sharing conflicts with pointer replacement, then release it before loading that immutable generation. In-memory snapshots retain immutable bytes and return independent parsed copies, so a later import cannot mix a new manifest with an old matrix or mutate an already held snapshot. A reader can retain an older complete generation while an import proceeds. `show` reports whether pending intent was observed; `verify` returns 1 if it observes pending intent. The pending flag is a separate observation and can change immediately under a concurrent writer.

If an operation is interrupted, inspect `catalog show --json` and run:

```powershell
uv run --locked itov catalog recover --json
uv run --locked itov catalog verify --check-files --json
```

Recovery holds the same lock and validates the entire intent, its target snapshot, and the exact extension of prior ledger history. It completes a prepared commit, or cleans up an already committed intent, without adding a second event. Running it again reports `not_needed`. New imports refuse pending transactions until recovery runs. Recovery restores the recorded metadata transaction; it does not roll back or rewrite model/workflow files. Verify those separately after recovery.

Lifecycle intent requires `candidate recover`; generic `catalog recover` refuses it. Before publication, lifecycle recovery revalidates the exact deployed authorization and preview. After publication it verifies the committed delta and cleans up intent without reauthorizing the model. `candidate recover --abandon` can archive an uncommitted lifecycle intent under `state/catalog/abandoned` without changing HEAD. Retirement can quarantine unavailable weights and does not verify unrelated model assets; activation validates its own bound deployment evidence. All lifecycle deltas still validate catalog schema and relationships.

Corrupt intent, divergent or missing committed HEAD, or a conflicting snapshot object causes a preserved, explicit error. Recovery never truncates the ledger, re-seals bad rows, guesses a snapshot from directory order, or overwrites corrupt objects. Temporary files left by a hard crash are unreferenced and ignored; no automatic deletion or retention pruning is performed.

## Qualification boundaries

Windows tests cover actual child-process exits after intent, snapshot, and HEAD publication, plus exits during partial snapshot/HEAD temporary writes. They also exercise simultaneous writers, stale rejection, repeat recovery, corrupt data preservation, immutable reads, and junction containment. Process-crash recovery is qualified; whole-machine power loss, remote shares, cloud-synced storage, backup retention/restore, malicious concurrent filesystem replacement, and other OS platforms are not qualified.

The protocol uses Python's [file flushing and replacement APIs](https://docs.python.org/3/library/os.html#os.fsync) and [Windows locking API](https://docs.python.org/3/library/msvcrt.html#msvcrt.locking). File fsync and atomic name replacement do not by themselves establish Windows directory-metadata durability through power loss. A failed replacement preserves the pending transaction for explicit recovery.

Hashes detect disagreement with retained data, not authenticity. Someone able to replace the entire store can recompute the chain or substitute a previously valid head. Keep an independent expected head to detect rollback; off-device signed anchors and backup qualification are not implemented. Verification checks the current generation's full ledger and catalog, not every historical object or historical asset file.
