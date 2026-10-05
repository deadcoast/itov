# D-02.1 FLUX code verification

**The experimental inference integration is implemented; actual GPU execution and
model quality are unqualified. D-02.1 remains active.** The user requested continued
code work with further GPU runs deferred. This constraint arrived after the prior
[21-image SDXL comparison](d021-image-results-20260926.md) had finished. No new
generation, GPU training, audio work or FLUX weight download occurred here.

## Implemented scope

The [FLUX workflow](flux-image-workflow.md) adds explicit model selection to
`inference spec` and `inference capabilities`, a strict v3 specification, three
pinned model assets, stock distilled sampling, live qualification and existing
owned execution/recovery/navigation. SDXL remains the default and retains its
v1/v2 identity. Nonempty negative prompts, adapters and incompatible SDXL settings
are refused before publication. Missing local assets fail preparation without
starting a server, acquiring a device lease or staging a deployment.

This is text-to-image backend code. Reference-image editing, a FLUX training
backend and the requested graphical training workspace are not implemented.
There is no model activation, package release or Git publication.

## Reference and protocol evidence

Pinned official workflow commit
`25ff90a51cc8f6ee56bd78ec3b11f294925fb36d` provides the distilled text-to-image
topology. Static comparison matched **12 node types and 23 connections/settings**.
The FP8 diffusion selector differs from the BF16 text template and is corroborated
by the official FP8 distilled edit template. User prompt/seed, immutable output
names and asset-hash metadata replace interactive template controls. Reference
editing nodes are not part of this integration.

Official Hugging Face metadata supplies the three SHA-256 identities, exact
repository revisions and file sizes. The Qwen3 encoder hash matches both Comfy's
Z-Image and Flux2-Klein repositories. Raw metadata/template snapshots are retained
under `docs/evidence/phase-d021-flux-sources/`. Twenty relevant model, sampler,
decoder and tokenizer source files are present in the installed ComfyUI checkout
and included in the new capability's runtime binding. Reading these files does
not prove node import, model load, GPU memory adequacy or successful rendering.

The new protocol tests use tiny fake model files and a local HTTP server returning
constructed PNG fixtures. They exercise model/settings refusal, changed model or
tokenizer bytes, stock-node/schema changes, ambiguous loader paths, resealed
graph/seed tampering, owned batch completion, offline replay, workspace navigation
and lost-acknowledgement reconciliation. Fixture success is not FLUX inference.

## Verification outcome

The [verification receipt](evidence/phase-d021-flux-code-20260926.json) records final
source/installed test counts, package parity, installed commands and preservation
checks. The initial focused run passed **28 new FLUX checks plus nine request
checks**. Lint and formatting checks passed. Full source and installed regression
results are recorded separately from the new-feature fixture coverage.

The complete source regression suite passed **1,624 tests in 22 minutes 12 seconds**,
with CUDA visibility disabled. No test failed and no test assertion was weakened.

The installed Python 3.11 wheel passed **232 focused checks**. Source, sdist,
wheel and clean core installation match across **88 Python modules and README**;
**18 installed command checks** passed. Formatting passed across 147 files.

The core installation has no Torch, Diffusers or Pillow. Installed commands are
run from an unrelated working directory with CUDA visibility disabled. They
exercise capabilities, draft/save/repeated-save, invalid settings, missing real
FLUX assets and the unchanged SDXL default. Seven existing SDXL specifications
retain their content identity; seven completed SDXL plans replay their 21 retained
images offline through the new package. Replay leaves quality unestablished.

The first metadata fetch and initial package dependency resolution hit the
sandbox's socket restriction. The metadata fetch succeeded through the approved
public-metadata request. Package installation succeeded from the existing local
uv cache with `--offline`; the failed logs remain. No dependency environment was
replaced and SCM 0.5.0 remains unchanged.

Prior evidence is retained. Exact pre-change source and document bytes are under
`docs/history/d021-before-flux-code-20260926/`, with mappings in the new receipt for
earlier manifests that bound those paths. Earlier GPU failures, model judgments
and the initial receipt's corrected finalizer-log error are not rewritten.
Scoped Git attributes disable line-ending conversion for the new D-02.1 history
and upstream snapshots so those archived byte hashes survive future checkouts.

## Pending qualification

When the user resumes GPU work, install and hash the exact declared assets, run
the graph through the real stock runtime, measure resource behavior and test
actual interruption/recovery. Declare new prompts/seeds and the decision criteria
before inspecting new model outputs. Treat the prior SDXL cases as exposed
regressions. Complete visual review is required before claiming a working bounded
recipe; code, schema, file integrity and package checks cannot grant that verdict.
