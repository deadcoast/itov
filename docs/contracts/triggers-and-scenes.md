# Trigger and scene validation

ITOV 0.11.0 implements Stage 10 as offline, deterministic diagnostics over the current catalog and replayed batch plans. It never changes prompts, activation tokens, catalog entries, seeds or execution policy. A passing report is not an execution receipt, trained-trigger qualification or media-quality score.

## Commands

```powershell
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
uv run --locked itov trigger lint examples/trigger.rules.json --json
uv run --locked itov inference plan examples/sdxl-lcm.inference.json --save --json
# Use the saved plan path printed above. Planning does not submit jobs.
uv run --locked itov trigger lint examples/trigger.rules.json --plan PATH_TO_PLAN --save --json
uv run --locked itov scene lint examples/neutral-image.scene.json --plan PATH_TO_PLAN --save --json
```

These examples require the previously imported SDXL/LCM catalog and pinned assets. For the existing audio baseline, use `audio plan examples/stable-audio.audio.json --save --json` and `examples/neutral-audio.scene.json`. Scene constraints bind exact preset IDs; a different specification needs explicitly reviewed constraints for its new preset. Both lint commands accept `--config`; neither needs a running ComfyUI server.

Exit codes: `0` passes, `1` reports constraint/collision errors (or warnings with trigger `--strict`), and `2` refuses invalid, unsupported, missing, stale or changed input. Without `--save`, no report is published. `--save` writes an immutable, hash-addressed JSON report below `workspace/state/lint/triggers/` or `scene/`. Existing different bytes are preserved and refused. Failed diagnostics can also be saved; an invalid input does not produce a passing/partial report.

## Trigger rules and vocabularies

The exact version-one rule fields are `version: 1`, `origin`, `near_distance` (integer 0, 1 or 2), and `vocabularies`. Each vocabulary reference has exactly `path` and `sha256`. Paths are portable relative paths beneath the rule file's directory; redirects, duplicate references and hash mismatches fail closed. See [rules](../../examples/trigger.rules.json).

Every origin has exactly two nonempty strings, `title` and `reference`. References document the supplied authority; the linter does not fetch or authenticate them. Each vocabulary file has exactly `version: 1`, `origin`, `base_models` (nonempty unique catalog-style IDs), `kind` (`base` or `reserved`), and `terms` (unique after normalization). [Base](../../examples/trigger-base-vocab.json) and [reserved](../../examples/trigger-reserved-vocab.json) examples are **operator demonstration policy**, not official tokenizer vocabularies. No model vocabulary is guessed or downloaded. An empty rule vocabulary list is allowed and explicitly reports uncovered models for declared triggers.

Only the existing catalog's `trigger_words` fields declare activation text. Active, candidate and flagged LoRAs are reviewed; quarantined entries are explicitly excluded. No arbitrary sidecar parsing occurs. Catalog-only review compares declarations across LoRAs sharing a base model and binds catalog asset references without reading weights. Plan review replays the whole saved plan against the current clean catalog and its planned asset bytes, then compares only the LoRAs actually selected together in each job, scoped to that preset's base model.

Plan replay verifies the catalog's workflow and eligible LoRA files. Embedded checkpoint, VAE and text-encoder pins remain graph references: lint does not reread or qualify those runtime model files. The existing execution qualification path remains responsible for runtime dependencies.

| Diagnostic | Severity | Meaning |
| --- | --- | --- |
| `C0_DUPLICATE` | Error | Two declarations on the same LoRA normalize identically. |
| `C1_EXACT` | Error | Different applicable LoRAs declare the same normalized text. |
| `C2_NEAR` | Warning | Different applicable LoRAs have edit distance within `near_distance`; zero disables this check. |
| `C3_BASE` | Warning | A declaration exactly matches a supplied applicable base vocabulary term. |
| `C4_RESERVED` | Error | A declaration exactly matches a supplied applicable reserved term, including a single holder. |
| `VOCABULARY_UNCOVERED` | Warning | No supplied vocabulary covers one or more base models for this declaration. |

Coverage means supplied policy coverage, not comprehensive tokenizer coverage. LoRAs without declared triggers are listed separately; passing an empty declaration set is not evidence of activation. Edit distance is a lexical heuristic, not tokenization or semantic similarity. Severity counts are diagnostics, not a numerical quality score.

Each report index preserves the original trigger, declaration position, LoRA ID/status, model scope and asset reference. Its `alias` is `LoRA_ID::normalized_trigger`, with `alias_use: report_label_only`. These labels identify rows and **never replace learned activation tokens or clear a collision**. A collision still requires review of the selected stack or independently justified catalog metadata. There is no automatic alias rewrite or promotion.

## Scene constraint contract

The exact top-level fields are `version: 1`, `id`, `origin`, and `presets`. The constraints must cover exactly the presets selected by the plan. Every preset rule requires all these fields; examples are [neutral image](../../examples/neutral-image.scene.json) and [neutral audio](../../examples/neutral-audio.scene.json).

| Field | Contract |
| --- | --- |
| `preset`, `sampler` | Exact catalog preset ID and workflow node ID. The graph must have exactly one `KSampler`, at that node. |
| `required_positive`, `forbidden_positive` | Literal phrases independently checked in the sampler's positive text. |
| `required_negative`, `forbidden_negative` | Literal phrases independently checked in the sampler's negative text. |
| `required_loras`, `forbidden_loras` | Unique known catalog IDs, checked against the actual selected stack. An ID cannot be both. |
| `max_loras` | Integer 0–8, at least the number of required LoRAs. |
| `max_words` | Exactly `positive` and `negative`, integer whitespace-separated word limits 0–4096. |
| `triggers` | Explicit `all_declared` or `none`. `all_declared` requires every selected LoRA declaration in positive text and forbids it in negative text; this is a chosen conjunction policy, not an assumption that all models need all tokens. |

Prompt resolution follows the sampler's actual links through stock `CLIPTextEncode` output 0, optionally through `ConditioningStableAudio` outputs 0 (positive) and 1 (negative). Text must be literal and bounded; dynamic text, other conditioning nodes, ambiguous samplers, cycles, invalid outputs, or one text encoder used for both roles are refused. Other graphs need a separately defined and tested adapter. Successful reports bind each expanded workflow hash, text node/input/hash/length, selected LoRAs and trigger policy.

All scene findings are errors: `EMPTY_POSITIVE`, `REQUIRED_PHRASE_MISSING`, `FORBIDDEN_PHRASE_PRESENT`, `WORD_LIMIT`, `REQUIRED_LORA_MISSING`, `FORBIDDEN_LORA_PRESENT`, `LORA_COUNT`, `TRIGGER_MISSING_POSITIVE`, and `TRIGGER_IN_NEGATIVE`. Required phrases containing a forbidden phrase in the same role are contradictory input and refused. Run trigger collision lint separately; scene presence checks do not establish collision freedom.

## Normalization, determinism and bounds

Text comparison applies Unicode case folding, NFC normalization and whitespace collapse. Phrase matches are literal, with boundaries at alphanumeric, underscore and combining-mark characters when the term begins/ends with such a character. There is no regex, stemming, prompt-weight parsing, semantic negation, object counting or cross-role concatenation. For example, `hand` does not match `handmade`; `no hand` still contains `hand` and fails a forbidden-positive rule. Put exclusions in explicitly checked negative text when appropriate.

Reports contain exact source-document hashes and byte lengths, vocabulary paths/hashes/origins, catalog and ledger heads, plan ID when used, policy inputs, sorted findings and the Unicode table version. Their IDs hash canonical integer-only JSON without timestamps or machine-specific absolute paths. The Unicode version is part of the normalizer identity: Python versions with different tables can produce different report IDs. Identical inputs under the same normalizer produce identical bytes. `saved_path` is a CLI convenience field, excluded from the stored document and ID.

The clean catalog head is rechecked under its OS lock before returning or publishing. Reports remain point-in-time diagnostics; future catalog/plan/input changes require a fresh lint. Source origin text and hashes establish which bytes were reviewed, not historical authenticity. There is no execution integration or automatic policy enforcement at submission time.

Bounds are explicit: 32 MiB per JSON document/report; 256 catalog LoRAs and 512 non-quarantined trigger declarations (also for plan lint); 128 characters per term; 16 vocabulary files with 5,000 terms each; 64 scene presets and 64 phrases per role/list; 32,768 characters per resolved prompt; 10,000 findings per report. Unknown fields, duplicate JSON keys, invalid types, ASCII controls below U+0020 and normalized duplicate vocabulary/constraint terms are rejected. Prompt text alone permits CR/LF/tab separators. Resource bounds fail rather than truncate diagnostics.

## Reconciliation and evidence

The original design sources remain unchanged. [Part 12](../design_spec/12_trigger_word_linter.md) contains incompatible `run()` implementations, schemas, collision classes and exit codes; incomplete helpers; silent skips; and a reserved-pair blocker whose required second holder is absent from the detector. Its suffix aliases do not prove renamed tokens activate trained weights. This implementation uses one explicit schema and diagnostic taxonomy, fails on declared input errors, and retains activation text.

[Part 12.2](../design_spec/12.2_balancing_constraints.md) describes phrase-bank balancing across phoneme, length, register and content axes. Its conflicting axis names and underspecified count/for-each grammar are not an executable scene contract. Corpus solving, scoring, relaxation and scheduling remain Stage 12. The [template overview](../design_spec/scene_templates/templates-overview.md) provides prose/bracket templates and legacy setup claims, not a versioned executable constraint schema. Stage 10 uses explicit neutral constraints on actual saved plans; it does not execute embedded source snippets.

[Local offline evidence](../evidence/stage-10-offline-20260921.json) records catalog review, two image and two audio planned jobs, repeatable immutable reports, and an intentionally rejected image constraint set. Runtime HTTP was forbidden during this exercise; catalog/workflow bytes, prior job records and the execution database remained unchanged. The real LCM catalog declares no triggers, so synthetic metadata tests carry collision coverage. [Source/package verification](../evidence/stage-10-verification-20260921.json) records the separate automated gate and its scope.

The original neutral image prompt passes these lexical rules even though Stage 6 retained rendered count/shape defects. Scene lint therefore does not close those defects or qualify media quality. Real trained-trigger activation, authoritative vocabulary coverage, independent quality evaluation and any execution guard remain separate tasks in [TODO](../../TODO.md).
