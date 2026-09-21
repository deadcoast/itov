# Deterministic batch and rotation planning

The planning commands introduced in ITOV 0.4.0 build a batch from one reviewed catalog snapshot. They select presets and LoRA stacks, assign seeds, and expand explicit inputs in real API workflow files. Planning does not submit prompts, reserve render seeds, change catalog status, or append render history. A successful plan establishes deterministic construction and file integrity, not successful inference. ITOV 0.5.0 adds separate opt-in [qualification and sequential execution](batch-execution.md) commands.

## Neutral example

After the neutral catalog from [stage three](catalog-and-ledger.md) is imported:

```powershell
uv run --locked python scripts/create_batch_example.py
uv run --locked itov batch plan workspace/templates/neutral.batch.json
uv run --locked itov batch plan workspace/templates/neutral.batch.json --save --json
uv run --locked itov batch verify workspace/state/plans/PLAN_ID.json --json
```

The helper creates a request with the current catalog head and refuses an existing destination. Inspect that request before planning. Plain `batch plan` previews without writing a plan. `--save` publishes canonical JSON under `workspace/state/plans/<plan_id>.json` without overwriting different data; an identical repeat reuses the same file. The text preview lists the first ten jobs. `--json` includes every job, exact workflow payload, file hashes, and exclusions. Use `--config` to select another workspace.

The neutral example requests four copies of the image-copy workflow, with no LoRAs or seed inputs. Its repeated workflow payloads are intentionally identical. It does not demonstrate stochastic model variation. The expanded workflow JSON is retained inside the plan, not automatically exported to the job queue.

The planner returns exit code 0 on success and 2 for invalid requests, stale or pending catalog state, missing/mismatched files, unsupported bindings, exhausted constraints, or resource limits. Exhaustion reports `code: rotation_exhausted`, the zero-based job index, and each preset's exclusion reason. No partial plan is saved.

## Request v1

Every listed key is required; unknown keys are rejected. A minimal request is:

```json
{
  "version": 1,
  "catalog_head": "COPY_THE_REVIEWED_HEAD_FROM_CATALOG_SHOW",
  "count": 4,
  "seed": 0,
  "presets": ["neutral-copy"],
  "no_repeat_within": 0,
  "category_cooldown": 0,
  "lora_policy": {
    "ids": [],
    "slots": [],
    "max_strength_milli": 0,
    "strength_mode": "recommended",
    "soft_conflicts": "exclude",
    "no_repeat_within": 0,
    "preferred_multiplier_milli": 1000,
    "loader_names": {}
  },
  "bindings": {
    "neutral-copy": {"seed_inputs": [], "lora_slots": []}
  }
}
```

Replace the head placeholder with the actual 64-character digest; the helper does this for the example. Version-one catalog schemas remain unchanged. Planning controls and node bindings live in the separate version-one request.

| Field | Meaning |
| --- | --- |
| `catalog_head` | Reviewed immutable catalog generation; it must still be current and have no pending transaction |
| `count` | Integer 1–1000 |
| `seed` | Unsigned 64-bit integer driving deterministic selection and offsetting workflow seeds |
| `presets` | Nonempty unique list of existing preset IDs, up to 64 |
| `no_repeat_within` | Exclude presets selected in the preceding N jobs; 0 disables the rule |
| `category_cooldown` | Exclude categories selected in the preceding N jobs; 0 disables the rule |
| `bindings` | Exactly one binding object for every requested preset |

All cooldowns range from 0 to 1000. They apply within this plan only. There is no hidden dependency on prior previews, wall-clock time, dictionary order, Python hash randomization, or current job history.

LoRA policy:

| Field | Meaning |
| --- | --- |
| `ids` | Explicit candidate allowlist, up to 256 catalog IDs; no implicit whole-catalog selection |
| `slots` | Unique required slots, up to 8; exactly one LoRA is selected for every requested slot |
| `max_strength_milli` | Total per-stack strength budget; 1250 means 1.25 |
| `strength_mode` | `recommended` uses declared recommended strengths; `uniform` draws bounded integer thousandths |
| `soft_conflicts` | `exclude` rejects them; `allow` retains them visibly in each job's `soft_conflicts` |
| `no_repeat_within` | Exclude any LoRA used in the preceding N jobs |
| `preferred_multiplier_milli` | Positive factor applied for each selected LoRA in the preset's preference pool; 1000 is neutral, 1500 is 1.5× |
| `loader_names` | Exact mapping from every candidate ID to its relative ComfyUI loader name |

Both `ids` and `slots` must be empty or nonempty together. Slots are all required; optional slot probabilities are not implemented. Candidate files marked `candidate`, `flagged`, or `quarantined` are excluded. Only `active` LoRAs with matching model-family declarations and slots are eligible. Every exclusion is recorded with its preset, LoRA ID, and reason. A LoRA's declared maximum must fit the supported loaders' nonnegative 0–100 range; this is an adapter bound, not an image-quality recommendation.

Loader names are explicit because workspace asset paths and ComfyUI's loader namespace are different. Names must be distinct ignoring case and use portable relative paths. Planning verifies the catalog asset's bytes; it does not prove that the running server resolves the supplied name to those same bytes. This mapping must be qualified before batch execution.

## Binding seed and LoRA inputs

A seeded preset requires one or more bindings to existing integer literal inputs named `seed` or `noise_seed`, with an exact declared class name. A preset with `seed: null` requires an empty seed-binding list. For example:

```json
{
  "seed_inputs": [
    {"node": "12", "class_type": "KSampler", "input": "seed"}
  ],
  "lora_slots": [
    {"slot": "style", "node": "8"},
    {"slot": "lighting", "node": "9"}
  ]
}
```

This illustrates bindings only; it must match the actual exported workflow and requested slots. No node ID is guessed. All bound seed inputs receive the job's same derived seed. Links, booleans, missing inputs, changed classes, duplicate addresses, duplicate slots, and shared loader nodes are rejected.

The implemented LoRA adapters are ComfyUI's built-in `LoraLoader` and `LoraLoaderModelOnly`, checked against the installed v0.37.0 [upstream definitions](https://github.com/Comfy-Org/ComfyUI/blob/v0.37.0/nodes.py). They require existing model links and, for `LoraLoader`, a clip link. The planner replaces literal `lora_name` and `strength_model`; `LoraLoader` also receives the same strength in `strength_clip`. Every built-in LoRA loader in the graph must have a binding, so an undeclared built-in loader cannot silently escape the stack budget. All other graph content stays unchanged.

Custom loader adapters and different model/clip strengths are not supported. Other custom-node semantics are not interpreted. The reported budget covers the declared built-in slots, and strength is counted once per selected LoRA, even when applied to both model and clip. This sum is a selection constraint, not a measurement of the composed model's effect.

## Selection algorithm: `itov-rotation-v1`

1. Load one clean catalog generation matching the request. Verify every requested workflow's raw SHA-256 and graph structure, and validate its bindings. Determine individually eligible LoRAs and verify all their file hashes, including eligible candidates that may not ultimately be picked. Unrequested or excluded LoRA files are not read.
2. Sort presets and LoRA IDs lexically; sort requested slots lexically. Enumerate complete candidate stacks in that stable slot/ID order. Reject hard conflicts, excluded soft conflicts, and combinations whose required strengths exceed the budget. Required strength is the recommended value in `recommended` mode and the minimum in `uniform` mode.
3. Compute each stack's exact rational weight: multiply its LoRA rotation weights, multiply `preferred_multiplier_milli / 1000` for each preferred member, and multiply `weight_milli / 1000` for every declared synergy contained in the stack. Convert all feasible weights for that preset to integers using their common denominator. No floating-point probability or rounding is used.
4. For each job, remove presets/categories in their cooldowns and stacks containing recently used LoRAs. Choose a remaining preset using its catalog rotation weight, then choose one of its feasible stacks using the precomputed stack weights. Preset weight is not multiplied by its number of feasible stacks.
5. Choose strengths. `recommended` preserves the exact recommendation. `uniform` processes sorted slots and samples an integer uniformly from `[min, min(max, remaining_budget - later_slot_minima)]`. It reserves later minima and never scales a strength below its range. This is conditional sampling in slot order, not a uniform distribution over all possible complete stacks and strengths.

Each weighted draw uses an integer ticket in `[0, sum(weights))`. The random-byte definition is [SHAKE-256](https://docs.python.org/3/library/hashlib.html#shake-variable-length-digests) over `b"ITOV-ROTATION-v1\0" + seed.to_bytes(8, "big") + counter.to_bytes(8, "big")`. Start the counter at zero, increment it for each candidate draw, mask the output to `(bound-1).bit_length()` bits, and reject values at or above the bound. Read the minimum whole-byte digest length and interpret it as big-endian. Bound 1 returns zero without consuming a counter value. Draw order is preset, stack, then each strength in sorted slot order. The [frozen vector](../tests/fixtures/rotation-v1-vector.json) fixes rejection draws, choices, strengths, and serialized workflow hashes.

For a seeded preset at zero-based job index `i`, start with `preset.seed.base + request.seed + i * preset.seed.step`. If that integer was already used by a seeded job in this plan, increment by the preset's positive step until unused. Exceeding 2^64−1 is an explicit `seed_overflow` error; there is no wraparound. Multiple bound inputs receive the same seed. Unseeded jobs retain null and do not reserve a number.

Zero cooldowns truly disable the rules. Exhaustion never silently relaxes them. Selection is sequential without backtracking across earlier choices: an unlucky prefix can exhaust a later pick even when another complete sequence might exist. Inspect the error and explicitly change the selection seed or constraints. Successful shorter requests are prefixes of longer requests when only `count` changes. Reordering catalog collections does not change picks, although a new catalog head or differently ordered request changes plan identity.

Enumeration is bounded at 20,000 raw combinations per preset and 100,000 across the request before conflict pruning. Planning supports at most 64 synergy declarations, 4096-bit selection weights, and 32 seed bindings per preset. The full saved document and aggregate workflow payloads are each limited to 32 MiB. Oversized requests fail explicitly instead of sampling only an undocumented subset.

## Provenance, replay, and persistence

The plan contains version 1, the algorithm ID, `scope: planning_only`, catalog and ledger heads, the exact request, verified asset references, individual candidate exclusions, static feasible-stack counts, and ordered jobs. Every job includes its preset/category, seed, selected LoRA identities and asset hashes, loader names, integer strengths, admitted soft conflicts, total strength, exact `workflow_json`, and that payload's SHA-256.

Workflow payloads use sorted-key compact JSON with UTF-8 strings and one LF, allowing the real graph's finite float inputs. They are embedded as strings in the existing integer-only ITOV canonical plan encoding. This preserves the catalog/ledger encoding contract. The plan ID hashes the canonical top-level object excluding `plan_id`, without a trailing newline. The saved file is canonical JSON followed by one LF. There are no timestamps or machine-specific absolute paths in that identity.

`batch verify` checks the stored hash and canonical encoding, requires the same clean current catalog head, rechecks asset bytes and bindings, then reconstructs and compares the entire plan. Merely editing a job and recomputing `plan_id` does not pass replay. A changed catalog requires a newly reviewed request/head and a new plan. Pending catalog transactions require the existing explicit recovery command; planning never repairs them.

Planning checks the head again after construction and before saving. Saving uses a same-directory fsynced temporary file and publication without overwrite. Publication failure leaves no partially named plan. Successful plans are immutable through ITOV; altered existing files are preserved with an error. Preview/save/verify leave the catalog ledger and job records unchanged. These are point-in-time checks: assets or catalog state can change afterward, so future execution must revalidate immediately before submission.

## Acceptance and next gate

Tests cover neutral and synthetic model-graph fixtures, exact replay, process hash-seed independence, the frozen cross-Python vector, cooldown exhaustion, active/model/slot filtering, conflicts, budget boundaries, seed collision/overflow, missing or linked inputs, stale and pending state, asset/plan tampering, and failed publication. The [local planning exercise](evidence/stage-04-planning-20260921.json) and [package verification](evidence/stage-04-verification-20260921.json) retain results.

Planning does not qualify a real LoRA, its compatibility assertions, the server's loader-name mapping, custom-node input bounds, output quality, or GPU concurrency. It creates no seed reservation or rotation history: identical requests repeat identical plans, and separate plans can overlap seeds. The separate [execution stage](batch-execution.md) now qualifies stock node/path bindings and implements sequential submission, ownership, workspace seed reservations, and uncertain-outcome resume. Its real acceptance is limited to the neutral workflow. Parallel workers remain behind measured GPU-capacity and isolation gates.
