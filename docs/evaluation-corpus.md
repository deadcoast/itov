# Frozen evaluation corpus and baselines

C-01 adds `corpus freeze`, `inspect`, `baseline` and `replay`, plus version-two `evaluation` specifications. A corpus is independent of a training run's original diagnostic matrix. Existing validated checkpoints can use its cases without retraining. The original version-one training suites, evaluation plans and reports retain their formats and identities.

C-02's [image checks](image-checks.md) measure completed evaluation images and compare narrow artifact screens or optional evaluators with complete reference annotations. Its [calibration](image-check-calibration-20260924.md) reuses the exposed baseline, preserves every semantic verdict and adds direct inspection of outer framing. This is evaluator calibration, not a new independent model holdout or authorization to tune training on these cases.

## Declare coverage before rendering

[The corpus example](../examples/still-life.corpus.json) contains twelve prompts, three fixed seeds per prompt, explicit expectations and seven coverage axes: counts, attributes, layout, textures, trigger specificity, strength range and unrelated-task regressions. Seven cases are new held-out target tasks; five are regression cases, including both previously inspected prompts. Their original text, expectations and two seeds remain unchanged, with a third seed added. New landscape, bicycle and bird tasks test unintended still-life/style transfer.

The specification binds a curated v2/v3/v4 training plan as its dataset and legacy-suite reference. Freezing validates that lineage, excludes exact normalized training **and validation** captions, preserves every legacy case and seed, and publishes a content-addressed corpus with a coverage manifest. An edited declaration creates a new identity; existing records are never replaced.

```powershell
uv run --inexact --locked itov corpus freeze examples/still-life.corpus.json --save --json
uv run --inexact --locked itov corpus inspect workspace/state/evaluation/corpora/CORPUS_ID.json
```

The schema supports 8–24 cases, 3–8 distinct seeds within each case, and two or three increasing positive strengths ending at 1000 milli. Seeds may repeat across different cases and intentionally repeat across conditions. Each coverage axis needs at least two cases; held-out and regression partitions each need at least two cases. The complete comparison is bounded to 768 images. These checks verify declarations and coverage, not semantic truth or statistical representativeness.

## Held-out policy

The fixed policy retains **all cases, seeds and failures**, excludes held-out cases from training and tuning, and requires declared exposure plus additional fresh holdouts if a holdout informs tuning. The method and limitations must describe how this is applied. Previously inspected legacy cases must be labeled `legacy_diagnostic` regressions. New cases are labeled `baseline_only`: inspecting their baseline is declared exposure, not a claim of a secret or untouched test set.

Use diagnostic regressions for subsequent development. Do not select training images, rewrite captions or choose hyperparameters to repair the held-out prompts. If that boundary is crossed, record contamination, keep the old corpus/results, and create an additive successor with fresh held-out cases. The current commands enforce legacy-suite retention and exact caption exclusion; they cannot detect an operator's tuning decisions or automatically prove additive retention across arbitrary future corpus specifications. Successor review must check those relationships explicitly. Near-duplicate semantics and unknown base-model pretraining exposure remain unmeasured.

## Base-model baseline and strength comparison

[The evaluation example](../examples/still-life-corpus.evaluation.json) uses version 2 with a hashed `corpus` reference and `mode: "baseline"`. Other fields bind the trained checkpoint, sampler and dimensions. The corpus's reference plan supplies data lineage; a different evaluated checkpoint must use the same dataset identity and trigger. A changed dataset needs a separately reviewed corpus identity and overlap check.

For each case/seed, baseline mode runs `base_plain` then `base_trigger`, both with `strength_milli: 0` and no LoRA node. Comparison mode runs those controls followed by `adapter_plain` and `adapter_trigger` at each frozen strength in increasing order. The example freezes 250, 500 and 1000 milli: **72 baseline images and 288 full-comparison images**. Baseline mode still binds the technically validated candidate and existing deployment lineage, but its graphs do not load or apply the candidate.

[The separate comparison example](../examples/still-life-corpus-comparison.evaluation.json) declares that full matrix with its own identity. Planning it does not submit its jobs; keep baseline observation separate from an eventual candidate decision.

```powershell
uv run --inexact --locked itov evaluation plan examples/still-life-corpus.evaluation.json --save --json
uv run --inexact --locked itov evaluation run workspace/state/evaluation/plans/PLAN_ID.json --wait-timeout 300 --json
uv run --inexact --locked itov evaluation status workspace/state/evaluation/plans/PLAN_ID.json
uv run --inexact --locked itov evaluation resume workspace/state/evaluation/plans/PLAN_ID.json --json
uv run --inexact --locked itov evaluation replay workspace/state/evaluation/plans/PLAN_ID.json --save --json
```

These use the existing [owned runtime protocol](deployed-evaluation.md): shared cooperative GPU admission, explicit runtime/model hashes, graph bindings, durable request identities, complete PNG decoding, uncertain-submission recovery and no blind POST retry. A missing or changed corpus blocks new submission. Each strength has a distinct job/index and exact graph strength. A corpus comparison remains a technical matrix; C-02/C-03 supply calibrated checks and deployed candidate assessment.

Base-trigger differences show how the base model responds to the token. They cannot establish learned activation. Compare adapter effects with both corresponding base controls, preserving identities, counts, composition, material and unrelated-task behavior at every strength. No monotonic improvement with decreasing strength is assumed. All strengths and seeds remain in subsequent reports, including unfavorable ones.

## Record observations and replay

```powershell
uv run --inexact --locked itov corpus baseline workspace/state/evaluation/corpora/CORPUS_ID.json --evaluation workspace/state/evaluation/plans/PLAN_ID.json --save --json
# Inspect the saved Markdown images and fill the sibling .review.json.
uv run --inexact --locked itov corpus baseline workspace/state/evaluation/corpora/CORPUS_ID.json --evaluation workspace/state/evaluation/plans/PLAN_ID.json --review workspace/state/evaluation/baselines/PENDING_ID.review.json --save --json
uv run --inexact --locked itov corpus replay workspace/state/evaluation/baselines/OBSERVED_ID.json --json
```

The first call saves a pending baseline, Markdown image report and review template. It requires a complete, decoded baseline matrix from the exact corpus. Every image then needs ordered case/seed/role/index bindings, `pass`, `fail` or `uncertain` for prompt adherence and image quality, and nonempty observation notes. Reviewer identity/kind, method, limitations and the exact evaluation report ID are mandatory. Regenerating a pending packet preserves an edited template.

The observed baseline embeds the review and reports image-level outcomes: any failed criterion makes that image fail; otherwise uncertainty dominates; otherwise it passes. These counts are descriptive, never a model selection score. Pending returns exit 1; successfully recorded observations return 0 even when images fail, because the operation records a baseline and cannot accept a candidate. Invalid/incomplete/stale evidence returns 2. `promotion_eligible` is always false.

Replay revalidates the corpus, model/runtime files, owned image artifacts, complete decoding and review coverage, then recomputes the sealed baseline. It requires neither network access nor the optional ML environment. Operation-local freshness checks precede publication. Hashes are consistency checks, not signatures or filesystem-wide transactions; earlier records cannot prove that an operator never tuned externally.

## Evidence and limits

The [C-01 baseline review](evaluation-corpus-baseline-20260924.md) records actual base-model images and observations before further training or tuning. The [verification receipt](evidence/phase-c01-verification-20260924.json) distinguishes protocol tests, installed commands, runtime execution and direct inspection. The [C-03 deployed review](deployed-candidate-review-20260924.md) now completes all 288 comparison conditions and rejects the candidate after direct inspection. Its 72 base controls exactly match the prior decoded pixels, while the original baseline judgments remain unchanged. B-05's numerical variation and rejected models remain unresolved; this baseline does not reverse those decisions or establish Diffusers/ComfyUI sampler parity.
