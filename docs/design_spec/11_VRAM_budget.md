# PART 11 — THE VRAM BUDGET PLANNER

## 11.0 Why this exists before Part 14

The batch orchestrator (Part 14) is going to press "go" on hundreds of compositions overnight. If even 3% of them OOM at model-load time, you lose that percentage of the queue plus the tail of everything that was warming behind it, because ComfyUI's crash recovery flushes the whole VRAM state and re-cold-starts. On a 40-clip/hour cadence that's a full hour of throughput per crash. The planner's job is to catch OOM compositions *before* they're ever queued — a static pass over the proposed stack that says "yes fits," "borderline, offload N blocks," or "no, reject."

Directory anchor:

```txt
D:\AI\ComfyUI_portable\workshop\scrape\vram\
├── config\
│   └── vram_budget.yaml
├── profiles\
│   ├── checkpoints\           (per-model base cost profiles)
│   ├── loras\                 (per-LoRA delta profiles from sandbox)
│   ├── vae\
│   ├── clip\
│   └── _profile_index.json
├── bin\
│   ├── vram_planner.py        (the analyzer)
│   ├── profile_capture.py     (sandbox measurement tool)
│   └── profile_backfill.py    (bulk re-profile on driver/torch changes)
├── logs\
│   ├── planner_decisions.csv
│   └── oom_incidents.csv
└── cache\
    └── stack_predictions.jsonl   (memoized results, keyed by stack hash)
```

## 11.1 The memory model

Peak VRAM on a Wan 2.2 / Hunyuan 2.0 / LTX 2.5 i2v render is the sum of, roughly:

```txt
peak = base_checkpoint
     + text_encoder_resident
     + vae_resident
     + Σ (lora_delta_i × strength_i^p)
     + latent_working_set(frames, resolution)
     + attention_working_set(frames, resolution, attn_impl)
     + safety_headroom
```

Two of those terms are non-obvious:

- `lora_delta_i × strength_i^p` — LoRA VRAM cost scales sub-linearly with strength on fused loaders (rgthree Power Loader fuses at load time). Empirically `p ≈ 0.85` on Blackwell fp8 paths. Store `p` per-loader in config, not per-LoRA.
- `attention_working_set` — sage-attention v2 uses ~40% less peak than default SDPA for the same (frames, resolution). The planner has to know which attention impl the runner will use.

Everything else is either constant-per-model (measured once, cached) or a closed-form function of frames × resolution × precision.

## 11.2 Config — `vram_budget.yaml`

```yaml
version: 11.0
gpu:
  name: "RTX 5090"
  total_vram_mb: 32607
  reserved_system_mb: 1200      # Windows compositor + display
  reserved_torch_mb: 800        # CUDA context, allocator overhead
  effective_ceiling_mb: 30607   # what the planner actually budgets against

safety:
  headroom_mb: 1500             # never plan above ceiling - headroom
  borderline_threshold_mb: 800  # within this of the cap → recommend block-swap
  reject_threshold_mb: 0        # above cap → hard reject

scaling:
  lora_strength_exponent: 0.85
  block_swap_savings_mb_per_block:
    wan2.2_14b: 340
    hunyuan2.0: 380
    ltx2.5: 210

attention:
  default_impl: "sage_v2"
  working_set_multiplier:
    sage_v2: 1.00
    sdpa: 1.68
    xformers: 1.22

latent:
  # bytes per pixel per frame, precision-dependent
  fp8_bytes_per_px_per_frame: 1.5
  bf16_bytes_per_px_per_frame: 3.0

profile_index_path: "../profiles/_profile_index.json"
decision_log: "../logs/planner_decisions.csv"
oom_log: "../logs/oom_incidents.csv"
prediction_cache: "../cache/stack_predictions.jsonl"
```

Two knobs you'll actually tune over time: `lora_strength_exponent` (re-fit after every driver bump) and `block_swap_savings_mb_per_block` (measured empirically per checkpoint family).

## 11.3 Profile schema

Every profileable asset has a JSON sidecar. Example — `profiles/checkpoints/wan2.2-i2v-14b-fp8.json`:

```json
{
  "asset_id": "wan2.2-i2v-14b-fp8",
  "asset_type": "checkpoint",
  "sha256": "a1b2c3…",
  "file_size_mb": 14200,
  "resident_vram_mb": {
    "load_only": 14380,
    "warm_idle": 14420,
    "first_forward": 15100
  },
  "attention_compatible": ["sage_v2", "sdpa"],
  "block_swap_supported": true,
  "block_count": 40,
  "profiled_at": "2026-09-18T22:14:00Z",
  "profiled_with": {
    "torch": "2.6.0.dev20260901+cu128",
    "sageattention": "2.1.4",
    "driver": "580.42"
  }
}
```

LoRA profile — `profiles/loras/anatomy_realistic_vulva_v4.json`:

```json
{
  "asset_id": "anatomy_realistic_vulva_v4",
  "asset_type": "lora",
  "sha256": "d4e5f6…",
  "file_size_mb": 148,
  "delta_vram_mb_at_strength_1.0": 172,
  "delta_measured_strengths": {
    "0.4": 82,
    "0.7": 128,
    "1.0": 172
  },
  "fitted_exponent": 0.87,
  "fuses_cleanly_with": ["wan2.2-i2v-14b-fp8", "hunyuan2.0-i2v"],
  "profiled_at": "2026-09-19T03:22:00Z"
}
```

`delta_measured_strengths` is what `profile_capture.py` writes; `fitted_exponent` is what `profile_backfill.py` regresses across the pool to sanity-check the global `lora_strength_exponent` in config.

## 11.4 `vram_planner.py` — the analyzer

```python
"""
vram_planner.py — static VRAM peak predictor for i2v stacks.

Usage:
  python vram_planner.py --stack stack.json
  python vram_planner.py --from-ledger-tail
  python vram_planner.py --batch queue.jsonl --reject-file rejected.jsonl
"""
from __future__ import annotations
import json, sys, hashlib, csv, argparse
from pathlib import Path
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional
import yaml

ROOT = Path(r"D:\AI\ComfyUI_portable\workshop\scrape\vram")
CFG_PATH = ROOT / "config" / "vram_budget.yaml"

@dataclass
class StackSpec:
    checkpoint: str
    vae: str
    clip: str
    loras: list[dict]              # [{"lora_id": str, "strength": float}, ...]
    frames: int
    width: int
    height: int
    precision: str                 # "fp8" | "bf16"
    attention_impl: str            # "sage_v2" | "sdpa" | "xformers"
    block_swap_blocks: int = 0     # 0 = no swap; >0 = N blocks offloaded to RAM

@dataclass
class Prediction:
    stack_hash: str
    predicted_peak_mb: int
    ceiling_mb: int
    headroom_mb: int
    verdict: str                   # "fit" | "borderline" | "reject"
    breakdown: dict
    recommended_block_swap: int
    notes: list[str]

def load_config() -> dict:
    with open(CFG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_profile(cfg: dict, asset_type: str, asset_id: str) -> Optional[dict]:
    idx_path = (CFG_PATH.parent / cfg["profile_index_path"]).resolve()
    with open(idx_path, "r", encoding="utf-8") as f:
        idx = json.load(f)
    entry = idx.get(asset_type, {}).get(asset_id)
    if not entry:
        return None
    profile_path = (idx_path.parent / entry["path"]).resolve()
    with open(profile_path, "r", encoding="utf-8") as f:
        return json.load(f)

def hash_stack(spec: StackSpec) -> str:
    payload = json.dumps(asdict(spec), sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()[:16]

def latent_working_set_mb(spec: StackSpec, cfg: dict) -> float:
    px = spec.width * spec.height
    bpp = (cfg["latent"]["fp8_bytes_per_px_per_frame"]
           if spec.precision == "fp8"
           else cfg["latent"]["bf16_bytes_per_px_per_frame"])
    return (px * spec.frames * bpp) / (1024 * 1024)

def attention_working_set_mb(spec: StackSpec, cfg: dict) -> float:
    # Baseline: latent set × attention multiplier × sequence factor
    base = latent_working_set_mb(spec, cfg)
    mult = cfg["attention"]["working_set_multiplier"].get(spec.attention_impl, 1.5)
    # Sequence factor grows with sqrt(frames) for temporal attention
    seq_factor = (spec.frames / 24.0) ** 0.5
    return base * mult * seq_factor * 1.4

def lora_delta_mb(lora: dict, profile: dict, cfg: dict) -> float:
    strength = lora["strength"]
    base = profile["delta_vram_mb_at_strength_1.0"]
    exp = cfg["scaling"]["lora_strength_exponent"]
    return base * (strength ** exp)

def block_swap_savings_mb(spec: StackSpec, ckpt_family: str, cfg: dict) -> float:
    per_block = cfg["scaling"]["block_swap_savings_mb_per_block"].get(ckpt_family, 0)
    return per_block * spec.block_swap_blocks

def infer_ckpt_family(ckpt_id: str) -> str:
    lid = ckpt_id.lower()
    if "wan2.2" in lid or "wan2_2" in lid: return "wan2.2_14b"
    if "hunyuan" in lid: return "hunyuan2.0"
    if "ltx" in lid: return "ltx2.5"
    return "unknown"

def predict(spec: StackSpec, cfg: dict) -> Prediction:
    notes: list[str] = []
    ceiling = cfg["gpu"]["effective_ceiling_mb"]
    headroom = cfg["safety"]["headroom_mb"]
    budget = ceiling - headroom

    ckpt_prof = load_profile(cfg, "checkpoints", spec.checkpoint)
    vae_prof  = load_profile(cfg, "vae", spec.vae)
    clip_prof = load_profile(cfg, "clip", spec.clip)

    if not ckpt_prof:
        raise RuntimeError(f"no profile for checkpoint {spec.checkpoint} — run profile_capture.py first")

    base_ckpt = ckpt_prof["resident_vram_mb"]["first_forward"]
    base_vae  = vae_prof["resident_vram_mb"]["warm_idle"] if vae_prof else 350
    base_clip = clip_prof["resident_vram_mb"]["warm_idle"] if clip_prof else 900

    lora_total = 0.0
    for lora in spec.loras:
        prof = load_profile(cfg, "loras", lora["lora_id"])
        if not prof:
            notes.append(f"unprofiled lora {lora['lora_id']} — assumed 200 MB @ strength 1.0")
            lora_total += 200 * (lora["strength"] ** cfg["scaling"]["lora_strength_exponent"])
        else:
            lora_total += lora_delta_mb(lora, prof, cfg)

    latent_ws = latent_working_set_mb(spec, cfg)
    attn_ws   = attention_working_set_mb(spec, cfg)

    family = infer_ckpt_family(spec.checkpoint)
    swap_save = block_swap_savings_mb(spec, family, cfg)
    if spec.block_swap_blocks > 0:
        notes.append(f"block-swap: {spec.block_swap_blocks} blocks → -{int(swap_save)} MB")

    peak = int(base_ckpt + base_vae + base_clip + lora_total + latent_ws + attn_ws - swap_save)

    room = budget - peak
    if peak > ceiling:
        verdict = "reject"
    elif room < cfg["safety"]["borderline_threshold_mb"]:
        verdict = "borderline"
    else:
        verdict = "fit"

    # Recommend block-swap if borderline/reject and family supports it
    rec_swap = 0
    if verdict != "fit" and ckpt_prof.get("block_swap_supported") and family in cfg["scaling"]["block_swap_savings_mb_per_block"]:
        per_block = cfg["scaling"]["block_swap_savings_mb_per_block"][family]
        needed = (peak - (budget - cfg["safety"]["borderline_threshold_mb"] - 200))
        rec_swap = min(ckpt_prof.get("block_count", 40), max(0, int(needed / per_block) + 1))
        if rec_swap:
            notes.append(f"recommendation: enable block_swap_blocks={rec_swap} to reach 'fit'")

    breakdown = {
        "checkpoint_mb": int(base_ckpt),
        "vae_mb": int(base_vae),
        "clip_mb": int(base_clip),
        "loras_mb": int(lora_total),
        "latent_working_set_mb": int(latent_ws),
        "attention_working_set_mb": int(attn_ws),
        "block_swap_savings_mb": int(swap_save),
    }

    return Prediction(
        stack_hash=hash_stack(spec),
        predicted_peak_mb=peak,
        ceiling_mb=ceiling,
        headroom_mb=int(room),
        verdict=verdict,
        breakdown=breakdown,
        recommended_block_swap=rec_swap,
        notes=notes,
    )

def log_decision(pred: Prediction, cfg: dict, spec: StackSpec):
    path = (CFG_PATH.parent / cfg["decision_log"]).resolve()
    exists = path.exists()
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(["timestamp", "stack_hash", "verdict", "peak_mb", "headroom_mb",
                        "checkpoint", "lora_count", "frames", "resolution", "block_swap"])
        w.writerow([
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            pred.stack_hash, pred.verdict, pred.predicted_peak_mb, pred.headroom_mb,
            spec.checkpoint, len(spec.loras), spec.frames,
            f"{spec.width}x{spec.height}", spec.block_swap_blocks,
        ])

def cache_prediction(pred: Prediction, cfg: dict):
    path = (CFG_PATH.parent / cfg["prediction_cache"]).resolve()
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(pred)) + "\n")

def load_stack(path: Path) -> StackSpec:
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    return StackSpec(**d)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stack", type=Path, help="single stack JSON to evaluate")
    ap.add_argument("--batch", type=Path, help="JSONL of stacks to evaluate")
    ap.add_argument("--reject-file", type=Path, help="write rejected stacks here")
    ap.add_argument("--json", action="store_true", help="emit prediction as JSON")
    args = ap.parse_args()

    cfg = load_config()

    if args.stack:
        spec = load_stack(args.stack)
        pred = predict(spec, cfg)
        log_decision(pred, cfg, spec)
        cache_prediction(pred, cfg)
        if args.json:
            print(json.dumps(asdict(pred), indent=2))
        else:
            print(f"[{pred.verdict.upper()}] {pred.stack_hash}  peak={pred.predicted_peak_mb} MB  "
                  f"headroom={pred.headroom_mb} MB")
            for k, v in pred.breakdown.items():
                print(f"    {k:32s} {v:>6} MB")
            for n in pred.notes:
                print(f"    · {n}")
        sys.exit(0 if pred.verdict != "reject" else 2)

    if args.batch:
        rejected = []
        with open(args.batch, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line: continue
                spec = StackSpec(**json.loads(line))
                pred = predict(spec, cfg)
                log_decision(pred, cfg, spec)
                cache_prediction(pred, cfg)
                if pred.verdict == "reject":
                    rejected.append({"stack": asdict(spec), "prediction": asdict(pred)})
                print(f"[{pred.verdict.upper():10s}] {pred.stack_hash}  peak={pred.predicted_peak_mb} MB")
        if args.reject_file and rejected:
            with open(args.reject_file, "w", encoding="utf-8") as f:
                for r in rejected:
                    f.write(json.dumps(r) + "\n")
        sys.exit(0)

    ap.print_help()
    sys.exit(1)

if __name__ == "__main__":
    main()
```

## 11.5 `profile_capture.py` — the measurement tool

**Path:** `D:\AI\ComfyUI_portable\workshop\scrape\vram\profile_capture.py`

Where `vram_planner.py` *predicts*, `profile_capture.py` *measures*. It hooks a running ComfyUI process via its `/prompt` + `/history` HTTP API, drives a canonical calibration workflow, and samples `nvidia-smi` (plus the Python-side `torch.cuda.mem_get_info`) at 250ms cadence to build the per-checkpoint, per-resolution profile rows that feed `_profile_index.json`.

The tool is deliberately dumb about *what* it profiles — you point it at a workflow JSON and a variant matrix, and it grinds through every combination, writing one profile row per successful run. Every failure (OOM, timeout, node error) becomes a row too, tagged `status: "oom"` or `status: "error"`, so the planner learns the ceiling as well as the floor.

```python
"""
profile_capture.py — measure real VRAM behavior of ComfyUI workflows.

Drives a running ComfyUI instance via HTTP, samples GPU memory during
execution, and emits profile rows into _profile_index.json.

Usage:
    python profile_capture.py \
        --workflow calibration_i2v.json \
        --matrix calibration_matrix.yaml \
        --out D:\\AI\\ComfyUI_portable\\workshop\\scrape\\vram\\profiles \
        --comfy http://127.0.0.1:8188

Exit codes:
    0  all variants captured (some may be OOM/error rows — that's still data)
    2  ComfyUI unreachable or calibration workflow malformed
    3  I/O failure writing profiles
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests
import yaml

try:
    import torch
    HAS_TORCH = torch.cuda.is_available()
except ImportError:
    HAS_TORCH = False

UTC = timezone.utc
SAMPLE_INTERVAL_SEC = 0.25
POLL_HISTORY_INTERVAL_SEC = 1.0
DEFAULT_TIMEOUT_SEC = 900  # 15 min per variant

log = logging.getLogger("profile_capture")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Variant:
    """One row in the calibration matrix — a single measurement target."""
    checkpoint: str
    resolution: str          # "832x480"
    frames: int
    steps: int
    loras: list[dict] = field(default_factory=list)  # [{"name":..., "weight":...}]
    batch: int = 1
    tag: str = ""            # optional freeform label

    @property
    def key(self) -> str:
        lora_sig = "+".join(f"{l['name']}@{l['weight']:.2f}" for l in self.loras) or "none"
        return f"{self.checkpoint}::{self.resolution}::{self.frames}f::{self.steps}s::{lora_sig}::b{self.batch}"


@dataclass
class Sample:
    t: float
    used_mb: int
    reserved_mb: int
    torch_allocated_mb: Optional[int] = None
    torch_reserved_mb: Optional[int] = None


@dataclass
class ProfileRow:
    key: str
    checkpoint: str
    resolution: str
    frames: int
    steps: int
    batch: int
    loras: list[dict]
    status: str                              # "ok" | "oom" | "error" | "timeout"
    peak_used_mb: int
    peak_reserved_mb: int
    mean_used_mb: int
    p95_used_mb: int
    baseline_used_mb: int
    duration_sec: float
    sample_count: int
    error: str = ""
    captured_at: str = ""
    gpu_name: str = ""
    driver: str = ""


# ---------------------------------------------------------------------------
# nvidia-smi sampling (works even without torch)
# ---------------------------------------------------------------------------

def query_smi() -> tuple[int, int, str, str]:
    """Return (used_mb, reserved_mb_placeholder, gpu_name, driver_version)."""
    result = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=memory.used,memory.total,name,driver_version",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True, text=True, check=True, timeout=5,
    )
    parts = [p.strip() for p in result.stdout.strip().split(",")]
    used_mb = int(parts[0])
    total_mb = int(parts[1])
    name = parts[2]
    driver = parts[3]
    return used_mb, total_mb, name, driver


def query_torch() -> tuple[Optional[int], Optional[int]]:
    if not HAS_TORCH:
        return None, None
    try:
        alloc = torch.cuda.memory_allocated() // (1024 * 1024)
        reserved = torch.cuda.memory_reserved() // (1024 * 1024)
        return alloc, reserved
    except Exception:
        return None, None


# ---------------------------------------------------------------------------
# Sampler thread
# ---------------------------------------------------------------------------

class Sampler(threading.Thread):
    def __init__(self, interval: float = SAMPLE_INTERVAL_SEC) -> None:
        super().__init__(daemon=True)
        self.interval = interval
        self.samples: list[Sample] = []
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                used_mb, total_mb, _, _ = query_smi()
                t_alloc, t_reserved = query_torch()
                self.samples.append(Sample(
                    t=time.time(),
                    used_mb=used_mb,
                    reserved_mb=total_mb,     # placeholder; total not per-proc
                    torch_allocated_mb=t_alloc,
                    torch_reserved_mb=t_reserved,
                ))
            except Exception as e:
                log.debug("Sampler tick failed: %s", e)
            self._stop.wait(self.interval)


# ---------------------------------------------------------------------------
# ComfyUI HTTP driver
# ---------------------------------------------------------------------------

class ComfyClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.client_id = str(uuid.uuid4())

    def ping(self) -> bool:
        try:
            r = requests.get(f"{self.base_url}/system_stats", timeout=5)
            return r.status_code == 200
        except requests.RequestException:
            return False

    def submit(self, workflow: dict) -> str:
        payload = {"prompt": workflow, "client_id": self.client_id}
        r = requests.post(f"{self.base_url}/prompt", json=payload, timeout=30)
        r.raise_for_status()
        return r.json()["prompt_id"]

    def wait(self, prompt_id: str, timeout_sec: int) -> dict:
        """Block until history contains prompt_id or timeout elapses."""
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            try:
                r = requests.get(f"{self.base_url}/history/{prompt_id}", timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    if prompt_id in data:
                        return data[prompt_id]
            except requests.RequestException:
                pass
            time.sleep(POLL_HISTORY_INTERVAL_SEC)
        raise TimeoutError(f"prompt {prompt_id} did not complete in {timeout_sec}s")

    def free_memory(self) -> None:
        """Ask ComfyUI to unload models between runs — resets the baseline."""
        try:
            requests.post(
                f"{self.base_url}/free",
                json={"unload_models": True, "free_memory": True},
                timeout=10,
            )
        except requests.RequestException as e:
            log.warning("free_memory call failed (continuing): %s", e)


# ---------------------------------------------------------------------------
# Workflow templating
# ---------------------------------------------------------------------------

def render_workflow(template: dict, variant: Variant) -> dict:
    """
    Deep-copy the template workflow and patch the well-known parameter nodes.

    Convention: the calibration workflow tags nodes with `_meta.title` values:
        "CKPT"        -> checkpoint loader
        "LATENT"      -> EmptyLatent / EmptyHunyuanLatent (width/height/length)
        "SAMPLER"     -> KSampler (steps)
        "LORA_SLOT_N" -> LoraLoader chain slots (name + strength)
    """
    wf = json.loads(json.dumps(template))  # deep copy
    w, h = (int(x) for x in variant.resolution.lower().split("x"))

    lora_slots_used = 0
    for node_id, node in wf.items():
        title = node.get("_meta", {}).get("title", "")
        cls = node.get("class_type", "")

        if title == "CKPT" and "ckpt_name" in node["inputs"]:
            node["inputs"]["ckpt_name"] = variant.checkpoint

        elif title == "LATENT":
            if "width" in node["inputs"]:  node["inputs"]["width"]  = w
            if "height" in node["inputs"]: node["inputs"]["height"] = h
            if "length" in node["inputs"]: node["inputs"]["length"] = variant.frames
            if "batch_size" in node["inputs"]: node["inputs"]["batch_size"] = variant.batch

        elif title == "SAMPLER":
            if "steps" in node["inputs"]:
                node["inputs"]["steps"] = variant.steps

        elif title.startswith("LORA_SLOT_"):
            slot_idx = int(title.split("_")[-1])
            if slot_idx < len(variant.loras):
                spec = variant.loras[slot_idx]
                node["inputs"]["lora_name"] = spec["name"]
                node["inputs"]["strength_model"] = spec["weight"]
                node["inputs"]["strength_clip"]  = spec.get("weight_clip", spec["weight"])
                lora_slots_used += 1
            else:
                # Neutralize unused slot
                node["inputs"]["strength_model"] = 0.0
                node["inputs"]["strength_clip"]  = 0.0

    if lora_slots_used < len(variant.loras):
        raise ValueError(
            f"variant needs {len(variant.loras)} LoRA slots but workflow exposes "
            f"only {lora_slots_used}"
        )
    return wf


# ---------------------------------------------------------------------------
# Per-variant capture
# ---------------------------------------------------------------------------

def capture_one(
    client: ComfyClient,
    template: dict,
    variant: Variant,
    timeout_sec: int,
    gpu_name: str,
    driver: str,
) -> ProfileRow:
    log.info("[%s] starting", variant.key)
    client.free_memory()
    time.sleep(2.0)  # let the allocator settle

    baseline_used, _, _, _ = query_smi()
    sampler = Sampler()
    sampler.start()

    t0 = time.time()
    status = "ok"
    error = ""

    try:
        workflow = render_workflow(template, variant)
        prompt_id = client.submit(workflow)
        client.wait(prompt_id, timeout_sec=timeout_sec)
    except TimeoutError as e:
        status = "timeout"
        error = str(e)
    except requests.HTTPError as e:
        body = e.response.text if e.response is not None else ""
        if "out of memory" in body.lower() or "oom" in body.lower():
            status = "oom"
        else:
            status = "error"
        error = f"{e} :: {body[:400]}"
    except Exception as e:
        # OOM often surfaces as a generic exception via /history
        msg = str(e).lower()
        status = "oom" if "out of memory" in msg or "cuda" in msg else "error"
        error = str(e)[:500]
    finally:
        sampler.stop()
        sampler.join(timeout=5)
        duration = time.time() - t0

    used_series = [s.used_mb for s in sampler.samples] or [baseline_used]
    peak_used = max(used_series)
    mean_used = int(statistics.fmean(used_series))
    p95_used  = int(statistics.quantiles(used_series, n=20)[18]) if len(used_series) >= 20 else peak_used
    peak_reserved = max((s.torch_reserved_mb or 0) for s in sampler.samples) if sampler.samples else 0

    row = ProfileRow(
        key=variant.key,
        checkpoint=variant.checkpoint,
        resolution=variant.resolution,
        frames=variant.frames,
        steps=variant.steps,
        batch=variant.batch,
        loras=variant.loras,
        status=status,
        peak_used_mb=peak_used,
        peak_reserved_mb=peak_reserved,
        mean_used_mb=mean_used,
        p95_used_mb=p95_used,
        baseline_used_mb=baseline_used,
        duration_sec=round(duration, 2),
        sample_count=len(sampler.samples),
        error=error,
        captured_at=datetime.now(UTC).isoformat(),
        gpu_name=gpu_name,
        driver=driver,
    )
    log.info(
        "[%s] %s peak=%dMB mean=%dMB dur=%.1fs",
        variant.key, status.upper(), peak_used, mean_used, duration,
    )
    return row


# ---------------------------------------------------------------------------
# Matrix loading
# ---------------------------------------------------------------------------

def load_matrix(path: Path) -> list[Variant]:
    """
    calibration_matrix.yaml format:

        defaults:
          steps: 20
          batch: 1
        variants:
          - checkpoint: wan2.2-i2v-14b.safetensors
            resolution: 832x480
            frames: 81
            loras: []
          - checkpoint: wan2.2-i2v-14b.safetensors
            resolution: 1280x720
            frames: 81
            loras:
              - {name: wet_skin_v3.safetensors, weight: 0.7}
              - {name: cinematic_grain.safetensors, weight: 0.4}
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    defaults = data.get("defaults", {}) or {}
    variants: list[Variant] = []
    for entry in data.get("variants", []):
        merged = {**defaults, **entry}
        variants.append(Variant(
            checkpoint=merged["checkpoint"],
            resolution=merged["resolution"],
            frames=int(merged["frames"]),
            steps=int(merged.get("steps", 20)),
            loras=merged.get("loras", []) or [],
            batch=int(merged.get("batch", 1)),
            tag=merged.get("tag", ""),
        ))
    return variants


# ---------------------------------------------------------------------------
# Profile index writer
# ---------------------------------------------------------------------------

def merge_into_index(index_path: Path, rows: list[ProfileRow]) -> None:
    if index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
    else:
        index = {"version": 1, "rows": {}}

    for row in rows:
        index["rows"][row.key] = asdict(row)

    index["updated_at"] = datetime.now(UTC).isoformat()
    tmp = index_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(index, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(index_path)
    log.info("wrote %d rows to %s", len(rows), index_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workflow", required=True, type=Path)
    p.add_argument("--matrix",   required=True, type=Path)
    p.add_argument("--out",      required=True, type=Path,
                   help="Directory for _profile_index.json and per-run logs")
    p.add_argument("--comfy",    default="http://127.0.0.1:8188")
    p.add_argument("--timeout",  type=int, default=DEFAULT_TIMEOUT_SEC)
    p.add_argument("--only",     default="",
                   help="Substring filter on variant.key (skip non-matching)")
    p.add_argument("--verbose",  action="store_true")
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    args.out.mkdir(parents=True, exist_ok=True)
    index_path = args.out / "_profile_index.json"

    client = ComfyClient(args.comfy)
    if not client.ping():
        log.error("ComfyUI unreachable at %s — start it before running.", args.comfy)
        return 2

    try:
        template = json.loads(args.workflow.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        log.error("workflow JSON malformed: %s", e)
        return 2

    variants = load_matrix(args.matrix)
    if args.only:
        variants = [v for v in variants if args.only in v.key]
    if not variants:
        log.error("no variants to run (matrix empty or --only filtered all)")
        return 2

    _, _, gpu_name, driver = query_smi()
    log.info("GPU=%s driver=%s variants=%d", gpu_name, driver, len(variants))

    rows: list[ProfileRow] = []
    for i, variant in enumerate(variants, 1):
        log.info("=== [%d/%d] %s ===", i, len(variants), variant.key)
        try:
            row = capture_one(client, template, variant, args.timeout, gpu_name, driver)
        except Exception as e:
            log.exception("capture_one crashed for %s", variant.key)
            row = ProfileRow(
                key=variant.key, checkpoint=variant.checkpoint,
                resolution=variant.resolution, frames=variant.frames,
                steps=variant.steps, batch=variant.batch, loras=variant.loras,
                status="error", peak_used_mb=0, peak_reserved_mb=0,
                mean_used_mb=0, p95_used_mb=0, baseline_used_mb=0,
                duration_sec=0.0, sample_count=0, error=str(e)[:500],
                captured_at=datetime.now(UTC).isoformat(),
                gpu_name=gpu_name, driver=driver,
            )
        rows.append(row)

        # Incremental save — a 40-variant matrix takes hours; don't lose it all to a crash
        try:
            merge_into_index(index_path, rows)
        except OSError as e:
            log.error("failed to persist index: %s", e)
            return 3

    ok    = sum(1 for r in rows if r.status == "ok")
    oom   = sum(1 for r in rows if r.status == "oom")
    err   = sum(1 for r in rows if r.status in ("error", "timeout"))
    log.info("done: ok=%d oom=%d error=%d", ok, oom, err)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

---

## 11.6 `calibration_matrix.yaml` — the canonical measurement sweep

**Path:** `D:\AI\ComfyUI_portable\workshop\scrape\vram\calibration_matrix.yaml`

This is the sweep we run monthly, or whenever a new checkpoint enters prod. It's not exhaustive — it's the *corner-defining* set. The planner interpolates between measured points; you only need the corners plus a few interior samples to keep the interpolation honest.

```yaml
defaults:
  steps: 20
  batch: 1

variants:
  # ── wan2.2-i2v-14b: resolution ladder, no LoRAs ──
  - {checkpoint: wan2.2-i2v-14b.safetensors, resolution: 512x512,   frames: 49, tag: floor}
  - {checkpoint: wan2.2-i2v-14b.safetensors, resolution: 832x480, frames: 49, tag: floor}
```
