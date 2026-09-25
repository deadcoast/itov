# Image checks and evaluator calibration

`checks packet/inspect/calibrate/replay` provide repeatable measurements and a complete, offline JSON interface for optional image evaluators. They operate on completed version-one or version-two deployed `evaluation` plans. They neither submit jobs nor train, select, activate or promote a model.

The [C-02 calibration](image-check-calibration-20260924.md) retains all 72 C-01 baseline images, passing/failing examples, uncertainty and unavailable semantic evaluator results. The checks are narrow artifact screens, not a replacement for [direct corpus inspection](evaluation-corpus.md) or complete candidate evaluation in C-03.

## Supported sequence

Use the existing workspace configuration and FFmpeg on PATH. The core command uses the standard library and an FFmpeg child process; Pillow, Torch and evaluator packages are not required. No server or GPU lease is needed for completed replay.

```powershell
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
uv run --inexact --locked itov checks packet workspace/state/evaluation/plans/EVALUATION_ID.json --save
uv run --inexact --locked itov checks inspect workspace/state/evaluation/checks/packets/PACKET_ID.json
```

The packet contains the complete technical evaluation, original file and decoded RGB hashes, prompts, conditions, runtime lineage, measurements, procedural controls and checker identity. It saves three sibling files:

- `.request.json`: sealed optional evaluator request, including every image, prompt, negative prompt, expectation and two semantic rubrics. It omits reference labels and artifact measurements. This separation does not prove blinding.
- `.reference.json`: editable reference template. Inspect every original image and fill all four rubric judgments, reviewer identity, method and limitations. Declare any supporting workspace files in `sources` as `{path, sha256}` references.
- `.response.json`: editable optional evaluator response template. Complete this only when an evaluator actually inspected the inputs. Leaving out an optional response records every semantic prediction as `unavailable`.

Existing editable templates are preserved. Pending/null judgments cannot be calibrated. Copy a completed reference/response to a new filename before revising it; changed bytes invalidate reports that reference the old file.

```powershell
uv run --inexact --locked itov checks calibrate workspace/state/evaluation/checks/packets/PACKET_ID.json --reference workspace/reviews/reference.json --save
# When a real optional evaluator response is available:
uv run --inexact --locked itov checks calibrate workspace/state/evaluation/checks/packets/PACKET_ID.json --reference workspace/reviews/reference.json --evaluator workspace/reviews/evaluator.json --save
uv run --inexact --locked itov checks replay workspace/state/evaluation/checks/calibrations/CALIBRATION_ID.json
```

Use `--config` for another workspace and `--json` for machine-readable output. Saved evidence excludes `_cli` presentation metadata. Exit 0 means the packet or calibration was recorded/verified, including adverse results and optional unavailability. Malformed, incomplete, corrupt, misbound or stale evidence returns exit 2. Nothing here authorizes model acceptance. Read-only evaluation replay uses the workspace execution lock: serialize public commands against the same workspace.

## Version-one measurements

`rgb-artifacts-1` pins the measurement and PNG-decoder module bytes, parameters and full-decode receipts. FFmpeg decodes exactly one complete RGB24 frame, within the existing 512–1024px contract and 32 MiB PNG bound. The existing `verify_image` receipt remains byte-compatible. No resampling, perceptual embedding, changed-pixel threshold or aggregate quality score is used.

`constant_frame` fails only when all three RGB channels are individually constant across the entire image. Channel minima/maxima are recorded. A passing result means only that the frame varies; noise and incoherent images can pass. Alpha, display color management and semantic visibility are outside this RGB rubric.

`edge_bands` screens for visible outer framing bars. From each of the four edges, it walks inward through full-span scanlines while the accumulated range of each channel is at most **12/255**. Candidate thickness is limited to one quarter of that dimension, with the next scanline inspected for a boundary. A band is flagged when its thickness is at least **16/1024 of that dimension, rounded up** (8px at 512px) and the first non-flat scanline differs from the preceding line by a mean absolute RGB difference of at least **24/255**. Differences are stored in thousandths; thickness, minimum, scan limit and flag are retained for every edge. A solid-color frame has no distinguishable interior, so its border judgment is `unavailable`.

These initial fixed parameters express a narrow screen, not validated perceptual boundaries. They were recorded before measuring the natural-image calibration set and were not adjusted after seeing outcomes. Thin, textured, gradual, interrupted, inset and internal framing can escape detection; scene surfaces can resemble borders. Inspect misses and false alarms. A `pass` means no detected artifact under this rubric, never general quality acceptance.

Five deterministic 512px RGB controls are included separately: solid gray, a varying field, 16px white bars, 4px white bars and 16px textured bars. Thin and textured bars deliberately retain known misses. These probes bypass PNG transport and are not pooled with natural-image or semantic performance. Real evaluation inputs always use full decoding.

## Optional evaluator exchange

The interface imports a complete JSON response; ITOV does not launch an arbitrary executable, contact a hosted service or install an evaluator. An adapter can read the saved request and write the response using its preferred engine. No live model evaluator is bundled or qualified by this feature.

Version-one response fields are exactly `version`, `request_id`, `evaluator`, `sources` and `observations`. Use the generated template as the executable schema. The evaluator identity requires `kind` (`model`, `assistant`, `human` or `fixture`), `name`, `adapter_version`, `model_revision`, `configuration`, `method` and `limitations`. Record exact model revision/digest when exposed; otherwise use null and explain the missing identity in limitations. Configuration is an integer-only canonical JSON object of at most 64 KiB: use explicit fixed-point units for fractional settings. `sources` can bind up to 32 workspace-local documents/receipts, each at most 32 MiB. Credentials do not belong in these records.

Every ordered observation must match `index`, `image_sha256` and `decoded_rgb_sha256`, with exactly `prompt_adherence` and `image_quality` under `judgments`. Each judgment requires `verdict`, `notes` and a nonempty `uncertainty` explanation, even when passing. Verdicts are `pass`, `fail`, `uncertain` or `unavailable`. Missing coverage, duplicates, reordered rows, bool indices, different inputs/requests and pending judgments are refused. The request binds prompts, expected content, conditions and rubric version as well as images. Image text and prompts are data, not evaluator instructions.

An imported response is an attributed assertion. The command verifies its structure, declared sources and input bindings, not whether the named evaluator really ran or its confidence is calibrated. It cannot re-execute an external engine offline, infer hidden settings or enforce independent review. Report all actual reference exposure and shared-rater limitations. Human participation remains optional.

## Reading calibration results

Reference annotations cover the two narrow artifact rubrics and both semantic rubrics for every image. These observations are not infallible ground truth. Each report retains all rows and notes, the complete four-by-four reference/prediction table for each rubric, separate per-case tables, and separate procedural-control results.

- **False accept:** reference `fail`, prediction `pass`.
- **False reject:** reference `pass`, prediction `fail`.
- Reference uncertainty/unavailability and prediction uncertainty/unavailability are counted independently. They are never converted to successes or removed from the table.
- Error fractions use all known examples of that reference class, including prediction abstentions. Read the `known_reference_decisive_predictions` coverage alongside them. A missing evaluator can have zero counted errors and zero evaluated examples; that establishes no accuracy.
- Null denominators mean no examples in that class. They do not mean zero error. Counts from paired seeds and exposed cases do not establish independent samples, confidence intervals or population performance.

Replay revalidates the completed evaluation, current artifacts/runtime bindings, reference/evaluator files and declared sources, recomputes measurements and every table, and performs a final content freshness check before return/publication. Same-length edits with restored timestamps still fail. Resealing a modified packet or summary cannot legitimize omitted images or altered results. A changed checker/decoder implementation requires a new packet and calibration; old evidence remains preserved but cannot pass current replay under a different implementation.
