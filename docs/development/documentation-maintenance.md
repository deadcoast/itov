# Documentation maintenance contract

Documentation follows implemented source, while preserving design intent and
all retained regression evidence. The root [AGENTS.md](../../AGENTS.md) and
[TODO.md](../../TODO.md) remain authoritative for execution constraints.

## Placement

| New material | Destination |
| --- | --- |
| Supported command workflow and recovery | `docs/guides/` |
| Shared integrity, ownership or scheduling/resource contract | `docs/contracts/` |
| Dataset and training backend behavior | `docs/training/` |
| Evaluation, quality judgments and candidate policy | `docs/evaluation/` |
| Current implementation overview, development map or command inventory | `docs/development/` |
| Requested future behavior and acceptance criteria | `docs/requirements/` |
| Explicit product direction/scope decision | `docs/decisions/` |
| Dated trial plan, investigation or verification narrative | `docs/reports/YYYY-MM-DD/` |
| Validation JSON, logs, original outputs and exact upstream inputs | `docs/evidence/`, retaining existing names/paths |
| Superseded document/source version needed for regression or receipt matching | `docs/history/`, with origin, date and hashes |

Original `design_spec/`, `legacy/` and `methods/` material stays available as design
and research history. Similar names or repeated passages do not establish that
two documents are interchangeable. Do not delete, merge away or deduplicate them
as routine cleanup. New generated documentation exports should use a named
directory such as `output/pdf/`; preserve existing exports and their receipts.

## Keep source and docs aligned

For a behavior change, review the affected module, tests, parser flags, refusal
and recovery paths, then update its feature contract and supported examples.
Keep the [source map](source-map.md) and [CLI inventory](cli-reference.md) aligned
with new modules/actions. Update TODO only for actual scope/status changes and
the changelog for delivered behavior. A newly passing check does not supersede a
quality failure unless it actually evaluates that failure.

Report implementation, execution, artifact validity, numerical comparison and
observed model quality separately. Distinguish planned behavior from code, and
current descriptions from dated evidence. Keep unfinished/deferred work explicit.
Old reports keep their original outcomes and command identities.

## Move or revise retained material

Before changing a receipt-bound document, preserve its exact bytes in a named
history snapshot. Record original/current/preserved paths and SHA-256 in a
manifest. Hashes prove byte continuity, not authorship or external authenticity.
Do not reseal old JSON, rewrite historical hashes, alter immutable saved plans or
replace failures with successful reruns. Every new run needs its own identity.

For moves, update live Markdown links, images and applicable source/tool
references. Command examples use repository-root paths even when their document
moves; do not mechanically add `../` to shell arguments. Dated report links may
be rebased for navigation, with original bytes retained for historical receipts.
Do not rewrite historical literal paths to pretend the old run used a new path.

The [2026-10-05 manifest](../history/docs-reorganization-20261005/manifest.json)
implements this distinction. Snapshot links are interpreted in their original
repository context and may not resolve within the snapshot directory.

## Verify the result

Run the repository documentation check from PowerShell:

```powershell
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
uv run --locked --offline python scripts/check_documentation.py
git diff --check
```

The checker validates maintained Markdown local links/fragments, fences, index
coverage, source-module links, parser actions and preserved hashes. It excludes
original design/research bodies and historical snapshots from live-link/fence
requirements, and reports that scope. Their existing bytes remain covered by
preservation checks. It does not fetch external URLs, run shell examples, inspect
model output or establish semantic correctness of prose.

When README/package metadata changes, build into a new verification directory
with `uv build --offline --out-dir PATH`, then compare wheel/sdist Python sources,
`py.typed` and README metadata (normalizing metadata line endings). Do not overwrite
retained package artifacts. Use relevant CPU/protocol tests when behavior changes;
do not launch GPU work or download models merely to check documentation.
