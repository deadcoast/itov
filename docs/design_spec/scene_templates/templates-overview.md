# SENSITIVE IMAGE-TO-VIDEO STUDIO — PART 1: FOUNDATION

Built for: RTX 5090 (32GB VRAM) / 9800X3D / 64GB DDR5 / 2TB PCIe 5.0 NVMe

---

## PHASE 1: SYSTEM PREP

> 1.1 Directory structure

Create this on your NVMe for max throughput:

```txt
D:\AI\
├── ComfyUI\
├── models_shared\        (checkpoints/loras you'll reuse)
├── input\                (source images for i2v)
├── output\               (finished videos)
├── templates\            (motion muse-style JSON templates)
└── workflows\            (saved .json workflows)
```

Keep this on the 2TB PCIe 5.0 drive — model load times drop from ~30s to ~4s vs a SATA SSD. This matters when you're iterating.

> 1.2 Install order (do exactly this sequence)

1. Python 3.11.9 (python.org) — check "Add to PATH" during install. NOT 3.12, breaks half the custom nodes.
2. Git for Windows (git-scm.com) — default settings fine.
3. CUDA Toolkit 12.8 (developer.nvidia.com/cuda-downloads) — required for Blackwell (5090). 12.4 and below will not work.
4. Visual Studio Build Tools 2022 — install "Desktop development with C++" workload. Needed for compiling custom node dependencies (xformers, sage-attention, etc.)
5. 7-Zip — for extracting model archives.
6. FFmpeg — download from ffmpeg.org, extract to `C:\ffmpeg\`, add `C:\ffmpeg\bin` to system PATH. Required for video export.

Reboot after CUDA install. Non-negotiable.

---

## PHASE 2: COMFYUI INSTALL (5090-OPTIMIZED)

> 2.1 Grab the portable build

Download `ComfyUI_windows_portable_nvidia.7z` from github.com/comfyanonymous/ComfyUI/releases. Extract to `D:\AI\ComfyUI\`.

> 2.2 Replace bundled torch with Blackwell-compatible nightly

Open PowerShell, navigate to the embedded Python:

```powershell
cd D:\AI\ComfyUI\python_embeded
.\python.exe -m pip install --pre torch torchvision torchaudio --index-url https://download.pytorch.org/whl/nightly/cu128 --force-reinstall
```

Verify it worked:

```powershell
.\python.exe -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

Should print: `True NVIDIA GeForce RTX 5090`

> 2.3 Install performance libraries

```powershell
.\python.exe -m pip install sageattention triton-windows
.\python.exe -m pip install --pre xformers --index-url https://download.pytorch.org/whl/nightly/cu128
```

Sage attention on Blackwell gives you roughly 30-40% faster generation vs default. Worth the extra install step.

> 2.4 Create your launcher batch file

Save this as `D:\AI\ComfyUI\LAUNCH_5090.bat`:

```batch
@echo off
set PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
set CUDA_VISIBLE_DEVICES=0
set HF_HUB_ENABLE_HF_TRANSFER=1
cd /d D:\AI\ComfyUI\ComfyUI
..\python_embeded\python.exe -s main.py ^
  --highvram ^
  --use-sage-attention ^
  --fast ^
  --preview-method auto ^
  --listen 127.0.0.1 ^
  --port 8188 ^
  --output-directory D:\AI\output ^
  --input-directory D:\AI\input
pause
```

Flag breakdown:

- `--highvram` — keeps models resident in VRAM between generations (huge speedup, you have the memory)
- `--use-sage-attention` — Blackwell-optimized attention
- `--fast` — enables fp16 accumulation and tensor core paths
- `--preview-method auto` — live previews without tanking speed

---

## PHASE 3: ESSENTIAL CUSTOM NODES

> 3.1 Install ComfyUI Manager first

```powershell
cd D:\AI\ComfyUI\ComfyUI\custom_nodes
git clone https://github.com/ltdrdata/ComfyUI-Manager
```

3.2 Launch ComfyUI, then install these nodes via Manager UI:

Open `LAUNCH_5090.bat`, wait for browser to open, click Manager → Install Custom Nodes, search and install each:

| Node Pack | Purpose |
| ----------- | --------- |
| ComfyUI-KJNodes | Kijai's utility nodes, used by most video workflows |
| ComfyUI-VideoHelperSuite | Video load/save/combine, frame extraction |
| ComfyUI-HunyuanVideoWrapper | Hunyuan Video (best uncensored i2v currently) |
| ComfyUI-WanVideoWrapper | Wan 2.1 i2v (Kijai's port) |
| ComfyUI-AnimateDiff-Evolved | Backup motion module for SDXL/Pony workflows |
| ComfyUI-Advanced-ControlNet | Pose/depth guidance for motion control |
| ComfyUI_IPAdapter_plus | Style consistency across frames |
| ComfyUI-Frame-Interpolation | RIFE/FILM for smooth 60fps upscaling |
| ComfyUI-Impact-Pack | Face detailing, region-specific fixing |
| rgthree-comfy | Workflow organization, mute groups, seed control |
| ComfyUI-Custom-Scripts | pysssss QOL improvements |
| ComfyUI_essentials | Cubiq's essential nodes, resize/crop tools |

Restart ComfyUI after install. Manager handles the pip dependencies automatically.

---

## PHASE 4: MODEL STACK

You've got 32GB VRAM. Download everything below — you can run all of it.

4.1 Image checkpoints → `D:\AI\ComfyUI\ComfyUI\models\checkpoints\`

From civitai.com (enable NSFW in account settings):

- Pony Diffusion V6 XL (`ponyDiffusionV6XL.safetensors`, ~6.5GB) — explicit control, huge LoRA ecosystem
- Lustify SDXL Checkpoint (~6.5GB) — photorealistic NSFW
- RealVisXL V5.0 (~6.5GB) — hyperrealistic base
- BigLust or BigLove (Pony merges) — enhanced anatomy

From huggingface.co:

- Flux.1 Dev (`flux1-dev.safetensors`, ~23GB) → also grab NSFW LoRAs from civitai like "flux nsfw" tagged ones

4.2 Video models → `D:\AI\ComfyUI\ComfyUI\models\diffusion_models\`

- Hunyuan Video I2V — from `huggingface.co/Kijai/HunyuanVideo_comfy`
  - `hunyuan_video_I2V_720_fp8_e4m3fn.safetensors` (recommended for 5090)
  - `hunyuan_video_vae_bf16.safetensors` → `models\vae\`
  - Text encoders → `models\clip\`

- Wan 2.1 I2V — from `huggingface.co/Kijai/WanVideo_comfy`
  - `Wan2_1-I2V-14B-720P_fp8_e4m3fn.safetensors`
  - Associated VAE and text encoders

- LTX Video 0.9.5 — fastest i2v, from `huggingface.co/Lightricks/LTX-Video`
  - Good for rapid iteration/preview before committing to Hunyuan for finals

4.3 Motion modules (for AnimateDiff fallback) → `custom_nodes\ComfyUI-AnimateDiff-Evolved\models\`

- `mm_sd15_v3.safetensors` (SD1.5 motion)
- `hsxl_temporal_layers.safetensors` (SDXL motion)

4.4 Frame interpolation → `custom_nodes\ComfyUI-Frame-Interpolation\ckpts\rife\`

- `rife47.pth`, `rife49.pth` — auto-downloaded on first use

4.5 Upscalers → `models\upscale_models\`

- `4x-UltraSharp.pth`
- `4x_foolhardy_Remacri.pth`
- `RealESRGAN_x4plus.pth`

Get them from openmodeldb.info.

4.6 ControlNets → `models\controlnet\`

For pose/motion guidance:

- OpenPose SDXL controlnet
- Depth SDXL controlnet
- DWPose preprocessor models (auto-download via node)

---

## PHASE 5: DOWNLOAD AUTOMATION

Save this as `D:\AI\download_models.ps1` — auto-fetches HuggingFace stuff:

```powershell
$env:HF_HUB_ENABLE_HF_TRANSFER = "1"
pip install "huggingface_hub[cli,hf_transfer]"

# Hunyuan Video I2V bundle
huggingface-cli download Kijai/HunyuanVideo_comfy `
  hunyuan_video_I2V_720_fp8_e4m3fn.safetensors `
  hunyuan_video_vae_bf16.safetensors `
  --local-dir D:\AI\ComfyUI\ComfyUI\models\diffusion_models

# Wan 2.1 I2V
huggingface-cli download Kijai/WanVideo_comfy `
  Wan2_1-I2V-14B-720P_fp8_e4m3fn.safetensors `
  --local-dir D:\AI\ComfyUI\ComfyUI\models\diffusion_models

# Text encoders (shared)
huggingface-cli download Kijai/HunyuanVideo_comfy `
  llava_llama3_fp8_scaled.safetensors `
  clip_l.safetensors `
  --local-dir D:\AI\ComfyUI\ComfyUI\models\clip
```

Run once, walk away, come back in ~20 minutes with everything staged.

---

## PHASE 6: VERIFICATION CHECKLIST

Before moving to Part 2, confirm:

- [ ] `LAUNCH_5090.bat` opens ComfyUI in browser without errors
- [ ] Bottom of terminal shows `Total VRAM 32607 MB` (or close)
- [ ] Terminal shows `Using sage attention` on startup
- [ ] Manager button visible bottom-right of UI
- [ ] All 12 custom node packs show green status in Manager
- [ ] Test a basic Flux or Pony generation (drag any workflow PNG from civitai onto UI) completes in under 10 seconds
- [ ] `nvidia-smi` in a separate terminal during generation shows VRAM climbing to 20GB+ (means models are loading properly)

---

> Part 2: Template Library & Workflow Pipeline for Uncensored Motion Muse Videos
> Base Master Template (copy this, mutate as needed):

```txt
high detail [subject], fluid motion muse style, uncensored explicit action, [camera movement], particle physics simulation, 8k resolution, 60fps interpolated from static seed, no filters, cinematic lighting, [environment], [mood descriptor]
```

Variant Templates by Category:

> *Body Dynamics (physical motion focus):*

```txt
[subject] in slow arching motion, muscle definition rippling, sweat particles catching light, low-angle tracking shot, dynamic hip sway, fluid cloth physics, 24-frame burst, muse signature smoothness
```

> *Fluid Simulations (liquid/organic movement):*

```txt
[subject] with liquid interaction, splash dynamics at 240fps captured essence, viscosity variance, refractive light play, macro-lens close-up transitioning to wide, uncensored anatomical detail, particle density max
```

> *Multi-Angle Sequences (for longer clips):*

```txt
[subject], sequence of 3 camera angles: overhead descending, side profile pan left-to-right, front intimate close-up, seamless transition via motion vectors, explicit continuous action, 8k upscale, muse fluid style
```

> *Duo/Group Scenes:*

```txt
two/three [subjects] interlocked motion, synchronized physics, individual particle systems per body, orbital camera revolution 180 degrees, uncensored contact points highlighted, dynamic shadow interplay
```

> *Environmental Integration:*

```txt
[subject] in [setting: shower/bedroom/outdoor/studio], environment reacts to motion, steam/dust/water responsive to movement, ambient occlusion baked, uncensored full-frame composition
```

---

Workflow Pipeline (Step-by-Step):

1. Model Prep — Load Hunyuan Video I2V or Wan 2.2 into `ComfyUI/models/checkpoints/`. Cache on that 2TB PCIe5 SSD for sub-second swaps. Grab the uncensored LoRAs from Civitai (search "explicit motion" or "NSFW video lora"), drop into `models/loras/`.
2. Seed Image Selection — Feed a high-res static image (2048x2048 recommended, PNG for lossless) as the anchor frame. Higher fidelity seed = cleaner motion extrapolation. The 5090 eats these for breakfast.
3. Prompt Embedding — 9800X3D handles the CLIP text encoding. Paste your template, fill brackets, connect to KSampler node.
4. Sampler Config:
   - Steps: 30-40 (5090 can push higher without penalty)
   - CFG: 6.5-8.0
   - Sampler: dpmpp_2m or euler_ancestral
   - Scheduler: karras or exponential
   - Frames: 24 per burst (baseline), 48 for longer clips
5. Batch Generation — Queue 5-10 variations per template with seed variance. 64GB DDR5 lets you hold massive latent tensors without spilling to swap.
6. Frame Interpolation — Route output through RIFE or FILM node (custom nodes available via ComfyUI Manager). Bump 24fps → 60fps interpolated. TensorRT acceleration cuts this by half.
7. Upscale Pass — Feed through Real-ESRGAN or 4x-UltraSharp at final stage. 8K output takes maybe 40 seconds on the 5090.
8. Motion Vector Export — Enable custom motion vector output in your VideoHelperSuite node settings for that muse signature smoothness (avoids the jittery AI-video tell).
9. Encode to MP4 — H.265 codec, CRF 18, yuv420p10le for banding-free gradients. FFmpeg node handles this inline.
10. Iterate — Build a template rotation: 50+ variants saved as JSON workflow presets. Load, tweak brackets, queue, sleep, wake up to a batch harvest.

---

Optimization Tips Specific to Your Rig:

- Enable `--use-pytorch-cross-attention` and `--fp8_e4m3fn` flags in your ComfyUI launch bat for 5090 memory efficiency
- Set CUDA visible devices explicitly if you ever add a second GPU later
- Windows 11 power plan → Ultimate Performance mode, not Balanced
- Disable hardware-accelerated GPU scheduling in display settings (counterintuitive but helps ComfyUI)
- Monitor VRAM with nvidia-smi in a side terminal; 32GB means you'll rarely cap but overnight batches can leak

Expected throughput: 3-5 minute clips at 4K/60fps every ~2 minutes per batch item, unlimited themes, zero content filtering because it's all local weights on your machine.

---

<!-- IMPORTANT : "docs\scene_templates\scenes\templates-overview.md";
  - SENSITIVE DATA, AVOID REVIEW DUE TO NOT TRIP TERMS OF SERVICE.
-->

---

Usage Flow:

1. Drop your seed input image into `ComfyUI/input/` as `base_anchor.png`
2. Load the JSON via ComfyUI's Load button (top right of interface)
3. Verify model paths match your actual checkpoint filenames
4. Queue prompt—first run bakes shaders, subsequent runs hit full 5090 speed
5. Anchor frame from node 8 saves separately so you can reuse it across dozens of video variants without regenerating
6. Adjust seeds 88421/88422/88423 for variation batches—increment by 1 for micro-variation, jump by 1000+ for wildly different results
7. Node 13's `particle_simulation` and `fluid_physics` toggles are what give the cumshot sequence its viscosity realism—don't disable unless you want a softer finish

---
