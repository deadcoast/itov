# Original designs and current implementation

The numbered specifications are retained unchanged. They contain design intent,
prototype code and alternate revisions, including known incomplete examples.
The [historical development review](../reports/2026-09-22/development-review.md)
records concrete defects. Current source, contracts and [TODO](../../TODO.md)
determine implemented behavior and remaining scope.

| Original material | Current implementation or contract | Remaining boundary |
| --- | --- | --- |
| [1. Overview](../design_spec/01_overview.md), [2. Workflow pipeline](../design_spec/02_workflow_pipeline.md) | [Workspace](../guides/workspace-workflow.md), [runtime/jobs](../guides/runtime-and-jobs.md), [base images](../guides/base-image-workflow.md), [video](../guides/image-to-video.md) | Cohesive usable generation and graphical training remain Phase D. Original workflow sketches are not API exports. |
| [3. Rotation](../design_spec/03_rotation.md), [4. LoRA stack](../design_spec/04_LoRA_Stack.md) | [Batch planning](../contracts/batch-planning.md), [explicit inference](../guides/candidate-inference.md) | Only declared compatibility and bounded tested model/adapter combinations are supported. |
| [5. LoRA/voice](../design_spec/05_LoRA_voice_pipeline.md) | [SDXL training](../training/training-and-promotion.md), [checkpoints](../training/training-checkpoints.md) | Voice/audio deferred; video training and training UI absent. |
| [6. Audio/visual batch](../design_spec/06_audio_visual_batch.md) | [Media](../guides/extended-media.md), [sequential execution](../contracts/batch-execution.md), [parallel audio](../contracts/parallel-execution.md) | Audio deferred; image/video parallelism and general quality unqualified. |
| [7. Scraper](../design_spec/07_scraper.md) | [Declared dataset import](../training/dataset-import.md), [review/freeze](../training/dataset-review.md) | Live provider acquisition, continuation and quarantine are E-02. Import uses already retained inputs. |
| [8. Reverse lookup](../design_spec/08_reverse_lookup_query.md) | [Catalog snapshots](../contracts/catalog-and-ledger.md), [workspace inventory](../guides/workspace-workflow.md) | Inventory is not the proposed semantic/lineage query service; E-03 remains open. |
| [9. Concurrency](../design_spec/09_concurrency_layer.md) | [Ownership](../contracts/execution-ownership.md), [parallel trials](../contracts/parallel-execution.md) | Existing Windows process helpers supersede unsafe original PID probes. General scheduling remains E-05. |
| [10. Ledger](../design_spec/10_ledger_integrity.md) | [Canonical catalog/ledger](../contracts/catalog-and-ledger.md), [lifecycle](../evaluation/candidate-lifecycle.md) | Original conflicting seal variants are not executable authority; hashes do not authenticate rewritten stores. |
| [11. VRAM](../design_spec/11_VRAM_budget.md) | [Measured exact-workload admission](../contracts/vram-profiling.md) | Original heuristic coefficients, capacity and speed assumptions are unqualified. |
| [12. Trigger linter](../design_spec/12_trigger_word_linter.md), [scene templates](../design_spec/scene_templates/templates-overview.md) | [Trigger and scene checks](../contracts/triggers-and-scenes.md) | Lexical checks do not prove activation or model quality. |
| [12.1 Audio scorecards](../design_spec/12.1_audio_scorecard_integration.md) | Retained [audio/media contracts](../guides/audio-and-av.md) | Dedicated listening, semantic/lip synchronization and audio development deferred. |
| [12.2 Balancing](../design_spec/12.2_balancing_constraints.md), [12.3 Curator](../design_spec/12.3_curator.md), [12.4 Phrase bank](../design_spec/12.4_phrase_bank_curator.md) | Existing deterministic planning and explicit quality/lifecycle decisions are narrower building blocks | Phrase-bank constraints, automated acquisition/curation and scheduled cycles remain E-01/E-04/E-05. |

The [legacy foundation](../legacy/01comfui_itov_specs.md),
[Pony setup variant](../legacy/comfyui-pony-diffusion.md) and
[method research variant](../methods/image-to-video-research.md) are preserved
separately. Their installation snippets and model recommendations are historical,
not instructions to modify the current uv or portable environments.
