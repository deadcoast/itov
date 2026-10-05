# C-02 image-check calibration — 2026-09-24

**The initial border screen is not a reliable filter:** it missed all six visually identified outer frames in the 72-image baseline. No model was accepted or promoted. The implemented [checks workflow](image-checks.md) records that failure, complete measurements, reference observations and optional evaluator unavailability. It does not replace the assistant's image inspection.

## Inputs and method

The calibration uses every image from C-01's [frozen base-model baseline](evaluation-corpus-baseline-20260924.md): twelve cases, three seeds each, paired base/plain and base/trigger conditions, pinned SDXL/ComfyUI, 512px, 20 steps, DPM++ 2M/Karras and CFG 7. It adds no training or rendering. All 72 original artifacts and their full-decode hashes remain unchanged.

The assistant inspected all original 512px tiles in the twelve retained lossless contact sheets before viewing the new natural-image measurements. New reference labels cover constant frames and outer border bands. Both semantic rubric labels and every explanatory note from C-01 remain preserved: prompt adherence has **7 pass / 52 fail / 13 uncertain**; general image quality has **58 pass / 9 fail / 5 uncertain**. These are different criteria, not two scores to combine.

The initial `rgb-artifacts-1` algorithm, parameters and reference labels were recorded before natural-image measurement. No parameter search or fitting followed the observed misses. Five procedural RGB controls are separate from the natural corpus. The images, prior semantic notes and case identities were exposed; no independent rater, blinded benchmark, fresh evaluator holdout or population accuracy estimate is claimed. This is descriptive calibration against assistant observations, which can themselves be wrong.

The final packet also binds all four reference rubric texts. An initial packet lacking the semantic rubric binding and its calibration are retained as pre-fix evidence; current inspection refuses that old packet. The final packet contains identical measurements, controls and checker parameters, and the reference judgments are unchanged. This contract correction did not repair or conceal the border-screen failure.

## Natural-image results

| Rubric | Known passing / failing references | False accepts | False rejects | Unknown references | Unavailable predictions |
| --- | ---: | ---: | ---: | ---: | ---: |
| Constant frame | 72 / 0 | 0; no failing-class denominator | 0 / 72 | 0 | 0 |
| Outer border bands | 65 / 6 | **6 / 6** | 0 / 65 | 1 uncertain | 0 |
| Prompt adherence, optional evaluator | 7 / 52 | 0 counted; no evaluations | 0 counted; no evaluations | 13 uncertain | **72** |
| Image quality, optional evaluator | 58 / 9 | 0 counted; no evaluations | 0 counted; no evaluations | 5 uncertain | **72** |

The artifact screen predicted `pass` on every natural image. For border bands, that includes the uncertain snow/border image; it is retained in the uncertainty row, not counted as a true or false accept. For constant frames, all 72 vary visibly, so this set cannot estimate sensitivity to naturally occurring blank outputs.

No optional semantic evaluator was invoked: **144 predictions are unavailable**, with zero decisive semantic comparisons. Zero counted semantic errors therefore establish no evaluator accuracy. A public interface smoke imports an explicitly labelled fixture response with every prediction unavailable; it tests transport/bindings, not model judgment or agreement with reference labels.

## Misses and inspection evidence

| Matrix index / case / seed / condition | Direct observation | Screen |
| --- | --- | --- |
| 26 / color-binding / 12061125 / plain | Dark strips frame the outer edges of the repeated six-panel composition | Missed |
| 27 / color-binding / 12061125 / trigger | Tan outer framing surrounds the rectangular still-life panel | Missed |
| 59 / mountain-photo / 12061626 / trigger | Broad straight white bars above and below the landscape | Missed |
| 61 / bicycle-photo / 12061724 / trigger | Full-height white bars on both sides of the cropped bicycle abstraction | Missed |
| 70 / bird-photo / 12061826 / plain | White outer margins and thin dark outline frame the bird image | Missed |
| 71 / bird-photo / 12061826 / trigger | White outer margins and thin dark outline frame the bird image | Missed |

See the original lossless sheets for [color binding](evidence/phase-c01-images/color-binding.png), [mountains](evidence/phase-c01-images/mountain-photo.png), [bicycles](evidence/phase-c01-images/bicycle-photo.png) and [birds](evidence/phase-c01-images/bird-photo.png). Index 58, mountain-photo / 12061626 / plain, retains uncertainty: the pale sloping lower strip could be foreground snow. No uncertain judgment was forced into a binary label.

The strict accumulated channel-range rule terminates at or near the first scanline in these misses. Even visibly white generated borders have pixel variation. The measured thickness therefore never reaches the declared minimum. A diagnostic comparison on index 59 confirmed the FFmpeg RGB bytes equal Pillow's RGB decode; changing decoder or silently relaxing the screen would not be a justified completion claim. The packet retains channel extrema and per-edge thickness/contrast measurements for investigation.

Object counts, hidden cup interiors, color/layout errors, substituted utensils, malformed bicycle geometry and internal panel repetition remain visible in the [full baseline inspection](evaluation-corpus-baseline-20260924.md). They are outside the two artifact rubrics. In particular, passing the artifact screen on all 72 images did not erase the 52 prompt-adherence failures or 13 uncertainties.

## Procedural controls and disposition

The exact solid-gray RGB probe is correctly rejected as a constant frame; the four varying probes pass that rubric. Border screening correctly clears the varying field and flags 16px white bars, but misses 4px white bars and 16px textured bars: **2 false accepts out of 3 known bordered controls**, zero false rejects out of one known clear control. The solid frame's border judgment/reference are unavailable because no interior is distinguishable. These five constructed probes establish bounded algorithm behavior, not natural-image performance.

Keep the measurements for diagnosis and the optional interface for attributed judgments. **Do not use `rgb-artifacts-1` to filter bordered natural images or infer semantic quality.** Future detector changes need a new version/packet, retained failures and fresh evaluation cases before any generalization claim. Human participation remains optional; direct assistant inspection is the available semantic evidence in this trial.

C-03 remains the complete deployed candidate evaluation. Its 288-image comparison is still unexecuted. C-04 retains count/layout/panel problems, trigger specificity, B-05's failed exact numerical reproduction and the unqualified border screen. No checkpoint, dataset, training setting, threshold, catalog activation or candidate disposition changed during C-02.

## Records and verification

Final packet: `0fe0029b87f20a8cd385a6d13b40b11d413539a659fd566aa3aa521dd6f0abe0`.

Optional evaluator request: `06f2957ff44a8042b1900344c4a8b6b168888e3624b31d4aed84f4136545e0ca`.

Final calibration: `524e17e48192e62815e88a0532f777d194f51dfc0b6054642f2180cdbfbeda04`.

The local records are under `workspace/state/evaluation/checks/`; the full reference, measurements, calibration tables and verification receipts are retained in [tracked C-02 evidence](evidence/phase-c02-verification-20260924.json). The reference's three source hashes bind the observed C-01 baseline, pre-measurement protocol and complete pre-measurement annotations. The evidence separates protocol tests, package verification, actual image measurements and direct inspection. It preserves the initial malformed-float fixture failure and pre-fix rubric-binding artifacts. ITOV and model-quality acceptance remain incomplete; version 0.13.1 is unreleased.

Verification passed 1,380 source and 1,380 initial-wheel regressions before the final rubric-binding correction. Final source checks passed 89; the final wheel passed all 46 image-check tests and 88 of 89 focused checks, retaining one fixture-server socket/stderr failure during a short timeout. All four unmodified recovery variants then passed. Thirteen sequential public commands per implementation verify current packets/calibrations, unavailable/pending/stale cases and historical replays without network or ML imports. Package parity covers 74 modules and exact README bytes; 1,155 historical files, SCM 0.5.0 and the catalog head remain unchanged. The shared device registry is idle.
