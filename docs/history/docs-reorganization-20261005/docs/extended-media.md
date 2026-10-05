# Extended media workflow (D-02)

Development contract: D-02 is active for image and silent image-to-video
operability. The user's [2026-09-26 priority change](visual-development-priority-20260926.md)
defers all audio/A/V development and listening gates. Work first on a usable base
image workflow, then subject-preserving video with requested motion. Existing
Stage 7/8 files and the unrequested-hand regression remain unchanged.

The [D-02 verification](d02-media-verification-20260925.md) records completed
implementation, longer runtime trials and all-frame inspection. The
[playback continuation](d02-playback-verification-20260926.md) records complete
browser playback of all six outputs. Visual quality remains unaccepted; D-02 is
not closed. Unfinished audio/listening work is deferred and no longer blocks
visual development. The audio/A/V contracts below document retained implementation,
not the active development priority.

## Design

Version-one video/audio specifications and saved graphs keep their existing
meaning. Version two adds explicit bounded sampler settings and longer durations:
Wan 2.2 5B up to 121 frames at the existing bounded resolutions; Stable Audio Open
up to 47 seconds. These are ITOV support bounds, not guarantees of model quality
or measured device capacity. Every configured setting enters the specification,
graph and plan identity. Media contracts distinguish their extended version.

Image-to-video source declarations may bind an exact completed image job, output
node, record hash and artifact hash. Staging validates that lineage, copies only
the exact bytes and retains the declaration in the graph. Planning and every new
submission recheck the source; observation of accepted work remains possible when
an input subsequently changes. Existing external PNG pins remain supported.

Cancellation is a durable request on a registered sequential plan. It prevents
further submissions, retains all reserved seeds and collects accepted work before
retiring the remainder. An optional `--interrupt-running` policy targets only the
proven running owned prompt through the runtime's atomic per-job cancellation
endpoint. It never clears a queue or sends a global interrupt. Pending requests
remain observable until running or terminal, since dequeuing them would erase the
positive terminal evidence required by the current device lease protocol. A lost
cancel acknowledgement never permits another POST or release based on absence.
Resuming the same owner reconciles the retained request and terminal evidence.

A/V composition exposes a saved specification builder and standalone replay,
using exact source records/artifacts and an explicit audio offset. Extended media
must pass complete frame/sample decoding, timing and immutable publication checks.
Replay must not create a missing output. Source lineage is rechecked before final
publication; failed and interrupted attempts remain available.

## Verification plan

- Preserve historical files, worker-source hashes, catalog HEAD, source baseline
  and SCM 0.5.0 before development; use a separate qualification workspace.
- Test legacy compatibility, extended bounds and graph/contract agreement;
  source mutation, missing artifacts and malformed declarations must refuse use.
- Test cancellation before submission, during owned execution, lost response,
  stale/mismatched ownership, another client's running prompt and resume without
  duplication. Cancellation must not erase failure evidence or reserved seeds.
- Test longer generated FFmpeg fixtures, exact offset/trim/pad, replay and changed
  source/publication boundaries, including process interruption.
- Run bounded image and silent video comparisons, retain resource samples, inspect
  every image/frame and complete video playback, and include the old hand regression.
  Separate technical acceptance from prompt/visual judgments. Audio generation,
  listening and A/V review are deferred under the current priority.
- Verify the final installed wheel from explicit paths, package/source parity,
  scoped tests, lint and historical preservation before closing D-02.

## Source authority

The [official Wan workflow](https://docs.comfy.org/tutorials/video/wan/wan2_2)
supports selecting the latent frame count; ITOV's cap remains a bounded local
policy. The [Stable Audio Open model card](https://huggingface.co/stabilityai/stable-audio-open-1.0)
describes variable-length stereo 44.1 kHz synthesis up to 47 seconds. The installed
ComfyUI `server.py`, `execution.py` and `comfy_execution/jobs.py` define the atomic
per-job cancellation behavior. ITOV requires the qualified implementation and
refuses unsupported runtimes instead of falling back to global interruption.

## Operator contract

The version-two examples are [video](../examples/wan22-extended.video.json) and
[audio](../examples/stable-audio-extended.audio.json). They retain the model pins
and scene prompts of the original examples. Select unused seeds and an explicit
duration before preparing a new run. A catalog import is still an explicit step
between `prepare` and `plan --save`; ordinary batch qualification/run/resume
commands execute the saved plan. No training or model promotion is implied.

| Setting | Video v2 | Audio v2 |
| --- | --- | --- |
| Duration | 9..121 frames, `4n+1`; 8..30 fps | Integer 1..47 seconds |
| Sampler steps | 10..30 | 10..100 |
| `cfg_milli` | 1000..10000 | 1000..10000 |
| `shift_milli` | 1000..16000 | Absent |
| Output | Silent MP4/H.264 | Stereo 44.1 kHz FLAC |

Dimensions remain multiples of 32 in 512..832, with area no larger than 832x640.
Sampler/scheduler stay `uni_pc/simple` for video and
`dpmpp_3m_sde_gpu/exponential` for audio; denoise remains one. Milli settings are
integer declarations (5000 means 5.0). Audio output is rounded to the model's
4096-sample grid; 47 requested seconds is 2,072,576 samples, approximately
46.997 seconds. Video duration is frames/fps; 121 frames at 24 fps is about
5.042 seconds. Longer frame support does not imply longer coherent motion.

For an exact completed source image in the same workspace/server:

```powershell
itov video bind-source VIDEO_SPEC SOURCE_JOB.json --node 2 --save --config WORKSPACE/itov.toml
itov video prepare SAVED_BOUND_SPEC --config WORKSPACE/itov.toml
```

The source must be a completed single-artifact `SaveImage` output, a regular PNG
no larger than 16 MiB, with dimensions supported by ITOV's image decoder
(multiples of 64 in 512..1024). `source: null` retains the external pinned PNG
workflow. Binding preserves exact PNG bytes, including metadata; source-job
lineage records declared saved provenance, not authorship or a model-quality
certificate. A changed source blocks new submission; accepted work can still be
observed and collected. Use the saved raw specification, not CLI JSON containing
presentation metadata.

Compose completed media by selecting their exact output nodes:

```powershell
itov av spec --video-record VIDEO_JOB.json --video-node 12 --audio-record AUDIO_JOB.json --audio-node 9 --audio-offset-ms 1500 --save --config WORKSPACE/itov.toml
itov av mux SAVED_AV_SPEC --config WORKSPACE/itov.toml
itov av replay SAVED_AV_SPEC --config WORKSPACE/itov.toml
```

`audio_offset_ms` selects a nonnegative start point **inside the source audio**;
it does not delay the output stream. Both output streams start at zero. The
selected audio is resampled to 48 kHz, trimmed or padded with silence to the video
duration, encoded to AAC, and checked by full decode. An offset that leaves no
source samples is refused. The immutable bundle contains `aligned.wav`,
`output.mp4`, exact source bindings and a receipt. Replay requires that bundle
already exist, rechecks both source records and all output bytes, and cannot
recreate missing output. Container alignment does not establish semantic sync.

To stop a registered sequential batch from another terminal:

```powershell
itov batch cancel SAVED_PLAN --config WORKSPACE/itov.toml
# Alternatively choose this policy on the first cancellation request:
itov batch cancel SAVED_PLAN --interrupt-running --config WORKSPACE/itov.toml
itov batch resume SAVED_PLAN --config WORKSPACE/itov.toml
```

The first request fixes the policy; it cannot be changed or rescinded. Exit zero
from `cancel` means the request was saved, **not** that work stopped. Keep the
owning controller running, or resume it after it detaches. Concurrent ownership
locks may briefly require retrying the request. A settled cancellation returns
`abandoned`/exit one with the marker, accepted-job outcomes and all seed
reservations retained. The default policy needs no cancellation runtime API.
Targeted interruption additionally requires the exact reviewed stock runtime
source fingerprints and managed launch arguments. Unsupported runtimes pause
without sending an interrupt. Pending or uncertain jobs retain ownership until
positive terminal evidence is available. `parallel recover` remains the owner of
managed parallel recovery; `batch cancel` refuses those plans.

Cancellation intent is durable before the targeted POST. An interrupted process
or lost response never retries that POST; it resumes terminal observation. If the
request was not delivered, the job may finish normally. Local evidence and
runtime files must remain under operator control, as with existing qualification.
