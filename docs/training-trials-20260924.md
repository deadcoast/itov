# B-03 bounded training trials and visual review

**Disposition: the optimization implementation passes these bounded checks; none of the six models is accepted for production or as a demonstrated quality improvement.** Object counts, layout and geometry remain wrong in the diagnostic cases. The previously rejected candidate and its evidence are unchanged.

The [configuration contract](training-configuration.md) documents the supported settings. The [verification record](evidence/phase-b03-verification-20260924.json) retains the protocol, exact plan/result identities, sample/noise order, observations, file hashes and command receipts.

## Declared experiment

Before executing SDXL, the assistant recorded six four-update trials, a 900-second limit per trial, the exact worker source hashes, technical success criteria and two matched batch/accumulation comparisons. Every trial used the unchanged B-02 frozen selection: Roesen and Ream in training, Peale in validation. Seed was 9032401, peak learning rate 0.0001, resolution 512px. No dataset, quality prompt, negative prompt or quality seed was changed in response to results.

The constant trials used sequential sampling, rank 4 and no warmup. Warmup trials used shuffled epochs, rank 8 and two warmup updates. All six completed four optimizer updates, checked all 1,120 adapter gradients/state entries per update, changed all 1,120 exported tensors, reloaded the serialized adapter and generated 18 diagnostic images. Five trials used the source CLI; `batched-warmup` used the installed wheel. Both use the same separately provisioned Python 3.13/Torch 2.13.0+cu130 training environment on the RTX 5090. Installed core commands ran under Python 3.11.

| Trial | Micro-batch / accumulation | Validation updates, including initial | Four update sections, seconds | Training peak allocated, GiB | Whole worker peak allocated / reserved, GiB | Final held-out loss |
| --- | --- | --- | --- | --- | --- | --- |
| serial-constant | 1 / 1 | 0, 1, 2, 3, 4 | 4.26 | 5.186 | 7.579 / 8.506 | 0.128778368 |
| serial-warmup | 1 / 1 | 0, 3, 4 | 4.90 | 5.254 | 7.611 / 8.580 | 0.129272223 |
| accumulated-constant | 1 / 2 | 0, 2, 4 | 8.44 | 5.208 | 7.579 / 8.523 | 0.128540337 |
| accumulated-warmup | 1 / 2 | 0, 2, 4 | 7.63 | 5.297 | 7.611 / 8.621 | 0.129050031 |
| batched-constant | 2 / 1 | 0, 2, 4 | 5.02 | 5.362 | 7.578 / 8.477 | 0.128521502 |
| batched-warmup, installed | 2 / 1 | 0, 2, 4 | 6.03 | 5.427 | 7.610 / 8.574 | 0.129010543 |

Initial held-out loss was 0.130279943 in every trial, using the same independent validation noise seed. These small loss reductions are diagnostics. The trials confound rank, sampler and schedule across the constant/warmup groups, and effective batch changes the number of examples seen. They cannot rank these options by learning quality. Each trial ran once; timings include gradient/state checks, exclude event publication, and do not establish a throughput claim. Full worker times were 54.86–69.02 seconds, including loading, caching, validation, export/reload and rendering. CUDA counters cover this process; they do not measure a whole-device capacity envelope. The lowest recorded available host commit was 17.11 GiB.

Matched accumulation/batch pairs had identical flattened sample/noise streams, rank, declared initialization seed and learning rates. Their BF16 computations were not identical. Maximum exported-weight absolute differences were 0.0006239153 for the constant pair and 0.0004621031 for the warmup pair. Relative L2 differences for the initially zero LoRA up matrices were about 8.62% and 7.22%; reporting only the much smaller whole-adapter relative difference would obscure this. Initial tensors were not separately saved. No SDXL equivalence tolerance was declared, so these are observations, not an equivalence pass. Separate actual-Torch CPU checks passed all 12 admitted batch/sampler/schedule combinations against an independent FP32 full-batch reference at a predeclared 1e-6 tolerance.

## Direct image inspection

All 108 generated PNGs were hash-checked, fully decoded and confirmed to be 512×512 RGB. The assistant directly inspected all six contact sheets below. Each sheet shows the paired held-out preview first, then the two cases at both frozen seeds in columns `base_plain`, `base_trigger`, `adapter_plain`, `adapter_trigger`. Tiles are reduced to 256px for comparison. Four original 512px images from the installed trial were also opened directly; links follow the findings. This is an assistant visual judgment over a tiny, reused diagnostic set, not a calibrated automated metric or independent human acceptance.

| Trial | Complete contact sheet | Disposition |
| --- | --- | --- |
| serial-constant | [18 images](evidence/phase-b03-images/serial-constant.contact.png) | Not accepted |
| serial-warmup | [18 images](evidence/phase-b03-images/serial-warmup.contact.png) | Not accepted |
| accumulated-constant | [18 images](evidence/phase-b03-images/accumulated-constant.contact.png) | Not accepted |
| accumulated-warmup | [18 images](evidence/phase-b03-images/accumulated-warmup.contact.png) | Not accepted |
| batched-constant | [18 images](evidence/phase-b03-images/batched-constant.contact.png) | Not accepted |
| batched-warmup | [18 images](evidence/phase-b03-images/batched-warmup.contact.png) | Not accepted |

| Case / seed | Observations across the six trials | Implication |
| --- | --- | --- |
| Vase and pears / 11760922 | One pear beside a blue vase, rather than exactly two pears. Flat outlined treatment and prominent border/background lines persist in baseline and adapter conditions. | Count and target-treatment failures remain. This shared baseline failure is not evidence of a candidate-only regression. |
| Vase and pears / 11760923 | Strong striped/grid backgrounds; pear-like forms attached to stems or yellow flower-like forms replace the requested pair beside the vase. Serial warmup's untriggered adapter gives a cluster of many yellow forms; accumulated/batched warmup give outlined flower-like forms. Constant batch/accumulation variants also retain stem-attached forms. | No demonstrated fix for object arrangement or specificity; visible differences without the trigger remain. |
| Paper geometry / 11860922 | Divided compositions contain multiple cones/other forms and extra objects in every condition, rather than a single red cube and white cone. | Layout, count and identity failures remain in both baselines and adapters. |
| Paper geometry / 11860923 | A red pyramid-like object replaces the cube. White forms vary between cone-like, elongated, textured and fan-like shapes; serial warmup's triggered adapter is particularly fan-like. | Cube identity fails throughout; changes in the white form do not establish material/shape preservation. |
| Held-out Peale caption / 9232401 | Cake, grapes and a plate remain recognizable, but the requested stemmed glass is absent. | A plausible-looking preview does not fulfill the complete caption or establish generalization. |

Full-resolution installed-trial examples: [one pear](evidence/phase-b03-images/batched-warmup-vase-11760922.png), [divided geometry](evidence/phase-b03-images/batched-warmup-geometry-11860922.png), [red pyramid and textured white form](evidence/phase-b03-images/batched-warmup-geometry-11860923.png), and [held-out cake/plate without the glass](evidence/phase-b03-images/batched-warmup-heldout.png). All original images remain in their local run folders with hashes in the verification record.

These are Diffusers worker renders of each reloaded adapter. No new ComfyUI deployment matrix or model activation was performed. The server was used for queue/admission checks, then the exact owned process was stopped to restore its initially stopped state. Existing quality failures, four-update budgets and the three-work corpus prevent a model-quality claim. Checkpoint/restart semantics are the next engineering task, B-04; experiment selection and broader quality evaluation remain B-05 and Phase C.
