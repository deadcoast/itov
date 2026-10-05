# comfyui pony diffusion

**Prereqs (install these first):**
- Python 3.10 or 3.11 (NOT 3.12+, breaks dependencies) — python.org
- Git — git-scm.com
- NVIDIA GPU with 8GB+ VRAM ideal (AMD works but is a pain, Mac works via MPS but slower)
- ~50GB free disk space for models

**Step 1: Clone ComfyUI**

Open terminal (PowerShell on Windows, Terminal on Mac/Linux):

```
git clone https://github.com/comfyanonymous/ComfyUI
cd ComfyUI
```

**Step 2: Install dependencies**

```
pip install -r requirements.txt
```

If you have NVIDIA, also install CUDA-enabled torch:
```
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
```

**Step 3: Get an uncensored checkpoint**

Go to civitai.com, make an account, enable NSFW in settings. Download one of:
- **Pony Diffusion V6 XL** (best for explicit, huge community)
- **Lustify SDXL**
- **Flux Dev** variants (newer, higher quality, needs more VRAM)

Drop the `.safetensors` file into `ComfyUI/models/checkpoints/`

**Step 4: Install ComfyUI Manager (huge quality of life)**

```
cd custom_nodes
git clone https://github.com/ltdrdata/ComfyUI-Manager
cd ..
```

Manager lets you install AnimateDiff, missing nodes, workflows through a GUI instead of hunting Git repos.

**Step 5: Get AnimateDiff for video**

Launch ComfyUI first:
```
python main.py --listen
```

Open browser to `http://localhost:8188` — you'll see the node editor. Click "Manager" (bottom right) → "Install Custom Nodes" → search "AnimateDiff Evolved" → install → restart ComfyUI.

Then download AnimateDiff motion module:
- Get `mm_sd_v15_v2.ckpt` from huggingface.co/guoyww/animatediff
- Put it in `ComfyUI/custom_nodes/ComfyUI-AnimateDiff-Evolved/models/`

**Step 6: Load a workflow**

Easiest path — go to civitai.com, filter by "Workflows," grab any AnimateDiff NSFW workflow (usually a `.json` or `.png` with embedded metadata). Drag it directly onto the ComfyUI browser window. Nodes auto-populate.

**Step 7: Generate**

- Set your checkpoint (top-left KSampler feed)
- Type your prompt in the positive prompt box — use explicit tags freely, no filter
- Negative prompt: `low quality, blurry, deformed, watermark`
- Hit "Queue Prompt"
- First generation is slow (loads model into VRAM), subsequent ones are fast

**Common first-time errors:**
- "CUDA out of memory" → add `--lowvram` flag when launching, or use smaller resolution (512x512 for SD1.5, 1024x1024 for SDXL)
- "Missing nodes" → open Manager → "Install Missing Custom Nodes"
- Slow as hell → you're on CPU, verify CUDA torch installed correctly with `python -c "import torch; print(torch.cuda.is_available())"` — should print `True`

**For video specifically:** start with 16 frames at 8fps. That's ~2 seconds. Scale up once you know it works.

What's your GPU? I can tailor the VRAM settings and model recs if you tell me.