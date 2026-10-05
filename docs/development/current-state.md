# Current implementation and qualification boundaries

Documentation reconciled with repository source on **2026-10-05**. Package version
is **0.13.1** in [pyproject.toml](../../pyproject.toml) and
[the package](../../src/itov/__init__.py); this is unreleased repository work.
ITOV remains incomplete. [TODO.md](../../TODO.md) is the active task authority,
and [CHANGELOG.md](../../CHANGELOG.md) retains delivered increments and failures.

## Product order and execution constraints

1. **D-02.1, active:** usable base image generation. The SDXL request builder and
   experimental FLUX integration are implemented; a usable image recipe has not
   been accepted.
2. **D-02.2, next:** silent image-to-video with subject preservation and requested
   motion. Retained videos include an unrequested hand and uncertain motion adherence.
3. **D-02.3, third:** a stable graphical training workspace with reference media,
   descriptions, progress/recovery and separate test-prompt previews. This UI and
   a video-training backend are not implemented. See the
   [requirements](../requirements/training-workspace-requirements.md).

Further GPU inference/training is deferred until the user resumes it. Audio/A/V
development, listening and synchronization are deferred under the
[priority decision](../decisions/visual-development-priority-20260926.md).
Source, CPU, protocol and package work continues. The shelved mandatory
independent-human gate is not a blocker.

## Implemented scope

| Area | Implemented behavior | Evidence and remaining limit |
| --- | --- | --- |
| Workspace and CLI | Packaged starter inputs, explicit requests, inventory, inspection, dependency diagnostics and shared text/JSON results | [D-01](../reports/2026-09-25/d01-workflow-verification-20260925.md) exercised installed neutral I/O and timeout recovery. Inventory reports recorded state; it does not revalidate models. |
| Catalog and execution | Canonical snapshots/ledger, deterministic planning, qualifications, permanent seed reservation, owned jobs and explicit recovery/cancellation | [Contracts](../contracts/README.md) define cooperative Windows/single-local-GPU scope. Fixture success does not establish arbitrary runtime or concurrency support. |
| Image generation | SDXL v1 preset batches, v2 explicit adapter/base requests, description-based `inference spec`; experimental FLUX v3 | [21-image trial](../reports/2026-09-26/d021-image-results-20260926.md): 1/6 passes at 512px, 0/6 development and 4/9 fresh passes at 1024px. Resolution hypothesis failed. [FLUX code checks](../reports/2026-09-26/d021-flux-code-verification-20260926.md) did not load the model. |
| Silent video | Pinned Wan workflow, explicit duration/settings, completed-image binding, media decode and replay | [Extended media report](../reports/2026-09-25/d02-media-verification-20260925.md) retains hand/motion defects. [Playback continuation](../reports/2026-09-26/d02-playback-verification-20260926.md) establishes playback, not prompt compliance. |
| Datasets and training | Transactional import, identity/caption review, frozen selections, bounded SDXL optimization, durable v4 checkpoints and experiments | [Training contracts](../training/README.md). Two training works and one validation work do not establish corpus adequacy or successful learning. Existing candidate remains rejected. |
| Evaluation | Frozen corpora, deployed matrices and loader mapping, case decisions, numerical reports, artifact measurements and optional evaluator exchange | [C-03 review](../reports/2026-09-24/deployed-candidate-review-20260924.md) rejects the candidate. [C-04](../reports/2026-09-24/c04-investigation-20260924.md) retains numerical and visual failures. The initial border screen missed all six observed natural borders. |
| Candidate lifecycle | Fresh deployed-policy preview/apply, retirement, targeted rollback and journal recovery | [C-05](../reports/2026-09-25/c05-lifecycle-verification-20260925.md) uses synthetic activation fixtures and real rejected-candidate refusal. No real activation or model acceptance is established. |
| Audio/A/V and parallel audio | Existing generation, composition, replay, resource admission and bounded two-worker trial | [Retained contracts](../guides/audio-and-av.md). Development is deferred; listening and synchronization remain unqualified. |
| Discovery and scheduling | Retained designs and offline Met input/curation support | Live acquisition, reverse lookup, phrase-bank curation and scheduled cycles remain Phase E. Original examples are not installed implementations. |

The C-01 baseline retains **7 passing, 52 failing and 13 uncertain** images.
C-03 rendered 288 conditions and inspected 108 matched strength comparisons, but
technical completion did not resolve quality. C-04's six training repetitions
retain four of six numerical pairs outside the declared tolerance and two exact
pairs. These are recorded observations, not new tests performed for this docs update.

## Development environment and latest retained checks

The core package targets Python 3.11+ and has no required third-party runtime
dependencies. The default uv dev group targets Python 3.13+ and includes the ML
libraries needed for native type analysis. The checked Windows `.venv` uses CPU
Torch; ComfyUI CUDA Python and the training environment serve separate purposes.
The actual pins and paths are in [pyproject.toml](../../pyproject.toml),
[training.PINNED](../../src/itov/training.py) and [AGENTS.md](../../AGENTS.md).

| Retained report | What passed at that snapshot | What it does not establish |
| --- | --- | --- |
| [Python pass three, 2026-10-03](../evidence/python-errors-pass3-20261003.json) | Full 1,647-test source suite, package checks and targeted worker behavior | That snapshot still had unresolved imports; it predates the subsequent environment repair. |
| [Development profile, 2026-10-03](../evidence/python-dev-profile-20261003.json) | Pyright zero errors over 88 files; mypy zero errors over 90 checked files; 236 targeted tests; native CPU/import checks; wheel/sdist and `py.typed` parity | The full suite was not repeated in that pass. Mypy skips unannotated bodies by default. No model load or GPU qualification occurred. |
| [Documentation reorganization, 2026-10-05](../evidence/docs-reorganization-20261005.json) | Documentation, preservation and package checks listed in that receipt | Does not replace source-test evidence or establish any model-quality improvement. |

Read each report's exact timing and scope. The docs refresh does not relabel old
test runs as current, clear failures, regenerate hash-bound plans or change any
catalog/model disposition.
