# Training workspace — priority three (D-02.3)

Requested by the user on 2026-09-26: an easy-to-use, stable pipeline to train
models, with a section for reference images and a text section describing the
image or video. This is planned development after usable image generation
(D-02.1) and silent image-to-video (D-02.2). The graphical workflow described here
is not implemented. Audio remains deferred.

## Required user workflow

1. **Create or reopen a training project.** Name it and choose a supported base
   model and training type. Use a tested preset by default, with advanced settings
   available separately. Save the project without requiring manual manifests,
   hash entry or command-line assembly.
2. **Add reference images.** Provide a visible upload/drop area, file/folder
   selection, thumbnail gallery and removal from the project. Preserve original
   files. Show which items are included, excluded or invalid and why. Preview any
   crop or resize before it becomes training data. Video clips require a supported
   video-training backend; image references are not silently treated as clips.
3. **Describe each reference.** A text section beside the selected preview says
   “Describe this image” or “Describe this video.” Save that text with its specific
   item as the training caption. For clips, include the action/motion when relevant.
   Allow explicit bulk edits to selected items; never silently overwrite captions.
   Keep a project-level “What should the model learn?” field separate from these
   factual descriptions. Describe any required trigger token in plain language.
4. **Check readiness and train.** Show actionable input/model/environment/memory
   problems before starting. Explain training/validation selection and keep related
   or duplicate media from crossing those sets. Display the selected settings and
   resource budget, then start one owned run with a clear progress view.
5. **Stop safely and resume.** Save checkpoints, expose the last completed
   checkpoint, and recover after an application restart or worker failure. Preserve
   edits and completed work. State what will be resumed and what may be repeated;
   do not promise continuation from an unsaved update. Prevent duplicate starts
   while an existing job is running or its state is uncertain. Keep the complete
   error available with a clear next action.
6. **Preview and save the trained result.** Provide a separate “Test prompt” field
   describing the desired new image/video. Show base-versus-trained outputs using
   recorded settings, with checkpoint selection and run history. Training captions
   teach from supplied examples; test prompts request new outputs. Save/export a
   compatible trained result without silently activating a failed candidate or
   treating a finished training job as proof of useful quality.

## Backend integration and missing support

Reuse the [dataset import](dataset-import.md), [review/freeze](dataset-review.md),
[configured training](training-configuration.md),
[checkpoint/recovery](training-checkpoints.md),
[experiment](training-experiments.md) and
[candidate lifecycle](candidate-lifecycle.md) contracts. Keep the existing GPU
ownership, input freshness and checkpoint integrity checks. The interface must
surface the real controller's state instead of maintaining a second job state.

The current trainer is bounded SDXL image LoRA training; it does not train an
arbitrary image/video model. Integrating user-provided local datasets into the
supported training/quality path is required work, not an assumption that the
existing curated museum path already covers it. Keep dataset manifests and
training settings versioned so editing a project cannot mutate an active run.

Video training requires its own implemented and qualified trainer, compatible
model/data selection, clip preparation and temporal validation. Show unavailable
training types honestly until supported; do not label frame extraction or still
image training as learning video motion. Qualify image and video training
separately. Broad full-model training is not implied by the existing LoRA backend.

## Acceptance evidence

- Complete an installed graphical session using user-supplied reference images and
  descriptions: import, prepare, train, preview, save and reopen, without manually
  editing JSON or invoking commands. Verify captions stay attached to the correct
  media through reordering, removal, saving and reopening.
- Exercise invalid media, missing descriptions, duplicates/split leakage, missing
  dependencies and insufficient memory with actionable messages and preserved
  project data. Test edited inputs during training without changing the active run.
- Exercise double starts, safe stopping, restart/crash recovery and continuation
  from a complete checkpoint without duplicate jobs or lost committed work.
- Inspect actual trained outputs against declared fresh cases and retained
  regressions. Record unsuccessful results as unsuccessful. UI tests and optimizer
  completion cannot establish model quality or general training stability.
- Qualify any video-training support with real clip training, recovery and complete
  visual inspection. Keep it unavailable until that evidence exists.

The [development order](visual-development-priority-20260926.md) remains images,
silent image-to-video, then this training workspace. D-03 through D-05 supply
additional visual evaluation, runtime and installation work as needed; audio is
not a dependency.
