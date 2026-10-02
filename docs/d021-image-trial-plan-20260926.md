# D-02.1 base-image comparison — declared before execution

Hypothesis: the earlier 512px evaluation understates the usable output of the
pinned SDXL base. The [ComfyUI reference workflow](https://comfyanonymous.github.io/ComfyUI_examples/sdxl/)
specifies roughly one megapixel, including 1024×1024. This is a hypothesis to test,
not a claim that resolution resolves the known composition failures.

## Audit and intervention

The current graph connects checkpoint CLIP to positive/negative conditioning,
checkpoint UNet to the sampler and checkpoint VAE to decoding. The installed
ComfyUI `encode_model_conds` supplies width and height from latent dimensions;
SDXL's fallback 768 values are not evidence of a live conditioning mismatch.
No graph rewiring or explicit conditioning override is justified by this audit.

Compare 512×512 and 1024×1024 using the same pinned checkpoint, prompts, negative
prompts, seed numbers, 20 `dpmpp_2m`/`karras` steps and CFG 7, without any adapter.
Only resolution changes. Different latent shapes do not imply identical noise
tensors. This comparison is about the two configurations, not pixel-level paired
noise or general causality. Retain all outputs.

## Cases and budget

- Development comparison: the existing exposed `vase-and-pears` and
  `paper-geometry` diagnostic prompts, verbatim. Seeds are 11760922..11760924 and
  11860922..11860924 respectively. The first two seeds per case were used before;
  the third is an additional development seed. Six images at each resolution.
- Fresh-case check: three newly declared prompts below, three consecutive seeds
  each, at 1024×1024 only. They are written before any new render is inspected and
  will not be used to choose prompts or settings in this comparison. All use
  negative prompt `text, watermark, signature, frame`.
- Total budget: **21 images**, 420 sampler steps, one sequential worker. No audio,
  video, adapter training, model downloads or model activation in this trial.
  Use separately owned workspaces per resolution to allow declared paired seed
  numbers without rewriting any existing seed reservations. Existing heldouts
  remain excluded from tuning and from this new development comparison.

| Fresh case | Prompt | Seeds |
| --- | --- | --- |
| yellow-duck | One yellow rubber duck centered on a plain blue tabletop, side view, the entire duck visible, empty background, studio photograph | 226092601..226092603 |
| two-lemons | Exactly two whole yellow lemons resting separately on a bare wooden table, both fully visible, plain gray background, studio photograph, no other objects | 226092611..226092613 |
| bottle-apple | One transparent green glass bottle standing to the left of one red apple on a plain gray table, both objects fully visible, plain background, studio photograph, no other objects | 226092621..226092623 |

## Judgments and continuation

Inspect every image for required subject/count, color/shape/material, specified
layout and coherent full framing. Missing/extra objects, split panels, substituted
shapes or contradictory layout fail; an obscured required feature is uncertain.
Record per-image observations; do not discard a bad seed or average it away.

The resolution hypothesis is supported only if 1024 yields more complete passes
on the six development images without losing a prior passing development image.
A bounded working recipe additionally requires all nine fresh images to pass.
Failure or uncertainty keeps visual quality unaccepted and requires a separately
declared next investigation. The historical 7/52/13 baseline remains unchanged.
No inference about unseen prompts or newly trained models follows from this trial.

## Implementation and resource boundary

Add `inference spec --prompt ... --save` to make the existing version-two base
workflow usable without manually constructing a specification. Default to
1024×1024; retain explicit settings and all legacy identities. This is a request
builder, not a model-quality fix by itself. Verify immutable saves, no unexpected
network/model loading and public command compatibility.

The initial machine observation had roughly 1.4 GiB of available host commit.
Before starting this verification session, require at least 12 GiB available
commit for the pinned model/server trial and record the actual readings. This is
a conservative trial admission condition, not a measured general requirement or
a change to the trainer's existing 24 GiB admission floor. Resource refusal is
retained; other applications are not stopped automatically.
