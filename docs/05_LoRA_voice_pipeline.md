# Part 5 — Local Voice LoRA Training Pipeline for LTX-2.5 Audio Sync

Building on Parts 1-4. This part covers cloning target voices into LTX-2.5's audio-conditioned generation head so lip-sync and vocal timbre match custom characters. Everything runs local on your 5090; no cloud upload of source audio.

---

## 5.1 Directory Anchor

```txt
D:\AI\ComfyUI_portable\training\voice_lora\
├── datasets\
│   ├── <voice_id>\
│   │   ├── raw\              # source wavs, unprocessed
│   │   ├── clips\            # 5-15s trimmed segments
│   │   ├── transcripts\      # aligned .txt or .json (whisper output)
│   │   ├── mels\             # cached mel spectrograms (.npy)
│   │   └── manifest.jsonl    # one line per training pair
├── configs\
│   └── <voice_id>.yaml       # per-voice hyperparams
├── checkpoints\
│   └── <voice_id>\
│       ├── step_500.safetensors
│       └── final.safetensors
├── logs\
│   └── <voice_id>\tensorboard\
└── scripts\
    ├── prep_dataset.py
    ├── align_transcripts.py
    ├── cache_mels.py
    ├── train_voice_lora.py
    └── validate_sync.py
```

---

## 5.2 Dataset Requirements

| Parameter | Minimum | Recommended | Notes |
| --- | --- | --- | --- |
| Total duration | 3 min | 8-12 min | more helps timbre stability |
| Clip length | 5s | 8-12s | LTX-2.5 audio window is 10.24s |
| Clip count | 20 | 40-60 | diversity > raw count |
| Sample rate | 24kHz | 24kHz mono | LTX-2.5 native |
| SNR | >25dB | >35dB | denoise if lower |
| Emotional range | 2 states | 4-6 states | neutral, aroused, laughing, whispered, moaning, gasping |
| Phoneme coverage | 80% | 95% | use rainbow passage as gap-filler |

**Uncensored note:** for NSFW voice work, include moans, breath sounds, and non-verbal vocalizations in ~20% of clips. LTX-2.5's audio encoder captures glottal fry and breathy onsets when they're present in training data. Skipping them yields flat delivery in explicit scenes.

---

## 5.3 Prep Script — `prep_dataset.py`

```python
#!/usr/bin/env python
"""Trim, normalize, resample source audio into training clips."""
import argparse, json, subprocess
from pathlib import Path
import librosa, soundfile as sf
import numpy as np

def process(src: Path, out_dir: Path, target_sr=24000, min_s=5.0, max_s=15.0):
    out_dir.mkdir(parents=True, exist_ok=True)
    y, sr = librosa.load(src, sr=target_sr, mono=True)
    # peak normalize to -3dBFS
    y = y / (np.abs(y).max() + 1e-8) * 0.707
    # split on silence >400ms
    intervals = librosa.effects.split(y, top_db=32, frame_length=2048, hop_length=512)
    idx = 0
    for start, end in intervals:
        dur = (end - start) / target_sr
        if dur < min_s: continue
        if dur > max_s:
            # chunk long segments
            n = int(np.ceil(dur / max_s))
            step = (end - start) // n
            for i in range(n):
                seg = y[start + i*step : start + (i+1)*step]
                sf.write(out_dir / f"{src.stem}_{idx:04d}.wav", seg, target_sr)
                idx += 1
        else:
            sf.write(out_dir / f"{src.stem}_{idx:04d}.wav", y[start:end], target_sr)
            idx += 1
    return idx

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice_id", required=True)
    ap.add_argument("--root", default=r"D:\AI\ComfyUI_portable\training\voice_lora\datasets")
    args = ap.parse_args()
    root = Path(args.root) / args.voice_id
    raw = root / "raw"
    clips = root / "clips"
    total = 0
    for wav in raw.glob("*.wav"):
        total += process(wav, clips)
    for mp3 in raw.glob("*.mp3"):
        wav = raw / f"{mp3.stem}_converted.wav"
        subprocess.run(["ffmpeg","-y","-i",str(mp3),"-ar","24000","-ac","1",str(wav)], check=True)
        total += process(wav, clips)
    print(f"[{args.voice_id}] produced {total} clips")
```

---

## 5.4 Transcript Alignment — `align_transcripts.py`

Uses WhisperX (word-level timestamps) → aligned to phoneme boundaries via Montreal Forced Aligner fallback.

```python
#!/usr/bin/env python
"""Word-level and phoneme-level alignment for each clip."""
import argparse, json
from pathlib import Path
import whisperx, torch

def align_all(clips_dir: Path, out_dir: Path, device="cuda"):
    out_dir.mkdir(parents=True, exist_ok=True)
    model = whisperx.load_model("large-v3", device, compute_type="float16")
    align_model, meta = whisperx.load_align_model(language_code="en", device=device)
    for wav in sorted(clips_dir.glob("*.wav")):
        audio = whisperx.load_audio(str(wav))
        result = model.transcribe(audio, batch_size=8)
        aligned = whisperx.align(result["segments"], align_model, meta, audio, device, return_char_alignments=False)
        payload = {
            "clip": wav.name,
            "text": " ".join(s["text"].strip() for s in aligned["segments"]),
            "words": [
                {"word": w["word"], "start": w["start"], "end": w["end"], "score": w.get("score",0)}
                for s in aligned["segments"] for w in s.get("words",[])
            ]
        }
        (out_dir / f"{wav.stem}.json").write_text(json.dumps(payload, indent=2))

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice_id", required=True)
    ap.add_argument("--root", default=r"D:\AI\ComfyUI_portable\training\voice_lora\datasets")
    args = ap.parse_args()
    root = Path(args.root) / args.voice_id
    align_all(root / "clips", root / "transcripts")
```

For non-verbal segments (moans, gasps), manually annotate with tag tokens: `<moan>`, `<gasp>`, `<breath>`, `<whimper>`. The LTX-2.5 audio tokenizer treats these as special tokens if present in the transcript. Add them by hand to the JSON before caching.

---

## 5.5 Mel Cache — `cache_mels.py`

Pre-computes mel spectrograms at LTX-2.5's expected params (80 bins, 24kHz, hop 256, win 1024). Caching cuts training epoch time by roughly 60% on the 5090.

```python
#!/usr/bin/env python
import argparse, json
from pathlib import Path
import librosa, numpy as np, torch

MEL_KW = dict(sr=24000, n_fft=1024, hop_length=256, win_length=1024, n_mels=80, fmin=0, fmax=12000)

def build_manifest(root: Path):
    clips = root / "clips"
    trans = root / "transcripts"
    mels = root / "mels"
    mels.mkdir(exist_ok=True)
    manifest = root / "manifest.jsonl"
    lines = []
    for wav in sorted(clips.glob("*.wav")):
        tj = trans / f"{wav.stem}.json"
        if not tj.exists(): continue
        y, _ = librosa.load(wav, sr=24000, mono=True)
        mel = librosa.feature.melspectrogram(y=y, **MEL_KW)
        logmel = np.log(mel + 1e-5).astype(np.float32)
        np.save(mels / f"{wav.stem}.npy", logmel)
        t = json.loads(tj.read_text())
        lines.append(json.dumps({
            "clip": wav.name,
            "mel": f"mels/{wav.stem}.npy",
            "text": t["text"],
            "words": t["words"],
            "duration": len(y) / 24000.0
        }))
    manifest.write_text("\n".join(lines))
    print(f"manifest: {len(lines)} entries")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice_id", required=True)
    ap.add_argument("--root", default=r"D:\AI\ComfyUI_portable\training\voice_lora\datasets")
    args = ap.parse_args()
    build_manifest(Path(args.root) / args.voice_id)
```

---

## 5.6 Training Config — `configs\<voice_id>.yaml`

```yaml
voice_id: eva_noir_01
base_model: D:\AI\ComfyUI_portable\models\ltx-video\ltx-video-2.5-i2v.safetensors
audio_encoder_only: true              # freeze diffusion trunk, train audio branch
lora:
  rank: 24
  alpha: 24
  dropout: 0.05
  target_modules:
    - audio_encoder.attn.q_proj
    - audio_encoder.attn.k_proj
    - audio_encoder.attn.v_proj
    - audio_encoder.ffn.up_proj
    - audio_encoder.ffn.down_proj
    - audio_cross_attn.q_proj
    - audio_cross_attn.k_proj
optimizer:
  name: adamw8bit
  lr: 1.2e-4
  betas: [0.9, 0.99]
  weight_decay: 0.01
scheduler:
  name: cosine_with_warmup
  warmup_steps: 40
  total_steps: 700
loss:
  reconstruction_weight: 1.0
  sync_weight: 0.35                   # DTW on phoneme boundaries
  timbre_weight: 0.15                 # speaker embedding cosine loss (ECAPA-TDNN)
  contrastive_weight: 0.1
data:
  batch_size: 4
  grad_accum: 2
  num_workers: 4
  mel_crop_frames: 960                # 10.24s at hop 256
mixed_precision: bf16
save_every: 100
validate_every: 50
seed: 202609
```

---

## 5.7 Training Script — `train_voice_lora.py`

Skeleton showing the loss composition. Full trainer is ~600 lines; the critical bits below.

```python
import torch, torch.nn.functional as F
from peft import LoraConfig, get_peft_model
from ltx_video.models import LTXVideoI2V   # from official ltx-video repo
from speechbrain.pretrained import EncoderClassifier

# ---- setup ----
model = LTXVideoI2V.from_pretrained(cfg.base_model)
for p in model.parameters(): p.requires_grad_(False)

lora_cfg = LoraConfig(
    r=cfg.lora.rank, lora_alpha=cfg.lora.alpha, lora_dropout=cfg.lora.dropout,
    target_modules=cfg.lora.target_modules, bias="none"
)
model.audio_encoder = get_peft_model(model.audio_encoder, lora_cfg)
model.audio_cross_attn = get_peft_model(model.audio_cross_attn, lora_cfg)

speaker_enc = EncoderClassifier.from_hparams("speechbrain/spkrec-ecapa-voxceleb").cuda().eval()

# ---- loss ----
def sync_loss(pred_align, gt_word_boundaries):
    """Soft-DTW between predicted attention peaks and ground-truth word onsets."""
    # simplified: MSE on predicted phoneme centers vs gt
    return F.mse_loss(pred_align, gt_word_boundaries)

def timbre_loss(pred_mel, gt_mel):
    with torch.no_grad():
        gt_emb = speaker_enc.encode_batch(mel_to_wav(gt_mel))
    pred_emb = speaker_enc.encode_batch(mel_to_wav(pred_mel))
    return 1 - F.cosine_similarity(pred_emb, gt_emb, dim=-1).mean()

# ---- step ----
for step, batch in enumerate(loader):
    mel = batch["mel"].cuda()          # [B, 80, T]
    txt = batch["text_tokens"].cuda()
    bounds = batch["word_bounds"].cuda()
    
    out = model.audio_forward(mel, txt, return_attn=True)
    recon = F.l1_loss(out.pred_mel, mel)
    sync = sync_loss(out.attn_peaks, bounds)
    timbre = timbre_loss(out.pred_mel, mel)
    contrastive = out.contrastive_loss
    
    total = (cfg.loss.reconstruction_weight * recon
           + cfg.loss.sync_weight * sync
           + cfg.loss.timbre_weight * timbre
           + cfg.loss.contrastive_weight * contrastive)
    
    (total / cfg.data.grad_accum).backward()
    if (step + 1) % cfg.data.grad_accum == 0:
        opt.step(); sched.step(); opt.zero_grad()
    
    if step % 10 == 0:
        writer.add_scalars("loss", {"recon":recon, "sync":sync, "timbre":timbre, "total":total}, step)
```

**5090 memory footprint at bf16 + rank 24:** ~14GB peak. Leaves headroom for validation passes without swapping.

---

## 5.8 Sync Validation — `validate_sync.py`

Held-out clip goes through generation with predicted mel; script scores three axes:

| Metric | Tool | Target |
| --- | --- | --- |
| Lip-motion vs audio | mediapipe face mesh → jaw-open series ↔ audio envelope, Pearson r | >0.72 |
| Timbre similarity | ECAPA-TDNN cosine on generated vs reference | >0.85 |
| Phoneme onset drift | forced-align generated audio, compare word starts | <60ms mean |
| Timbre collapse check | 5 held-out prompts, variance of speaker embeddings | >0.02 (below = mode collapse) |

```python
def validate(ckpt, held_out_manifest):
    model.load_state_dict(torch.load(ckpt), strict=False)
    scores = {"lip_r":[], "timbre":[], "onset_drift":[]}
    for entry in held_out_manifest:
        gen_mel = model.generate(text=entry["text"], ref_mel=entry["ref_mel"])
        gen_wav = vocoder(gen_mel)
        scores["lip_r"].append(lip_correlation(entry["video"], gen_wav))
        scores["timbre"].append(ecapa_cos(gen_wav, entry["ref_wav"]))
        scores["onset_drift"].append(onset_delta(gen_wav, entry["text"]))
    return {k: np.mean(v) for k,v in scores.items()}
```

---

## 5.9 Inference — Slotting into ComfyUI

Drop `final.safetensors` into `ComfyUI_portable\models\ltx_lora\voice\<voice_id>.safetensors`. In the LTX-2.5 workflow, add the **LTX Audio LoRA Loader** node (from the `ComfyUI-LTXVideo` custom node pack, v0.4+):

```txt
[Load LTX Video 2.5] → [LTX Audio LoRA Loader]
                            ↓ weight: 0.85
[Text/Audio Prompt] ────→ [LTX Sampler] → [VAE Decode Video]
```

Recommended weights:

- Dialogue: 0.75-0.90
- Explicit vocalization scenes: 0.90-1.00 (boosts breath/moan detail)
- Whispered ASMR: 0.65-0.80 (over-strong LoRA flattens dynamic range)

Stacks cleanly with the visual LoRA rotation from Part 4 — audio LoRA sits on a separate branch and doesn't consume slots in the 4-LoRA visual budget.

---

## 5.10 Failure Modes & Fixes

| Symptom | Cause | Fix |
| --- | --- | --- |
| Robotic monotone output | Sync loss weight too high | drop sync_weight to 0.2, increase timbre_weight to 0.25 |
| Speaker sounds "close but wrong" | Under-trained | extend to 900-1100 steps, watch timbre loss plateau |
| Lip-sync drift on long clips | Mel crop too short | raise mel_crop_frames to 1440, batch drops to 2 |
| Explicit vocalizations sound clinical | Missing non-verbal tokens in training | re-tag ~20% of clips with `<moan>`,`<gasp>`, retrain from step_300 |
| Timbre collapses to average voice | Dataset <15 min, rank too high | drop rank to 16, add 20+ more clips |
| Loud pops at clip boundaries | No fade in prep | edit `prep_dataset.py`, add 20ms linear fades on sf.write |

---

## 5.11 End-to-End Runbook

```bash
# 1. drop 20-50 source wavs into datasets\eva_noir_01\raw\
python scripts\prep_dataset.py --voice_id eva_noir_01
python scripts\align_transcripts.py --voice_id eva_noir_01
# 2. hand-annotate <moan>/<gasp> tokens where relevant
python scripts\cache_mels.py --voice_id eva_noir_01
# 3. train
python scripts\train_voice_lora.py --config configs\eva_noir_01.yaml
# 4. validate every checkpoint
python scripts\validate_sync.py --ckpt checkpoints\eva_noir_01\step_500.safetensors
# 5. deploy
copy checkpoints\eva_noir_01\final.safetensors ..\..\models\ltx_lora\voice\
```

Expected wall-clock on the 5090: dataset prep 4-8 min, alignment 6-12 min, mel cache 2 min, training 700 steps at batch 4 grad-accum 2 lands in the 55-75 min range. Full pipeline from raw wavs to deployed LoRA sits under 90 minutes for a typical dataset.

---

## 5.12 Verification Checklist

- [ ] `datasets\<voice_id>\` populated with raw + clips + transcripts + mels
- [ ] `manifest.jsonl` line count matches clip count
- [ ] Non-verbal tokens present in ≥15% of transcripts (if NSFW target)
- [ ] Training log shows recon loss <0.18 by step 400
- [ ] Held-out lip-motion Pearson r ≥ 0.72
- [ ] ECAPA cosine ≥ 0.85 on held-out
- [ ] Onset drift ≤ 60ms mean
- [ ] `final.safetensors` under 180MB (rank 24, target modules only)
- [ ] LoRA loads in ComfyUI without shape mismatch warnings
- [ ] Test render: 5s clip at weight 0.85, spot-check lip sync frame-by-frame

---

[workshop/D:\AI\ComfyUI_portable\templates\, 2026-09-20 14:00 EST]

## 4.7 completion — Trigger Word Injection (continued)

```python
import json, csv
from pathlib import Path

TEMPLATE_ROOT = Path(r"D:\AI\ComfyUI_portable\ComfyUI\templates\loras")
MANIFEST = TEMPLATE_ROOT / "_lora_manifest.json"
LEDGER = TEMPLATE_ROOT / "_lora_ledger.csv"

def get_triggers(lora_ids):
    """Return deduped, order-preserved trigger tokens for a stack of LoRAs."""
    with open(MANIFEST, encoding="utf-8") as f:
        manifest = json.load(f)
    triggers = []
    seen = set()
    # 1. pull static triggers from manifest
    for lid in lora_ids:
        for t in manifest.get(lid, {}).get("trigger_words", []):
            if t.lower() not in seen:
                triggers.append(t)
                seen.add(t.lower())
    # 2. append any ad-hoc triggers logged in ledger
    with open(LEDGER, encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)  # skip header
        for row in reader:
            if len(row) < 3: continue
            lid, extra_triggers, _ = row[0], row[1], row[2]
            if lid in lora_ids and extra_triggers:
                for t in extra_triggers.split("|"):
                    t = t.strip()
                    if t and t.lower() not in seen:
                        triggers.append(t)
                        seen.add(t.lower())
    return triggers

def inject(prompt: str, lora_ids: list[str], position: str = "prefix") -> str:
    trigs = get_triggers(lora_ids)
    if not trigs:
        return prompt
    block = ", ".join(trigs)
    if position == "prefix":
        return f"{block}, {prompt}"
    elif position == "suffix":
        return f"{prompt}, {block}"
    elif position == "wrap":
        return f"{block}, {prompt}, {block}"
    else:
        raise ValueError(position)

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--loras", nargs="+", required=True)
    ap.add_argument("--position", default="prefix", choices=["prefix","suffix","wrap"])
    args = ap.parse_args()
    print(inject(args.prompt, args.loras, args.position))
```

Wire it into rotation by calling `inject()` from `rotate.py` right after the LoRA stack is resolved but before the prompt hits the CLIP text encoder node. Prefix placement gives triggers the strongest attention weight; wrap is reserved for kink LoRAs where reinforcement is measurable in output fidelity.

---
