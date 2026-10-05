# D-02.1 image development — first increment

**D-02.1 remains active.** The base-image request builder is implemented and
package-verified. The declared GPU comparison has not run because available
Windows commit memory is below the trial admission budget. No image-quality
improvement or usable-model acceptance is claimed.

## Implemented

`inference spec --prompt ... --save` creates an ordinary version-two base-only
request, with explicit 1024×1024, 20-step, CFG-7 defaults. Operators can override
supported dimensions/settings, seed and count. They can inspect a draft without
writing, then save an immutable specification and follow the returned preparation
action. No checkpoint read, network call, seed reservation or generation happens
while describing an image. Existing v1/v2 specifications, graph identities and
runtime ownership behavior retain their meaning.

The [base-image workflow](../../guides/base-image-workflow.md), `workspace guide models`, README
and operator runbook expose the path. A clean core wheel installation without
Pillow, Torch or Diffusers created/repeated the request from an unrelated working
directory and verified the real pinned SDXL checkpoint through `inference prepare`.
No model was loaded and no inference job was submitted.

## Model-path audit and pending experiment

The checkpoint matches the pinned SDXL base hash. The stock graph connects the
checkpoint model, CLIP and VAE correctly. Inspection of the installed ComfyUI
sampler confirms that latent dimensions populate SDXL size conditioning; the
model class's 768 fallback does not demonstrate a live wiring error.

The older C-01 evaluation ran at 512×512. The
[upstream ComfyUI SDXL example](https://comfyanonymous.github.io/ComfyUI_examples/sdxl/)
recommends roughly 1024×1024. The existing historical v1 image example already
uses 1024; this is a correction to how the next baseline will be tested, not a
claim that every earlier image path used the wrong resolution.

The [declared comparison](d021-image-trial-plan-20260926.md) holds prompts,
sampling settings, checkpoint and seed numbers fixed across 512 and 1024, using
two exposed diagnostic cases. Nine additional fresh-case outputs would check
the 1024 recipe. Budget: 21 images, no adapters, training, audio or video jobs.
The new command will construct all requests through the public installed/source
contract. All images require direct review against the declared criteria.

Initial available commit was approximately 1.4 GiB. The saved admission attempt
observed **1,089,024,000 bytes (about 1.01 GiB)** against the preregistered **12 GiB**
trial condition and refused before server startup. A later reading was about
1.89 GiB. The user was asked to free memory; no other application was stopped,
system memory setting changed or training admission floor relaxed. The prepared
trial driver and refusal remain under `workspace/state/verification/phase-d021/`.

## Verification and retained failures

- Nine new request checks cover draft/save behavior, exact prompt/graph bindings,
  no runtime contact, immutable-save conflicts, invalid inputs and explicit settings.
- The final focused source suite passed **156 tests**; the installed Python 3.11
  wheel passed the same **156 tests**. These include inference ownership/recovery,
  legacy inference, public CLI outcomes and workspace navigation.
- An earlier focused run had **155 passes and one failure**: a fixture HTTP
  response hit Windows `ConnectionAbortedError` after a short client timeout,
  contaminating captured stderr. No assertion was weakened or exception silenced.
  The isolated test and complete focused rerun passed; the failed log is retained.
- Lint passed and formatting passed across 145 files. A final workspace-guide
  line-ending normalization was checked for identical Python AST, then rebuilt.
  Final source/sdist/wheel/core-install parity covers **87 modules and README**.
  Two final installed commands verify the rebuilt guide and unchanged saved request;
  seven earlier installed commands include the real checkpoint check.

The [receipt](../../evidence/phase-d021-development-20260926.json) binds these results and
the trial refusal. Original model/media/quality evidence, the 21 training-worker
source hashes, main catalog HEAD and SCM 0.5.0 are retained. Planning documents
modified by this increment have pre-change snapshots under
`docs/history/d021-before-development-20260926/`.

Next required work: run the declared image comparison when memory admission
passes, inspect every output and record whether the resolution hypothesis holds.
If the recipe fails its declared visual criteria, keep it unaccepted and diagnose
the next factor under a new declared comparison. Silent video and the requested
training interface remain second and third priorities. Audio remains deferred.
