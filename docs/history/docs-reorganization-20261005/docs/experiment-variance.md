# Numerical repetition evidence

Experiment specification version 2 adds `numerical_tolerances` to the existing
[bounded experiment contract](training-experiments.md). Declare two or three
repetitions per endpoint and integer absolute tolerances in billionths:

```json
"numerical_tolerances": {
  "weight_abs_billionths": 1000,
  "optimizer_abs_billionths": 1000,
  "loss_abs_billionths": 1000
}
```

These values mean an absolute maximum difference of `0.000001`, including both
AdamW moments. Zero requires numerical equality; allowed values run from zero to
one billion. Tolerances belong to the immutable experiment before execution.
Existing v1 manifests and their failed exact-reproduction evidence remain valid;
the variance command refuses to invent retrospective tolerances for them.

```powershell
uv run --inexact --locked itov experiment plan EXPERIMENT.json --save
uv run --inexact --locked itov experiment run MANIFEST.json --member short-r1 --gpu GPU-UUID
# Execute every other declared member, retaining failures.
uv run --inexact --locked itov experiment variance MANIFEST.json --save
uv run --inexact --locked itov experiment variance-replay MANIFEST.json --report REPORT.json
```

`variance` validates the complete experiment packet and measures every unordered
pair within each endpoint. Three repetitions produce three comparisons, including
the pair that does not contain repetition one. It compares FP32 adapter weights,
first/second optimizer moments, checkpoint RNG payloads, Python/NumPy RNG,
sample/noise/rate order, update position, runtime flags, precision, training and
validation losses, and all corresponding frozen diagnostic image file hashes.
Resource measurements, elapsed time, gradient norms and micro-loss values are
outcomes, not controls; differences in them do not falsely imply different sample
order. The reported loss range uses recorded update/validation losses at their
existing billionth precision, not unrecorded full-precision losses.

Parameter groups include element counts, counts of numerically different elements,
payload equality and maximum absolute differences encoded as exact hexadecimal
floating-point strings. This preserves the measured binary value in the project's
integer/string-only canonical JSON format. For example, Python's
`float.fromhex(row["max_absolute_difference_hex"])` gives the display value.
Byte inequality such as signed zero remains visible even if the absolute difference
is zero. Image hashes measure file identity; they are not perceptual distances.

A failed attempt contributes unavailable pairs and makes the report inconclusive.
An unfinished attempt prevents publication. A measured pair exceeds the contract
if a numerical tolerance fails or its declared repetition controls differ.
The CLI exits 0 for tolerance pass, 1 for failed/inconclusive evidence and 2 for an
invalid or stale request. Exact reproduction is reported separately and can remain
false when tolerances pass. It does not include an assertion of image equality:
inspect the separately reported image hash comparisons.

Reports are sealed under `state/experiments/variance/`. Replay recomputes every
measurement and rechecks evidence bytes at the observation boundary. These commands
need no network, GPU, NumPy, Torch or other optional ML imports. They never run
training, change a catalog or select a candidate. Use the existing complete visual
review and decision commands after measuring repetition variation.

Observed ranges from two or three same-seed attempts are descriptive. They are not
population variance estimates, confidence intervals, proof of determinism across
machines, or evidence that a training change caused a visual improvement. Passing
tolerances cannot establish prompt adherence, activation specificity or model
quality. Preserve adverse seeds and compare them with both base conditions.
