# D-01 workspace workflow verification — 2026-09-25

D-01 delivers the [installed workspace workflow](workspace-workflow.md). The
[operator runbook](operator-runbook.md) now starts with an explicit wheel,
interpreter, ComfyUI installation and new workspace. Packaged commands create
neutral inputs and a HEAD-bound request, navigate saved records and expose
generation, model, training, evaluation, catalog and recovery sequences.
**D-02 is next. ITOV remains incomplete; the actual candidate remains rejected.**

## Actual installed runtime

The final wheel was installed in a separate Python 3.11.14 core environment with
no Pillow or optional training stack. From an unrelated working directory, its
public executable initialized a new workspace with spaces in its path, created
starter inputs, retained one missing dataset dependency and eleven missing
training-package checks, and started the explicitly configured stock ComfyUI
runtime on loopback port 8197. No source helper or repository example supplied
workflow inputs.

The standalone job first returned `timed_out`; waiting on the same record completed
it. A newly initialized neutral catalog then produced a saved request, qualified
two-job batch and completed owned records. Server history contains exactly three
jobs. All three saved outputs fully decode to 64×64 pixels identical to the
starter. An earlier session also completed three jobs and is retained. These six
outputs establish neutral image I/O, not model generation or learned quality.

The owned server was stopped. The final installed executable then replayed the
completed standalone job and batch offline. Additional isolated CLI processes
forbade network connections and checked that image/ML libraries were not imported.
The initial session also replayed with HTTP explicitly forbidden. No duplicate
submission was used for timeout recovery.

Actual retained training inventory, both inference plans and all eight evaluation
plans remain discoverable. Installed candidate summary revalidated the complete
deployed evidence and preserved rejection and ineligibility. Catalog HEAD remains
`ba91f4aa5b2b50cfd149b0b77cd8169dea8bbabacd84ef6c750b19cb13720148`.
Recorded-state inspection is distinct from that expensive domain revalidation:
one observed training inventory took 422 ms while candidate summary took 96,640 ms.
These are single observations, not a performance qualification or resolved D-05
latency work item.

## Source, package and recovery checks

**1541 broad source tests, 146 final focused source tests and 207
final installed tests passed.** The broad run began before the final
inference-version and malformed parallel-assignment refinements. The final focused
and installed suites cover those changes, including executed version-two
inference ownership and rejection of an invalid recorded worker assignment.
All 83 source/sdist/wheel/installed modules and packaged README bytes match.
Lint, format, build and scoped diff checks pass. Version is 0.13.1, unreleased.

Tests cover every generated command's parser contract, idempotent and interrupted
starter publication, changed inputs, redirected paths, bounded/paginated inventory,
corrupt/misplaced records, missing execution databases, lost acknowledgements,
managed parallel routing, training-state inspection, and refusal to suggest
activation for rejected decisions. Full domain evidence is not revalidated by
inventory; recorded success is explicitly labeled. Fixture execution and synthetic
approvals prove protocol and policy routing, not trained-model acceptance.

Review found that the initial inspector admitted only version-one artifacts,
excluding supported version-two inference plans. The correction uses each family's
supported version and now passes both the executed regression and retained-plan
inspection. This was fixed before the final wheel verification.

The first runtime harness failed an immediate TCP-refusal assertion after native
job shutdown. Its log and all successful job evidence remain. The recorded owner
was subsequently confirmed dead and three connection attempts were refused; the
same artifacts replayed with HTTP blocked. The final harness waits boundedly for
listener closure after confirmed process exit and completes successfully. This
does not establish general socket-teardown timing.

## Preservation and limits

All 1,512 scoped historical files, all 21 training-worker source hashes, the real
catalog HEAD and SCM 0.5.0 remain unchanged. Existing dirty changes and historical
failures were preserved. The [verification receipt](evidence/phase-d01-verification-20260925.json)
separates test tiers, runtime commands, decoded-image identity, missing optional
packages, actual rejected-candidate evidence and the retained harness failure.

No new model training, model-quality judgment, activation, tuning, release or Git
publication occurred. Guides require explicit model/data/specification inputs;
dependency diagnostics do not install or qualify optional environments. Inventory
is a bounded point-in-time observation of saved records. Longer media behavior is
D-02; broader provisioning, configuration migration, backup/restore and I/O costs
remain D-05 work.
