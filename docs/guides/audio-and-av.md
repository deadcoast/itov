# Pinned audio and audiovisual output

**Development deferred by the user on 2026-09-26.** Images and silent
image-to-video take priority. The [priority decision](../decisions/visual-development-priority-20260926.md)
removes audio generation, listening and synchronization from the active work and
its completion gates until explicitly reprioritized. Commands and evidence below
remain reference material; unfinished audio review is not marked accepted.

This page preserves the version-one baseline. See [extended media](extended-media.md)
for longer audio, explicit sampler settings, saved A/V source selection and offset,
standalone replay and durable cancellation.

ITOV 0.8.0 adds `audio prepare`, `audio plan`, `audio verify`, and `av mux`. Audio generation uses the existing qualified sequential runner. Composition consumes completed local job artifacts and never submits another GPU job.

## Baseline and setup

The selected neutral baseline is Stable Audio Open 1.0, powered by Stability AI, with Google's T5 base encoder. It follows the [official ComfyUI workflow](https://docs.comfy.org/tutorials/audio/stable-audio/stable-audio-1) and [stock audio example](https://github.com/comfyanonymous/ComfyUI_examples/tree/master/audio). The [upstream model card](https://huggingface.co/stabilityai/stable-audio-open-1.0) describes stereo 44.1 kHz generation and its limitations. This increment exercises ambient sound; it does not qualify voices or music.

[audio-assets.json](../../examples/audio-assets.json) pins immutable repository revisions, byte lengths, destinations and SHA-256 values for the 4,853,889,016-byte [Comfy-Org checkpoint](https://huggingface.co/Comfy-Org/stable-audio-open-1.0_repackaged) and 891,646,390-byte [Google T5 file](https://huggingface.co/google-t5/t5-base). Refer to the upstream repositories for their licenses. Models remain in ignored local storage.

```powershell
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
uv run --locked python scripts/fetch_inference_baseline.py --baseline audio
uv run --locked itov audio prepare examples/stable-audio.audio.json --json
```

The downloader checks capacity for all missing bytes plus a 2 GiB reserve, verifies exact bytes before publication, preserves differing files and retains failed partial downloads. Preparation creates immutable workflow/catalog candidates. It requires the pinned models and preserves existing presets. Import the printed candidate with its printed head, then plan:

```powershell
uv run --locked itov catalog import CATALOG_CANDIDATE --expected-head EXPECTED_HEAD
uv run --locked itov audio plan examples/stable-audio.audio.json --save --json
uv run --locked itov batch qualify workspace/state/plans/PLAN_ID.json --save --json
uv run --locked itov batch run workspace/state/plans/PLAN_ID.json --qualification workspace/state/qualifications/QUALIFICATION_ID.json --wait-timeout 900 --json
uv run --locked itov batch resume workspace/state/plans/PLAN_ID.json --json
```

Replace placeholders with the preceding commands' results. Global seed reservations apply; change the specification's seed to create new work after completing the example. Existing completed plans can be resumed after a catalog import.

## Generation contract

The strict version-one specification has exactly `version`, `profile`, `checkpoint`, `text_encoder`, `prompt`, `negative_prompt`, `seconds`, `seed`, and `count`. Both model objects require a relative `.safetensors` loader name and SHA-256. The profile is `stable-audio-open-v1`; prompts are bounded to 4096 characters without external embeddings. Duration is an integer from 1 to 10 seconds, count is 1 to 4, and consecutive seeds must fit unsigned 64-bit integers.

The stock graph uses `CheckpointLoaderSimple`, `CLIPLoader` with `stable_audio`, `CLIPTextEncode`, `ConditioningStableAudio`, `EmptyLatentAudio`, `KSampler`, `VAEDecodeAudio`, and `SaveAudioAdvanced`. Sampling is fixed at 50 steps, CFG 4.98, `dpmpp_3m_sde_gpu`, `exponential`, full denoising. Conditioning starts at zero. Output is lossless FLAC.

The `stock-stable-audio-v1` qualification receipt binds the live schema, core runtime files, `comfy_extras/nodes_audio.py`, and both model files. It requires the controlled stock launch, default search paths and device, pinned checkpoint/encoder, explicit reserved sampler seeds and a bounded output contract. Ambiguous encoder aliases, custom implementations, compressed audio outputs and combined audio/video generation plans are refused. The existing image and silent-video paths retain their contracts.

Stock latent allocation rounds the requested duration to `round(seconds × 44100 / 4096) × 4096` decoded samples per channel. A four-second request therefore produces exactly **176128 stereo samples at 44100 Hz**, or about **3.993832 seconds**. ITOV records that actual contract rather than claiming exactly four seconds. Collected FLAC files must have one audio stream, the correct rate/channels, exact full decoded sample count, finite samples and nonzero signal. Peak, RMS and decoded PCM hash are retained. These checks do not measure perceived quality.

```powershell
uv run --locked itov audio verify examples/stable-audio.audio.json docs/evidence/stage-08-output-01.flac --json
```

This command validates media only. The batch runner separately establishes prompt ownership. Failed collection pauses the batch with its artifact and prompt intact; resume observes the same request and validates the media again before advancing. Completed intact resume makes no HTTP requests.

## Composition contract

[The first recorded pair](../../examples/stage-08-pair-01.av.json) demonstrates the version-one mux specification. It contains exactly `version`, `policy`, `video`, and `audio`. Each input binds a completed workspace job's `request_id`, output `node_id`, artifact `sha256`, and `record_sha256`. Obtain the latter from `Get-FileHash workspace/state/jobs/REQUEST_ID.json -Algorithm SHA256` and lowercase it. These example IDs belong to this qualification workspace; another workspace must bind its own completed jobs.

```powershell
uv run --locked itov av mux examples/stage-08-pair-01.av.json --json
```

The only policy is `start-zero-trim-or-pad-v1`:

| Property | Rule |
| --- | --- |
| Inputs | One completed owned silent-video artifact and one completed owned FLAC artifact; both records and file hashes must match. |
| Target duration | Video frames divided by fps; nearest 48 kHz sample, using ties-to-even rounding. |
| Audio alignment | Start at zero, resample to 48000 Hz stereo, trim excess or pad the end with silence, produce exactly the target sample count. |
| Gain | No loudness normalization or volume adjustment. Retain an aligned 16-bit PCM WAV. |
| Output | MP4 with copied H.264 video and 192 kbit/s AAC stereo audio. No `-shortest` or silent video truncation. |
| Timing checks | Both streams start within one 48 kHz sample of zero and end within 1 ms of target. Full video timestamps and hashes match the silent source. Full decoded audio timestamps are contiguous. |
| AAC tail | MP4 duration must match; a decoder may expose fewer than 1024 extra terminal samples. The receipt records the actual tail. The two real outputs had zero extra samples. |

The receipt records both sources and contracts, exact target samples, estimated resampled trim/pad counts, full validation, output hashes, and FFmpeg/ffprobe versions and executable hashes. The target sample count is exact; the resampled source length estimate can differ from a resampler's rounding by one sample. Measurement receipts use sorted finite-number JSON; catalog and specification hashing remain integer-only.

An OS lock serializes each operation. A private attempt directory receives the WAV, MP4 and receipt; the completed directory is published by rename under `workspace/output/av/OPERATION_ID`. Repeating the command verifies the inputs, receipt, published bytes and decoded media without re-encoding. Differing published files are preserved and refused. Failed attempts retain their files and error record; a retry creates a separate attempt. Process interruption may leave an attempt without an error record. No automatic deletion, power-loss or remote-filesystem guarantee is provided.

## Evidence and limits

The [runtime evidence](../evidence/stage-08-audio-20260921.json) records two actual seeded FLAC generations and two paired audiovisual outputs. Listen/view the [first audio](../evidence/stage-08-output-01.flac), [second audio](../evidence/stage-08-output-02.flac), [first A/V clip](../evidence/stage-08-av-01.mp4), and [second A/V clip](../evidence/stage-08-av-02.mp4). Each paired clip retains all 33 source frames at 24 fps and exactly 66000 aligned samples at 48 kHz: **1.375 seconds**. Both streams start at zero. Existing job records were preserved; completed audio and mux replay created no new prompts or encodes.

The [source/package verification](../evidence/stage-08-verification-20260921.json) separates synthetic HTTP/model fixtures, actual FFmpeg decode/trim/pad tests, installed-package checks and live model evidence. Initial receipt serialization failures were corrected without changing catalog encoding; failed attempts were retained. The runtime log retains an upstream TorchSDE floating-point boundary warning.

This establishes functional synthesis, provenance, media integrity and container timing for the bounded baseline. It does not establish human listening acceptance, loudness targets, semantic sound-to-scene synchronization, lip sync, voice LoRAs, long sequences or arbitrary model compatibility. The stage-seven unrequested hand remains visible in the first paired clip. Whole-device GPU samples reached 17809 MiB during this audio batch; cached models and unrelated allocations prevent treating that as a per-job memory estimate. Later [VRAM profiling](../contracts/vram-profiling.md) and [parallel audio trials](../contracts/parallel-execution.md) provide separate bounded cold/warm and admission evidence. Audio development remains deferred.
