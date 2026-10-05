# Validation evidence and retained artifacts

Existing JSON receipts, logs, original images/media and upstream source files stay
at their original paths with unchanged bytes. Use the [complete artifact index](INDEX.md)
to locate a file. No failed run, duplicate-looking image or legacy validation was
deleted. File names and old paths inside receipts are part of their history.

## Read evidence by scope

| Evidence family | Scope and reading route |
| --- | --- |
| Stages 01–11B | Original prototype trials. Read the [historical development review](../reports/2026-09-22/development-review.md) and preserve initial failures alongside completed checks. |
| Phase A01–A06 | Result validation, deployed runtime, shared ownership, inference, assessment records and CLI integration. Current [contracts](../contracts/README.md) supersede old next-task labels. |
| Phase B01–B05 | Dataset import/review, optimization, checkpoints and experiments. [Training reports](../reports/2026-09-24/README.md) retain failed quality and numerical comparisons. |
| Phase C01–C05 | Corpus baselines, calibration, complete deployed review, failure investigation and lifecycle. The candidate remains rejected. |
| Phase D01, D02, D021 | Installed workspace, extended media, playback, visual priorities and image/FLUX increments. Read [September 25](../reports/2026-09-25/README.md) and [September 26](../reports/2026-09-26/README.md) in sequence. |
| Python diagnostic passes | Retained correction passes; their unresolved-import counts describe different snapshots. |
| [Development profile, October 3](python-dev-profile-20261003.json) | Later environment/type-resolution repair, native CPU/import checks and package evidence. Full suite not repeated; no GPU qualification. |
| Review policy | Historical reassessment/verification of the shelved mandatory independent-human gate. |
| [Documentation reorganization, October 5](docs-reorganization-20261005.json) | Preservation, navigation, command/source-map and package checks for the docs refresh. |

## Historical paths and hashes

The [relocation manifest](../history/docs-reorganization-20261005/manifest.json)
maps moved document names to current locations and exact original copies.
Receipts continue to bind the original bytes from their recorded run; navigation
edits and later prose have different hashes. New documentation does not reseal or
replace those receipts. The manifest also checks all 486 existing documents that
were left in place, including older snapshots and the two untracked design exports.

Some receipts refer to ignored workspace artifacts, models or runtime files.
Those references describe the original local verification environment; their
presence in JSON does not guarantee availability in a fresh clone. Do not download
models or start GPU work just to satisfy a historical reference.
