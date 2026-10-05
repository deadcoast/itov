# C-04 failure and repetition investigation

The declared model investigation is complete: six training attempts, 18 optimizer
updates, 108 training images and 64 deployed diagnostic images. Every image was
inspected. **Both training endpoints and all six repetitions are rejected**;
the fixed deployed candidate also remains rejected. Four of six numerical pairs
exceed the preregistered tolerance; the other two pairs reproduce exactly.
Neither strength nor resolution change resolves the required cases across seeds.
Trigger-specific painting activation and the cause of numerical variation remain
unestablished. Final source/installed replay verification passed. **C-04 is delivered within this bounded scope; C-05 is next.**

This delivers a bounded investigation, not an accepted model or a completed
application. The existing [C-03 rejection](deployed-candidate-review-20260924.md)
is preserved. No candidate was activated or promoted.

The [complete image index](c04-image-index-20260924.md) exposes all 29 inspection
sheets, including every repetition and unfavorable seed.

## Declared investigation

Experiment `1192ef70ad6324a7c7ef6efef16187f28f4e02cfea2622049baec511d4d0cbc1`
declares two and four optimizer updates, each repeated three times. It retains
B-05's seed 9052401, rank 8, learning rate 0.0001, two-sample effective batches,
constant schedule, frozen training/validation works and legacy diagnostic suite.
The budget is six attempts, 18 updates, 5,400 worker seconds and 108 images.
Absolute tolerances are 1e-6 for adapter weights, both optimizer moments and
recorded losses; exact equality remains a separate result. No new retry or endpoint
is authorized by an unfavorable result.

The [v2 example](../examples/sdxl-tabletop-numerical.experiment.json) identifies this
local declaration. Its workspace references are not portable inputs. See the
[numerical contract](experiment-variance.md) for supported commands and limits.

A separate fixed-candidate study declares 512px and 1024px generation at strengths
0.25 and 1.0. Each setting retains both legacy prompts, both original seeds and
all four base/plain, base/trigger, adapter/plain and adapter/trigger conditions:
64 images in total. The candidate is B-05 long-r1, selected before seeing new
repetition results. Sampler settings remain 20 steps, CFG 7, DPM++ 2M/Karras.
Resolution is a diagnostic hypothesis: the local UNet configuration declares
sample size 128, while existing generation uses 64-by-64 latent images at 512px.
The completed comparison below retains the adverse outcomes. Changing resolution
also changes the latent shape/noise field; an identical integer seed does not
provide identical noise tensors. This does not isolate SDXL microconditioning.

All development uses the two exposed legacy regression cases. The older v1
training suite calls the pears case a holdout; C-01 explicitly preserves it as an
exposed diagnostic. None of the seven newer held-out prompts is used for tuning,
selection, training or this study. No border detector was revised or used as a
filter; C-02's missed borders remain unqualified evidence.

## Completed data and conditioning audit

The exact frozen dataset remains two training works (Met 11939 and 16590) and one
validation work (Met 11737). Both training captions describe fruit still lifes
with multiple objects. They contain the trigger and painting vocabulary; there
are no untriggered preservation examples in this training selection. This is a
property of the declared input, not proof of why a particular generated object
is missing.

Direct inspection compared all three source images with their prepared versions.
The artwork's outer edges remain visible, and cream padding fills the square
canvas above/below the image. The abundant fruit work also retains its dark outer
area and clipped corners. These provide a possible framing confound to investigate;
they do not establish causation. Base-model count/panel failures already existed
without the adapter, so these training inputs cannot explain all baseline defects.

![All three source and prepared images](evidence/phase-c04-data-source-prepared.png)

Both local CLIP tokenizers produce identical token IDs for the audited texts.
Captions use 31, 35 and 37 tokens; plain diagnostic prompts use 28 and triggered
prompts use 31. None exceeds the 77-token limit. `itovstill` is encoded as existing
IDs `[529, 6420, 1170]` (`it`, `ov`, `still</w>`). The worker freezes both text
encoders and trains only UNet LoRA parameters; it does not create a new token
embedding. The adapter remains applied in both adapter conditions. The token is
conditioning, not an execution gate. These checks rule out truncation of these
specific inputs, while leaving learned style specificity unresolved.

## Completed numerical implementation cross-check

The dependency-free comparator was run on the retained B-05 checkpoint bytes and
matched its earlier CPU Torch/float64 maxima exactly:

| Endpoint | Weight maximum absolute difference | First moment | Second moment |
| --- | ---: | ---: | ---: |
| Two updates | 0.0003590876003727317 | 0.0000010716939868871123 | 0.000000000012714745922792758 |
| Four updates | 0.000237340216699522 | 0.000006343547283904627 | 0.00000000007006994984237735 |

Sample/noise/rate order, update position, runtime, precision and saved RNG match
within both historical pairs. Exact numerical reproduction still fails. This
cross-check validates the new implementation against real files; applying C-04's
1e-6 threshold to B-05 is retrospective and does not rewrite B-05's protocol.

The backend records deterministic algorithms and cuDNN determinism as disabled.
That leaves numerical nondeterminism possible; this investigation has not isolated
a particular kernel or reduction as the cause. The new repetition ranges below
were measured before interpreting the duration comparison.

## New repetition results

All six members completed as `artifacts_validated`, with no failed training
attempt or extra retry. The 24 GiB available host-commit admission floor remained
unchanged. Worker-reported elapsed time totals 306.398 seconds, excluding
provisioning, startup and controller validation; the declared ceiling was 5,400
seconds. Every pair has matching recorded runtime, precision, position,
sample/noise/rate order and saved Python/NumPy/Torch RNG controls.

| Endpoint / pair | Weight max absolute difference | First moment | Second moment | Update loss difference | Validation loss difference | Result |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Two updates, r1/r2 and r1/r3 | 0.00012125812645535916 | 0.0000002384185791015625 | 1.0488832025146166e-12 | 0 | 0.000047043 | Tolerance and exact failure |
| Two updates, r2/r3 | 0 | 0 | 0 | 0 | 0 | Exact and tolerance pass |
| Four updates, r1/r2 and r1/r3 | 0.00006683501123916358 | 0.0000014045835996512324 | 1.1627365736899264e-11 | 0.000006279 | 0.000005886 | Tolerance and exact failure |
| Four updates, r2/r3 | 0 | 0 | 0 | 0 | 0 | Exact and tolerance pass |

The threshold is **0.000001 absolute** for each group and recorded loss. Loss
differences use the worker's recorded billionth precision; tensor differences
are stored as exact hexadecimal strings. Each r1 comparison matches 8/16
diagnostic image files (the base controls); r2/r3 matches all 16 at each endpoint.
The exact matches do not erase the four failed pairs. No threshold was relaxed.
Matching recorded controls does not prove that all intermediate GPU tensor bytes
matched. A kernel, warm-up effect or other numerical cause was not isolated.

Held-out loss starts at 0.203395754 in all six runs. The two-update endpoints end
at 0.202658519–0.202705562; four updates end at 0.201980233–0.201986119. The
four-update range is lower than the two-update range, beyond the observed
within-endpoint spread. This is a denoising-loss observation on one validation
work, **not visual improvement or checkpoint acceptance**.

## Complete training review

The assistant inspected all 96 diagnostic images at their native 512px tile size
and all 12 validation previews. Each of 24 member/case/seed reviews records all
four criteria and observations. All 24 adherence judgments fail and all 24
activation judgments are uncertain. Image coherence is considered separately:
the unframed second geometry seed passes image quality even though its objects
are wrong. The sealed decision rejects all six members and both endpoints.

| Case / seed | Base conditions | Two updates, all repetitions | Four updates, all repetitions |
| --- | --- | --- | --- |
| Pears / 11760922 | One pear and one blue vase; outlined graphic frame | One pear remains; ring/shadow details vary | One pear remains; adapter/plain adds a bent or banded foreground plane |
| Pears / 11760923 | Grid/reflective ground; trigger puts fruit on stems above the vase | Wrong layout persists; plain vase changes color/shape without restoring two pears | Both adapter roles put fruit above changed vases; no plain wooden tabletop |
| Geometry / 11860922 | Divided collage of cones, spheres or jug/folded forms | Adds cap/ornament in a lower panel; no requested cube/cone scene | Adds folded sheet and cup forms; divided panels persist |
| Geometry / 11860923 | Red pyramid with waffle/ice-cream-like cone | Triggered adapter substitutes a crumpled/fluted ball | Both adapter roles substitute textured tree/brush forms; trigger often adds a stick |

Repetition one's details differ from the matching r2/r3 pair, including ornament,
vase and branch geometry. The case failures survive all repetitions. Longer
training changes content, including without the trigger, but provides no robust
case pass. All validation previews retain repeated/cropped plate panels; the
longer endpoint's rounder fruit and new vessels do not resolve that composition.

Representative complete sheets: [short-r1 geometry](evidence/phase-c04-images/training-short-r1-paper-geometry.png),
[short-r2 geometry](evidence/phase-c04-images/training-short-r2-paper-geometry.png),
[long-r1 geometry](evidence/phase-c04-images/training-long-r1-paper-geometry.png),
[long-r2 geometry](evidence/phase-c04-images/training-long-r2-paper-geometry.png),
[all validation previews](evidence/phase-c04-images/training-validation-previews.png).
The verification receipt binds every sheet and every original image, including r3.

## Deployed resolution and strength comparison

All 64 declared images completed and decoded at their requested 512px or 1024px
dimensions. The assistant inspected all 16 four-role sheets. The 1024px sheets
use 768px Lanczos previews; original triggered geometry images were additionally
inspected at full resolution to resolve red-object shape ambiguity. Original
PNGs remain intact. The fixed candidate is B-05 long-r1; no new checkpoint was
selected after observing the repetitions.

| Case / seed | 512px, strengths 0.25 and 1.0 | 1024px, strengths 0.25 and 1.0 | Before/after finding |
| --- | --- | --- | --- |
| Pears / 11760922 | Every role has only one pear and one blue vase | Two foreground pears, multiple vases and many flower/fruit branches | Missing pear changes to excess objects. At strength 1, adapter/trigger removes a third vase but still has two and extra fruit/flowers |
| Pears / 11760923 | Two pears but no vase in every role | Plain roles have two vases and leafy branches; triggered roles have two vases and four pears | Vase appears, but exact count/extra-object requirements still fail. Adapter/plain removes a small dark vessel at both strengths, a local positive observation |
| Geometry / 11860922 | All roles show one red wooden cube and one white paper cone | Every role adds a white support block and small red cylinder; white pointed form is pyramid-like | **Regression from passing to failing adherence** across all roles at both strengths |
| Geometry / 11860923 | Single folded red form instead of separate cube/cone | More distinct forms, but extra white object, loose paper/brown cone and wrong materials; triggered adapter distorts the red cube | Changed failure; adapter regression at both strengths, not a case improvement |

Across the 64 images, **56 adherence judgments fail and eight pass**. All eight
passes are the first geometry seed at 512px. Coherence/quality has 52 passes and
12 uncertain judgments, separately from object adherence. No divided collage or
external frame was observed in this ComfyUI subset. The training-runtime panels
therefore cannot be treated as controlled ComfyUI outcomes: scheduler, precision
and noise/runtime differences remain confounded.

All **16 activation-specificity comparisons remain uncertain**. Stronger adapter
settings visibly affect background, texture and geometry without the trigger;
those changes do not establish the requested painting style or reliable trigger
control. Of 16 four-role comparisons, 14 are rejected on required-case failures
and two remain inconclusive for activation. The overall fixed-candidate
disposition is **rejected**. Neither strength nor resolution adjustment qualifies
as an improvement surviving both seeds and both prompts.

All 16 repeated base-control pairs across strengths have identical decoded pixels.
These are same-session controls: ComfyUI may reuse cached nodes. This is not
independent GPU sampling reproduction. The unchanged export and loader bytes have
historical C-03 mapping evidence; no new mapping certificate binds these v1 plans.
This diagnostic review does not replace the complete C-03 corpus acceptance gate.

Before/after sheets for the passing-to-failing geometry seed:
[512 / 0.25](evidence/phase-c04-images/diagnostic-512-250-paper-geometry-11860922.png),
[512 / 1.0](evidence/phase-c04-images/diagnostic-512-1000-paper-geometry-11860922.png),
[1024 / 0.25](evidence/phase-c04-images/diagnostic-1024-250-paper-geometry-11860922.png),
[1024 / 1.0](evidence/phase-c04-images/diagnostic-1024-1000-paper-geometry-11860922.png).
The [1024 / 0.25 second geometry seed](evidence/phase-c04-images/diagnostic-1024-250-paper-geometry-11860923.png)
retains the red cube-to-pointed-form regression.

## Disposition, limits and reproducible identities

**Reject** both new training endpoints and the unchanged deployed candidate.
**Inconclusive** on the exact numerical mechanism, data-padding causality and
intended activation specificity. The input audit ruled out truncation for these
specific captions/prompts and documented data/conditioning confounds. It did not
change data or perform a new data ablation. No automatic detector was revised;
C-02's missed natural borders and unavailable semantic evaluator remain visible.

Three repetitions per endpoint do not estimate a population distribution. Two
exposed prompts do not establish generalization or corpus sufficiency. All seven
C-01 holdouts remain unused by this investigation. Assistant review supplies
observations and limitations, not independent human acceptance. Additional
training, tuning or a new evaluation campaign requires a new declaration; none
was added to rescue an unfavorable result.

| Record | Identity |
| --- | --- |
| Experiment | `1192ef70ad6324a7c7ef6efef16187f28f4e02cfea2622049baec511d4d0cbc1` |
| Training packet | `040c7425b05732aef6f2f683a0c08e4f226bed280a27fd70e7063582a501d8c9` |
| Numerical report | `4ce12568f14f8cf87f7b82710e4437e0d71134632b0d231a6aa007a89e411d8c` |
| Training rejection | `c4604b6207f474aea6f286ca9d289c3e19d326e92eda73f726f35ba93bb235b9` |
| Diagnostic investigation | `4ac58b2b0352632e11bacc3f39af96017cbc8db9fd460277ab732c862652ec4a` |

Plans and reports remain under `workspace/state/experiments/`; diagnostic plans,
replays, exact image identities and observations are indexed by the final
verification receipt. The [numerical CLI](experiment-variance.md) and existing
experiment/evaluation replay commands reproduce supported evidence checks without
training or rendering. The diagnostic assistant investigation is a recorded study,
not a new automatic evaluator or an activation authority.

## Implementation and runtime verification

The [interim verification receipt](evidence/phase-c04-interim-verification-20260924.json)
retains **1,454 passing source regressions**, **17 final focused source checks**,
**50 installed-wheel experiment/variance checks** and four offline public commands
per implementation. The broad source run began before the final refinement that
compares declared order controls separately from measured gradient/micro-loss
outcomes. Final focused, installed and real-checkpoint checks cover that refinement.
The entire installed suite was not repeated for this addition.

Source, sdist, wheel and installed bytes match across 78 modules and the README.
Build, lint, formatting and scoped diff checks pass. The initial missing test
directory and three canonical-JSON float serialization failures remain recorded;
the final report stores exact hexadecimal difference strings. Tests include stale
evidence, failed/incomplete members, three-pair coverage, tolerance boundaries and
exact failures that survive a tolerance pass.

The interim receipt remains unchanged as the earlier memory-blocked checkpoint.
All 696 files in the scoped historical preservation manifest, the catalog head,
training-worker source hashes and SCM 0.5.0 remain unchanged after execution. This
scope covers model/data/evaluation/experiment evidence, not all prior test fixtures.
All three owned temporary servers are stopped; each cleanup checked its exact
process identity, empty queue and idle shared device lease.

The deployed server history records exactly 64 successful prompts and 64 distinct
owned requests. Its first-start to last-finish span is 17.477 minutes; server
reported prompt durations sum to 161.53 seconds. Repeated controller validation
and possible node caching make this an observed run, not a throughput benchmark.
No package release or Git publication was performed. Version remains 0.13.1,
unreleased.

Six serialized offline public commands per implementation now replay the numerical
report, training rejection and four complete evaluation matrices. Both source
(Python 3.13.9) and the installed wheel (Python 3.11.14) retain the same failed
numerical and rejected quality outcomes. Network connections and optional ML/image
imports were forbidden during these checks. All 78 module bytes still match the
tested source/package artifacts; README package parity remains unchanged.

The [final verification receipt](evidence/phase-c04-verification-20260924.json)
contains the declarations, complete review/decision records, numerical pairs,
image identities, execution history, test boundaries, public replay and cleanup.
The interim receipt and failed test evidence remain intact. **C-05 is next**;
its lifecycle work must preserve the current rejection and stale-evidence guards.
