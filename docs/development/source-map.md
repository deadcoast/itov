# Source, contracts and tests

Reconciled 2026-10-05 against all **88 top-level Python modules** in src/itov and the current test filenames. This is a navigation map, not a new source-test result. [Current state](current-state.md) records evidence limits; [CLI inventory](cli-reference.md) covers public actions.

## Dependency and integrity boundaries

The CLI remains dependency-light. Optional Pillow/ML/ComfyUI work runs through explicit worker boundaries; importing a contract must not start CUDA or load models. Source-bound plans can become stale when workers change: regenerate through supported commands rather than rewriting hashes. Preserve canonical JSON, immutable records, lineage, seed reservations and refusal/recovery behavior.

Each group links directly to source and regression tests. Tests are relevant entry points, not an assertion that every possible behavior is covered. [py.typed](../../src/itov/py.typed) is a packaged marker, not an executable module.

## Package, CLI and presentation

Command parsing/dispatch and presentation metadata; CLI metadata stays outside sealed records.

**Source:** [__init__.py](../../src/itov/__init__.py), [__main__.py](../../src/itov/__main__.py), [cli.py](../../src/itov/cli.py), [cli_output.py](../../src/itov/cli_output.py).

**Contract:** [operator-runbook](../guides/operator-runbook.md).

**Tests:** [test_cli.py](../../tests/test_cli.py), [test_cli_contract.py](../../tests/test_cli_contract.py), [test_json_documents.py](../../tests/test_json_documents.py).

## Workspace and diagnostics

Configuration, packaged starter generation, read-only navigation and isolated package metadata probes.

**Source:** [config.py](../../src/itov/config.py), [doctor.py](../../src/itov/doctor.py), [workspace_dependencies.py](../../src/itov/workspace_dependencies.py), [workspace_guide.py](../../src/itov/workspace_guide.py), [workspace_navigation.py](../../src/itov/workspace_navigation.py), [workspace_starter.py](../../src/itov/workspace_starter.py).

**Contract:** [workspace-workflow](../guides/workspace-workflow.md).

**Tests:** [test_config.py](../../tests/test_config.py), [test_cli.py](../../tests/test_cli.py), [test_workspace_workflow.py](../../tests/test_workspace_workflow.py).

## Runtime, API and graph checks

Explicit foreground startup, HTTP metadata and graph validation without implicit submission retries.

**Source:** [comfyui.py](../../src/itov/comfyui.py), [runtime.py](../../src/itov/runtime.py), [workflow.py](../../src/itov/workflow.py).

**Contract:** [runtime-and-jobs](../guides/runtime-and-jobs.md).

**Tests:** [test_comfyui.py](../../tests/test_comfyui.py), [test_runtime.py](../../tests/test_runtime.py), [test_workflow.py](../../tests/test_workflow.py).

## Catalog and canonical ledger

Canonical revisions, immutable snapshots, one HEAD and explicit redo recovery.

**Source:** [catalog.py](../../src/itov/catalog.py), [catalog_store.py](../../src/itov/catalog_store.py), [ledger.py](../../src/itov/ledger.py).

**Contract:** [catalog-and-ledger](../contracts/catalog-and-ledger.md).

**Tests:** [test_catalog.py](../../tests/test_catalog.py), [test_catalog_store.py](../../tests/test_catalog_store.py), [test_catalog_cli.py](../../tests/test_catalog_cli.py), [test_ledger.py](../../tests/test_ledger.py).

## Deterministic planning

Declared graph bindings, selection, seed derivation and immutable replay.

**Source:** [batch.py](../../src/itov/batch.py), [batch_request.py](../../src/itov/batch_request.py), [rotation.py](../../src/itov/rotation.py).

**Contract:** [batch-planning](../contracts/batch-planning.md).

**Tests:** [test_batch.py](../../tests/test_batch.py), [test_batch_cli.py](../../tests/test_batch_cli.py).

## Owned execution and cancellation

Qualification, durable observations, seed reservations and cancellation that preserves uncertain requests.

**Source:** [batch_execution.py](../../src/itov/batch_execution.py), [batch_cancellation.py](../../src/itov/batch_cancellation.py), [jobs.py](../../src/itov/jobs.py), [owned_jobs.py](../../src/itov/owned_jobs.py), [qualification.py](../../src/itov/qualification.py), [execution_store.py](../../src/itov/execution_store.py).

**Contract:** [batch-execution](../contracts/batch-execution.md).

**Tests:** [test_batch_execution.py](../../tests/test_batch_execution.py), [test_batch_cancellation.py](../../tests/test_batch_cancellation.py), [test_jobs.py](../../tests/test_jobs.py), [test_qualification.py](../../tests/test_qualification.py).

## Cross-family/device ownership

Workspace exclusion, same-user GPU leases and exact native-owned process identity/recovery.

**Source:** [execution_ownership.py](../../src/itov/execution_ownership.py), [client_ownership.py](../../src/itov/client_ownership.py), [device.py](../../src/itov/device.py), [locking.py](../../src/itov/locking.py), [windows_process.py](../../src/itov/windows_process.py).

**Contract:** [execution-ownership](../contracts/execution-ownership.md).

**Tests:** [test_execution_ownership.py](../../tests/test_execution_ownership.py), [test_device.py](../../tests/test_device.py), [test_parallel.py](../../tests/test_parallel.py), [test_jobs.py](../../tests/test_jobs.py).

## Measured resource admission

Exact-workload measurement, observer bootstrap and bounded managed parallel admission.

**Source:** [vram.py](../../src/itov/vram.py), [vram_identity.py](../../src/itov/vram_identity.py), [vram_runtime.py](../../src/itov/vram_runtime.py), [worker_bootstrap.py](../../src/itov/worker_bootstrap.py), [parallel.py](../../src/itov/parallel.py).

**Contract:** [vram-profiling](../contracts/vram-profiling.md).

**Tests:** [test_vram.py](../../tests/test_vram.py), [test_parallel.py](../../tests/test_parallel.py).

## Image requests and inference

Versioned SDXL/FLUX requests, pure graph construction, preparation and owned runtime execution.

**Source:** [image_request.py](../../src/itov/image_request.py), [inference.py](../../src/itov/inference.py), [inference_capabilities.py](../../src/itov/inference_capabilities.py), [inference_graph.py](../../src/itov/inference_graph.py), [inference_runtime.py](../../src/itov/inference_runtime.py), [flux_image.py](../../src/itov/flux_image.py).

**Contract:** [candidate-inference](../guides/candidate-inference.md).

**Tests:** [test_image_request.py](../../tests/test_image_request.py), [test_inference.py](../../tests/test_inference.py), [test_inference_runtime.py](../../tests/test_inference_runtime.py), [test_flux_image.py](../../tests/test_flux_image.py).

## Video, audio and composition

Pinned generation specs, completed-source binding, full decoding and immutable composition/replay; audio work deferred.

**Source:** [video.py](../../src/itov/video.py), [audio.py](../../src/itov/audio.py), [audio_media.py](../../src/itov/audio_media.py), [audiovisual.py](../../src/itov/audiovisual.py), [media.py](../../src/itov/media.py), [media_configuration.py](../../src/itov/media_configuration.py), [media_sources.py](../../src/itov/media_sources.py).

**Contract:** [extended-media](../guides/extended-media.md).

**Tests:** [test_video.py](../../tests/test_video.py), [test_audio.py](../../tests/test_audio.py), [test_extended_media.py](../../tests/test_extended_media.py).

## Trigger and scene constraints

Offline vocabulary/collision and explicit lexical constraints, without rewriting prompts.

**Source:** [linting.py](../../src/itov/linting.py), [trigger.py](../../src/itov/trigger.py), [scene.py](../../src/itov/scene.py).

**Contract:** [triggers-and-scenes](../contracts/triggers-and-scenes.md).

**Tests:** [test_trigger.py](../../tests/test_trigger.py), [test_scene.py](../../tests/test_scene.py).

## Dataset declarations/import

Declared provenance, isolated image transforms, complete-bundle commits and retained failed attempts.

**Source:** [training_data.py](../../src/itov/training_data.py), [curation.py](../../src/itov/curation.py), [dataset_manifest.py](../../src/itov/dataset_manifest.py), [dataset_import.py](../../src/itov/dataset_import.py), [dataset_images.py](../../src/itov/dataset_images.py), [dataset_snapshot.py](../../src/itov/dataset_snapshot.py).

**Contract:** [dataset-import](../training/dataset-import.md).

**Tests:** [test_dataset_import.py](../../tests/test_dataset_import.py), [test_training.py](../../tests/test_training.py), [test_quality.py](../../tests/test_quality.py).

## Dataset identity/review

Fingerprints, attributed identity groups, explicit captions/splits and frozen reviewed selection.

**Source:** [dataset_features.py](../../src/itov/dataset_features.py), [dataset_identity.py](../../src/itov/dataset_identity.py), [dataset_inspection.py](../../src/itov/dataset_inspection.py), [dataset_freeze.py](../../src/itov/dataset_freeze.py).

**Contract:** [dataset-review](../training/dataset-review.md).

**Tests:** [test_dataset_review.py](../../tests/test_dataset_review.py).

## Training plans and optimization

Pinned plans, deterministic declared schedules and optional isolated SDXL workers.

**Source:** [training.py](../../src/itov/training.py), [training_config.py](../../src/itov/training_config.py), [training_optimization.py](../../src/itov/training_optimization.py), [training_worker.py](../../src/itov/training_worker.py).

**Contract:** [training-configuration](../training/training-configuration.md).

**Tests:** [test_training.py](../../tests/test_training.py), [test_training_config.py](../../tests/test_training_config.py).

## Checkpoints and continuation

Committed optimizer/RNG bundles, bounded safetensors validation and explicit new continuation plans.

**Source:** [training_checkpoints.py](../../src/itov/training_checkpoints.py), [training_checkpoint_worker.py](../../src/itov/training_checkpoint_worker.py), [checkpoint_tensors.py](../../src/itov/checkpoint_tensors.py).

**Contract:** [training-checkpoints](../training/training-checkpoints.md).

**Tests:** [test_training_checkpoints.py](../../tests/test_training_checkpoints.py).

## Training result validation

Worker completion is separate from read-only validated artifacts and result publication recovery.

**Source:** [training_results.py](../../src/itov/training_results.py), [training_records.py](../../src/itov/training_records.py).

**Contract:** [training-result-states](../training/training-result-states.md).

**Tests:** [test_training_results.py](../../tests/test_training_results.py), [test_assessment_records.py](../../tests/test_assessment_records.py).

## Assessment records and freshness

Immutable internal values and operation-local read observations with final byte-freshness checks.

**Source:** [records.py](../../src/itov/records.py), [review_records.py](../../src/itov/review_records.py), [evaluation_cases.py](../../src/itov/evaluation_cases.py), [evidence_reads.py](../../src/itov/evidence_reads.py), [assessment_context.py](../../src/itov/assessment_context.py).

**Contract:** [assessment-records](../contracts/assessment-records.md).

**Tests:** [test_assessment_records.py](../../tests/test_assessment_records.py), [test_json_documents.py](../../tests/test_json_documents.py).

## Training quality and candidate export

Technical assessment, complete training review packets and export; legacy apply cannot activate.

**Source:** [evaluation.py](../../src/itov/evaluation.py), [quality.py](../../src/itov/quality.py).

**Contract:** [curated-quality-review](../training/curated-quality-review.md).

**Tests:** [test_evaluation.py](../../tests/test_evaluation.py), [test_quality.py](../../tests/test_quality.py).

## Experiments and numerical comparison

Preregistered endpoints/budgets, quality decisions and all-pair numerical reports with declared tolerances.

**Source:** [experiments.py](../../src/itov/experiments.py), [experiment_variance.py](../../src/itov/experiment_variance.py).

**Contract:** [training-experiments](../training/training-experiments.md).

**Tests:** [test_experiments.py](../../tests/test_experiments.py), [test_experiment_variance.py](../../tests/test_experiment_variance.py).

## Corpus and deployed execution

Frozen baseline/comparison matrices, exposure rules and shared owned-job execution/replay.

**Source:** [evaluation_corpus.py](../../src/itov/evaluation_corpus.py), [evaluation_runtime.py](../../src/itov/evaluation_runtime.py).

**Contract:** [deployed-evaluation](../evaluation/deployed-evaluation.md).

**Tests:** [test_evaluation_corpus.py](../../tests/test_evaluation_corpus.py), [test_evaluation_runtime.py](../../tests/test_evaluation_runtime.py).

## Deployed loader and review

Installed loader tensor-target evidence and complete matrix judgments, with isolated optional CPU probe.

**Source:** [deployed_loader.py](../../src/itov/deployed_loader.py), [deployed_loader_worker.py](../../src/itov/deployed_loader_worker.py), [deployed_review.py](../../src/itov/deployed_review.py).

**Contract:** [deployed-review](../evaluation/deployed-review.md).

**Tests:** [test_deployed_review.py](../../tests/test_deployed_review.py).

## Image artifact checks

Full PNG decode, narrow artifact screens and explicit optional-evaluator calibration.

**Source:** [image_media.py](../../src/itov/image_media.py), [image_metrics.py](../../src/itov/image_metrics.py), [image_checks.py](../../src/itov/image_checks.py).

**Contract:** [image-checks](../evaluation/image-checks.md).

**Tests:** [test_image_checks.py](../../tests/test_image_checks.py), [test_evaluation_runtime.py](../../tests/test_evaluation_runtime.py).

## Candidate lifecycle

Fresh deployed authorization, one-entry catalog transitions, retirement/rollback and journal recovery.

**Source:** [candidate_lifecycle.py](../../src/itov/candidate_lifecycle.py).

**Contract:** [candidate-lifecycle](../evaluation/candidate-lifecycle.md).

**Tests:** [test_candidate_lifecycle.py](../../tests/test_candidate_lifecycle.py).

## Adjacent development tools

The [Markdown PDF converter](../../tools/markdown_pdf/README.md) has its own package, tests and [historical validation](../../tools/markdown_pdf/VALIDATION.md). Cipher/Bamboozle test files concern the separate AI/dev_tools package and are not application modules. When supplied, src/PYTHON_ERRORS.js is preserved diagnostic input; that export is absent from this checkout at the documentation review. The retained Python evidence reports describe the prior export.

Neutral starter assets are generated by the packaged workspace_starter module; they require no checkout helper or downloaded image. Packaging checks include Python modules, py.typed and normalized README metadata. The [documentation checker](../../scripts/check_documentation.py) does not modify application state.
