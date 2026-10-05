# Curated data and evidence-backed quality review

A-05 factors cases and review decisions into immutable internal records and reuses one validated snapshot when building a packet. It retains the existing review versions and policy. The [record/freshness contract](../contracts/assessment-records.md) documents compatibility, measured cost and final input checks.

Version 0.13.0 introduced prototype curation and comparison records. Version 0.13.1 removes the mandatory independent-human gate at the user's instruction and supports explicit assistant reviews. The [source audit](../reports/2026-09-22/development-audit-20260922.md) and [new TODO](../../TODO.md) supersede earlier stage-completion claims. The data/training/evaluation methods remain partial. The prior synthetic candidate remains smoke-purpose evidence.

## Curated pilot

The later [B-02 review/freeze](dataset-review.md) retains all original works and pair observations but selects **two training works and one validation work** for subsequent experiments. The eight-work description below is the original pilot, not the current selected training corpus.

The original v2 pilot contains eight color oil still lifes from the Met Open Access collection: six training works and two validation works. Every retained object record declares `isPublicDomain: true`. The [Met's policy](https://www.metmuseum.org/hubs/open-access) describes CC0 use of its public-domain artwork images and collection data. The source records, JPEGs, captions, prepared images and policy observation are individually hashed. This is verification of supplied provider declarations and bytes, not independent source authentication.

The [current API](https://metmuseum.github.io/) provides paginated `/v1.1/search`; object metadata still uses `/v1/objects/{id}`. Discovery encountered HTTP 403 and 404 responses, and a direct policy download returned 429. Acquisition stopped; no repeated download attempts or larger-collection claim followed. A short policy observation from the web reader is retained explicitly as an excerpt/summary, not a full HTML capture.

| Split | Met object IDs | Scope |
| --- | --- | --- |
| Train | 11939, 16590, 16592, 436305, 488147, 898372 | Fruit, vessels and flowers, with varied oil-painting styles |
| Validation | 11737, 436450 | Separate works and artists: cake/grapes and pears/bottle |

The assistant inspected the source contact sheet and wrote descriptive captions using `itovstill`. A monochrome reproduction (10895), fish, vanitas and trompe-l'oeil subjects were excluded. The small sample and varied painting styles limit what the trial can establish. These are local artist/work splits; overlap with SDXL's pretraining data is unknown.

The historical pilot used a fixed eight-ID preparation helper. B-01 replaces that implementation with [transactional dataset import](dataset-import.md) and a [declared museum manifest](../../examples/met-still-life.import.json). The helper now forwards manifest arguments to the public CLI. The transform retains full composition: EXIF orientation, RGB, fit within 512×512 with Lanczos, centered ivory `(245,240,225)` padding. New imports fully decode sources and outputs, preserve per-image transform receipts and failed attempts, and publish a verified complete bundle. Historical version-one snapshots retain their byte/header validation and original IDs. Padding remains a possible learned artifact; preparation does not perform perceptual deduplication or establish visual suitability.

```powershell
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
uv run --locked itov dataset curate workspace/training/data/met-still-life-v1/curation.json --save
uv run --locked itov training plan examples/sdxl-still-life.training.json --save
```

The v1 curation declaration requires exactly `version`, `dataset`, `curator`, `selection_policy`, `rights`, `transform`, and `works`. Each work binds a sample, Met object ID, metadata reference, provider image URL, selection note and caption note. Repeated artwork IDs/URLs, missing samples, changed bytes, missing public-domain declarations, mismatched work groups and artists crossing splits are refused. Artist identity uses the provider's display name, not a universal authority identifier.

B-02 adds [stable identifier, duplicate and caption review](dataset-review.md) without rewriting that historical v1 contract. New v2 curation adds a pinned `selection` freeze and requires the exact reviewed import declaration/provenance. The review records all 28 pilot pairs and retains the mixed-style confound, qualified Gauguin attribution and caption omissions. Its narrower selection has Roesen/Ream in training and Peale in validation; the tiny three-work pool does not establish improved learning. Historical eight-work training and rejected model results remain unchanged.

## Evaluation fixed before training

The v2 training specification adds `qualification: {curation, suite}`, both hashed file references. The plan binds those declarations and five trainer/qualification source modules. Controller revalidation checks them before and after execution; changing curation, captions or cases requires a new plan. Legacy v1 training evidence can still be inspected, but its review contract cannot authorize non-smoke promotion.

[The suite](../../examples/still-life.quality.json) fixes two prompts, two seeds per prompt, and explicit expectations before training. The held-out case asks for two yellow pears beside one blue vase; the regression case asks for a photographic red cube and white cone. Prompts omit the trigger, differ lexically from training captions, and include both held-out and regression categories. This is not proof of semantic or foundation-training independence.

Each case/seed has all four conditions: base without trigger, base with trigger, adapter without trigger, adapter with trigger. The optional worker reloads the serialized adapter and renders all 16 comparisons at 512px, 20 steps and CFG 7 using the pinned Diffusers pipeline. Existing paired held-out losses/previews remain additional diagnostics. No score derived from loss or pixel differences accepts model quality. These Diffusers comparisons do not substitute for stock ComfyUI export testing.

## Evidence-backed review and promotion

```powershell
uv run --locked itov evaluation packet workspace/state/training/plans/PLAN_ID.json --save
```

After a successful owned v2 training run, this command revalidates the dataset, curation, complete ordered comparison matrix, file hashes, assessment and converted candidate. It publishes an immutable JSON packet, a Markdown image report and a pending `.review.json` template under `workspace/state/training/reviews/`. Repeating the command preserves reviewer edits. Conditions are openly labeled; this is not a blinded experiment.

Current version-three reviews support `reviewer_kind: "assistant"` or `"human"` and require a nonempty `method` and `limitations`. They retain the five global evidence-backed criteria (`activation`, `prompt_adherence`, `image_quality`, `regression`, `runtime_compatibility`), packet reference and four criterion verdicts plus notes for **every case and seed**. Runtime compatibility needs separately hashed actual-runtime evidence. The assistant can also be the curator; human participation or a separate identity is not required. Legacy v2 attestations retain their original semantics when read; use v3 for new reviews. These contracts check declarations and consistency, not identity or the correctness of subjective judgments.

The pending template is deliberately invalid for promotion. Missing, duplicate, stale, failed or unreviewed cases cannot pass. The assistant conducts testing/inspection and records its actual findings without claiming to be human. A training review can support the legacy `promotion prepare` preview, but since C-05 `promotion apply` refuses activation. Activation requires complete deployed evaluation and a fresh [candidate lifecycle](../evaluation/candidate-lifecycle.md) preview/apply; training-only approval is insufficient. Rejections and pending reviews leave the catalog unchanged. Removing the human-only restriction does not replace the engineering work needed for repeatable quality evaluation.

## Recorded pilot evidence

The [corrected owned run](../evidence/stage-11b-training-attempt-03-20260922.json) completed 128 rank-four optimizer steps in 144.485 worker seconds, changing 1,120 finite tensors across 5,806,080 adapter parameters. It reloaded the serialized weights and produced all 16 matrix images plus four held-out previews. Held-out losses decreased from 0.011254031 to 0.010980256 and from 0.197922140 to 0.186335206. Torch allocator peaks were 8,341,601,280 allocated and 9,588,178,944 reserved bytes; these are one-run observations, not capacity guarantees.

The [stock ComfyUI pair](../evidence/stage-11b-comfy-export-20260922.json) completed with different fully decoded pixels. These were two sequential jobs on the existing server, not a new managed-parallel qualification. Prior server history, all 146 checked prior files and the main catalog were preserved; the training worker exited and the shared device lease returned idle. The initial memory refusal and invalid weight-reference result remain retained separately.

The [review packet](../evidence/stage-11b-review/README.md) shows every case/seed and the runtime pair. [Assistant observations](../evidence/stage-11b-assistant-observations-20260922.json) identify a failing regression seed with divided panels/extra objects and a ComfyUI candidate with one pear instead of two. Strong adapter changes without the token also leave trigger specificity unresolved. The [v3 assistant reassessment](../evidence/review-policy-reassessment-20260922.json) records **reject**, with all case/seed findings, preserved model bytes and unchanged catalog.

[Version 0.13.0 source/package verification](../evidence/stage-11b-verification-20260922.json) passed 872 tests on Python 3.13.9 and 872 against the installed Python 3.11.14 wheel, lint/format/build, exact README packaging and 42-module byte parity. At that checkpoint, the five training-bound source modules matched the worker/qualification implementation. Subsequent policy changes produce new assessment/packet metadata; they do not rewrite or claim to repeat the historical live run. Tests establish specified software behavior, not general model quality.

These are prototype checks, not completion of Stage 11 or the application. Work proceeds autonomously through the new TODO, starting with training result validation and integrated runtime evaluation. The candidate is rejected for observed/unresolved quality issues; the user is no longer the testing dependency. Assessment and packet schema/metadata revisions create new content IDs without rewriting historical receipts or retraining weights.

On 2026-09-23, A-02 replaced the helper-dependent runtime route with [supported deployed evaluation commands](../evaluation/deployed-evaluation.md). The installed package completed the full 16-image ComfyUI matrix, including pause/resume observation without duplicate submissions. [Inspection of all deployed images](../reports/2026-09-23/deployed-evaluation-review-20260923.md) still rejects the candidate: missing pears/vase and merged geometry remain. This adds complete coverage of the existing small suite; it does not broaden that suite, establish sampler parity or close the quality work.
