# UNCENSORED IMAGE-TO-VIDEO STUDIO — PART 4: LoRA ROTATION SUBSYSTEM

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

<!-- IMPORTANT: SENSITIVE DATA ; REFERENCE [04LS](docs\design_spec\scene_templates\sensitive\00_templates.md) -->

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
