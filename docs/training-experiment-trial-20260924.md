# B-05 preregistered checkpoint experiment

All four checkpoint attempts are rejected against the frozen quality cases. The declared experiment executed both two- and four-update endpoints through source and installed controllers, within its twelve-update budget. **Exact numerical reproduction failed**: the weights and adapter images differ between repetitions. These failures remain recorded; no checkpoint is selected or promoted. The broader evaluation corpus, numerical-variation investigation and deployed-runtime work remain Phase C requirements.

## Protocol and inputs

The manifest was published before training as experiment `ec31b306ed90a4eec05ec6c10993d8968c66b62173a43fef96118089ffad8bd6`. The [example declaration](../examples/sdxl-tabletop.experiment.json) retains its exact bytes. It declares two independent final-checkpoint endpoints, each repeated twice, with a total budget of four attempts, twelve optimizer updates and 3,600 worker seconds. Each worker has a 900-second limit. This budget includes repeated training prefixes; these are not extra updates appended through resume.

Both endpoints use seed 9052401, rank 8, 512px, learning rate 100 millionths, micro-batch 1 with accumulation 2, shuffled epochs, constant scheduling without warmup, and validation/checkpoints every two updates. The pinned SDXL base, optional Python 3.13.9 training environment and RTX 5090 match the prior configured/checkpoint trials. The source and installed controllers are tested separately.

The unchanged B-02 freeze is `e5edc2a9721f924c37b0bd21e5e8edc89b75c84e922a1f595a6f60b26316aa38`: Roesen and Ream training works, Peale validation. The prepared dataset hash is `00b52a9ad88d7578ced82d765c53316e62ce6eb9d4f4efceb02a5e8b5746e56f`. The fixed suite hash is `9b4e52c6abdfcb8331852516fdabcbd78e2bcf174b3169ff5cb8ba8b45e7ecf3`, covering vase/pears seeds 11760922 and 11760923, and paper geometry seeds 11860922 and 11860923, each under all four base/trigger/adapter conditions.

The preregistered hypothesis asks whether four updates improve triggered still-life appearance over two while preserving object counts and untriggered photographic geometry. Every criterion in every case and repetition must pass. Eligible endpoints are ordered by fewer updates, then endpoint ID. Uncertainty cannot qualify a checkpoint. No learning-rate, caption, seed or suite tuning is permitted after observing these results.

## Execution and failed exact reproduction

All four attempts passed technical artifact validation and produced eighteen decoded 512px RGB images each. The worker used the same pinned Python 3.13.9 environment; source controllers used Python 3.13.9 and installed controllers Python 3.11.14. Times below include worker loading, training and rendering, not all controller planning/hashing overhead.

| Member | Updates | Worker seconds | Held-out loss after |
| --- | --- | --- | --- |
| short-r1, source | 2 | 68.46 | 0.202714846 |
| short-r2, installed | 2 | 55.13 | 0.202705562 |
| long-r1, source | 4 | 80.33 | 0.201978147 |
| long-r2, installed | 4 | 66.27 | 0.201963991 |

All start at held-out loss 0.203395754. Peak CUDA allocation is 8,172,685,312 bytes and reservation 9,256,828,928 bytes in each attempt. These observations do not establish capacity, throughput improvement or quality acceptance. Background activity and memory availability changed during the trials.

Sample/noise/rate order, completed positions, Python/NumPy RNG and Torch CPU/CUDA RNG bytes match across repetitions. Weights, AdamW moments, later losses and adapter images do not. Only nine of eighteen corresponding image hashes match for each endpoint: the eight base-condition images and the held-out baseline. All nine adapter images differ. The constant-rate source endpoints also have different numerical state at their shared planned two-update prefix.

| Repetition comparison | Maximum adapter/export absolute difference | Maximum training-loss difference | Maximum held-out-loss difference |
| --- | --- | --- | --- |
| Two updates | 0.0003590876003727317 | 0.000010331 | 0.000009284 |
| Four updates | 0.000237340216699522 | 0.000014030 | 0.000014156 |

The initial exact-equality assertion failed and is retained. The subsequent measurement report records the mismatch rather than changing its tolerance. No further training was added. Saved runtime flags have `deterministic_algorithms: false` and `cudnn_deterministic: false`; GPU backward reductions are a possible cause, but this trial did not isolate the cause. Matching seeds/order/RNG are insufficient to promise identical numeric results. B-04's exact match for a different seed/run remains valid bounded historical evidence, not a universal guarantee. This experiment reproduces the declared execution and quality rejection; it **does not qualify exact numerical reproducibility** or a clean causal duration effect.

## Direct image inspection

Eight labeled contact sheets cover all 64 condition images, with each repetition independently inspected. Four adverse condition images and the shared held-out baseline plus all four candidates were also inspected at full resolution. This is unblinded assistant inspection; it is not a calibrated metric, a blinded causal test or a production acceptance review. The table describes the source repetitions; the additional differences below are retained for the installed repetitions.

| Frozen case | Two-update endpoint | Four-update endpoint |
| --- | --- | --- |
| Vase/pears 11760922 | One yellow pear beside a blue vase in every condition. Flat outlines and background panels persist. | Still one pear. The no-trigger adapter changes table borders; the triggered image remains flat and outlined. |
| Vase/pears 11760923 | Stripes/reflections persist; triggered pear-like shapes attach to stems in the vase. The base trigger already causes similar errors. | Both adapter conditions place pear forms on stems in a dark vase, rather than beside one blue vase on a plain table. |
| Geometry 11860922 | Every condition has multiple panels and extra/wrong shapes. The triggered adapter adds a textured white cap. | Multiple panels remain. Without trigger, a large folded white sheet and altered cup-like form replace other shapes. |
| Geometry 11860923 | Red pyramid rather than cube. The triggered adapter turns the white form into a fluted disk on its side. | Still a red pyramid; small textured white scoop/cone forms fail the requested paper identity. |

Every case fails prompt adherence. Activation remains uncertain because the baseline trigger already changes outputs and significant adapter effects also appear without it. Some geometry images have coherent lighting, but this does not repair their object identities or layouts. Neither source checkpoint supports the hypothesis.

The installed repetitions retain the same case failures with different details. The two-update no-trigger vase image loses pear/stem details; its geometry collage changes cone forms. In the four-update repetition, the source table-border change does not recur. Its geometry collage has a different cup/dome, and the no-trigger white object at seed 11860923 becomes a tall feathered ornament with a projecting stick. These differences reinforce the need to inspect each repetition; they cannot be treated as identical images or a reliable duration effect.

| Endpoint and repetition | Vase/pears contact sheet | Geometry contact sheet |
| --- | --- | --- |
| Two updates, source | [Images](evidence/phase-b05-images/short-r1-vase-and-pears.png) | [Images](evidence/phase-b05-images/short-r1-paper-geometry.png) |
| Two updates, installed | [Images](evidence/phase-b05-images/short-r2-vase-and-pears.png) | [Images](evidence/phase-b05-images/short-r2-paper-geometry.png) |
| Four updates, source | [Images](evidence/phase-b05-images/long-r1-vase-and-pears.png) | [Images](evidence/phase-b05-images/long-r1-paper-geometry.png) |
| Four updates, installed | [Images](evidence/phase-b05-images/long-r2-vase-and-pears.png) | [Images](evidence/phase-b05-images/long-r2-paper-geometry.png) |

The held-out diagnostic uses seed 9252401. Its baseline and both candidates divide the image into horizontal bands with oversized fruit and cropped plate/table objects. The four-update candidate adds glass-like objects in cropped bands; it does not produce the requested coherent cake, grapes, dried-fruit and stemmed-glass composition. This seed differs from B-03/B-04, so these previews do not establish a repair or regression relative to those earlier seeds. They are not part of the frozen selection matrix.

The installed held-out candidates also retain the banded composition. Fruit details differ, and the four-update repetition adds a cropped stemmed glass and cake-like rectangular form in its top band. The central plate remains oversized fruit rather than the requested coherent scene.

## Recorded disposition

Packet `b9396c951bfdd1b7d854b6fdd641b9c065b354b267f5be1ef3f3a016ef2bd474` binds every final checkpoint and image. Decision `52b4990afefce9c3e752cb100c53072aeff5b4f5d28b7cddc53144c58cb8e336` embeds all sixteen case/seed reviews and rejects every member and both endpoints. `selected_endpoint` is null and `promotion_eligible` is false. Lower held-out loss at four updates did not select it. The numerical mismatch and quality failures are separate negative outcomes.

The [verification record](evidence/phase-b05-verification-20260924.json) includes 1,299 source and 1,299 installed tests, source/installed public replay, exact 71-module package parity, the four actual attempts, decoded-image receipts, numerical comparisons and review observations. It preserves 802 historical files, the catalog head and SCM 0.5.0. All owned workers/jobs are stopped, the shared device registry is idle, and the temporary server is stopped. No production acceptance, activation, release or new training beyond the declared budget occurred.

## Admission and retained failures

Two CLI launches were refused before any training attempt was created because available host commit memory was below the existing 24 GiB floor. The original refusal occurred with the temporary ComfyUI server in GPU mode. Its identity-verified process was stopped and restarted in CPU mode for queue observation. A later installed repetition was also refused at the floor; its receipt remains separate from any admitted execution. The queue service was subsequently restarted with unused API nodes disabled. Worker configuration, budgets and admission floors were unchanged. No unrelated applications were stopped.

The initial B-05 focused checks passed 30 tests; the expanded experiment and CLI checks passed 61. A separate invocation with an incorrect test filename collected no tests and remains retained as a failed verification attempt. Historical replay and package checks are recorded separately from model execution and image quality. The earlier B-04 failed publication and all snapshotted historical artifacts remain part of the preservation check.
