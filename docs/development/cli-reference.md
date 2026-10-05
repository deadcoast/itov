# Public CLI inventory

Checked against [itov.cli.parser()](../../src/itov/cli.py) on 2026-10-05. These are the implemented command families/actions, not a claim of GPU or model qualification. Use `uv run --locked itov FAMILY ACTION --help` for exact required arguments, types, defaults and choices; help does not execute the action.

Commands below are reference material. Further GPU runs and audio development remain deferred. Planning may read a live runtime; the specific contract establishes whether an operation is offline. Saving can publish immutable evidence. JSON output adds response metadata; do not save that augmented response over a domain record.

| Family | Actions (— means a top-level command) | Contract |
| --- | --- | --- |
| `init` | — | [workspace-workflow](../guides/workspace-workflow.md) |
| `workspace` | `guide`, `starter`, `request`, `status`, `inspect`, `dependencies` | [workspace-workflow](../guides/workspace-workflow.md) |
| `doctor` | — | [runtime-and-jobs](../guides/runtime-and-jobs.md) |
| `workflow` | `validate` | [runtime-and-jobs](../guides/runtime-and-jobs.md) |
| `server` | `start` | [runtime-and-jobs](../guides/runtime-and-jobs.md) |
| `job` | `run`, `wait` | [runtime-and-jobs](../guides/runtime-and-jobs.md) |
| `catalog` | `validate`, `init`, `import`, `show`, `verify`, `recover` | [catalog-and-ledger](../contracts/catalog-and-ledger.md) |
| `batch` | `plan`, `verify`, `qualify`, `run`, `resume`, `status`, `abandon`, `cancel` | [batch-execution](../contracts/batch-execution.md) |
| `inference` | `spec`, `capabilities`, `prepare`, `plan`, `run`, `status`, `resume`, `replay`, `abandon` | [candidate-inference](../guides/candidate-inference.md) |
| `video` | `prepare`, `plan`, `verify`, `bind-source` | [image-to-video](../guides/image-to-video.md) |
| `audio` | `prepare`, `plan`, `verify` | [audio-and-av](../guides/audio-and-av.md) |
| `av` | `mux`, `replay`, `spec` | [extended-media](../guides/extended-media.md) |
| `vram` | `server`, `capture`, `check` | [vram-profiling](../contracts/vram-profiling.md) |
| `parallel` | `calibrate`, `qualify`, `resume`, `recover` | [parallel-execution](../contracts/parallel-execution.md) |
| `device` | `status`, `recover` | [execution-ownership](../contracts/execution-ownership.md) |
| `trigger` | `lint` | [triggers-and-scenes](../contracts/triggers-and-scenes.md) |
| `scene` | `lint` | [triggers-and-scenes](../contracts/triggers-and-scenes.md) |
| `dataset` | `validate`, `prepare`, `curate`, `import`, `status`, `recover`, `verify`, `inspect`, `freeze`, `review-verify` | [dataset-review](../training/dataset-review.md) |
| `training` | `plan`, `run`, `status`, `recover`, `candidate`, `checkpoints`, `resume-plan` | [training-and-promotion](../training/training-and-promotion.md) |
| `experiment` | `plan`, `run`, `status`, `packet`, `decide`, `replay`, `variance`, `variance-replay` | [training-experiments](../training/training-experiments.md) |
| `evaluation` | `mapping`, `mapping-inspect`, `review-packet`, `review-inspect`, `decide`, `decision-replay`, `assess`, `packet`, `plan`, `run`, `status`, `resume`, `replay`, `abandon` | [deployed-evaluation](../evaluation/deployed-evaluation.md) |
| `promotion` | `prepare`, `apply` | [candidate-lifecycle](../evaluation/candidate-lifecycle.md) |
| `candidate` | `summary`, `deployment`, `preview`, `retirement`, `rollback`, `apply`, `status`, `replay`, `recover` | [candidate-lifecycle](../evaluation/candidate-lifecycle.md) |
| `corpus` | `freeze`, `inspect`, `baseline`, `replay` | [evaluation-corpus](../evaluation/evaluation-corpus.md) |
| `checks` | `packet`, `inspect`, `calibrate`, `replay` | [image-checks](../evaluation/image-checks.md) |

## Interpretation

- Inference defaults to SDXL v2; explicit model flux2-klein-4b-fp8 selects experimental v3. [Base-image defaults](../guides/base-image-workflow.md) and [FLUX limits](../guides/flux-image-workflow.md) are separate contracts.
- Training recovery reconciles stopped work; resume-plan creates a new explicit continuation. Neither silently restarts an unchanged attempt.
- Legacy promotion prepare preserves its training-only preview. Promotion apply refuses activation; current policy uses deployed decisions and candidate preview/apply.
- A valid rejection can return exit 0. Read disposition and eligibility, not just exit status. See [response and recovery meanings](../guides/operator-runbook.md#read-a-response).
- The inventory lists actions only. The checker compares it to the parser; flag schemas remain defined by parser source and per-action help.
