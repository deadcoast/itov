# Assessment records and evidence freshness

A-05 separates internal records from stored documents and removes repeated validation inside `evaluation packet`. It changes no CLI syntax and requires no artifact migration. The current curated candidate remains rejected; this is a technical integrity and command-cost improvement.

## Responsibilities

| Module | Responsibility |
| --- | --- |
| `records.py` | Immutable canonical document bytes with fresh dictionary copies at serialization boundaries |
| `training_records.py` | A validated training result and its exact finite, rank-checked weight snapshot |
| `training_results.py` | File/schema, optimizer, held-out, preview, weight and complete quality-matrix validation; the existing dictionary-returning API remains available |
| `evaluation_cases.py` | Immutable cases, ordered case/seed/role conditions and validated evaluation evidence |
| `review_records.py` | Pure review/check/case-verdict records and version-specific review policy; no file I/O or catalog activation |
| `assessment_context.py` | One owned assessment operation: load the plan/run, validate once, derive artifacts and check freshness before returning |
| `evidence_reads.py` | Operation-local observations of read documents and file references; fresh content checks at the operation boundary |
| `evaluation.py`, `quality.py` | Public assessment/export/review/packet orchestration, evidence I/O and existing publication/promotion policy |

Records own immutable bytes, primitive fields and tuples. Returning a dictionary for an existing public API gives the caller a new value; changing it cannot mutate another consumer's validated snapshot. Frozen dataclasses are internal program records, not a new persisted format or a security boundary for arbitrary Python code.

`ValidatedTrainingResult` binds the result, dataset, weight bytes/integrity and optional complete curated evaluation evidence. The weight snapshot's bytes pass SHA-256, finite-value, matrix-pair, rank and layout checks together. Export renames tensors from those exact bytes without a second finite scan. Capturing weights is bounded by the existing 256 MiB maximum; candidate/packet construction also holds exported bytes temporarily. Controller/status validation retains its streaming weight scan.

`EvaluationCase` and `EvaluationCondition` preserve case order, then seed order, then `base_plain`, `base_trigger`, `adapter_plain`, `adapter_trigger`. Training diagnostics and deployed evaluation still consume the same ordered dictionary contract. `ReviewDecision` separates a review's declared approval from verified evidence/coverage and promotion eligibility. Historical v1 reviews, v2 independent-human declarations and v3 assistant/human method-and-limitations requirements retain their original policy. A passing technical result cannot become a quality approval through these records.

## Reuse and final checks

The packet command now performs one complete validation, one finite-weight scan and one curation/matrix validation. Assessment and export derive from that operation's immutable snapshot. Subsequent commands create a fresh context and reread their inputs; there is no persistent cache or metadata-only shortcut.

Read observations include the plan, run/result documents, dataset snapshot and referenced sources/images/captions, weights, held-out previews, curated metadata/policy/suite and every quality-matrix image. Before an assessment, candidate or packet can return or publish, the context rehashes each unique observed file. It checks byte count, path resolution and metadata changes during that final read. Conflicting observations within the same operation also fail. Nested scopes feed their parent; context isolation prevents unrelated threads from sharing read receipts, and exceptions restore the previous scope.

A same-length edit with the original timestamp restored still fails content verification. Changes after initial validation are reported at `input_freshness`; no new assessment, candidate export or packet is published by that failing command. Publication remains exclusive and preserves conflicting existing files. This is a final freshness check over ordinary files, not a filesystem-wide atomic snapshot or an exclusion lock against external editors. Keep inputs under operator control while publishing. Existing per-submission runtime checks, post-worker revalidation, recovery rules and catalog compare-and-swap remain in place.

## Compatibility

Successful legacy v1 and curated v2 training results remain readable through the existing public commands. Canonical assessment, exported candidate, packet and status outputs were compared against captured pre-change outputs from both successful local training plans. The candidate weights' names, payload bytes, hashes and identities are unchanged. The prior A-02 deployed evaluation and both A-04 inference technical reports remain replayable offline.

No old run/result/review is rewritten or marked accepted. Historical rejected/failed attempts remain evidence. New training plans include the newly factored validation dependencies in their worker-source manifest, so their plan IDs differ from plans bound to older source. Old completed-result inspection does not pretend to have run under the new source. Fresh execution/recovery still requires the original pinned execution inputs or a genuinely new plan.

## Measured command cost

The measured public command was `evaluation packet` on the existing curated training plan `5fab677a…dfc67`. Three uninstrumented warm-file samples were collected before and after. A separate instrumented invocation counted hash reads and Python calls; its timing is excluded from the wall-time comparison.

| Observation | Before | After |
| --- | ---: | ---: |
| Median command time | 1.459 s | 0.572 s |
| Complete training-result validations | 2 | 1 |
| Finite-weight scans | 3 | 1 |
| Curation/qualification passes | 4 | 1 |
| `file_digest` calls | 353 | 167 |
| Bytes read by `file_digest` | 122,288,965 | 72,963,330 |

The measured median is about 61% lower. The 167 hash calls include the final fresh check of 60 unique files. Some dataset checks remain repeated inside the validation/curation layers; there is no claim that all I/O or all commands have been optimized. Counts cover `file_digest` reads, not every read or in-memory hash. Wall timings depend on the host and filesystem cache and are not an inference/training throughput or GPU-capacity result. The canonical packet output hash is identical before and after.

A separate Python 3.11 installed-wheel comparison measured medians of 1.636 s for the retained A-04 wheel and 0.595 s for A-05, with the same packet output and hash-read counts. The slowest old-wheel sample was 2.560 s and is retained. Development/test processes were active during some samples; these are local command measurements, not isolated benchmark guarantees.

Reproduce the read-only measurement with an existing valid local plan and a new output filename:

```powershell
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
uv run --inexact --locked python scripts/profile_training_reads.py packet workspace/state/training/plans/PLAN_ID.json --repeats 3 --output profile.json
```

The helper also supports `assess`, refuses to overwrite its output and never requests `--save`, launches a worker or submits a model job. See [A-05 verification](evidence/phase-a05-verification-20260923.json) and [before/after profiling](evidence/phase-a05-profile-20260923.json) for retained measurements and their limits.
