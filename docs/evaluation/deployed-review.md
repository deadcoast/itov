# Deployed loader mapping and candidate disposition

C-03 adds a supported decision path after a complete [deployed corpus comparison](deployed-evaluation.md). Loader compatibility, decoded artifacts and quality judgments are separate evidence. No command here changes the catalog or activates a candidate. The [C-05 lifecycle](candidate-lifecycle.md) consumes these complete decisions through a separate explicit preview/apply path.

## Verify the actual exported loader targets

```powershell
uv run --inexact --locked itov evaluation mapping workspace/state/evaluation/plans/PLAN_ID.json --save --json
uv run --inexact --locked itov evaluation mapping-inspect workspace/state/evaluation/mappings/MAPPING_ID.json
```

`mapping` freshly validates the plan's candidate, training inputs, deployed LoRA, checkpoint and declared runtime files. It launches the configured ComfyUI Python in isolated mode, loads the actual checkpoint on CPU with an FP16 UNet, and calls the installed `model_lora_keys_unet`, `convert_lora`, `load_lora` and `load_lora_for_models` functions. It requires every exported tensor to belong to exactly one up/down pair, every pair to map to a distinct existing UNet target, compatible base/up/down shapes, finite adapter values, the supported absent-alpha scale of one, and complete patch registration at every declared adapter strength. The worker hides CUDA devices before importing ComfyUI and verifies that no CUDA device is visible and every checkpoint/adapter tensor is on CPU. It records whether the library initialized its CUDA subsystem; that flag can be true even with zero visible devices. GPU rendering is a separate test of application during inference.

The immutable certificate binds the evaluation plan, candidate and deployed artifact; full per-target mappings; accepted strengths; declared runtime and additional mapping/adapter source files; worker implementation bytes; command; request; result; and log. Attempts retain their own files, including failures. The probe has a ten-minute timeout. It consumes host memory for a checkpoint load, even though it does not use the GPU. Run it when host memory is available.

`mapping-inspect` rehashes those inputs and revalidates coverage without importing Torch or connecting to the server. An installed ITOV package can replay a source-created certificate when the worker bytes match and its retained original worker path still exists. Hashes establish consistency, not authenticity or exhaustive dependency attestation. The certificate does not prove the running server's in-memory cache or numerical equivalence with Diffusers.

## Inspect all images and matched conditions

```powershell
uv run --inexact --locked itov evaluation review-packet workspace/state/evaluation/plans/PLAN_ID.json --mapping workspace/state/evaluation/mappings/MAPPING_ID.json --save --json
uv run --inexact --locked itov evaluation review-inspect workspace/state/evaluation/review-packets/PACKET_ID.json
```

This requires a complete version-two comparison, current loader certificate and successful full PNG decoding. The sealed packet contains the technical report, exact prompts and expectations, image file and decoded RGB identities, and all matched comparisons. Each comparison binds base/plain, base/trigger, adapter/plain and adapter/trigger at one case, seed and strength. No missing condition or changed artifact is accepted.

The sibling `PACKET_ID.md` displays every image by case, seed, strength and plain/trigger condition. The sibling `PACKET_ID.review.json` is an editable template. Repeating packet creation preserves existing edits. Fill every image's prompt-adherence and image-quality judgment and every comparison's activation-specificity, preservation and usable-strength judgment. Each judgment needs a verdict, concrete notes and explicit uncertainty. The reviewer, reviewer kind (`assistant` or `human`), inspection method and limitations are required. Optional local evidence sources are hashed. Direct inspection is necessary while the C-02 border screen remains unqualified and semantic evaluator predictions remain unavailable.

Assess the baseline trigger effect separately from adapter activation. Changed pixels, a smoother background or a more painterly image in both conditions do not by themselves establish trigger specificity. Record existing base failures alongside new regressions. Include all seeds and strengths, even when an early failure already prevents acceptance. Exposed cases remain excluded from training/tuning as specified by the frozen corpus policy; inspection does not restore a blind holdout.

## Record and replay the decision

```powershell
uv run --inexact --locked itov evaluation decide workspace/state/evaluation/review-packets/PACKET_ID.json --review workspace/state/evaluation/review-packets/PACKET_ID.review.json --save --json
uv run --inexact --locked itov evaluation decision-replay workspace/state/evaluation/decisions/DECISION_ID.json
```

The packet freezes the rubrics and decision policy. Any failing adapter-image or comparison criterion produces `rejected`. In the absence of failures, any `uncertain` or `unavailable` required judgment produces `inconclusive`. Only all passing required judgments produce `accepted_for_matrix`. Base-image judgments remain mandatory context, but a base failure alone does not reject a candidate that fixes it. Counts remain categorical evidence, without a synthetic quality score.

Every outcome retains `promotion_eligible: false`. `accepted_for_matrix` is a bounded review conclusion, not production activation. C-05's `candidate preview` freshly replays this decision and applies its own versioned activation policy; the old decision format and its meaning remain unchanged. Legacy training-only `promotion apply` cannot activate. An assistant or human assertion is not independently authenticated by its recorded label.

Replay checks the complete technical matrix and mappings again, current source/image/review references, exact row ordering, every criterion, and the recomputed disposition. Altering a verdict, swapping an image or strength, dropping a case, changing rubric text or resealing a fabricated summary is refused. Publication rehashes observed inputs at the operation boundary. Concurrent file changes remain possible between commands; this is not a filesystem-wide transaction.

Exit 0 means a valid packet, mapping or recorded decision, including adverse dispositions. Exit 2 means invalid, incomplete or stale evidence. Read `disposition` and the required-judgment counts; a successful command is not candidate acceptance. Core review/replay imports no ML or image library and performs no HTTP. Serialize commands against a real workspace because evaluation replay takes the shared execution lock.

## Sampler comparisons

C-03's comparison uses stock ComfyUI `dpmpp_2m` with `karras`, 20 steps, CFG 7, 512 × 512, strengths 0.25/0.5/1.0, the pinned SDXL checkpoint and the exported UNet-only adapter. The earlier Diffusers worker is configured with `EulerDiscreteScheduler`, `use_karras_sigmas: false`, leading timestep spacing and offset 1 from the pinned local SDXL configuration. Its separately constructed `DDPMScheduler` is used for training noise; it does not replace the pipeline's inference scheduler.

Both paths use 20 steps and CFG 7, but their algorithms and schedules differ. Diffusers creates inference noise with a CUDA generator; ComfyUI creates noise on CPU. The earlier worker uses BF16 pipeline weights and an explicit FP32 VAE decode; the C-03 server reports FP16 UNet/text encoder weights and BF16 VAE loading. Identical integer seeds do not establish identical latent noise or arithmetic. These are documented runtime comparisons, not controlled sampler parity. Do not attribute cross-runtime image differences solely to export correctness, training or the adapter. A future parity study must bind and control those differences explicitly.

