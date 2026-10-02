# D-02.1 base-image results

**The resolution hypothesis failed. D-02.1 remains active.** The request builder
is implemented, but the tested SDXL recipe is not accepted as a usable image
baseline. This report supersedes the pending-memory status in the retained
[first-increment report](d021-image-development-20260926.md).

## Implemented workflow

`inference spec --prompt ... --save` creates a normal immutable base-image
specification. Prompt, negative prompt, dimensions, seed range and sampler settings
remain explicit. Drafting needs neither a model read nor a running server; saved
requests proceed through the existing prepare, plan, run and recovery commands.
The [runbook](base-image-workflow.md) documents the installed workflow.

Nine new request checks and the surrounding inference/CLI/workspace regressions
passed: **156 source and 156 installed-wheel tests**. Lint and 145-file formatting
checks passed. Source, final sdist, final wheel and core installation match across
87 Python modules and README. The final guide formatting change had an identical
Python AST; the test suite preceded this formatting-only change. Final installed
commands and the completed-image replays exercise the final package bytes.
The earlier Windows fixture connection-abort failure and successful reruns remain
in the [initial report](d021-image-development-20260926.md).

This is a CLI improvement. The requested graphical reference-image/description
training workspace remains planned under D-02.3; it is not implemented by this
increment.

## Declared comparison and direct review

The [frozen trial plan](d021-image-trial-plan-20260926.md) specified all prompts,
seeds and judgments before rendering. Both development arms use the same pinned
SDXL base, no adapter, 20 `dpmpp_2m`/`karras` steps and CFG 7. The only configured
difference is 512 versus 1024 dimensions. Equal seed numbers across different
latent shapes do not mean identical noise tensors. Three new cases were reserved
for the 1024 fresh-case check and were not used to retune this comparison.

| Arm | Images | Complete passes | Failures |
| --- | ---: | ---: | ---: |
| 512px exposed development | 6 | 1 | 5 |
| 1024px exposed development | 6 | 0 | 6 |
| 1024px fresh cases | 9 | 4 | 5 |
| Total | 21 | 5 | 16 |

All 21 original outputs were directly inspected. The
[per-image review](evidence/phase-d021-image-review-20260926.json) binds each
judgment to its prompt, seed and original PNG hash. Inspection was not blinded;
the assistant saw case labels and previous failures. Passes mean the declared
subjects/count, color/shape/material, layout and framing were readable. They do
not establish photographic perfection or unseen-prompt reliability.

- Every 1024px pear scene adds vases, vessels, branches or fruit/flower hybrids.
- All three 1024px geometry scenes add or substitute shapes. Seed 11860922 loses
  the sole complete development pass observed at 512px.
- One duck satisfies the requested yellow side-profile composition. Another has
  a blue lower body/base, and two show a three-quarter rather than side view.
  These view judgments are direct qualitative observations, not a measured angle.
- All three lemon images retain two separate whole yellow lemons, bare wood and
  gray background. Their irregular surfaces are visible in the originals.
- Two bottle/apple images add a green apple; the third reverses the explicitly
  requested bottle-left/apple-right relation.

The hypothesis required more complete development passes without losing an
existing one. It failed both conditions. The bounded recipe also required all
nine fresh images to pass; five failed. No seed was discarded or rerendered to
replace an adverse output. Even treating the view-only duck judgment as a pass
would not satisfy either acceptance condition.

The historical C-01 **7 pass / 52 fail / 13 uncertain** observations remain
unchanged. The seven earlier C-01 holdouts were not used in this trial. The three
new cases are now exposed and cannot be relabeled as unseen in a later comparison.

## Inspectable outputs

These sheets are labeled previews; their 1024px originals are linked individually
from the review record. All 21 originals are retained without recompression.

| Case | 512px preview | 1024px preview |
| --- | --- | --- |
| Vase and pears | [Three images](evidence/phase-d021-images/512-vase-and-pears-sheet.png) | [Three images](evidence/phase-d021-images/1024-vase-and-pears-sheet.png) |
| Paper geometry | [Three images](evidence/phase-d021-images/512-paper-geometry-sheet.png) | [Three images](evidence/phase-d021-images/1024-paper-geometry-sheet.png) |
| Yellow duck | Not planned | [Three images](evidence/phase-d021-images/1024-yellow-duck-sheet.png) |
| Two lemons | Not planned | [Three images](evidence/phase-d021-images/1024-two-lemons-sheet.png) |
| Bottle and apple | Not planned | [Three images](evidence/phase-d021-images/1024-bottle-apple-sheet.png) |

## Runtime, pauses and preservation

The initial attempt refused startup at about 1.01 GiB available Windows commit,
below the trial's declared 12 GiB condition. After memory recovered, a new attempt
completed the six 512px images. An immediate admission check after stopping that
server refused the next arm. The exact transient shortage was not sampled at the
assertion; shutdown lag is a possible explanation, not an established cause.
Once memory recovered again, continuation verified the six completed artifact
hashes and generated only the 15 unstarted 1024px images.

Two separate owned server histories contain exactly six and fifteen successful
prompts. Every image decoded at its declared dimensions. Seven public installed
replays verify the owned records, current pinned model/runtime bytes and decoded
outputs. Technical replay intentionally leaves quality acceptance unestablished.
Both temporary servers were stopped through their Windows Job owners; final
identity and closed-port checks are recorded in the verification receipt.

Resource samples are whole-machine/device observations at approximately two-second
intervals. Other applications contribute to them and short peaks can be missed;
they do not establish a general memory or concurrency limit. No unrelated
application was stopped, system memory setting changed or 24 GiB training floor
relaxed. There were **zero audio, video or training jobs** in this increment.

All 2,047 prior preservation-manifest files, 143 prior D-02 evidence files, 21
training-worker source hashes, main catalog HEAD and SCM 0.5.0 remain unchanged.
The existing candidate remains rejected. Version 0.13.1 is unreleased; no catalog
activation or Git publication occurred.

The initial receipt accidentally hashed `finalize-01.log` while that finalizer's
redirected output was still open and empty. Its recorded empty-file hash is
incorrect for the completed 270-byte log. The corrected completed-file SHA-256 is
`0d1ae4e027c109e02fc7443ca3ed477227bcec5b45ad9075d570ce36666a3364`.
The original receipt and completed log are preserved. The
[successor receipt](evidence/phase-d021-verification-20260926.json) records this
exception and exact pre-results snapshots for the three updated receipt-bound
documents. It excludes its own still-open log from evidence hashing.

## Next intervention

The installed graph audit found no checkpoint/CLIP/VAE wiring defect, and this
comparison does not support another resolution-only fix. The next intervention
should compare a different base image model through the owned inference path,
with pinned assets, stock-node qualification and newly declared fresh cases.

FLUX.2 Klein 4B is a candidate for that investigation: its
[official model card](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B)
provides a four-step text-to-image example, and the
[ComfyUI guide](https://docs.comfy.org/tutorials/flux/flux-2-klein) documents local
4B workflows. This is a candidate selection based on available integration
evidence, not an observed quality improvement. No FLUX assets were downloaded,
capability integrated or FLUX images generated in this increment. A new capability
must preserve the existing SDXL specifications and rejected-candidate evidence.
Silent video remains second, the training workspace third, and audio deferred.
