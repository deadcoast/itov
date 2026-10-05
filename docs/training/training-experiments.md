# Bounded experiments and checkpoint selection

B-05 adds `experiment plan`, `run`, `status`, `packet`, `decide` and `replay` to the installed CLI. A manifest declares a hypothesis, final-checkpoint endpoints, exact training inputs, repetitions, a worker budget and an evaluation protocol before execution. Decisions retain every endpoint and repetition, including failures. Training and held-out losses are diagnostics; they never rank or accept a checkpoint.

The supported endpoint is the final checkpoint of an independent v4 training run. To compare update 2 and update 4, declare two training specifications ending at those steps. Each repetition starts from its declared seed, consuming six updates per repetition. B-04 intermediate optimizer bundles remain restart evidence and are not individually rendered by this feature. A schedule that depends on total steps can produce different prefixes; use constant schedules when the intended comparison requires identical prefixes. The manifest pins the full schedules through its training plans.

## Declare and register

Use [the example](../../examples/sdxl-tabletop.experiment.json) as a schema reference. Its workspace references identify the retained local trial; a new workspace must prepare its own reviewed inputs and v4 training specifications. Every endpoint has an ID, a hypothesis and a `{path, sha256}` reference to a v4 training specification. All endpoints must share the prepared dataset, curation, frozen suite, base checkpoint, model configuration, environment and trigger. Rank, rate, seed, steps and optimization settings can differ when explicitly declared.

Declare one to four endpoints and one to three repetitions, with at most eight attempts. Budget fields are positive integers: `max_attempts` (at most 8), `max_optimizer_steps` (at most 2048), and `max_worker_seconds` (at most 28800). Registration reserves the sum of every endpoint's step and worker timeout limits, including repeated prefixes. An insufficient budget is refused before publication. Host planning, hashing and review time are outside the worker-time limit. Training retains its own admission floors and whole-worker timeout enforcement.

The protocol requires a method, limitations, and selection rule `all_cases_all_repetitions_then_fewest_steps`. State the inspection criteria and expected outcomes before seeing outputs. The training suite has two cases, two fixed seeds each and four conditions per seed: base/plain, base/trigger, adapter/plain and adapter/trigger. C-01 adds a separate [frozen corpus](../evaluation/evaluation-corpus.md) for broader cases and strength coverage without changing those training diagnostics or historical experiment decisions.

```powershell
uv run --inexact --locked itov experiment plan workspace/training/trial.experiment.json --save --json
uv run --inexact --locked itov experiment status workspace/state/experiments/plans/EXPERIMENT_ID.json
```

`plan --save` publishes canonical training plans and then the sealed experiment manifest. It captures the suite, allocation and every member plan's path/hash. Training IDs derive from the complete declaration and endpoint/repetition identity. Registration holds the training publication lock and refuses any already-started member. Registration before execution is idempotent. After execution, use the saved manifest for observation and replay; a new campaign needs a new declaration ID and budget.

## Execute and reproduce

```powershell
uv run --inexact --locked itov experiment run workspace/state/experiments/plans/EXPERIMENT_ID.json --member short-r1 --gpu GPU-UUID
uv run --inexact --locked itov experiment run workspace/state/experiments/plans/EXPERIMENT_ID.json --member short-r2 --gpu GPU-UUID
```

Run each declared member explicitly. Repetitions have identical training parameters, source/environment bindings, sample/noise order and evaluation seeds, with separate immutable attempt identities. This reproduces the declared endpoint from the manifest without changing the budget or rewriting the first attempt. Reproduction is observed evidence, not a universal promise of bitwise equality across devices or runtime versions.

Execution delegates to the Windows training controller: exact GPU UUID, shared device lease, workspace/native-job ownership, current input/source/environment checks and no existing-attempt overwrite. The configured ComfyUI server must respond with an empty queue. Use `training status` and `training recover` on the member plan for an interrupted controller. Failed members retain their allocated slot; unused time/updates do not authorize retries. Admission refusals before an attempt folder is created consume no execution slot; retain their diagnostics before retrying. A B-04 continuation has a different plan identity and cannot replace a declared endpoint. Declare follow-up work as a new experiment.

## Inspect and decide

```powershell
uv run --inexact --locked itov experiment packet workspace/state/experiments/plans/EXPERIMENT_ID.json --save --json
# Inspect the generated Markdown report and fill the sibling .review.json.
uv run --inexact --locked itov experiment decide workspace/state/experiments/plans/EXPERIMENT_ID.json --review workspace/state/experiments/packets/PACKET_ID.review.json --save --json
uv run --inexact --locked itov experiment replay workspace/state/experiments/plans/EXPERIMENT_ID.json --decision workspace/state/experiments/decisions/DECISION_ID.json --json
```

Packet creation requires every declared attempt to be terminal. Missing, unfinished or unreconciled attempts block review. Technically invalid or failed attempts remain explicit failed rows. Valid rows bind the controller record, result, final optimizer checkpoint, exported weights, trace and all frozen matrix images. Hash/finite/result checks do not establish image quality or substitute for full image decoding and direct inspection.

`status` reports execution readiness for review, including `review_pending` once all attempts are terminal. It does not choose among saved decisions or treat an old review as current. Use `replay` with an explicit decision to check its recorded disposition and freshness.

The pending template requires reviewer identity/kind, method, limitations and observations for every member. Successful members require every case/seed in suite order, with `pass`, `fail` or `uncertain` for activation, prompt adherence, image quality and regression. Inspect all four conditions. Failed members have no quality cases and require a failure note. Missing cases, pending verdicts, empty observations and stale packet bindings are refused. Regenerating a packet preserves edits to its review template.

Any failed criterion rejects that member; otherwise uncertainty makes it inconclusive. An endpoint is eligible only when every criterion passes for every case, seed and repetition. If several endpoints qualify, the fewest optimizer steps wins, then lexical endpoint ID breaks a tie. Any failed or rejected repetition rejects its endpoint. With no eligible endpoint, the decision records rejection or inconclusive status. It never chooses the least-bad model by loss. A selected endpoint retains all repetition identities; no arbitrary repetition is silently promoted.

Saved decisions embed the complete review and bind its original byte hash. Replay recomputes the decision against current evidence and refuses altered selections or stale inputs. Operation-local freshness checks precede publication. Historical replay does not import the optional ML stack, probe its current environment, start a worker or access the network. The model checkpoint/environment references remain bound in saved plans; execution revalidates them.

Selection means **selected for further evaluation**. It is not production quality acceptance, deployed-runtime qualification, catalog promotion or activation. Existing candidate/promotion requirements remain separate. Rejection, inconclusive and unfinished status return CLI exit 1; malformed/stale evidence returns 2. Packet generation succeeds while retaining pending review scope.

## Evidence and limits

The [B-05 trial](../reports/2026-09-24/training-experiment-trial-20260924.md) records the bounded experiment, reproduction comparison, direct image inspection and checkpoint dispositions. The B-02 selection remains two training works and one validation work. This feature does not establish corpus adequacy, general quality improvement, intermediate-checkpoint rendering, automatic search or production readiness.

The actual repetitions had identical sample/noise/rate order and RNG bytes, but different weights, losses and adapter images. Exact numerical reproduction failed and all checkpoints were rejected on independently inspected quality evidence. A manifest reproduces the declared execution protocol; it cannot guarantee numeric determinism from seeds alone. Preserve such mismatches and measure repetition variation before making causal comparisons. The current GPU profile does not enable deterministic algorithms.

Version-two experiment declarations add [preregistered numerical tolerances](experiment-variance.md).
After every member is terminal, `experiment variance MANIFEST --save` measures all
within-endpoint pairs, preserving failed attempts and exact-equality failures.
`experiment variance-replay MANIFEST --report REPORT` recomputes the saved evidence
offline. Use these measurements before interpreting a changed training endpoint;
they never replace the complete visual decision.
