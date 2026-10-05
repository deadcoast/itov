# C-01 frozen corpus and base-model baseline

The broader corpus is frozen and all **72 base-model images** have been rendered, decoded and directly inspected. The observations contain **7 passing, 52 failing and 13 uncertain images** against the preregistered prompt-adherence and image-quality criteria. Every case has an adverse or uncertain seed/condition; no case or seed was removed. These are descriptive judgments from this bounded corpus, not a population failure rate or a candidate acceptance decision.

## Preregistered coverage

[The declaration](../examples/still-life.corpus.json) freezes twelve prompts and three seeds per prompt before baseline generation or further tuning. Seven target cases are held out from training/tuning; five are diagnostic regressions. The original vase/pears and paper-geometry text, expectations and two seeds are retained, with a third seed added and prior exposure declared. Counts, attributes, layout, textures, trigger specificity, strength range and unrelated-task behavior each have multiple cases in the coverage manifest.

- Corpus: `7c9474c4f3c4803e6fed60c01df34df0d4023390da26ed1545685a61517dfae0`.
- Baseline plan: `2755ea457fefdebcfa4c8fdfb2c6b34ca4cdb809e6d87c2b349133533b9feb85`.
- Observed baseline: `41c6be1c9ac4279ddfd3c0d5243a7c704e50329dda563bbf63174dad76a00838`.
- Full comparison plan: `8f97aaba629359f7818d37de50bd627a6b6090b7d604bd4506fea2d5936f2270`.
- Reference training plan: B-05 `long-r1`, `26c3cb899dddae04e8f06919642e431742434e61c8e66b5a6a33968a2ae91cf7`. Its rejected quality outcome remains unchanged.

The corpus binds the unchanged B-02 dataset: two training works and one validation work. Exact normalized training and validation captions are excluded. Semantic/pretraining independence is not proven. Baseline inspection is declared exposure; the seven held-out prompts must not guide subsequent data selection, captions or tuning. If that boundary is crossed, record contamination and add fresh heldouts in an additive successor while retaining this corpus and its failures. The [runbook](evaluation-corpus.md) describes the enforced checks and the process constraints that hashes cannot establish.

The frozen strength comparison contains base/plain and base/trigger controls, then adapter/plain and adapter/trigger at **0.25, 0.5 and 1.0**, for 288 images. Its plan is saved and technically validated but **no comparison jobs were submitted** in C-01. Only the 72 base controls ran. No new training or tuning occurred.

## Actual runtime and recovery

The baseline uses the pinned SDXL base checkpoint `31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b`, ComfyUI 0.37.0, embedded Python 3.13.14, Torch 2.13.0+cu130 and the RTX 5090. All images are 512×512, with 20 `dpmpp_2m`/`karras` steps and CFG 7. Each graph has strength zero and no LoRA loader node. The existing instrumented stock runtime records its source/executable/schema identities. These settings differ from the prior Diffusers diagnostic pipeline; matching seed numbers do not imply sampler parity or numerical equivalence.

Windows denied replacement of the owned record for index 26 after its server submission. The controller paused with 26 outputs recorded complete, leaving the affected record at `submitting` without a prompt ID. The error, pre-resume record and shared lease observation remain retained. Public `evaluation resume` reconciled the accepted request and completed the same plan. The server history contains exactly **72 distinct completed prompts**, and the log contains 72 completed renders, including the interrupted record's job. No extra completed render was used to replace it.

The process causing the file-sharing refusal is undetermined. Inspection stopped reading active job records; only earlier completed cases were opened thereafter. General transient Windows sharing-failure hardening remains D-05. This trial proves this observed recovery, not immunity to future file-sharing failures. The temporary server was stopped by verified process identity after an empty queue and idle shared GPU registry were confirmed.

## Direct inspection

Every original image was fully decoded with Pillow in addition to the runtime's FFmpeg verification. The twelve linked contact sheets contain lossless 512px tiles, two conditions per seed and all three seeds. Observations disclose the assistant reviewer, method and limitations, and are embedded in the immutable baseline. Prompt adherence tests required content; image quality addresses visible rendering coherence. Unseen interiors, ambiguous borders/materials and uncertain geometry stay uncertain.

| Case and all six images | Pass / fail / uncertain | Observations |
| --- | --- | --- |
| [Vase and pears](evidence/phase-c01-images/vase-and-pears.png) | 0 / 6 / 0 | One pear instead of two; two pears without a vase; added seed repeats one-pear and striped-background failure. |
| [Paper geometry](evidence/phase-c01-images/paper-geometry.png) | 2 / 4 / 0 | First seed has the red cube and white cone. Other seeds produce a folded triangular form or reverse colors/shapes. |
| [Three apples](evidence/phase-c01-images/three-apples.png) | 0 / 6 / 0 | Four images contain only two apples; two contain repeated grids/strips and cropped forms. |
| [Single cup](evidence/phase-c01-images/single-cup.png) | 0 / 0 / 6 | One yellow cup and handle appear consistently, but the nearly edge-on opening prevents verification of an empty interior. |
| [Color binding](evidence/phase-c01-images/color-binding.png) | 0 / 5 / 1 | Reversed bottle/bowl positions, missing bowls and substituted oranges. One correctly arranged pair has an ambiguously orange/green bowl. |
| [Size binding](evidence/phase-c01-images/size-binding.png) | 0 / 6 / 0 | Every image collapses the white bowl and blue cup into one vessel; size/depth relations cannot hold. |
| [Plate left of vase](evidence/phase-c01-images/plate-left-vase.png) | 0 / 5 / 1 | Missing vase, blue plate, vase standing on plate, or added bowl/saucer/flowers. One improved arrangement retains ambiguous plate color and vessel identity. |
| [Linen and metal](evidence/phase-c01-images/linen-metal.png) | 0 / 4 / 2 | Cropped spoon/cloth views leave napkin placement uncertain; other seeds substitute a plate or fork for the spoon. |
| [Matte and gloss](evidence/phase-c01-images/matte-gloss.png) | 1 / 5 / 0 | Repeated panels, merged colors on one object, and a glossy/glass-like red sphere. One plain image distinguishes matte clay from a black sphere's specular response. |
| [Mountain photo](evidence/phase-c01-images/mountain-photo.png) | 4 / 1 / 1 | Four coherent photographic landscapes. The third seed introduces an ambiguous pale lower strip, then clear white presentation bands with the token. |
| [Bicycle photo](evidence/phase-c01-images/bicycle-photo.png) | 0 / 4 / 2 | Malformed/cropped or repeated bicycle-like forms. Two complete two-wheel compositions retain uncertain drivetrain/frame detail and photographic coherence. |
| [Bird photo](evidence/phase-c01-images/bird-photo.png) | 0 / 6 / 0 | Bird count often holds, but moss replaces the bare perch, tails are cropped, or borders and pseudo-text/signatures appear. |

The seven passing images are individual controls, not passing cases across all seeds. The matte/gloss and mountain comparisons also show why a changed image after adding the token is insufficient activation evidence: the adapter is absent. Correct object count alone does not resolve missing materials, positions, framing or visibility requirements.

## Verification and remaining work

[Verification evidence](evidence/phase-c01-verification-20260924.json) separates 1,335 source and 1,335 installed-wheel tests from actual GPU execution and these observations. The final presentation-only change has 44 additional focused checks per implementation; final source/sdist/wheel/installed parity covers 72 modules and exact README bytes. Public offline replay preserves earlier evaluation and B-05 rejection identities, with network and optional ML imports forbidden. Initial fixture/setup failures and an expected workspace-lock refusal during concurrent verification are retained; final shared-workspace verification runs sequentially.

The 983 historical files captured before C-01 retain their bytes, the catalog head is unchanged and SCM 0.5.0 remains installed. B-05's failed exact numerical reproduction and all rejected endpoints are preserved. No model was accepted, activated or promoted; no release or commit was created.

C-01 delivers a broader frozen coverage manifest, explicit held-out policy, supported baseline workflow and observed results before tuning. C-02 still needs calibrated checks and uncertainty handling; C-03 still needs the complete deployed adapter matrix and loader assessment. C-04 retains count/layout/material failures, trigger specificity and numerical variation. The product remains incomplete.
