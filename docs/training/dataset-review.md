# Dataset duplicate, identity and caption review (B-02)

The supported sequence is `dataset inspect`, an explicit assistant/operator review, `dataset freeze`, `dataset review-verify`, and [B-01 import](dataset-import.md). For Met training, `dataset curate --freeze` binds the resulting import to the reviewed selection. These commands freeze data decisions; they do not accept model quality. The historical eight-work pilot, its training results and the rejected candidate remain unchanged.

## Inspect a declared pool

Use a hash-pinned prepared dataset (legacy v1 or committed v2), a declared visual target, a trigger and retained exclusions. Met inspection also requires its **base version-one curation declaration**. Local inputs instead require one identity declaration per sample. Inspection does not discover/download data, change captions or decide which images to keep.

```powershell
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
uv sync --inexact --locked
$cfg = 'workspace/itov.toml'
$pool = uv run --inexact --locked itov dataset inspect examples/met-still-life.inspection.json --config $cfg --save --json | ConvertFrom-Json
$pool._cli
$pool.artifacts
```

Exit **1 / incomplete** is expected for a successful inspection because its review is pending. `--save` writes an immutable inspection JSON, a `.report-v1.md` report with source-image links/captions/all pair distances, and a `.review.json` template. Repeating the command preserves edits to that template. A fresh checkout must provision the declared inputs and perform its own inspection/review; the example review is bound to this workspace's exact evidence. `--image-python PATH` selects a separately provisioned Python with Pillow 12.3.0. The checkout dev environment and wheel's `dataset` extra provide that dependency. Verification/freezing use retained evidence and import no Pillow or ML packages in the core process.

The inspection specification has exactly these fields:

| Field | Required value |
| --- | --- |
| `version` | Integer `1` |
| `dataset` | Workspace-relative `path` and lowercase file `sha256` for a prepared snapshot |
| `curation` | Met base curation file reference, or `null` for local inputs |
| `target` | `id`, `description`, nonempty `include` and `exclude` arrays of criteria |
| `trigger` | Literal identifier required once at the start of each selected caption |
| `local_identities` | Empty for Met; otherwise every sample with `sample`, `work` aliases, `creators` aliases and explanatory `notes` |
| `exclusions` | Retained external candidates: `id`, optional pinned `source`/`metadata`, `reason`, `limitations`; at least one file reference required |

The [museum example](../../examples/met-still-life.inspection.json) is complete. Local identity entries have this shape:

```json
{
  "sample": "photo-one",
  "work": ["local:my-collection:work-001"],
  "creators": ["local:my-collection:creator-001"],
  "notes": "Operator-maintained collection identity; attribution is not independently authenticated."
}
```

Identifiers are stable, explicitly namespaced assertions. Supported forms are `local:NAMESPACE:ID`, `met:work:NUMBER`, `met:creator:NUMBER`, `wikidata:QNUMBER` and `ulan:NUMBER`. Alias lists are bounded to 32 identifiers. Do not invent separate creator identifiers to make a split appear independent. Empty work/creator lists remain unresolved and block selection. Local notes must explain the basis and limits of identity assertions. Met identities derive from the retained metadata; local overrides cannot replace them.

Met object IDs and optional object Wikidata IDs identify works. Constituent IDs and normalized Wikidata/ULAN references identify associated creators. Connected identifier overlaps form conservative groups, including transitive aliases and multiple associated creators. Groups are computed over the entire inspected pool before exclusions, so removing an alias bridge cannot hide a connection. Unknown roles, missing identifiers, unsupported identifier URLs and qualified attribution remain visible. Shared display names with disjoint identifiers create an ambiguity; a name is never promoted to a universal identifier. The [Met API](https://metmuseum.github.io/) documents its object, constituent and attribution fields. These provider associations do not authenticate the actual maker.

## Duplicate and caption observations

An isolated worker fully decodes each source JPEG/PNG, applies EXIF orientation and converts to RGB. Fingerprints use the source before prepared-image padding. Input limits match the B-01 decoder: RGB/L, one frame, at most 32 million pixels/32 MiB, with truncation and decompression warnings refused. Pillow opening is lazy; the worker verifies, reopens and explicitly loads pixels ([Pillow reference](https://pillow.readthedocs.io/en/stable/reference/Image.html)).

The recorded `oriented-rgb-dhash64-ahash64-v1` profile uses grayscale Lanczos resizing. dHash compares adjacent pixels of a 9×8 image (`left > right`), row-major with the first comparison in the least-significant bit. aHash uses an 8×8 image and `pixel * 64 >= sum(pixels)`, with the same bit order. Both hashes are fixed 16-digit lowercase hex strings. Every unordered pair records both Hamming distances, source-file equality, oriented RGB equality with matching dimensions, prepared-file equality, identity overlaps and the original split relationship. RGB equality is distinct from encoded-file equality.

A pair is flagged when either distance is at most 6, any exact-content check matches, work identifiers overlap, or creator-name identity is ambiguous. These thresholds were fixed before inspecting the pilot's distances. They are conservative review prompts, not an accuracy-calibrated detector. Full pair results remain available even above the threshold; reviewers can record additional pairs. Grayscale range below 16 is marked low-information. Different solid colors can collide completely, so a small distance never automatically excludes an image. Source crops, mirroring, rotation, texture and color can defeat these simple hashes. The fixture checks demonstrate selected behavior, not corpus-wide precision/recall.

Caption inspection retains exact original text/hash, normalized repeated-caption groups, missing/repeated trigger findings and creator-label mentions. It does not claim that lexical checks establish semantic correctness. The reviewer must inspect every image and proposed caption, including excluded pool samples. New captions may correct omissions or uncertain specificity; the original text remains in the inspection. Frozen selected captions must be nonempty UTF-8, at most 4096 characters, with one literal trigger token first and no creator-label conditioning or interior control characters. Exact selected line endings are preserved.

## Review and freeze

Edit the generated review, or supply a new review with its exact inspection reference. The reviewer may be `assistant` or `human`; `name`, `method` and `limitations` must describe the actual process. Human independence is not required. Every sample needs:

- `decision`: `include`, `exclude`, `unresolved` or `pending`.
- `split`: `train`, `validation` or `null`; included samples need a split.
- Exact proposed `caption`, `caption_verdict` (`accept`, `reject`, `uncertain`, `pending`) and `caption_notes`.
- `target_fit` (`match`, `mismatch`, `uncertain`, `pending`), `target_notes`, and `decision_notes`.

Every flagged pair requires a `pair_id`, `decision` (`distinct`, `duplicate`, `same_work`, `unresolved`, `pending`) and substantive `notes`. Additional unflagged pairs may be reviewed. Pair judgments apply to this exact inspection. Pending placeholders cannot authorize a freeze. An unresolved pair can remain recorded when at least one member is explicitly excluded; it cannot be used to retain both. Excluding a sample preserves its identity warnings, original caption and review.

```powershell
$review = $pool.artifacts.'review template'
# Inspect and complete the review before running freeze.
uv run --inexact --locked itov dataset freeze $review --config $cfg
$frozen = uv run --inexact --locked itov dataset freeze $review --config $cfg --save --json | ConvertFrom-Json
uv run --inexact --locked itov dataset review-verify $frozen.saved_path --config $cfg
```

Freeze refuses unresolved sample decisions, pending notes, selected identity uncertainty, selected caption/target failures, exact duplicates, repeated selected works, unresolved selected pairs and work/creator/original-group leakage across the chosen split. Both train and validation need selected samples. Different works by one creator may share a training split; a creator component cannot span train and validation. A supplied `distinct` judgment cannot waive an exact-content match or ambiguous creator identity.

Without `--save`, freeze returns a checked proposal. With `--save`, blocked decisions are retained under `state/dataset-reviews/blocked`. Accepted freezes publish `state/dataset-reviews/freezes/FREEZE_ID/` containing `freeze.json`, `import.json` and exact selected caption files. The freeze retains the original review bytes; later draft edits do not rewrite it. It binds the inspection and target, selected sources/images, original captions, new captions and chosen split. The full inspected pool and external exclusions remain pinned dependencies.

Publication builds an isolated UUID attempt, checks every expected output and freshly rehashes observed inputs, then renames the complete directory under an OS lock. Interruption leaves its attempt intact; repeat the same `freeze --save` to publish a new complete attempt. An identical committed freeze is idempotent; changed/extra/missing artifacts fail verification and are never overwritten. This is cooperative process-interruption handling on the exercised Windows filesystem, not power-loss durability or protection against hostile concurrent writers. `review-verify` requires the committed `freeze.json` location and checks the complete directory. It reconstructs the decision from retained fingerprints and pinned bytes without rerunning the decoder.

## Prepare and bind the selected dataset

```powershell
$selected = uv run --inexact --locked itov dataset import $frozen.artifacts.'import declaration' --source-root workspace --config $cfg --json | ConvertFrom-Json
uv run --inexact --locked itov dataset verify $selected.artifacts.prepared --config $cfg
$curated = uv run --inexact --locked itov dataset curate $selected.artifacts.curation --freeze $frozen.saved_path --config $cfg --save --json | ConvertFrom-Json
$curated.artifacts
Get-FileHash -Algorithm SHA256 $selected.artifacts.prepared
Get-FileHash -Algorithm SHA256 $curated.saved_path
```

Use the configured workspace root for `--source-root`; the generated declaration references pinned sources/provenance there. B-01 creates a new dataset with the selected captions and split. The historical dataset is not modified. For local data this completes the data workflow; the existing curated training qualification still supports the selected Met provider only.

For Met, `curate --freeze` writes a **version-two curation declaration** with the existing provenance fields plus `selection`, a pinned freeze reference. Verification requires the imported operation's exact declaration bytes to match the freeze's generated `import.json`, and all base curation fields to match the committed provenance. A valid but different import cannot borrow the review. Training specification v2 already accepts this curation through its qualification reference; new plans also pin the added review validators. Later changes to the frozen captions, inspection, metadata or selected import fail revalidation. Version-one curation declarations and historical result IDs keep their prior semantics.

Set the new prepared-snapshot reference as the training spec's `dataset` and the printed **curation declaration**, not its report, as `qualification.curation`. Quality cases, training configuration and execution remain separately declared. For a subsequent data review, inspect the import's base v1 `curation.json`; v2 reviewed-curation chains are refused as inspection inputs to avoid recursive evidence.

Successful freeze/verification/binding exits 0; pending inspection and blocked selection exit 1; malformed/stale inputs and publication refusals exit 2. `_cli` exposes artifact paths, causes and conditional next commands. Saved evidence never contains that presentation metadata.

## Observed pilot disposition

The [recorded review](../../examples/met-tabletop.review.json) uses the narrower target: representational tabletop oil paintings with recognizable fruit/food and vessels, naturalistically modeled volume and one continuous scene, without animal subjects. This is a bounded subject/treatment choice, not a single-artist style or a claim that all historic realism is interchangeable.

The original eight-work pilot used the same `itovstill` trigger for naturalistic tabletop arrangements, hanging grapes, angular modernist forms and a floral study. Its validation split combined Peale with the qualified Gauguin attribution. That mixes subject, composition and treatment within the conditioning target and across evaluation examples. The resulting mixed-style confound limits interpretation of the old pilot: loss or a favorable image cannot isolate what the trigger learned. No controlled experiment establishes that this mixture caused the candidate's count, panel or trigger-specificity failures.

| Work | Disposition | Caption/target finding |
| --- | --- | --- |
| 11939, Roesen | Train | Dense fruit/basket/glass display; revised caption includes baskets, melon and glassware |
| 16590, Ream | Train | Fruit, cloth, glass and tall pitcher; red grapes replace the less specific red-fruit wording |
| 11737, Peale | Validation | Cake, grapes, dried fruit and glass; held-out creator/work retained |
| 16592, Ream | Exclude | Hanging grapes, no tabletop; shared creator association with 16590 retained |
| 436305, Flegel | Exclude | Original caption omits the live bird and carcass; animal subjects are outside the refined target |
| 436450, attributed in the style of Gauguin | Exclude | Different treatment and unresolved maker attribution; associated identifiers are not autograph proof |
| 488147, Benn | Exclude | Angular forms/fractured perspective; revised review caption identifies a basket rather than a bowl |
| 898372, Bridges | Exclude | Floral study with blue/white flowers and fern leaves, no tabletop food arrangement |

The Flegel details were checked against its [Met object description](https://www.metmuseum.org/art/collection/search/436305); the [retained observation](../evidence/phase-b02-source-observations-20260923.json) is a paraphrase, not a full page archive. The broader first inspection and an unresolved-selection report remain retained. The final target was refined before any new training. External exclusions retain monochrome 10895 and four metadata-only fish/vanitas/trompe-l'oeil candidates; unavailable images are not described as visually inspected.

All 28 pilot pairs were recorded and visually judged distinct at the retained resolutions. No exact duplicate or threshold candidate was found; the minimum dHash distance was 22, and the minimum aHash distance was 14. These observations do not prove absence of alternate crops, pretraining overlap or duplicates in unavailable data. Ream's two works form one creator group; the qualified Gauguin record remains unresolved and excluded.

The freeze contains **two training works and one validation work**. It preserves original split assignments for selected works and exact revised captions. The corpus is still too small to establish a representative distribution or useful learning. Palette, historical treatment, scene density, artwork borders, signatures and fit/pad borders remain possible confounds. Removing mismatched examples does not show that the rejected model improves. B-03 training configuration and later experiments must keep these limitations visible.

[B-02 verification](../evidence/phase-b02-verification-20260923.json) separates source/installed contract tests, native interruption, retained museum review/rebuild, historical replay and remaining quality limits. No new model training, rendering, promotion or release is part of this delivery.
