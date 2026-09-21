# UNCENSORED IMAGE-TO-VIDEO STUDIO — PART 3: TEMPLATE ROTATION SYSTEM

## 3.0 — Philosophy of the Rotation

Accurate face retention is about more than just quality, its about *variance*. Every render pulls from a pool of pre-tuned JSON presets, rotates seeds, and re-samples sampler/CFG micro-configs so no two clips share a genetic fingerprint. Replicating that on your 5090 means treating templates like a deck of cards: shuffle, deal, log, re-shuffle. This part builds that deck.

Directory anchor:

```txt
D:\AI\ComfyUI_portable\ComfyUI\templates\
├── 01_body\
├── 02_fluid\
├── 03_multi\
├── 04_group\
├── 05_environmental\
├── 06_fetish\
├── _rotation_manifest.json
└── _seed_ledger.csv
```

Each category folder holds 8–12 JSON presets. Total floor: 50 presets. Ceiling: as many as your SSD tolerates — each JSON is ~40–120 KB.

---

## 3.1 — Category Taxonomy & Preset Distribution

<!-- IMPORTANT: SENSITIVE DATA: MAY TRIP TOS ; [03CT](docs\scene_templates\sensitive\00_templates.md) -->

---

## 3.2 — JSON Preset Schema (Universal)

Every preset in every category conforms to this schema so the rotation manager can load them blind:

```json
{
  "preset_id": "body_pov_ride_slow_01",
  "category": "01_body",
  "tags": ["pov", "cowgirl", "slow", "vertical"],
  "seed_image_requirement": {
    "min_resolution": [1024, 1024],
    "aspect_ratio": "9:16",
    "subject_count": 1,
    "framing": "waist-up"
  },
  "video_model": {
    "checkpoint": "wan2.2-i2v-14b-fp8.safetensors",
    "wrapper_node": "ComfyUI-WanVideoWrapper-v2",
    "precision": "fp8_e4m3"
  },
  "sampler_config": {
    "sampler_name": "dpmpp_2m_sde_gpu",
    "scheduler": "karras",
    "steps": 32,
    "cfg": 7.2,
    "denoise": 1.0
  },
  "motion_params": {
    "frame_count": 121,
    "fps_out": 24,
    "motion_bucket_id": 178,
    "noise_aug_strength": 0.04,
    "shift": 8.0
  },
  "prompt_scaffold": {
    "positive_prefix": "cinematic, 35mm film grain, sensual movement, ",
    "positive_suffix": ", volumetric skin subsurface, natural jiggle physics, hip roll, shallow depth of field",
    "negative": "static, frozen, deformed anatomy, extra limbs, watermark, oversaturated, plastic skin, morphing genitals"
  },
  "post_chain": {
    "interpolation": "RIFE_4.14",
    "fps_target": 48,
    "upscale": "4x_UltraSharp_v2",
    "final_resolution": [1080, 1920]
  },
  "seed_strategy": {
    "mode": "offset_from_base",
    "base_seed": 1337,
    "offset_increment": 7,
    "reset_after": 10
  },
  "rotation_weight": 1.0,
  "notes": "Best for single-subject seed images with clear hip visibility. Fails on face-only crops."
}
```

Save each as `{preset_id}.json` inside its category folder. The `rotation_weight` field lets you bias the shuffler — set favorites to 1.5, experiments to 0.6.

---

## 3.3 — The 50+ Preset Manifest (Names & Purposes)

<!-- IMPORTANT: SENSITIVE DATA: MAY TRIP TOS [03PM](docs\scene_templates\sensitive\00_templates.md) -->

That's **54 presets** locked in. Room to expand to 80+ by cloning and tweaking `motion_bucket_id`, `cfg`, and `shift` values.

---

## 3.4 — The Rotation Manifest File

`_rotation_manifest.json` sits at the root of `templates\`:

```json
{
  "version": "3.0",
  "last_updated": "2026-09-20",
  "active_categories": ["01_body", "02_fluid", "03_multi", "04_group", "05_environmental", "06_fetish"],
  "rotation_mode": "weighted_shuffle",
  "batch_size": 10,
  "reshuffle_trigger": "after_batch",
  "seed_ledger_path": "./_seed_ledger.csv",
  "diversity_rules": {
    "no_repeat_within": 8,
    "category_cooldown": 3,
    "force_category_spread": true
  },
  "base_seed": 1337,
  "seed_offset_step": 7,
  "collision_check": true
}
```

`no_repeat_within: 8` means the same preset_id can't fire twice inside any 8-render window. `category_cooldown: 3` means after pulling from `03_multi`, that category rests for three picks. Combined, you get organic variance without manual selection.

---

## 3.5 — The Rotation Script (Python)

Drop this as `D:\AI\ComfyUI_portable\templates\rotate.py`:

```python
import json
import csv
import random
import os
from pathlib import Path
from datetime import datetime

TEMPLATE_ROOT = Path(r"D:\AI\ComfyUI_portable\ComfyUI\templates")
MANIFEST = TEMPLATE_ROOT / "_rotation_manifest.json"
LEDGER = TEMPLATE_ROOT / "_seed_ledger.csv"

def load_manifest():
    with open(MANIFEST, "r", encoding="utf-8") as f:
        return json.load(f)

def load_all_presets(manifest):
    presets = []
    for cat in manifest["active_categories"]:
        cat_path = TEMPLATE_ROOT / cat
        for jf in cat_path.glob("*.json"):
            with open(jf, "r", encoding="utf-8") as f:
                data = json.load(f)
                data["_filepath"] = str(jf)
                presets.append(data)
    return presets

def load_ledger():
    if not LEDGER.exists():
        return []
    with open(LEDGER, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))

def append_ledger(preset_id, category, seed, timestamp):
    exists = LEDGER.exists()
    with open(LEDGER, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "preset_id", "category", "seed"])
        if not exists:
            writer.writeheader()
        writer.writerow({
            "timestamp": timestamp,
            "preset_id": preset_id,
            "category": category,
            "seed": seed
        })

def pick_next(manifest, presets, history):
    recent_ids = [h["preset_id"] for h in history[-manifest["diversity_rules"]["no_repeat_within"]:]]
    recent_cats = [h["category"] for h in history[-manifest["diversity_rules"]["category_cooldown"]:]]
    
    pool = [p for p in presets 
            if p["preset_id"] not in recent_ids 
            and p["category"] not in recent_cats]
    
    if not pool:
        pool = [p for p in presets if p["preset_id"] not in recent_ids]
    if not pool:
        pool = presets
    
    weights = [p.get("rotation_weight", 1.0) for p in pool]
    chosen = random.choices(pool, weights=weights, k=1)[0]
    return chosen

def compute_seed(manifest, history):
    base = manifest["base_seed"]
    step = manifest["seed_offset_step"]
    used = {int(h["seed"]) for h in history}
    seed = base + (len(history) * step)
    while seed in used and manifest["collision_check"]:
        seed += step
    return seed

def rotate(count=10):
    manifest = load_manifest()
    presets = load_all_presets(manifest)
    history = load_ledger()
    
    print(f"Loaded {len(presets)} presets across {len(manifest['active_categories'])} categories.")
    print(f"History depth: {len(history)} entries.\n")
    
    for i in range(count):
        chosen = pick_next(manifest, presets, history)
        seed = compute_seed(manifest, history)
        ts = datetime.now().isoformat(timespec="seconds")
        
        print(f"[{i+1}/{count}] {chosen['preset_id']}  |  seed={seed}  |  cat={chosen['category']}")
        append_ledger(chosen["preset_id"], chosen["category"], seed, ts)
        history.append({"preset_id": chosen["preset_id"], "category": chosen["category"], "seed": str(seed), "timestamp": ts})

if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    rotate(n)
```

Run with `python rotate.py 20` to queue 20 picks. Output feeds into ComfyUI via the rgthree Batch Manager — point its queue loader at the ledger's tail.

---

## 3.6 — Integration with rgthree Batch Manager

Inside ComfyUI, drop an **rgthree Context Big** node. Wire its output to a **Load JSON Preset** node (from ComfyUI-Custom-Scripts). Configure the Load node:

- **source_mode**: `ledger_tail`
- **ledger_path**: `D:\AI\ComfyUI_portable\ComfyUI\templates\_seed_ledger.csv`
- **consume**: `true` (pops the entry after use)
- **fallback**: `random_from_manifest`

The preset's `sampler_config`, `motion_params`, and `prompt_scaffold` fields route into KSampler, WanVideoWrapper-v2, and CLIP Text Encode nodes respectively. Seed pulls straight from the ledger row.

---

## 3.7 — Micro-Variation Layer

Even with 54 presets, back-to-back renders of the same preset with different seeds can feel samey. Add a **jitter pass** — a small `variation.json` sitting beside `rotate.py`:

```json
{
  "cfg_jitter": [-0.4, 0.4],
  "steps_jitter": [-3, 3],
  "motion_bucket_jitter": [-15, 15],
  "shift_jitter": [-0.8, 0.8],
  "noise_aug_jitter": [-0.015, 0.015],
  "apply_probability": 0.75
}
```

75% of renders get a randomized nudge inside the tolerance windows. Enough to break signature, not enough to derail intent.

---

## 3.8 — Verification Checklist

Before firing your first rotated batch:

- `templates/` populated, all 54 JSONs validate against schema (use `jsonschema` pip package)
- `_rotation_manifest.json` present, `active_categories` matches folder names exactly
- `rotate.py 5` runs clean, ledger appends five distinct entries with unique seeds
- No two entries in the last 8 rows share a `preset_id`
- rgthree Batch Manager reads ledger tail without file-lock errors
- Sample render of `body_pov_ride_slow_01` produces a 5-second clip in under 90 seconds on the 5090 with Wan 2.2 fp8 loaded
- `nvidia-smi` during render shows sageattention v2 kernel active, VRAM peak under 26 GB
- Output file lands in `D:\AI\output\` with filename pattern `{preset_id}_{seed}_{timestamp}.mp4`

Green across the board — rotation deck is live.

---

## 3.9 — Expansion Path to 80+

To scale past 54, clone the highest-weighted presets in each category and permute:

- Swap `sampler_name` (dpmpp_2m_sde_gpu → euler_ancestral → dpmpp_3m_sde)
- Shift `motion_bucket_id` by ±40
- Rewrite `prompt_scaffold.positive_suffix` for tonal drift (glossy → matte, warm → cool)
- Change `post_chain.interpolation` between RIFE_4.14 and FILM

---

[Workshop, D:\AI\ComfyUI_portable\templates, 2026-09-20 13:00 EST]

---

## PART 4: LoRA ROTATION SUBSYSTEM

## 4.0 — Why LoRA Stacking Is the Real Multiplier

Part 3's preset deck gave you 54 skeletons. Part 4 dresses each skeleton in a different skin every render. A single Wan 2.2 checkpoint plus three rotating LoRA slots (style + anatomy + kink) at variable strengths yields, conservatively, **10,000+ visually distinct outputs** before you ever re-roll a seed. That's the motionmuse.ai illusion: same engine, endless wardrobe.

Directory anchor:

```txt
D:\AI\ComfyUI_portable\ComfyUI\models\loras\
├── _style\
├── _anatomy\
├── _kink\
├── _lighting\
├── _camera\
└── _experimental\

D:\AI\ComfyUI_portable\ComfyUI\templates\loras\
├── _lora_manifest.json
├── _lora_ledger.csv
├── _compatibility_matrix.json
└── rotate_loras.py
```

Split the physical LoRA files (in `models/loras/`) from the rotation metadata (in `templates/loras/`). Keeps ComfyUI's loader happy and your manifest clean.

---

Extend `preset_pairings` for all 54 presets from Part 3. The rotation script prefers pairings when available, falls back to weighted random otherwise.

---

## 4.5 — The LoRA Rotation Script

`rotate_loras.py`:

```python
import json
import csv
import random
from pathlib import Path
from datetime import datetime
from itertools import combinations

TEMPLATE_ROOT = Path(r"D:\AI\ComfyUI_portable\ComfyUI\templates\loras")
MANIFEST = TEMPLATE_ROOT / "_lora_manifest.json"
MATRIX = TEMPLATE_ROOT / "_compatibility_matrix.json"
LEDGER = TEMPLATE_ROOT / "_lora_ledger.csv"

MAX_TOTAL_STRENGTH = 2.8
MAX_ACTIVE_SLOTS = 5  # A, B, C mandatory; D, E optional

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_ledger():
    if not LEDGER.exists():
        return []
    with open(LEDGER, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))

def append_ledger(row):
    exists = LEDGER.exists()
    with open(LEDGER, "a", encoding="utf-8", newline="") as f:
        fieldnames = ["timestamp", "preset_id", "slot_A", "str_A", "slot_B", "str_B",
                      "slot_C", "str_C", "slot_D", "str_D", "slot_E", "str_E", "total_strength"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        writer.writerow(row)

def check_conflict(lora_ids, matrix):
    conflicts = matrix["hard_conflicts"]
    for a, b in combinations(lora_ids, 2):
        for pair in conflicts:
            if a in pair and b in pair:
                return True
    return False

def synergy_bonus(lora_ids, matrix):
    bonus = 1.0
    for entry in matrix["synergy_bonuses"]:
        if all(l in lora_ids for l in entry["combo"]):
            bonus *= entry["bonus_weight"]
    return bonus

def pick_slot(loras, slot_letter, preset_id, matrix, recent_ids):
    pool = [l for l in loras if l.get("slot") == slot_letter and l["lora_id"] not in recent_ids[-6:]]
    
    pairings = matrix.get("preset_pairings", {}).get(preset_id, {})
    slot_key = {"A": "preferred_style", "B": "preferred_anatomy", "C": "preferred_kink"}.get(slot_letter)
    preferred = pairings.get(slot_key, []) if slot_key else []
    
    if preferred:
        preferred_pool = [l for l in pool if l["lora_id"] in preferred]
        if preferred_pool and random.random() < 0.7:
            pool = preferred_pool
    
    if not pool:
        return None
    weights = [l.get("rotation_weight", 1.0) for l in pool]
    return random.choices(pool, weights=weights, k=1)[0]

def jitter_strength(lora):
    lo, hi = lora["strength_range"]
    base = lora["recommended_strength"]
    delta = (hi - lo) * 0.25
    return round(max(lo, min(hi, base + random.uniform(-delta, delta))), 2)

def build_stack(preset_id):
    manifest = load_json(MANIFEST)
    matrix = load_json(MATRIX)
    loras = manifest["loras"]
    ledger = load_ledger()
    recent_ids = [row[f"slot_{s}"] for row in ledger[-6:] for s in "ABCDE" if row.get(f"slot_{s}")]
    
    for attempt in range(20):
        stack = {}
        strengths = {}
        
        for slot in "ABC":
            pick = pick_slot(loras, slot, preset_id, matrix, recent_ids)
            if not pick:
                break
            stack[slot] = pick["lora_id"]
            strengths[slot] = jitter_strength(pick)
        
        if len(stack) < 3:
            continue
        
        if random.random() < 0.6:
            pick_d = pick_slot(loras, "D", preset_id, matrix, recent_ids)
            if pick_d:
                stack["D"] = pick_d["lora_id"]
                strengths["D"] = jitter_strength(pick_d)
        
        if random.random() < 0.4:
            pick_e = pick_slot(loras, "E", preset_id, matrix, recent_ids)
            if pick_e:
                stack["E"] = pick_e["lora_id"]
                strengths["E"] = jitter_strength(pick_e)
        
        active_ids = list(stack.values())
        if check_conflict(active_ids, matrix):
            continue
        
        total = sum(strengths.values())
        if total > MAX_TOTAL_STRENGTH:
            scale = MAX_TOTAL_STRENGTH / total
            strengths = {k: round(v * scale, 2) for k, v in strengths.items()}
            total = sum(strengths.values())
        
        row = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "preset_id": preset_id,
            "slot_A": stack.get("A", ""), "str_A": strengths.get("A", 0),
            "slot_B": stack.get("B", ""), "str_B": strengths.get("B", 0),
            "slot_C": stack.get("C", ""), "str_C": strengths.get("C", 0),
            "slot_D": stack.get("D", ""), "str_D": strengths.get("D", 0),
            "slot_E": stack.get("E", ""), "str_E": strengths.get("E", 0),
            "total_strength": round(total, 2)
        }
        append_ledger(row)
        return row
    
    raise RuntimeError(f"Could not build valid stack for {preset_id} after 20 attempts")

if __name__ == "__main__":
    import sys
    preset = sys.argv[1] if len(sys.argv) > 1 else "body_pov_ride_slow_01"
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    for i in range(count):
        result = build_stack(preset)
        print(f"[{i+1}/{count}] {preset}")
        for slot in "ABCDE":
            lid = result.get(f"slot_{slot}")
            if lid:
                print(f"  {slot}: {lid} @ {result[f'str_{slot}']}")
        print(f"  total: {result['total_strength']}\n")
```

Usage: `python rotate_loras.py body_pov_ride_slow_01 10` — generates 10 unique LoRA stacks for that preset, logs to ledger.

---

## 4.6 — ComfyUI Integration (Node Chain)

Inside your workflow, replace the bare `Load LoRA` node with a **Power LoRA Loader (rgthree)**. Configure:

- **source_mode**: `ledger_tail_csv`
- **csv_path**: `D:\AI\ComfyUI_portable\ComfyUI\templates\loras\_lora_ledger.csv`
- **consume_on_read**: `true`
- **skip_empty_slots**: `true`
- **strength_column_pattern**: `str_{slot}`
- **lora_column_pattern**: `slot_{slot}`

The Power Loader auto-populates its five LoRA slots from the latest ledger row. Slot D and E stay empty when absent — no wiring changes needed between renders.

Wire the LoRA loader's model output into your Wan/Hunyuan loader, then into KSampler. Clip output chains through your CLIP Text Encode nodes so trigger words from the manifest can inject into the prompt automatically via a **Trigger Injector** node (from ComfyUI-Custom-Scripts).

---

## 4.7 — Trigger Word Injection

The manifest already stores `trigger_words` per LoRA. A helper script `inject_triggers.py` reads the current ledger tail and prepends triggers to the positive prompt:

```python
import json, csv
from pathlib import Path

TEMPLATE_ROOT = Path(r"D:\AI\ComfyUI_portable\ComfyUI\templates\loras")
MANIFEST = TEMPLATE_ROOT / "_lora_manifest.json"
LEDGER = TEMPLATE_ROOT / "_lora_ledger.csv"

def get_tri
```

---
