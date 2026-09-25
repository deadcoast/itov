# C-03 deployed candidate review

This record is being completed while the full 288-condition run and direct inspection finish. It does not yet close C-03. The candidate has already shown required-object failures; technical loader success does not reverse them.

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

## Loader compatibility and sampler limits

The supported [loader and review commands](deployed-review.md) load the actual checkpoint and exported adapter through the installed ComfyUI mapping functions. The final CPU probe accounts for all 1,120 tensors as 560 distinct compatible UNet targets and confirms patch registration at all three strengths. Every tensor is on CPU, no CUDA devices are visible, and the final probe reports CUDA uninitialized. The certificate binds model/adapter bytes, target shapes, strength registration, worker bytes, request/result/log and declared runtime sources. It establishes mapping and registration, not an exhaustive attestation of dependencies or the running server's cached tensors.

Earlier Diffusers images used the pinned `EulerDiscreteScheduler` configuration without Karras sigmas, leading timestep spacing and offset 1. The training worker's separate `DDPMScheduler` supplies training noise and does not replace the inference pipeline scheduler. Diffusers inference uses CUDA-generated noise and BF16 pipeline weights with FP32 VAE decode. This ComfyUI run uses CPU-generated noise, FP16 UNet/text encoder weights and BF16 VAE loading. Matching seed numbers, dimensions, steps and CFG therefore do not establish sampler, latent-noise or arithmetic parity. No new Diffusers run or controlled parity experiment was performed.

## Inspection method and acceptance boundary

The assistant directly inspects all conditions as 36 lossless contact sheets, one case/seed per sheet. Each sheet has base, 0.25, 0.5 and 1.0 rows with plain/trigger columns. Labels and prior failures are visible; this is not blinded review. Image judgments cover prompt adherence and coherent image quality. Each matched comparison separately records intended activation specificity, preservation against its base controls and usability of both adapter conditions. Notes and uncertainty accompany every criterion.

The protocol was recorded before the first sheet inspection. Existing base failures remain distinct from adapter-induced regressions. A changed image alone cannot establish intended trigger activation. Missing visibility, ambiguous material/identity and unsupported style attribution remain uncertain. C-02's unqualified border screen and unavailable semantic evaluators do not supply quality judgments here.

Any failed required adapter-image or comparison criterion rejects the candidate for the matrix. With no failures, uncertainty would produce an inconclusive result. An all-pass matrix would still have `promotion_eligible: false`; lifecycle integration is C-05. These exposed prompts, the three-work dataset and one render per condition cannot establish independent holdout performance, general numerical determinism, corpus sufficiency or production quality.

## Retained failures and corrections

The first run request encountered a server-startup connection refusal. Status showed zero started jobs, and resume correctly refused a never-started plan. Once the server was ready, the original plan was refused for changed server-session identity. Those commands and both plan identities remain preserved.

The first loader probe incorrectly treated ComfyUI's cumulative `loaded_keys` set as a per-adapter tensor pair. The worker now traces each loaded up/down tensor by object identity and validates its exported stem against the target. Further probes exposed that `--cpu` alone, and an empty CUDA visibility setting, did not isolate this installation from CUDA. The final worker and parent use `CUDA_VISIBLE_DEVICES=-1` before imports and require zero visible devices plus CPU tensors. Earlier failed probes remain intact. A first successful isolated probe emitted an empty log and lacked the final environment binding; its certificate is retained as superseded, not current evidence. The final certificate has a nonempty CPU-probe header and explicit environment binding.

The initial focused suite found a nested template alias that could mutate packet bindings in memory; comparison bindings are now deep-copied. A later focused check failed because its expected log omitted the newly added CPU header; the exact expected log was updated. Both failures remain recorded separately from later passing suites.

## Verification and remaining work

The early full source suite passed 1,436 tests before the final loader-isolation/logging and Markdown refinements. Final focused source verification passed 99 tests, including all 56 new deployed-review tests. The final built wheel passed all 1,437 tests on Python 3.11.14. The source environment remains Python 3.13.9 with SCM development tools 0.5.0. These protocol/package checks do not themselves establish image quality.

Final runtime completion, the sealed review/decision, source/installed offline replay, preserved-history checks and owned-server cleanup will be recorded here before C-03 is marked delivered. Version remains 0.13.1, unreleased.
