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

## 4.1 — Category Taxonomy & Slot Assignment

Three primary slots per render, two optional. Strength budgets keep things from collapsing into mud.

| Slot | Category | Count Target | Strength Range | Purpose |
| --- | --- | --- | --- | --- |
| A | _style | 15+ | 0.4 – 0.9 | Aesthetic — film, anime, glossy, analog, oil |
| B | _anatomy | 12+ | 0.5 – 1.0 | Body types, genitalia detail, skin realism |
| C | _kink | 20+ | 0.3 – 0.85 | Act-specific — deepthroat, squirt, latex, etc. |
| D (opt) | _lighting | 8+ | 0.3 – 0.7 | Golden hour, neon, candlelit, harsh flash |
| E (opt) | _camera | 6+ | 0.2 – 0.6 | Handheld, drone, fisheye, macro |
| F (opt) | _experimental | rotating | 0.1 – 0.5 | New civitai pulls under evaluation |

Hard rule: total stacked strength across all active slots must stay under **2.8**. Over that, you start getting fried outputs on Wan 2.2 and Hunyuan 2.0. The rotation script enforces this.

---

## 4.2 — The LoRA Manifest Schema

`_lora_manifest.json` — one master registry for every LoRA in the pool:

```json
{
  "version": "4.0",
  "last_updated": "2026-09-20",
  "loras": [
    {
      "lora_id": "style_analog_35mm_v3",
      "filename": "analog_35mm_grain_v3.safetensors",
      "category": "_style",
      "slot": "A",
      "base_model": ["wan2.2", "hunyuan2.0", "ltx1.1"],
      "recommended_strength": 0.65,
      "strength_range": [0.4, 0.85],
      "trigger_words": ["35mm film", "kodak portra", "grain"],
      "conflicts_with": ["style_anime_flat_v2", "style_3d_render_v1"],
      "synergy_with": ["lighting_golden_hour_v2", "camera_handheld_v1"],
      "nsfw_safe": true,
      "rotation_weight": 1.2,
      "notes": "Warm cast, mild vignette. Softens Hunyuan's plasticky faces."
    },
    {
      "lora_id": "anatomy_realistic_vulva_v4",
      "filename": "realistic_vulva_anatomy_v4.safetensors",
      "category": "_anatomy",
      "slot": "B",
      "base_model": ["wan2.2", "hunyuan2.0"],
      "recommended_strength": 0.8,
      "strength_range": [0.6, 1.0],
      "trigger_words": ["detailed vulva", "realistic labia", "anatomical accuracy"],
      "conflicts_with": ["anatomy_hentai_stylized_v2"],
      "synergy_with": ["kink_squirt_arc_v3", "kink_fingering_wet_v2"],
      "nsfw_safe": true,
      "rotation_weight": 1.4,
      "notes": "Fixes Wan's tendency to smooth over genital detail. Essential for closeups."
    },
    {
      "lora_id": "kink_deepthroat_gag_v2",
      "filename": "deepthroat_gag_reflex_v2.safetensors",
      "category": "_kink",
      "slot": "C",
      "base_model": ["wan2.2", "hunyuan2.0"],
      "recommended_strength": 0.7,
      "strength_range": [0.4, 0.85],
      "trigger_words": ["deepthroat", "gag reflex", "throat bulge", "drool"],
      "conflicts_with": ["kink_gentle_kiss_v1"],
      "synergy_with": ["anatomy_realistic_mouth_v3", "style_analog_35mm_v3"],
      "nsfw_safe": true,
      "rotation_weight": 1.0,
      "notes": "Adds throat physics + saliva strings. Pair with facefuck or spitroast presets."
    }
  ]
}
```

Repeat entries for every LoRA in your pool. The three above are examples — your full manifest will run 60–80 entries.

---

## 4.3 — Suggested LoRA Pool (2026 Civitai + HuggingFace Pulls)

### _style (15)

1. `style_analog_35mm_v3`
2. `style_kodak_portra_v2`
3. `style_cinematic_teal_orange_v4`
4. `style_glossy_magazine_v2`
5. `style_amateur_iphone_v3` — grainy homemade aesthetic
6. `style_vhs_retro_v2`
7. `style_oil_painting_v1`
8. `style_anime_flat_v2`
9. `style_3d_render_octane_v1`
10. `style_noir_bw_v2`
11. `style_polaroid_faded_v1`
12. `style_hyperreal_skin_v3`
13. `style_watercolor_soft_v1`
14. `style_neon_cyberpunk_v2`
15. `style_soft_focus_dreamy_v2`

### _anatomy (12)

 1. `anatomy_realistic_vulva_v4`
 2. `anatomy_detailed_cock_v3` — girth/vein detail, foreskin toggle
 3. `anatomy_natural_breasts_v4` — jiggle physics, areola detail
 4. `anatomy_augmented_breasts_v2`
 5. `anatomy_thick_thighs_v3`
 6. `anatomy_athletic_build_v2`
 7. `anatomy_petite_frame_v2`
 8. `anatomy_bbw_curves_v3`
 9. `anatomy_realistic_ass_v3` — cheek separation, dimples
10. `anatomy_detailed_feet_v2`
11. `anatomy_realistic_mouth_v3` — lip detail, teeth, tongue
12. `anatomy_pregnant_belly_v1`

### _kink (20)

 1. `kink_deepthroat_gag_v2`
 2. `kink_squirt_arc_v3`
 3. `kink_creampie_reveal_v2`
 4. `kink_facial_finish_v3`
 5. `kink_bukkake_multi_v2`
 6. `kink_anal_stretch_v2`
 7. `kink_double_penetration_v2`
 8. `kink_fisting_slow_v1`
 9. `kink_latex_shine_v3`
10. `kink_bondage_rope_v2`
11. `kink_watersports_arc_v1`
12. `kink_tentacle_wrap_v2`
13. `kink_lactation_v1`
14. `kink_pregnancy_progression_v1`
15. `kink_futa_hybrid_v2`
16. `kink_furry_hybrid_v3`
17. `kink_public_flash_v2`
18. `kink_lesbian_scissor_v2`
19. `kink_gangbang_multi_v2`
20. `kink_orgasm_face_v3` — ahegao, tongue-out, eye-roll

### _lighting (8)

 1. `lighting_golden_hour_v2`
 2. `lighting_neon_pink_blue_v2`
 3. `lighting_candlelit_warm_v1`
 4. `lighting_harsh_flash_v2`
 5. `lighting_moonlit_cool_v1`
 6. `lighting_studio_softbox_v2`
 7. `lighting_underwater_caustic_v1`
 8. `lighting_firelight_flicker_v1`

### _camera (6)

 1. `camera_handheld_shaky_v1`
 2. `camera_drone_orbit_v2`
 3. `camera_fisheye_pov_v1`
 4. `camera_macro_extreme_v2`
 5. `camera_slow_dolly_v1`
 6. `camera_static_tripod_v1`

**Total pool: 61 LoRAs.** Room to grow via `_experimental`.

---

## 4.4 — Compatibility Matrix

`_compatibility_matrix.json` — pre-computed synergy and conflict lookups so the rotation script doesn't hit expensive checks at pick-time:

```json
{
  "hard_conflicts": [
    ["style_anime_flat_v2", "style_hyperreal_skin_v3"],
    ["style_anime_flat_v2", "anatomy_realistic_vulva_v4"],
    ["anatomy_petite_frame_v2", "anatomy_bbw_curves_v3"],
    ["anatomy_natural_breasts_v4", "anatomy_augmented_breasts_v2"],
    ["kink_gentle_kiss_v1", "kink_deepthroat_gag_v2"],
    ["style_watercolor_soft_v1", "kink_squirt_arc_v3"]
  ],
  "soft_conflicts": [
    ["style_noir_bw_v2", "lighting_neon_pink_blue_v2"],
    ["style_oil_painting_v1", "camera_macro_extreme_v2"]
  ],
  "synergy_bonuses": [
    {
      "combo": ["style_analog_35mm_v3", "lighting_golden_hour_v2", "camera_handheld_shaky_v1"],
      "bonus_weight": 1.5,
      "label": "amateur_warm_cinematic"
    },
    {
      "combo": ["anatomy_realistic_vulva_v4", "kink_squirt_arc_v3", "camera_macro_extreme_v2"],
      "bonus_weight": 1.8,
      "label": "detailed_finish_closeup"
    },
    {
      "combo": ["kink_latex_shine_v3", "lighting_neon_pink_blue_v2", "style_cinematic_teal_orange_v4"],
      "bonus_weight": 1.6,
      "label": "cyberdom_aesthetic"
    }
  ],
  "preset_pairings": {
    "body_pov_ride_slow_01": {
      "preferred_style": ["style_analog_35mm_v3", "style_amateur_iphone_v3"],
      "preferred_anatomy": ["anatomy_realistic_vulva_v4", "anatomy_natural_breasts_v4"],
      "preferred_kink": ["kink_orgasm_face_v3"]
    },
    "fluid_squirt_arc_04": {
      "preferred_style": ["style_hyperreal_skin_v3", "style_cinematic_teal_orange_v4"],
      "preferred_anatomy": ["anatomy_realistic_vulva_v4"],
      "preferred_kink": ["kink_squirt_arc_v3", "kink_orgasm_face_v3"]
    },
    "multi_facefuck_08": {
      "preferred_style": ["style_analog_35mm_v3", "style_glossy_magazine_v2"],
      "preferred_anatomy": ["anatomy_realistic_mouth_v3", "anatomy_detailed_cock_v3"],
      "preferred_kink": ["kink_deepthroat_gag_v2"]
    }
  }
}
```

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
