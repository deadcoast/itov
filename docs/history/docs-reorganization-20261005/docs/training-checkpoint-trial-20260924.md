# B-04 native interruption and restart trial

**Restart comparison passed for this bounded configuration. No model is accepted for production or as a demonstrated quality improvement.** The [checkpoint contract](training-checkpoints.md) describes supported commands and limitations; the [verification record](evidence/phase-b04-verification-20260924.json) binds the protocol, attempts, comparisons, tests and preserved files.

## Declared method and observed execution

Before GPU execution, the assistant recorded a six-update SDXL experiment using the unchanged B-02 selection (two training works, one validation work), rank 8, 512px, micro-batch 1 with accumulation 2, shuffled epochs, peak rate 0.0001, two warmup updates, validation at updates 0/3/6 and checkpoints at updates 2/4/6. Seed was 9042401; the budget was two fresh attempts and one continuation, each bounded to 900 seconds. State and loss comparisons had a predeclared maximum absolute tolerance of 1e-6; Python/NumPy/Torch RNG and sample/schedule comparisons required exact equality. These are restart tolerances, not quality thresholds.

1. The source CLI ran the uninterrupted reference through all six updates, export/reload and 18 diagnostic renders. All three checkpoint bundles passed technical validation.
2. A separate source attempt used the same settings except its experiment ID. The harness observed committed checkpoint 2, the completed update-4 event and a 139,643,256-byte partial checkpoint tensor file. It verified the controller's PID and creation time, then terminated that controller with exit 77 before the manifest existed. The native Job Object stopped its worker. The final `step-000004` directory was absent.
3. Public `training recover` confirmed exit and released the abandoned lease, preserving the failed attempt. `training checkpoints` reported complete step 2 and the partial directory. Public `resume-plan` refused the partial manifest with exit 2. No checkpoint was inferred from the later uncommitted step events.
4. The installed Python 3.11 CLI planned a new continuation from the exact committed step-2 manifest. Its separately provisioned Python 3.13/Torch worker restored state and executed updates 3–6, producing new checkpoints 4/6 and complete export/image evidence. All 17 files in the stopped source attempt's post-recovery snapshot remained byte-identical.

The three attempts performed 14 optimizer updates in total: six reference updates, four before interruption and four continuation updates. The resumed logical training history has six updates, including the two inherited from its checkpoint. Six complete bundles and one incomplete staging directory remain locally; no previous attempt was overwritten or silently retried.

## Comparison results

| Check | Observed result |
| --- | --- |
| Independent fresh attempts at committed update 2 | All 1,120 parameter tensors and both sets of 1,120 AdamW moments equal; maximum absolute difference 0 |
| Reference versus installed continuation at update 6 | All parameter and moment tensors equal; maximum absolute difference 0 |
| Optimizer counter and next sample/rate position | Exact agreement at both compared checkpoints |
| Python/NumPy RNG metadata and Torch CPU/CUDA RNG bytes | Exact agreement at both compared checkpoints |
| Six training losses and three validation observations | Maximum absolute difference 0 |
| Exported adapter | Tensor values and serialized SHA-256 equal |
| Sample/noise/rate order and inherited committed events | Exact agreement |

The reference and continuation used the same RTX 5090, driver 616.64 and recorded Torch 2.13.0+cu130 / Diffusers 0.38.0 / PEFT 0.21.0 environment. Final held-out loss was 0.010490909, versus 0.010571631 before training. Full worker elapsed times were 77.95 seconds for the reference and 80.13 seconds for the continuation, including loading, checkpoint serialization, export and rendering. Both reported 8,172,685,312 bytes peak CUDA allocation; reserved peaks differed. The continuation reconstructs frozen caches and validates checkpoint state. One timing per path, while regression tests also ran, cannot establish restart speed or general capacity.

Actual Torch CPU tests separately exercised all 12 batch/accumulation × sampler × schedule combinations, consuming all three host RNG sources and using BF16 linear/dropout computation. Each restored at update 2 and reached update 5 with exact parameter/moment and subsequent RNG agreement, within its declared 1e-7 state tolerance. An injected write interruption retained the prior complete checkpoint and the new partial tensor file; an attempted overwrite of the complete bundle was refused. CPU fixtures are distinct from the native SDXL exercise.

## Image inspection and quality disposition

All 36 generated PNGs were fully decoded and checked as 512×512 RGB. The assistant inspected both complete contact sheets and three original continuation images at 512px. The 18 corresponding reference/continuation images have matching hashes. Contact tiles are reduced to 256px; this is a bounded visual judgment on reused diagnostic prompts, without a calibrated quality metric or independent human acceptance.

- [Reference contact sheet](evidence/phase-b04-images/uninterrupted.contact.png) and [continuation contact sheet](evidence/phase-b04-images/resumed.contact.png): all held-out and four-condition case images remain visible.
- Vase/pears seed 11760922 still gives **one pear**, rather than exactly two, in baseline and adapter conditions. The [full-resolution continuation image](evidence/phase-b04-images/resumed-one-pear.png) also retains a flat outlined treatment and prominent background/border lines.
- Vase/pears seed 11760923 retains a striped/grid background and stem-attached pear-like forms instead of two pears beside the vase. The adapter changes appearance without the trigger as well as with it; specificity is unresolved.
- Paper geometry seed 11860922 still produces divided panels and extra forms. Seed 11860923 gives a red pyramid-like object instead of the requested cube, with a textured white form. The [full-resolution continuation example](evidence/phase-b04-images/resumed-geometry.png) preserves this identity failure.
- The [held-out continuation preview](evidence/phase-b04-images/resumed-heldout.png) contains cake, grapes, a plate and a stemmed glass, but uses a cool teal/gray background and stylized treatment. Its seed differs from B-03's held-out preview, so the glass's presence is not evidence that training fixed the earlier omission.

No new ComfyUI deployment matrix, activation, promotion or release was performed. The temporary server was used for queue/admission checks and then its identity-verified process was stopped, restoring its initially stopped state. The original rejected candidate and unfavorable images remain unchanged. This experiment qualifies restart behavior in one bounded environment; experiment/checkpoint selection remains B-05 and broader data/model-quality work remains open.
