# D-02 extended media verification — 2026-09-25

**D-02 remains active: implementation and technical verification are complete;
required playback/listening inspection is incomplete.** No connected browser was
available, including the in-app browser. Automatic approval review rejected
exporting the generated FLAC through the Node/audio renderer as unacceptable risk.
No listening judgment is recorded. These are unavailable inspection paths, not a
new mandatory human-review gate. The [contract](../../guides/extended-media.md) describes the
supported commands; the [receipt](../../evidence/phase-d02-verification-20260925.json)
binds the evidence and remaining gates.

## Implementation and technical checks

- Version-two video supports 9..121 frames with explicit steps/CFG/shift; audio
  supports 1..47 requested seconds with steps/CFG. Legacy formats retain their
  meaning. Extended output contracts must agree with connected stock graphs.
- `video bind-source` binds a completed image record, output node and exact PNG.
  Preparation, planning and new submission recheck source bytes and record hashes.
- `batch cancel` saves an immutable policy outside the execution lock. It reads a
  consistent read-only database snapshot and serializes with new submissions and
  terminal retirement. Accepted work retains ownership; remaining seeds stay
  reserved. Optional targeted interruption requires the reviewed atomic endpoint,
  exact running-prompt provenance and runtime fingerprints. Lost acknowledgements
  and controller interruption never authorize a duplicate POST.
- `av spec` saves exact completed-source bindings and a source-audio offset.
  `av replay` requires an existing immutable bundle. Full frame/sample decoding,
  source-record freshness, offset/trim/pad, output hashes and stream timing are
  checked; failed/interrupted attempts are retained.

The broad source suite passed **1,584 tests** before the final graph-link and
cancellation-snapshot refinements. The first final source/wheel suites passed
**254 each**; the subsequent cancellation refinement passed **134 source and
134 final-wheel checks**. These include real FFmpeg fixtures, exact PCM offset
comparison, changed source records, missing replay output, retained interrupted
attempts, cancellation during qualification, unrelated prompts, unreviewed
runtimes, lost replies and no duplicate submissions.

Final source, sdist, wheel and clean installed package match across **86 Python
modules** and README bytes. A final line-ending formatting correction preserved
the parsed Python AST; its rebuilt wheel passed exact parity. Lint, format and
scoped diff checks pass. The Python 3.11.14 core installation has no Pillow,
Torch or Diffusers dependency. Supported commands ran from an unrelated directory.
The initial installed verification completed 25 commands including fresh live
preflight without new prompts. Final-byte verification replayed all six longer
media products and settled a fresh three-pick neutral image-copy batch: **one
accepted job completed; two unsubmitted picks remained reserved; no duplicate
prompt appeared**. Cancellation left execution-database bytes unchanged until
the controller resumed. Both temporary servers were stopped through their exact
owned Windows Job objects. The shared GPU lease is released.

## Actual longer media

The pinned ComfyUI 0.37.0 / Torch 2.13.0+cu130 runtime on the RTX 5090 generated:

| Output | Contract | Technical result |
| --- | --- | --- |
| [Video 81](../../evidence/phase-d02-video-81.mp4) | 640×640, 81 frames, 24 fps, 3.375 s | All 81 frames decoded; silent H.264 contract passed |
| [Video 121](../../evidence/phase-d02-video-121.mp4) | 640×640, 121 frames, 24 fps, 5.041667 s | All 121 frames decoded; completed-image lineage bound |
| [Audio 20](../../evidence/phase-d02-audio-20.flac) | 44.1 kHz stereo, 880,640 samples, 19.969161 s | Full finite, nonzero FLAC decode |
| [Audio 47](../../evidence/phase-d02-audio-47.flac) | 44.1 kHz stereo, 2,072,576 samples, 46.997188 s | Full finite, nonzero FLAC decode |
| [A/V 81](../../evidence/phase-d02-av-81.mp4) | Video 81 + audio 20, source offset 0 | 162,000 aligned 48 kHz samples; unchanged decoded video frames |
| [A/V 121](../../evidence/phase-d02-av-121.mp4) | Video 121 + audio 47, source offset 1.5 s | 242,000 aligned 48 kHz samples; unchanged decoded video frames |

Both A/V containers start at zero, preserve contiguous audio timestamps and meet
the 1 ms stream-duration tolerance. Both had zero terminal AAC padding samples in
this run. These measurements establish container alignment, not semantic sync.
The audio is numerically quiet: peak/RMS **0.014313/0.002010** for audio 20 and
**0.003784/0.000721** for audio 47. No normalization was applied. Nonzero samples
do not establish audible suitability, absence of speech/music, or natural rain.

The actual targeted-cancellation case used a separate 47-second/100-step audio
plan with two picks. The first accepted prompt was interrupted, recorded a
terminal `execution_interrupted` failure, and retained its failed job record.
The second pick was not submitted. Both seeds, **920260929 and 920260930**, remain
reserved. The controller settled as `abandoned`; repeated resume submitted
nothing. The media session contains **six prompts: five successes (one source
copy plus four model outputs) and one interrupted failure**.

## Frame inspection and quality disposition

The assistant directly inspected **all 202 decoded frames** in twelve labelled
contact sheets at 240-pixel tile resolution. The original 640-pixel frames remain
in the local verification folder. A/V frame hashes exactly match these inspected
source frames. This is complete frame coverage, not a claim of real-time playback
or detection of every subtle artifact.

- Video 81: the red teapot, four green pears, table and window curtain persist.
  No hand appears in the inspected frames. Motion is slight; the requested rightward
  orbit is not clearly established. Camera-motion adherence remains uncertain.
- Video 121: an unrequested hand/forearm enters from the upper edge at approximately
  frame 9, moves toward the lid and withdraws after approximately frame 63. The
  underlying still life persists. **Prompt compliance fails.** Camera-orbit
  adherence remains uncertain.
- The [preserved Stage 7 final frame](../../evidence/stage-07-output-01-frame-32.png)
  still shows its earlier unrequested hand. The longer run reproduces the defect
  class; it does not fix it. Different seeds and durations prevent a causal claim
  that duration created or removed the hand.

The video source is the original pinned **1024×1024** PNG. The new completed-image
copy has different PNG metadata/file bytes but identical decoded RGB pixels. The
source-job binding and that equality are retained in the receipt.

Sheets: video 81
[0–19](../../evidence/phase-d02-video-81-sheet-01.png),
[20–39](../../evidence/phase-d02-video-81-sheet-02.png),
[40–59](../../evidence/phase-d02-video-81-sheet-03.png),
[60–79](../../evidence/phase-d02-video-81-sheet-04.png),
[80](../../evidence/phase-d02-video-81-sheet-05.png).
Video 121:
[0–19](../../evidence/phase-d02-video-121-sheet-01.png),
[20–39](../../evidence/phase-d02-video-121-sheet-02.png),
[40–59](../../evidence/phase-d02-video-121-sheet-03.png),
[60–79](../../evidence/phase-d02-video-121-sheet-04.png),
[80–99](../../evidence/phase-d02-video-121-sheet-05.png),
[100–119](../../evidence/phase-d02-video-121-sheet-06.png),
[120](../../evidence/phase-d02-video-121-sheet-07.png).

## Measured resources

| Job | Runtime execution | CLI run wall time | Sampled whole-device peak | Minimum available host commit during CLI run |
| --- | ---: | ---: | ---: | ---: |
| Video 81 | 38.017 s | 58.725 s | 25,576 MiB | 7.485 GiB |
| Video 121 | 53.475 s | 77.132 s | 25,330 MiB | 5.613 GiB |
| Audio 20 | 3.672 s | 11.366 s | 20,208 MiB | 9.613 GiB |
| Audio 47 | 2.646 s | 10.605 s | 5,584 MiB | 24.846 GiB |

The receipt retains 50 ms runtime CUDA observations and roughly one-second host/
`nvidia-smi` samples. This was one mixed warm-runtime sequence, with concurrent
pytest and other applications. Video allocations remained when audio 20 began;
the table is not per-process model memory. Torch allocator peaks omit dynamic/
external allocations. Neither sample interval establishes an absolute peak.
The measurements do not qualify other resolutions, repeated capacity, training
admission or concurrency. Training's existing 24 GiB floor was not changed.

## Preserved failures and remaining gate

The local verification directory retains the initial nonexistent test filename;
unsupported FFmpeg `-vsync` inspection flag (corrected to `-fps_mode passthrough`);
the runtime driver's `Job.close` error (the process tree exited through Windows
kill-on-job-close, subsequently confirmed dead); an unsupported `--config` flag
on `device status`; and summary-driver ACL/dimension/TEXT-seed/device-status-label assumptions. The
corrected drivers pass. These failures were in verification tooling; none of the
four model outputs or two A/V compositions was rerendered to hide a failure.

All **2,047 predeclared historical files**, **21 training-worker source hashes**,
the main catalog HEAD and SCM 0.5.0 are preserved. The earlier candidate stays
rejected. No model training, tuning, activation, package release or Git publication
was performed. Version remains 0.13.1, unreleased.

Required next action for D-02: obtain an available playback path, inspect both
complete video clips, both complete audio tracks and both A/V outputs, and record
listening/playback limitations and disposition. **D-03 has not started.**
