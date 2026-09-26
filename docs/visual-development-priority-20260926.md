# Development priority: images, silent image-to-video, then usable training

The user redirected development on 2026-09-26: deprioritize audio completely and
address the image and image-to-video models' lack of useful operation first.
This supersedes the audio/listening completion gates in the earlier D-02 plans.
Audio is deferred, not accepted or completed. D-02 remains active for visual work.
The user subsequently added a third priority: an easy-to-use, stable training
pipeline with reference image input and image/video description fields.

## Current evidence

- The [base image review](evaluation-corpus-baseline-20260924.md) recorded 7 passes,
  52 failures and 13 uncertain images. Object counts, identity, layout, framing and
  unwanted panels failed. These results do not establish a usable image model.
- The [deployed candidate review](deployed-candidate-review-20260924.md) rejected
  the candidate. The [C-04 investigation](c04-investigation-20260924.md) did not
  resolve the required cases. More adapter training is not the immediate next step.
- The [extended video review](d02-media-verification-20260925.md) retained an
  unrequested hand in the 121-frame clip and uncertain camera-orbit adherence.
  [Successful browser playback](d02-playback-verification-20260926.md) proves
  playback behavior, not useful visual generation.

## Development order

1. **D-02.1 — usable base image generation, active.** Audit the pinned checkpoint,
   conditioning, graph, resolution and sampling path against its reference
   workflow. Isolate implementation/configuration faults from model limitations.
   Use the exposed diagnostic cases and explicit base-only controls before more
   LoRA training. Implement justified corrections through the supported image
   commands, then inspect every output across predeclared prompts and seeds.
   Establish correct subjects/counts, layout and coherent framing in a bounded
   working recipe; retain every failure and existing rejected-candidate decision.
2. **D-02.2 — usable silent image-to-video, next.** Start with inspected source
   images. Diagnose the added hand and inadequate requested motion against the
   pinned video workflow. Validate subject/scene preservation, temporal coherence
   and requested motion across complete clips and repeated seeds. Retain the old
   hand clips as regressions. An MP4 that decodes successfully is insufficient.
3. **D-02.3 — easy-to-use, stable training workspace, third priority.** Provide a
   graphical reference image section, per-image/video description fields, tested
   training presets, progress, checkpoints/recovery and a separate test-prompt
   preview. Reuse the actual training controller and preserve user projects.
   [Requirements](training-workspace-requirements.md) distinguish current image
   LoRA support from the additional backend work needed for video training.
4. **D-03 visual checks and D-04/D-05 visual runtime/recovery work, afterward.**
   Integrate the checks, measurements and operator behavior that make the working
   visual paths usable. Audio does not block these tasks.

Acceptance criteria and bounded trial budgets must be declared before each new
comparison. Change one justified factor at a time where a causal comparison is
intended, and record when that is not possible. Existing C-01 heldouts remain
excluded from tuning; an exposed development case cannot become a fresh holdout.
Before claiming improvement, evaluate on fresh declared cases as well as retained
regressions, with all outcomes visible. Quality acceptance stays separate from
protocol, package and playback checks.

## Deferred audio scope

Audio generation, audio model acquisition/tuning, dedicated audio repetitions,
listening review, A/V composition, semantic/lip synchronization and voice features
are removed from the active development path. They resume only when the user
explicitly reprioritizes them. No additional audio generation or listening
permission request is needed to continue visual development.

Existing commands, files and historical audio evidence remain available. Their
unfinished review remains unfinished; it is no longer a visual-release dependency.
Ordinary shared-code regression checks may still cover existing audio contracts,
but audio-specific expansion or investigation is deferred.

## Evidence continuity

Earlier dated reports and receipts retain their original bytes and describe the
scope at the time they were written. The prior playback receipt also bound three
living planning documents. Their exact pre-change bytes are preserved under
[the history snapshot](history/d02-before-visual-priority-20260926/TODO.md), with
the original paths and hashes mapped in the
[priority-change receipt](evidence/phase-d02-visual-priority-20260926.json).
Updating development priorities does not convert failed or missing observations
into passes. No model-quality improvement is claimed by this planning correction.

The later [training-priority receipt](evidence/phase-d02-training-priority-20260926.json)
records the added third priority and preserves the previous planning-document
bytes. Neither priority change claims that the requested training interface exists.
