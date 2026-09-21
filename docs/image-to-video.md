# Pinned image-to-video baseline

ITOV 0.7.0 adds `video prepare`, `video plan`, and `video verify` for the `wan22-ti2v-5b-v1` profile. The prepared graph reuses the catalog, deterministic planner, and sequential executor. Input/model pins, stock node qualification, and decoded output checks define the supported path.

## Model and workflow provenance

The profile follows the [official ComfyUI Wan 2.2 5B workflow](https://docs.comfy.org/tutorials/video/wan/wan2_2) and its [upstream template](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/video_wan2_2_5B_ti2v.json). It uses `UNETLoader`, `CLIPLoader` with type `wan`, `VAELoader`, `Wan22ImageToVideoLatent`, `ModelSamplingSD3`, `KSampler`, `VAEDecode`, `CreateVideo`, and `SaveVideo`, plus stock input/text nodes. No custom nodes are enabled.

The sampler settings are fixed by the profile: 20 steps, CFG 5, `uni_pc`, `simple`, denoise 1, and model sampling shift 8. The three assets in [video-assets.json](../examples/video-assets.json) pin the official workflow distribution's revision, length and SHA-256 for the 5B diffusion model, UMT5 FP8 text encoder and Wan 2.2 VAE. The total download is 18,144,966,705 bytes. These are separate weights from the retained SDXL/LCM image baseline.

```powershell
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
uv run --locked python scripts/fetch_inference_baseline.py --baseline video
```

The helper checks capacity for the complete missing baseline plus 2 GiB, verifies exact hashes/lengths, preserves differing existing files, and records receipts under `workspace/state/model-downloads`. Default `--baseline image` remains compatible. Model files are ignored by Git; no repository upload is needed.

## Prepare and execute

Use an initialized workspace/catalog and the existing stock server (`uv run --locked itov server start`). The example pins the retained stage-six neutral teapot image:

```powershell
uv run --locked itov video prepare examples/wan22.video.json --image-source docs/evidence/stage-06-output-02.png --json
uv run --locked itov catalog import CATALOG_CANDIDATE_PATH --expected-head HEAD_FROM_PREPARE
uv run --locked itov video plan examples/wan22.video.json --save --json
uv run --locked itov batch qualify workspace/state/plans/PLAN_ID.json --save
uv run --locked itov batch run workspace/state/plans/PLAN_ID.json --qualification workspace/state/qualifications/QUALIFICATION_ID.json --wait-timeout 900
```

Use the paths/IDs actually printed. Preparation checks weights, copies the exact source PNG when supplied, and publishes immutable workflow/catalog candidates while preserving existing entries. It does not import, reserve seeds, or contact ComfyUI. If the pinned input already exists, omit `--image-source`. Differing existing input/workflow/candidate files are preserved with an error; failed preparation may leave complete unreferenced files.

The example requests two 640×640 silent clips, each 33 frames at 24 fps (1.375 seconds), with seeds 720260921 and 720260922. This is a bounded functional baseline, not a production length or quality recommendation. Another render requires a new specification with unused seeds. Importing another catalog head invalidates older plans for additional submissions; completed jobs remain observable.

## Specification and qualification

The exact version-one fields are `version`, `profile`, `diffusion`, `text_encoder`, `vae`, `input_image`, `prompt`, `negative_prompt`, `width`, `height`, `frames`, `fps`, `seed`, and `count`. Model objects contain `loader_name` and lowercase `sha256`; `input_image` contains `name` and `sha256`.

- Models use safe relative `.safetensors` names in their stock folders. The qualifier rejects duplicate names across ComfyUI's `unet`/`diffusion_models` or `text_encoders`/`clip` search paths, even if the duplicates match.
- The PNG uses a top-level input filename. The installed stock `LoadImage` dropdown lists top-level files; an initial nested-input preflight failed before submission and is retained in the evidence.
- Prompts are at most 4096 characters without external `embedding:` references or control characters. Positive text must be nonempty.
- Width/height are multiples of 32 in 512..832, with area at most 832×640. Frames are 4n+1 in 9..49; fps is an integer in 8..30; count is 1..4. Latent batch size stays one. Consecutive uint64 seeds cannot overflow and remain subject to workspace reservations.

The graph retains expected model/input hashes in `_meta.itov_asset_sha256` and an exact output contract in `SaveVideo._meta.itov_video`. Changing a same-named asset cannot silently qualify an old plan. Preparation/planning and every new submission recheck relevant hashes.

`stock-wan22-v1` extends the stock allowlist with these nodes' exact module identities and source-file hashes. Existing image workflows continue to produce `stock-local-v1` receipts. It retains the controlled launch arguments, disabled custom nodes, no extra search-path configuration, explicit seeds, safe output prefixes, and exclusive runtime-control assumptions described in [batch execution](batch-execution.md). Runtime dependencies and model caches are not an attestation: restart after changes to previously loaded model bytes or search paths.

ComfyUI V3 uses dotted inputs such as `format.codec` for nested encoding choices. Workflow validation expands the selected branches and checks required children and allowed choices; the video profile specifically requires MP4/H.264 and silent `CreateVideo` defaults.

## Artifact acceptance and recovery

Collection downloads the exact owned history descriptor and verifies its bytes, then invokes installed FFmpeg/ffprobe on the local artifact. These checks require one H.264 video stream in an MP4 container, no audio stream, exact dimensions/frame count/frame rate, duration within 1 ms of frames/fps, complete RGB decode, constant decoded frame timestamps and at least two distinct decoded frames. Each tool invocation is limited to 120 seconds; artifacts remain subject to the existing 512 MiB download limit.

Only a passing artifact advances the batch. Failed video checks preserve downloaded bytes, prompt identity and a `collection_failed` record. `batch resume` retries observation/validation without another POST. Completed resume rechecks both artifact hashes and video decoding. To retire an invalid completed output and its unsubmitted remainder, `batch abandon` requires fresh matching server ownership and terminal success evidence; absent/ambiguous history still refuses abandonment and seeds remain reserved.

An independently selected file can be checked against a specification without loading models or contacting ComfyUI:

```powershell
uv run --locked itov video verify examples/wan22.video.json PATH_TO_COLLECTED_MP4 --json
```

This validates the file's media contract, not its provenance. Batch collection separately establishes request/graph ownership. Decoded variation does not prove natural motion, source-image fidelity, aesthetic quality, or absence of artifacts.

## Evidence and limits

Stage-seven records live in [execution evidence](evidence/stage-07-video-20260921.json), the [initial preflight failure](evidence/stage-07-initial-preflight-20260921.json), and [verification evidence](evidence/stage-07-verification-20260921.json). The report distinguishes actual pretrained model execution from synthetic loader fixtures, generated FFmpeg test clips, and installed-package checks.

On 2026-09-21 the local ComfyUI 0.37.0 / Torch 2.13.0+cu130 / RTX 5090 completed both example jobs, with 33 distinct decoded frames per clip and no duplicate prompt ownership. Completed resume passed and earlier job records were unchanged. Retained clips: [first MP4](evidence/stage-07-output-01.mp4) and [second MP4](evidence/stage-07-output-02.mp4). Representative frames show the recognisable source scene; [the first clip's final frame](evidence/stage-07-output-01-frame-32.png) adds an unrequested hand. The second shows subtle composition changes. This is functional media acceptance with a recorded prompt-compliance defect, not general quality acceptance.

Whole-device GPU samples include other allocations and can miss peaks. They do not calibrate Part 11, establish per-job memory demand, or authorize concurrency. Stage eight separately qualifies [bounded audio and A/V composition](audio-and-av.md). Longer clips, other resolutions/models/LoRAs, cross-runtime pixel determinism and human quality acceptance remain separate tasks in [TODO.md](../TODO.md).
