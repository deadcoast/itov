# Candidate lifecycle

C-05 connects a complete [deployed decision](deployed-review.md) to an explicit catalog change. Summary, deployment validation and policy preview are read-only unless `--save` writes their evidence. Only `candidate apply` and explicit recovery publish catalog changes. The current candidate remains **rejected**; successful activation tests use synthetic approvals in isolated workspaces.

## Inspect and propose

Use a saved `evaluation decide` result from a complete version-two comparison:

```powershell
$cfg = 'workspace/itov.toml'
$decision = 'workspace/state/evaluation/decisions/DECISION_ID.json'
uv run --inexact --locked itov candidate summary $decision --config $cfg --save
uv run --inexact --locked itov candidate deployment $decision --config $cfg --save
$preview = uv run --inexact --locked itov candidate preview $decision --strength-milli 500 --config $cfg --save --json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Candidate policy refused; inspect blockers' }
```

Both inspection commands freshly replay the bound decision, matrix, decoded artifacts, review sources, candidate/export, deployed weights, checkpoint and recorded runtime/loader evidence. `deployment` checks existing evidence; it neither copies weights nor starts a loader probe. Summaries contain candidate identity, mapping and plan IDs, technical result, disposition, judgment counts, reviewed strengths and blockers. Exit 0 establishes valid evidence, including a valid rejection. Read `activation_eligible` separately.

Activation requires `accepted_for_matrix`, dataset purpose `training`, and one explicitly selected nonzero strength present in that complete matrix. Uncertainty, rejection, smoke training, an unreviewed strength or changed evidence cannot activate. A preview pins catalog `min`, `recommended` and `max` to that one reviewed strength. This does not qualify intermediate strengths or broader cases.

The preview contains the exact before/after entry, expected catalog HEAD, policy, decision reference, selected strength, previous authorization when known, and a sealed operation ID. Existing metadata other than status/strength must match the evaluated entry. Every unrelated entry and compatibility declaration is retained. A refused preview can be saved for inspection; it cannot be applied.

## Apply, retire and roll back

After inspecting an eligible saved preview, explicitly apply its path:

```powershell
uv run --inexact --locked itov candidate apply $preview.saved_path --config $cfg
uv run --inexact --locked itov candidate status --config $cfg
uv run --inexact --locked itov candidate replay OPERATION_ID --config $cfg
```

Apply recomputes the preview from current evidence and requires the exact HEAD and entry. It checks observed file bytes again while holding the catalog commit lock. Changed evidence, policy, intervening catalog writes, repeated application or a no-op are refused without publishing a new catalog revision. Preview files may remain after an unsuccessful apply; only the ledger proves a committed operation. `status` and `replay` verify historical operation references, predecessor history and the exact entry delta. They do not requalify current model quality. The pending flag is a separate point-in-time observation, as with `catalog show`.

Retirement proposes `quarantined`, so ordinary rotation stops selecting the entry. It keeps weights, decisions, prior snapshots and all compatibility declarations. It can quarantine an entry whose asset has disappeared; checking every unrelated weight is unnecessary for this metadata operation.

```powershell
$retire = uv run --inexact --locked itov candidate retirement ENTRY_ID --reason 'Recorded regression' --config $cfg --save --json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Retirement preview failed' }
uv run --inexact --locked itov candidate apply $retire.saved_path --config $cfg
$undo = uv run --inexact --locked itov candidate rollback OPERATION_ID --reason 'Undo reviewed change' --config $cfg --save --json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Rollback preview failed' }
uv run --inexact --locked itov candidate apply $undo.saved_path --config $cfg
```

Rollback is a new recorded operation. It undoes only the latest managed change for that entry and requires its current value to equal that operation's result. It restores the prior value, or removes an entry that the original activation added. Later unrelated catalog imports are preserved. Removal that would break a current compatibility reference is refused; rollback never deletes those relationships.

Restoring active status requires the original complete deployed authorization to pass again and exactly match the restored metadata/strength. A legacy/manual active entry without that authorization can be retired but cannot be reactivated by undo. Retirement and historical replay still work when model approval has gone stale.

## Atomic lineage and interrupted work

Each lifecycle commit appends a version-two [ledger event](catalog-and-ledger.md) containing the preview's path and file SHA-256. The entry change and reference share one immutable snapshot and one atomic HEAD publication. Previous version-one ledger rows remain unchanged. There is no separate success receipt to disagree with HEAD.

```text
state/candidates/previews/OPERATION_ID.json
state/candidates/summaries/SUMMARY_ID.json
state/candidates/lifecycle.lock
state/catalog/pending.json
state/catalog/abandoned/INTENT_SHA256.json
```

After interrupted apply, inspect status and recover through the owning interface:

```powershell
uv run --inexact --locked itov candidate status --config $cfg --json
uv run --inexact --locked itov candidate recover --config $cfg --json
```

Before HEAD publication, recovery repeats the exact policy/evidence checks. Stale authorization leaves intent pending and HEAD unchanged. After HEAD publication, recovery verifies the committed historical delta and removes pending intent; a later adverse review cannot silently undo an already committed catalog change. Retire it explicitly. Repeated recovery reports `not_needed` and adds no ledger row. Generic `catalog recover` refuses lifecycle intent so it cannot bypass this gate.

To abandon an **uncommitted** lifecycle intent after inspecting its cause:

```powershell
uv run --inexact --locked itov candidate recover --abandon --config $cfg --json
```

This archives the exact intent bytes before removing the pending file. HEAD, objects, previews and weights remain unchanged. Abandonment cannot undo a published HEAD. Malformed/divergent intent is preserved for investigation rather than guessed or repaired. No command deletes lock files or rewrites historical approvals.

## Compatibility and limits

`promotion prepare` retains its historical training-only preview format and checks, with `activation_eligible: false` in its command output. `promotion apply` now refuses activation and directs operators to this complete deployed-review path. Historical preview IDs remain evidence of their original scope. Manual `catalog import` remains a separate explicit operator interface; this policy is not a security boundary against an operator rewriting their own catalog or Python environment.

Core lifecycle commands use the standard library, make no network requests and import no optional ML/image modules. Fresh validation can be costly because it rehashes model/runtime files; serialize real-workspace evidence commands. They do not start training or rendering. Exit 1 indicates a refused policy preview or pending status; exit 2 indicates malformed/stale inputs or operational failure. An eligible preview and historical replay have narrower meanings than general model quality.

Qualification covers cooperative local Windows process crashes at intent, object and HEAD publication, stale decisions, explicit abandonment, retirement and targeted rollback. It does not establish whole-machine power-loss durability, hostile concurrent writes, remote filesystems, authenticated review, general model quality or numerical determinism. Synthetic fixture approvals are separate from the real rejected candidate.
