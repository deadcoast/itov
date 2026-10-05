# C-05 lifecycle verification — 2026-09-25

C-05 is delivered within the [candidate lifecycle contract](../../evaluation/candidate-lifecycle.md). The current candidate remains **rejected**, and its entry was not activated. This task adds policy and catalog behavior; it does not produce a new quality judgment, trained model or render. D-01 is next; ITOV remains incomplete.

## Actual retained candidate

- Candidate: `60399a05e5b87f2a3c7de57b5c9e54443fcd6186070be1dde2f1574e569d09d6`.
- Deployed decision: `0ab0bd418b90ce6f6172149c8dcc4184d3ebb8e46d71a6d6f161619ef36ae4ff`; disposition `rejected`.
- Deployment summary: `416e8265d1704053d331c2a78a6347a98d092b5dac785623d39bbc2f1a298e89`.
- Refused preview: `5284a0c7b578af0848af4bcc582e7dce79c7d5d76ac571afe12c2bcd7e446f1a`.
- Unchanged catalog HEAD: `ba91f4aa5b2b50cfd149b0b77cd8169dea8bbabacd84ef6c750b19cb13720148`.

Source and installed public commands replayed the complete C-03 decision and loader/runtime/artifact bindings offline. Summary/deployment validation returned valid rejection, preview returned refusal (exit 1), and apply returned a policy error (exit 2). Status showed no committed lifecycle operation; recovery reported `not_needed`. C-04 numerical replay remained `failed`. Network calls and optional ML/image imports were forbidden in each command process. The detailed command results and timings are retained in the [receipt](../../evidence/phase-c05-verification-20260925.json).

## Implementation and package evidence

1493 broad source tests passed. That run began before the final text-label cleanup and malformed-version-two-action validation refinement; 142 final focused source tests and 201 final installed tests cover final code, including the full public lifecycle sequence. All 79 modules match source, sdist, wheel and installed bytes, and packaged README bytes match. Scoped lint, format, build and diff checks pass. Version remains 0.13.1, unreleased.

Six installed child processes exited with the injected code after intent, snapshot-object or HEAD publication during activation and retirement. Recovery retained lineage, finished or cleaned up exactly one committed event, and repeated recovery added none. Those tests use synthetic runtime/loader evidence while running production packet, review, decision, evidence, policy and catalog code. Additional tests cover stale images/reviews/runtime/weights/mapping/head, a change at the locked publication boundary, malformed previews/ledger rows, rollback with later unrelated imports, reference conflicts and refusal to restore active status from a missing/stale authorization.

Retirement can quarantine missing weights. Pre-commit recovery with stale authorization leaves intent and HEAD unchanged; explicit abandonment archives the exact intent. Post-commit cleanup verifies historical integrity without silently undoing or reauthorizing the model. Generic catalog recovery refuses lifecycle intent.

The retained initial failures include a nonexistent test filename, an offline dependency-resolution correction, a verification text-label expectation and stale cached same-version wheel bytes. The stale-wheel regression was resolved through a distinct artifact path and explicit reinstall, then all installed checks and byte parity passed. No failing model evidence was edited to produce a pass.

## Preserved scope and remaining work

All 1,508 scoped historical files, catalog HEAD and SCM 0.5.0 remain unchanged. This count covers the prior C-04 manifest plus current training, experiment, evaluation and owned-job evidence; it is not an exhaustive count of every historical fixture file. Existing failed numerical/quality outcomes and assistant-review limitations remain.

No real model activation, new training/rendering, data change, tuning, release or Git publication occurred. Successful fixture activation proves lifecycle behavior only. General model quality, trigger specificity, numerical causality, power-loss durability, hostile concurrent writes and remote-filesystem support are not established. Fresh evidence checks still rehash large model/runtime files; command latency and broader operator integration remain D-01/D-05 work.
