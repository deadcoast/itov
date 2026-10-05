# Workspace workflow (D-01)

The installed `itov workspace` commands connect setup, generation, training,
evaluation and catalog work to the existing execution and evidence authorities.
Use the [operator runbook](operator-runbook.md) for a fresh installation and the
exact neutral image session. Model training, asset provisioning and quality
decisions remain explicit prerequisites and separate results.

## Commands and effects

| Command | Result and effect |
| --- | --- |
| `workspace guide [TOPIC]` | Ordered command recipes, named inputs and conditions; works before configuration exists; executes nothing |
| `workspace starter` | Publishes a deterministic 64×64 PNG, stock image-copy graph and neutral catalog declaration inside the configured workspace |
| `workspace request PRESET --count N --seed N --save` | Saves a neutral request bound to current catalog HEAD; supports presets without seed/LoRA bindings; submits nothing |
| `workspace status --kind KIND --offset N --limit N` | Bounded offline inventory of saved records and catalog history, with inspection commands |
| `workspace inspect FILE` | Reads a saved artifact, checks its content seal or job identity/owner binding, reports recorded state and routes to the owning commands |
| `workspace dependencies dataset\|training --python PATH --save` | Runs an isolated package-metadata probe and retains its success or failure receipt |

Each command accepts `--config PATH` and `--json`. Guide topics are `overview`,
`setup`, `generation`, `models`, `training`, `evaluation`, `catalog` and `recovery`.
Guide steps include `argv`, `needs` and `when`; replace named inputs using the
preceding command's saved artifact or an explicit declaration. Commands are never
automatically executed. Paths derive from the supplied configuration, not the
checkout or current working directory. Existing result commands also link back
to the workspace guide.

## Starter publication and requests

The starter creates `input/itov-starter.png`,
`workflows/itov-starter.api.json` and `templates/itov-starter.catalog.json`.
It checks all existing destinations before writing another input, refuses changed
bytes or redirected paths, and serializes cooperating starter writers. A partial
publication is retained; an unchanged retry finishes missing files. The immutable
manifest under `state/workspace/starters` is published only after every file
matches. No catalog import, server startup or job submission occurs.

Import that declaration only into an explicitly initialized empty catalog, using
its exact expected HEAD. An existing catalog needs a reviewed merge. Requests
under `state/workspace/requests` use the existing request schema unchanged; the
CLI response's `_cli` metadata is not saved. Existing batch planning, runtime
qualification, GPU ownership and freshness checks remain mandatory.

## Discovery is a recorded observation

Status reads only known directories for jobs, batch/training/inference/evaluation
plans, experiment manifests, candidate exports, deployed decisions, lifecycle
previews, dependency diagnostics and dataset import operations. It does not walk
model, input, output or verification trees. Default page size is 25, maximum 200;
`total`, `offset` and `more` describe the enumerated inventory. Only the returned
page is inspected. Pages sort by family and full path. A directory exceeding
10,000 entries yields an explicit issue rather than silently truncated success.
Corrupt or misplaced documents remain visible as invalid rows with their causes.

Read-only SQLite observations check the saved plan and configured server binding.
A missing initialized database is an error, never an unstarted plan. Neither
inspection nor status creates execution ownership, locks, databases or catalog
state, requests HTTP, probes processes or imports optional image/ML packages.
Concurrent observations are point-in-time reads, not a cross-file snapshot.

`recorded_status: succeeded` means the saved record says succeeded. It does not
rehash weights, decode outputs, prove a controller alive/dead or repeat a quality
review. `ok: true` / exit 0 means navigation succeeded, including a correctly read
failed or rejected record. Content seals check document integrity, not the full
domain schema or current input/artifact validity. Follow `training status`,
`evaluation replay`, `candidate summary`, or the corresponding owning command for
those checks. Inventory issues return exit 1; an invalid explicit inspection
returns exit 2. Dependency failures return exit 1 and remain inspectable.

Owned jobs point to their exact batch/inference/evaluation plan. Managed parallel
jobs bind the recorded worker server and route through `parallel resume` for
completed artifacts or `parallel recover` for confirmed stopped workers. Missing
or ambiguous ownership refuses inspection; it never suggests standalone wait or
a duplicate POST. A lifecycle preview suggests apply only when the saved preview
was eligible, explicitly subject to fresh policy/HEAD checks. Rejected decisions
and refused previews never suggest activation.

## Optional environments

The core environment can inspect all supported record families without Pillow,
Torch or the training stack. `dependencies` uses the specified interpreter with
`-I`, checks installed distribution metadata against the existing dataset/training
pins, and saves diagnostics under `state/workspace/diagnostics`. A missing
interpreter, package, wrong pin, malformed probe or timeout is retained as a failed
check. No installer, ML import or CUDA probe runs. Metadata success is not runtime
compatibility, memory admission, model readiness or quality acceptance; the
training plan and runtime commands still perform their existing checks.

## Development and validation plan

The review identified source-only starter helpers and disconnected saved-path
handoffs. D-01 adds packaged starter creation, explicit recipes and bounded
navigation without replacing domain controllers. Validation covers command
parsing, changed/partial starter publication, corruption and redirects, retained
optional dependency failures, lost-acknowledgement recovery without duplicate
submission, completed training record routing, rejected-candidate policy routing,
and a fresh installed CLI session against the local stock runtime.

The real candidate remains rejected. The neutral session establishes image I/O
and workflow integration only. Longer media behavior is D-02; general environment
provisioning, migration, backup/restore and I/O cost work remain D-05. Historical
source helpers remain available for their older documented examples.
