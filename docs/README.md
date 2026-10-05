# ITOV documentation

ITOV is a development repository. Source, feature contracts, original designs,
agent guidance, failed validation, successful checks and legacy versions all have
a place here. Retaining a document does not make its claims current.

Start with [current implementation and limits](development/current-state.md),
then use the [operator runbook](guides/operator-runbook.md) for supported workflows
or the [source and test map](development/source-map.md) for development.
[TODO.md](../TODO.md) remains the active product plan;
[AGENTS.md](../AGENTS.md) governs repository work.

## Find the right document

| Directory | Contents | How to use it |
| --- | --- | --- |
| [guides](guides/README.md) | Workspace setup, runtime, images and media workflows | Commands, prerequisites, recovery and bounded operational evidence |
| [contracts](contracts/README.md) | Catalogs, batches, ownership, records, resources and lexical checks | Integrity rules to preserve when changing source |
| [training](training/README.md) | Data preparation/review, optimization, checkpoints and experiments | Supported backend contracts; the graphical workspace is still planned |
| [evaluation](evaluation/README.md) | Corpora, deployed comparisons, image checks and candidate lifecycle | Technical results and quality decisions remain separate |
| [development](development/README.md) | Current status, module/test map, command inventory and documentation maintenance | Source-backed orientation and rules for keeping documentation current |
| [requirements](requirements/README.md) | Requested capabilities and acceptance criteria | Planned behavior, not an implementation claim |
| [decisions](decisions/README.md) | Product direction and superseding scope decisions | Read alongside TODO before starting work |
| [reports](reports/README.md) | Dated investigations, trial plans, reviews and verification narratives | Historical claims at the reported snapshot; follow the index for later findings |
| [evidence](evidence/README.md) | Validation JSON, original media, logs and upstream snapshots | Exact retained evidence; existing paths and bytes are preserved |
| [history](history/README.md) | Prior document versions, earlier TODO and source snapshots | Regression and provenance reference; never the active work queue |
| [design_spec](development/design-status.md) | Original numbered specifications and scene templates | Original design intent, mapped to current implementation and open work |
| [legacy](legacy/README.md), [methods](methods/README.md) | Original setup and research variants | Preserved research, including incompatible or outdated examples |

The existing [design PDF](itov-design-specs.pdf) and
[export validation](itov-design-specs.validation.json) remain at the docs root.
They were untracked inputs when the 2026-10-05 reorganization began and were left
unchanged. They are a historical export, not the current application manual.

## Current boundaries

The product order is usable base images, silent image-to-video, then a stable
graphical training workspace. Further GPU runs are deferred until the user
resumes them; audio/A/V development is deferred. CPU/source/protocol/package
work may continue. The curated candidate remains rejected. FLUX integration has
code/protocol evidence but no recorded real model execution or visual acceptance.

An implemented command, a successful worker, a validated artifact, a numerical
comparison and an accepted model are different outcomes. See the
[current evidence summary](development/current-state.md) for their actual scope.

## Preservation and path changes

The [relocation manifest](history/docs-reorganization-20261005/manifest.json)
records every moved document, its old/new path, original SHA-256 and byte-exact
preserved copy. Dated report navigation was adjusted for the new locations; their
results were not rewritten. Existing evidence, design specifications and earlier
history retain their original bytes and locations. No document or artifact was
discarded or deduplicated.

Older JSON receipts and historical prose may name pre-reorganization paths.
Resolve those through the manifest when comparing a receipt to its original
document; do not rewrite a receipt to match today's prose. Future additions and
moves follow the [documentation maintenance contract](development/documentation-maintenance.md).
