# C-03 deployed candidate review

**The candidate is rejected.** All 288 deployed conditions completed and decoded successfully, all 1,120 adapter tensors mapped to compatible loader targets, and the assistant inspected every image and all 108 matched comparisons. Missing objects, count/layout errors and observed regressions prevent acceptance; intended trigger specificity remains unestablished. This completes the bounded C-03 evaluation task, not model or product acceptance. [Machine-readable verification](evidence/phase-c03-verification-20260924.json) retains the complete review and separate technical evidence.

## Scope and fixed inputs

The unchanged [C-01 comparison specification](../examples/still-life-corpus-comparison.evaluation.json) covers twelve cases, three seeds per case, base/plain and base/trigger controls, and adapter/plain and adapter/trigger at strengths 0.25, 0.5 and 1.0. That is 288 images and 108 matched four-condition comparisons. All conditions use 512 × 512, 20 steps, CFG 7 and stock ComfyUI `dpmpp_2m`/`karras`. No training, threshold tuning or additional candidate selection is part of this task.

| Binding | Identity |
| --- | --- |
| Current evaluation plan | `24f2e130bdec26c6f48d059e16c990bd91acb32180f72a5e444dd70b425586bf` |
| Original, unexecuted C-01 comparison plan | `8f97aaba629359f7818d37de50bd627a6b6090b7d604bd4506fea2d5936f2270` |
| Frozen corpus | `7c9474c4f3c4803e6fed60c01df34df0d4023390da26ed1545685a61517dfae0` |
| B-05 long-r1 candidate | `60399a05e5b87f2a3c7de57b5c9e54443fcd6186070be1dde2f1574e569d09d6` |
| Exported/deployed LoRA SHA-256 | `2c3c3b56760e1d2ddcb71bdf713b23d32c6c236edb578c423faf476a25badfd2` |
| SDXL checkpoint SHA-256 | `31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b` |
| Loader certificate | `24d9d6e13d031762214fc195e57ee38925da16cba1e6350ce06e0f2e0246afdb` |

The runtime is the existing portable ComfyUI 0.37.0 installation, Python 3.13.14, Torch 2.13.0+cu130 and RTX 5090 with driver 616.64. A fresh server session changed the bound observer PID/session/start time. The old plan was refused; a new plan was created from the same declared cases/settings. The original plan was not edited or relabeled as executed.

## Recorded outcome

| Record | Identity |
| --- | --- |
| Review packet | `251821eb1d09fa0ba80259065a4dc58d7d2b632b950a514fe81b6d23468d732e` |
| Technical report | `5974fc742b0dc9dcae802c783e5ca12234ae0cd23c01d5608dbbf7d20ea12836` |
| Candidate decision | `0ab0bd418b90ce6f6172149c8dcc4184d3ebb8e46d71a6d6f161619ef36ae4ff` |

The 756 required judgments comprise **274 pass, 301 fail, 181 uncertain and 0 unavailable**. These are categorical criterion counts, not a composite quality score or independent statistical trials. Base judgments are retained as context and are excluded from that candidate-gating denominator.

Each case below has 24 image observations, including six base controls, and nine matched strength comparisons. Counts are shown as pass / fail / uncertain / unavailable. They must not be compared with C-01's combined per-image verdict counts as if the denominators were the same.

| Case | Prompt adherence (24) | Image quality (24) | Activation specificity (9) | Preservation (9) | Usable strength (9) |
| --- | --- | --- | --- | --- | --- |
| bicycle-photo | 0 / 17 / 7 / 0 | 0 / 17 / 7 / 0 | 0 / 0 / 9 / 0 | 0 / 5 / 4 / 0 | 0 / 7 / 2 / 0 |
| bird-photo | 0 / 24 / 0 / 0 | 15 / 8 / 1 / 0 | 0 / 0 / 9 / 0 | 7 / 2 / 0 / 0 | 0 / 9 / 0 / 0 |
| color-binding | 3 / 18 / 3 / 0 | 20 / 4 / 0 / 0 | 0 / 0 / 9 / 0 | 4 / 5 / 0 / 0 | 1 / 8 / 0 / 0 |
| linen-metal | 0 / 24 / 0 / 0 | 19 / 0 / 5 / 0 | 0 / 0 / 9 / 0 | 6 / 0 / 3 / 0 | 0 / 9 / 0 / 0 |
| matte-gloss | 0 / 22 / 2 / 0 | 16 / 8 / 0 / 0 | 0 / 0 / 9 / 0 | 4 / 3 / 2 / 0 | 0 / 9 / 0 / 0 |
| mountain-photo | 20 / 4 / 0 / 0 | 20 / 4 / 0 / 0 | 0 / 0 / 9 / 0 | 9 / 0 / 0 / 0 | 6 / 3 / 0 / 0 |
| paper-geometry | 8 / 16 / 0 / 0 | 16 / 0 / 8 / 0 | 0 / 0 / 9 / 0 | 4 / 0 / 5 / 0 | 3 / 6 / 0 / 0 |
| plate-left-vase | 0 / 20 / 4 / 0 | 24 / 0 / 0 / 0 | 0 / 0 / 9 / 0 | 9 / 0 / 0 / 0 | 0 / 9 / 0 / 0 |
| single-cup | 0 / 0 / 24 / 0 | 24 / 0 / 0 / 0 | 0 / 0 / 9 / 0 | 9 / 0 / 0 / 0 | 0 / 0 / 9 / 0 |
| size-binding | 0 / 24 / 0 / 0 | 24 / 0 / 0 / 0 | 0 / 0 / 9 / 0 | 9 / 0 / 0 / 0 | 0 / 9 / 0 / 0 |
| three-apples | 0 / 24 / 0 / 0 | 16 / 8 / 0 / 0 | 0 / 0 / 9 / 0 | 6 / 0 / 3 / 0 | 0 / 9 / 0 / 0 |
| vase-and-pears | 0 / 24 / 0 / 0 | 24 / 0 / 0 / 0 | 0 / 0 / 9 / 0 | 9 / 0 / 0 / 0 | 0 / 9 / 0 / 0 |

Strength summaries retain all 36 case/seed comparisons at each strength. A usable-strength pass alone does not establish activation specificity or overall candidate acceptance.

| Strength | Activation specificity | Preservation | Usable strength |
| --- | --- | --- | --- |
| 0.25 | 0 / 0 / 36 / 0 | 28 / 3 / 5 / 0 | 3 / 30 / 3 / 0 |
| 0.5 | 0 / 0 / 36 / 0 | 24 / 5 / 7 / 0 | 3 / 29 / 4 / 0 |
| 1.0 | 0 / 0 / 36 / 0 | 24 / 7 / 5 / 0 | 4 / 28 / 4 / 0 |

The new base controls have **72/72 exact decoded-RGB matches** with the retained C-01 baseline across server sessions. PNG file metadata can differ. This bounded base-control observation does not reverse B-05's failed training reproduction or qualify general GPU determinism. The original C-01 observations remain unchanged.

## Loader compatibility and sampler limits

The supported [loader and review commands](deployed-review.md) load the actual checkpoint and exported adapter through the installed ComfyUI mapping functions. The final CPU probe accounts for all 1,120 tensors as 560 distinct compatible UNet targets and confirms patch registration at all three strengths. Every tensor is on CPU, no CUDA devices are visible, and the final probe reports CUDA uninitialized. The certificate binds model/adapter bytes, target shapes, strength registration, worker bytes, request/result/log and declared runtime sources. It establishes mapping and registration, not an exhaustive attestation of dependencies or the running server's cached tensors.

Earlier Diffusers images used the pinned `EulerDiscreteScheduler` configuration without Karras sigmas, leading timestep spacing and offset 1. The training worker's separate `DDPMScheduler` supplies training noise and does not replace the inference pipeline scheduler. Diffusers inference uses CUDA-generated noise and BF16 pipeline weights with FP32 VAE decode. This ComfyUI run uses CPU-generated noise, FP16 UNet/text encoder weights and BF16 VAE loading. Matching seed numbers, dimensions, steps and CFG therefore do not establish sampler, latent-noise or arithmetic parity. No new Diffusers run or controlled parity experiment was performed.

## Inspection method and acceptance boundary

The assistant directly inspects all conditions as 36 lossless contact sheets, one case/seed per sheet. Each sheet has base, 0.25, 0.5 and 1.0 rows with plain/trigger columns. Original 512px images 216, 222 and 223 were also inspected separately to assess landscape texture. Labels and prior failures are visible; this is not blinded review. Image judgments cover prompt adherence and coherent image quality. Each matched comparison separately records intended activation specificity, preservation against its base controls and usability of both adapter conditions. Notes and uncertainty accompany every criterion.

The protocol was recorded before the first sheet inspection. Existing base failures remain distinct from adapter-induced regressions. A changed image alone cannot establish intended trigger activation. Missing visibility, ambiguous material/identity and unsupported style attribution remain uncertain. C-02's unqualified border screen and unavailable semantic evaluators do not supply quality judgments here.

Any failed required adapter-image or comparison criterion rejects the candidate for the matrix. With no failures, uncertainty would produce an inconclusive result. An all-pass matrix would still have `promotion_eligible: false`; lifecycle integration is C-05. These exposed prompts, the three-work dataset and one render per condition cannot establish independent holdout performance, general numerical determinism, corpus sufficiency or production quality.

## Concrete observations

- **Count and missing-object failures persist across strengths.** The pear/vase cases show one pear or omit the vase; the apple cases show two apples or repeated panels; the size-binding cases collapse two vessels into one blue/white bowl. These failures are already present in matched base controls and are not automatically attributed to the adapter.
- **Some conditions improve.** The red-cube/white-cone case at seed 11860922 remains usable across strengths. In [color-binding seed 12061125](evidence/phase-c03-images/color-binding-12061125.png), full strength removes the plain repeated-panel layout and produces a single green bottle left of an orange bowl; the triggered counterpart also satisfies the object/color arrangement. The improvement occurs without the trigger too, so it does not establish intended activation specificity or overall acceptance.
- **Lower strength does not reliably preserve requested objects.** In [color-binding seed 12061126](evidence/phase-c03-images/color-binding-12061126.png), the triggered bottle disappears at 0.25 and 0.5 and returns at 1.0; the bowl color remains ambiguous. Full strength adds another fruit in the plain condition. In seed 12061124, the triggered full-strength image adds an orange wedge outside the bowl.
- **Hidden or ambiguous details remain uncertain.** The single-cup images do not expose enough of the opening to establish an empty interior. A blue-centered dish and handled blue vessel in plate-left-vase seed 12061325 leave white-plate and vase/pitcher identity uncertain, while its plain images place the vase on the plate rather than beside it.
- **Material prompts often substitute objects.** Linen/metal seeds produce a spoon on broad cloth without a separate folded napkin, a napkin on a plate without a spoon, or a fork on a napkin. Some shiny handle-like strips make utensil structure uncertain. Surface detail cannot compensate for the absent or substituted requested object.
- **Strong adapters can introduce new content failures.** In [matte/gloss seed 12061524](evidence/phase-c03-images/matte-gloss-12061524.png), the triggered full-strength image changes the already-wrong many-object panels into stand-mounted disk/mirror-like forms and a red capsule. In [seed 12061526](evidence/phase-c03-images/matte-gloss-12061526.png), the plain full-strength image adds a third sphere; at 0.5 the small sphere acquires a foot-like protrusion. These changes are recorded against each matched base, not inferred from pixel distance.
- **Landscape content is largely preserved, including an existing failure.** Seeds 12061624 and 12061625 retain usable photographic mountain/lake scenes in both conditions across strengths. [Seed 12061626](evidence/phase-c03-images/mountain-photo-12061626.png) retains its triggered base's straight white top/bottom borders at every strength, while its plain condition remains unframed. Preservation of an existing defect is distinct from a new regression, but the framed pair still fails usability. No learned oil-painted activation is established by the subtle terrain/reflection changes.
- **Bicycle structure is weak before and after adapter application.** [Seed 12061724](evidence/phase-c03-images/bicycle-photo-12061724.png) has malformed frames/wheels and a cropped triggered graphic; higher strengths restore full triggered objects but retain structural faults, and full-strength plain adds a floating saddle-like fragment. Seed 12061725 retains two-wheel blue compositions with uncertain mechanics/photographic appearance and an apparently detached triggered pedal at 0.25. Seed 12061726 retains repeated vehicle patterns throughout, with further identity substitution at full strength. None is a demonstrated consistently usable bicycle pair.
- **Bird subjects remain recognizable, while prompt defects persist.** Seed 12061824 keeps green growth on the requested bare branch at every strength. [Seed 12061825](evidence/phase-c03-images/bird-photo-12061825.png) keeps multiple branches/cropped details and adds greater foreground body occlusion in the triggered 0.5/1.0 images. Seed 12061826 retains an outer frame and pseudo-text/signature-like marks in every condition. Preserving a recognizable single bird does not resolve those complete-case failures.

These are examples from the complete recorded observations, not a selection that replaces the remaining seeds or comparisons. Every seed and strength is included in the final decision.

## Retained failures and corrections

The first run request encountered a server-startup connection refusal. Status showed zero started jobs, and resume correctly refused a never-started plan. Once the server was ready, the original plan was refused for changed server-session identity. Those commands and both plan identities remain preserved.

The first loader probe incorrectly treated ComfyUI's cumulative `loaded_keys` set as a per-adapter tensor pair. The worker now traces each loaded up/down tensor by object identity and validates its exported stem against the target. Further probes exposed that `--cpu` alone, and an empty CUDA visibility setting, did not isolate this installation from CUDA. The final worker and parent use `CUDA_VISIBLE_DEVICES=-1` before imports and require zero visible devices plus CPU tensors. Earlier failed probes remain intact. A first successful isolated probe emitted an empty log and lacked the final environment binding; its certificate is retained as superseded, not current evidence. The final certificate has a nonempty CPU-probe header and explicit environment binding.

The initial focused suite found a nested template alias that could mutate packet bindings in memory; comparison bindings are now deep-copied. A later focused check failed because its expected log omitted the newly added CPU header; the exact expected log was updated. Both failures remain recorded separately from later passing suites.

## Verification and remaining work

The early full source suite passed 1,436 tests before the final loader-isolation/logging and Markdown refinements. Final focused source verification passed 99 tests, including all 56 new deployed-review tests. The final built wheel passed all 1,437 tests on Python 3.11.14. The source environment remains Python 3.13.9 with SCM development tools 0.5.0. These protocol/package checks do not themselves establish image quality.

Six sequential public commands per implementation replay the mapping, packet and rejection with network connections and ML/image imports forbidden; they also refuse pending reviews, preserve C-02's six false accepts and B-05's rejection, and confirm the managed device is idle. All **77 source/sdist/wheel/installed modules** and README bytes match. Lint, formatting, build and scoped diff checks pass. **46,182 historical files**, the catalog head and SCM 0.5.0 remain unchanged. The broad preservation manifest includes prior verification fixtures as well as model/data evidence; its file count is not a quality measure.

Server history contains exactly **288 successful prompts and 288 distinct owned requests**, with an empty queue. The elapsed first-start to last-finish span was 89.26 minutes; ComfyUI's reported prompt durations sum to 804.61 seconds. This was one sequential run with repeated input validation and concurrent test/probe work, not isolated profiling or a throughput claim. The identity-verified temporary server was stopped, restoring its initially stopped state.

No model was trained, tuned, promoted or activated, and no release was published. **C-04 is next**: investigate failure mechanisms and repetition variance with predeclared bounded experiments while retaining unfavorable cases, B-05's failed exact reproduction and C-02's missed borders. C-05 still owns lifecycle integration. ITOV remains incomplete; version stays 0.13.1, unreleased.

## Complete inspected contact sheets

Each link contains all eight conditions for one seed, without cropping or omitted failures.

| Case | Seed 1 | Seed 2 | Seed 3 |
| --- | --- | --- | --- |
| vase-and-pears | [11760922](evidence/phase-c03-images/vase-and-pears-11760922.png) | [11760923](evidence/phase-c03-images/vase-and-pears-11760923.png) | [11960924](evidence/phase-c03-images/vase-and-pears-11960924.png) |
| paper-geometry | [11860922](evidence/phase-c03-images/paper-geometry-11860922.png) | [11860923](evidence/phase-c03-images/paper-geometry-11860923.png) | [11960925](evidence/phase-c03-images/paper-geometry-11960925.png) |
| three-apples | [12060924](evidence/phase-c03-images/three-apples-12060924.png) | [12060925](evidence/phase-c03-images/three-apples-12060925.png) | [12060926](evidence/phase-c03-images/three-apples-12060926.png) |
| single-cup | [12061024](evidence/phase-c03-images/single-cup-12061024.png) | [12061025](evidence/phase-c03-images/single-cup-12061025.png) | [12061026](evidence/phase-c03-images/single-cup-12061026.png) |
| color-binding | [12061124](evidence/phase-c03-images/color-binding-12061124.png) | [12061125](evidence/phase-c03-images/color-binding-12061125.png) | [12061126](evidence/phase-c03-images/color-binding-12061126.png) |
| size-binding | [12061224](evidence/phase-c03-images/size-binding-12061224.png) | [12061225](evidence/phase-c03-images/size-binding-12061225.png) | [12061226](evidence/phase-c03-images/size-binding-12061226.png) |
| plate-left-vase | [12061324](evidence/phase-c03-images/plate-left-vase-12061324.png) | [12061325](evidence/phase-c03-images/plate-left-vase-12061325.png) | [12061326](evidence/phase-c03-images/plate-left-vase-12061326.png) |
| linen-metal | [12061424](evidence/phase-c03-images/linen-metal-12061424.png) | [12061425](evidence/phase-c03-images/linen-metal-12061425.png) | [12061426](evidence/phase-c03-images/linen-metal-12061426.png) |
| matte-gloss | [12061524](evidence/phase-c03-images/matte-gloss-12061524.png) | [12061525](evidence/phase-c03-images/matte-gloss-12061525.png) | [12061526](evidence/phase-c03-images/matte-gloss-12061526.png) |
| mountain-photo | [12061624](evidence/phase-c03-images/mountain-photo-12061624.png) | [12061625](evidence/phase-c03-images/mountain-photo-12061625.png) | [12061626](evidence/phase-c03-images/mountain-photo-12061626.png) |
| bicycle-photo | [12061724](evidence/phase-c03-images/bicycle-photo-12061724.png) | [12061725](evidence/phase-c03-images/bicycle-photo-12061725.png) | [12061726](evidence/phase-c03-images/bicycle-photo-12061726.png) |
| bird-photo | [12061824](evidence/phase-c03-images/bird-photo-12061824.png) | [12061825](evidence/phase-c03-images/bird-photo-12061825.png) | [12061826](evidence/phase-c03-images/bird-photo-12061826.png) |
