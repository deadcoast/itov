# Part 3 — Template rotation system

**Directory:** `D:\AI\ComfyUI_portable\workshop\templates`

This component generates **54 non-explicit scene presets**, rotates them without repeats within each cycle, and writes render-job specifications. The requested category names are retained; `fetish` contains wardrobe/material aesthetics, and `fluid` contains environmental liquid effects.

**Boundary:** these are workshop presets—not importable ComfyUI workflows. A later workflow adapter maps their fields to the installed model’s actual nodes.

## 3.1 — Directory layout

```text
workshop\templates\
├── template_rotation.py
├── presets\
│   ├── body\             # 9 presets
│   ├── fluid\            # 9 presets
│   ├── multi\            # 9 presets
│   ├── group\            # 9 presets
│   ├── environmental\    # 9 presets
│   └── fetish\           # 9 presets
├── queue\
│   └── <job_id>.json
└── state\
    ├── rotation.json
    └── rotation.lock     # Exists only during selection
```

### 3.2 — Rotation rules

1. Each model/tier/category/subject-count combination has its own rotation pool.
2. A preset is selected once per pool cycle before repeats are allowed.
3. Subject counts must match: solo, two-person, or four-person.
4. Subject IDs are explicit; identity association is never inferred from prompt order alone.
5. Every job requires face-retention auditing before promotion.
6. Presets contain no model compatibility claims or assumed node IDs.

Quality tiers are **starting targets**, not validated speed or VRAM guarantees:

| Tier | Target canvas | Duration | FPS |
| --- | --- | --- | --- |
| B | 768 × 432 | 3 seconds | 24 |
| A | 1024 × 576 | 4 seconds | 24 |
| S | 1280 × 720 | 5 seconds | 24 |

The workflow adapter must reconcile these targets with the selected model’s supported dimensions and frame-count rules.

### 3.3 — Complete generator and rotation script

**File:** `workshop\templates\template_rotation.py`

```python
#!/usr/bin/env python3
"""Generate 54 scene presets and queue model-neutral render jobs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PRESETS = ROOT / "presets"
STATE = ROOT / "state"
QUEUE = ROOT / "queue"

TIERS = {
    "B": {"width": 768, "height": 432, "seconds": 3, "fps": 24},
    "A": {"width": 1024, "height": 576, "seconds": 4, "fps": 24},
    "S": {"width": 1280, "height": 720, "seconds": 5, "fps": 24},
}

# category -> (subject count, [(slug, scene description), ...])
CATALOG = {
    "body": (1, [
        ("portrait_turn", "Clothed adult portrait, slow head turn"),
        ("walking_profile", "Clothed adult walking in profile"),
        ("seated_posture", "Clothed adult seated upright on a stool"),
        ("stretch_sequence", "Adult in sportswear performing a gentle stretch"),
        ("hand_gesture", "Clothed adult making a small conversational gesture"),
        ("shoulder_turn", "Clothed adult turning shoulders toward the camera"),
        ("dance_step", "Adult in dancewear taking one measured dance step"),
        ("balance_pose", "Adult in sportswear holding a balanced standing pose"),
        ("coat_movement", "Adult walking slowly in a flowing overcoat"),
    ]),
    "fluid": (1, [
        ("rain_portrait", "Clothed adult portrait in gentle rain"),
        ("umbrella_walk", "Clothed adult walking beneath an umbrella"),
        ("fountain_backdrop", "Clothed adult beside a distant fountain"),
        ("shoreline_walk", "Clothed adult walking beside a calm shoreline"),
        ("puddle_reflection", "Clothed adult near a reflective rain puddle"),
        ("window_droplets", "Clothed adult beside a window covered in droplets"),
        ("mist_backlight", "Clothed adult framed by softly backlit water mist"),
        ("stream_crossing", "Clothed adult crossing a shallow stream on stones"),
        ("waterfall_distance", "Clothed adult with a distant waterfall backdrop"),
    ]),
    "multi": (2, [
        ("paired_portrait", "Two clothed adults posing side by side"),
        ("conversation", "Two clothed adults having a calm conversation"),
        ("parallel_walk", "Two clothed adults walking parallel to each other"),
        ("seated_pair", "Two clothed adults seated on separate chairs"),
        ("mirrored_gesture", "Two clothed adults making mirrored hand gestures"),
        ("partner_dance", "Two clothed adults taking a simple ballroom step"),
        ("object_exchange", "Two clothed adults exchanging a closed notebook"),
        ("opposite_profiles", "Two clothed adults in opposing profile poses"),
        ("foreground_background", "Two clothed adults at different scene depths"),
    ]),
    "group": (4, [
        ("lineup", "Four clothed adults standing in a spaced lineup"),
        ("semicircle", "Four clothed adults arranged in a shallow semicircle"),
        ("table_discussion", "Four clothed adults seated around a meeting table"),
        ("walking_formation", "Four clothed adults walking in a loose formation"),
        ("staggered_portrait", "Four clothed adults in a staggered portrait"),
        ("synchronized_step", "Four clothed adults taking one synchronized step"),
        ("gallery_visit", "Four clothed adults viewing an art gallery"),
        ("lounge_scene", "Four clothed adults seated in a spacious lounge"),
        ("courtyard_gathering", "Four clothed adults gathering in a courtyard"),
    ]),
    "environmental": (1, [
        ("neon_alley", "Clothed adult in a softly illuminated neon alley"),
        ("forest_path", "Clothed adult on a shaded forest path"),
        ("desert_dusk", "Clothed adult in a desert landscape at dusk"),
        ("snow_courtyard", "Adult in winter clothing in a snowy courtyard"),
        ("rooftop_sunset", "Clothed adult on a rooftop at sunset"),
        ("industrial_hall", "Clothed adult inside a spacious industrial hall"),
        ("library_window", "Clothed adult beside a tall library window"),
        ("greenhouse", "Clothed adult inside a sunlit greenhouse"),
        ("station_platform", "Clothed adult on a quiet railway platform"),
    ]),
    "fetish": (1, [
        ("latex_fashion", "Adult in fully covering latex-inspired runway fashion"),
        ("leather_jacket", "Adult in a leather jacket and tailored trousers"),
        ("patent_boots", "Adult in a full outfit featuring patent boots"),
        ("satin_eveningwear", "Adult in fully covering satin eveningwear"),
        ("velvet_tailoring", "Adult in a tailored velvet suit"),
        ("lace_layering", "Adult in opaque clothing with decorative lace layers"),
        ("opera_gloves", "Adult in formal eveningwear and opera gloves"),
        ("corset_outerwear", "Adult wearing a fashion corset over an opaque shirt"),
        ("metallic_runway", "Adult in fully covering metallic runway clothing"),
    ]),
}

CAMERAS = [
    "locked camera",
    "slow dolly inward",
    "gentle lateral tracking",
]

LIGHTING = [
    "soft directional light",
    "diffuse daylight",
    "controlled studio light",
]

SCHEMA_VERSION = 1


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False,
                      allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


@contextmanager
def rotation_lock():
    STATE.mkdir(parents=True, exist_ok=True)
    path = STATE / "rotation.lock"
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError(
            f"Rotation is locked: {path}. If a previous process crashed, "
            "confirm it is no longer running before deleting this file."
        )

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"pid": os.getpid(), "created_at": now()}, handle)
        yield
    finally:
        path.unlink(missing_ok=True)


def make_preset(category: str, count: int, index: int,
                slug: str, scene: str) -> dict:
    camera = CAMERAS[index % len(CAMERAS)]
    light = LIGHTING[index % len(LIGHTING)]

    # Simplify multi-person scenes to reduce identity-association ambiguity.
    if count > 1:
        camera = "locked camera"

    return {
        "schema_version": SCHEMA_VERSION,
        "id": f"{category}.{slug}",
        "category": category,
        "subject_count": count,
        "scene": scene,
        "composition": {
            "camera_motion": camera,
            "lighting": light,
            "framing": "medium shot" if count == 1 else "wide group shot",
            "face_visibility": "all subject faces remain visible",
            "occlusion": "minimal",
        },
        "motion": {
            "intensity": "low",
            "single_continuous_shot": True,
            "avoid_subject_crossing": count > 1,
        },
        "prompt": {
            "positive": (
                f"{scene}, {camera}, {light}, consistent facial identity, "
                "stable composition, natural movement"
            ),
            "negative": (
                "identity drift, duplicate people, face distortion, "
                "flicker, abrupt cuts, heavy face occlusion"
            ),
        },
        "quality": {
            "face_retention_audit_required": True,
            "required_audit_decision": "pass",
            "subject_association_required": count > 1,
        },
        "compatibility": {
            "status": "unvalidated",
            "workflow_adapter_required": True,
        },
    }


def initialize(force: bool) -> None:
    created = 0
    preserved = 0

    with rotation_lock():
        for category, (count, entries) in CATALOG.items():
            if len(entries) != 9:
                raise ValueError(f"{category} must contain exactly 9 presets.")

            for index, (slug, scene) in enumerate(entries):
                path = PRESETS / category / f"{slug}.json"
                if path.exists() and not force:
                    preserved += 1
                    continue

                atomic_json(
                    path,
                    make_preset(category, count, index, slug, scene),
                )
                created += 1

    print(f"Written: {created}; preserved: {preserved}; catalog total: 54")


def load_presets() -> list[dict]:
    presets = []
    seen = set()

    for path in sorted(PRESETS.glob("*/*.json")):
        preset = read_json(path)
        if preset.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"Unsupported schema: {path}")

        preset_id = preset.get("id")
        if not isinstance(preset_id, str) or not preset_id:
            raise ValueError(f"Missing preset ID: {path}")
        if preset_id in seen:
            raise ValueError(f"Duplicate preset ID: {preset_id}")

        if preset.get("category") not in CATALOG:
            raise ValueError(f"Unknown category: {path}")
        count = preset.get("subject_count")
        if type(count) is not int or count < 1:
            raise ValueError(f"Invalid subject_count: {path}")

        for field in ("composition", "motion", "prompt", "quality",
                      "compatibility"):
            if not isinstance(preset.get(field), dict):
                raise ValueError(f"Missing object '{field}': {path}")

        seen.add(preset_id)
        presets.append(preset)

    if not presets:
        raise ValueError("No presets found. Run 'init' first.")
    return presets


def queue_job(args) -> None:
    subjects = args.subjects
    if any(not subject.strip() for subject in subjects):
        raise ValueError("Subject IDs cannot be blank.")
    if len(set(subjects)) != len(subjects):
        raise ValueError("Subject IDs must be unique within a job.")

    with rotation_lock():
        candidates = [
            preset for preset in load_presets()
            if preset["subject_count"] == len(subjects)
            and (
                args.category == "all"
                or preset["category"] == args.category
            )
        ]
        if not candidates:
            raise ValueError(
                "No presets match this category and subject count."
            )

        state_path = STATE / "rotation.json"
        state = (
            read_json(state_path)
            if state_path.exists()
            else {"schema_version": SCHEMA_VERSION, "pools": {}}
        )
        if state.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("Unsupported rotation state schema.")

        # Persisted reservation recovery: materialize the prior job before
        # selecting another. This handles a crash after state publication.
        pending = state.get("pending_job")
        if pending:
            atomic_json(QUEUE / f"{pending['job_id']}.json", pending)
            del state["pending_job"]
            atomic_json(state_path, state)

        pool_spec = {
            "model_profile": args.model,
            "tier": args.tier,
            "category": args.category,
            "subject_count": len(subjects),
        }
        pool_key = hashlib.sha256(
            json.dumps(pool_spec, sort_keys=True).encode("utf-8")
        ).hexdigest()[:24]

        pool = state["pools"].setdefault(
            pool_key,
            {"spec": pool_spec, "cycle": 1, "used": []},
        )

        used = set(pool["used"])
        available = [p for p in candidates if p["id"] not in used]

        if not available:
            pool["cycle"] += 1
            pool["used"] = []
            available = candidates

        rng = random.Random(args.selection_seed)
        preset = rng.choice(sorted(available, key=lambda p: p["id"]))

        job_id = uuid.uuid4().hex
        render_seed = (
            args.render_seed
            if args.render_seed is not None
            else random.SystemRandom().randrange(2**32)
        )

        job = {
            "schema_version": SCHEMA_VERSION,
            "job_id": job_id,
            "created_at": now(),
            "status": "awaiting_workflow_adapter",
            "model_profile": args.model,
            "tier": args.tier,
            "render_targets": TIERS[args.tier],
            "render_seed": render_seed,
            "subjects": [
                {"slot": index, "subject_id": subject}
                for index, subject in enumerate(subjects, start=1)
            ],
            "preset_id": preset["id"],
            "preset_snapshot": preset,
            "rotation": {
                "pool_key": pool_key,
                "cycle": pool["cycle"],
                "selection_seed": args.selection_seed,
            },
            "promotion_gate": {
                "audit_status": "ok",
                "audit_decision": "pass",
                "require_every_subject": True,
            },
        }

        pool["used"].append(preset["id"])

        # Reserve selection before publishing the job. If publication fails,
        # the next invocation recovers exactly this job.
        state["pending_job"] = job
        atomic_json(state_path, state)

        destination = QUEUE / f"{job_id}.json"
        atomic_json(destination, job)

        del state["pending_job"]
        atomic_json(state_path, state)

    print(destination)
    print(f"Preset: {preset['id']}; cycle: {pool['cycle']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init")
    init.add_argument("--force", action="store_true")

    pick = commands.add_parser("pick")
    pick.add_argument(
        "--category", choices=["all", *CATALOG], default="all"
    )
    pick.add_argument("--subjects", nargs="+", required=True)
    pick.add_argument("--model", required=True,
                      help="Your local model-profile ID; not a compatibility claim.")
    pick.add_argument("--tier", choices=TIERS, default="B")
    pick.add_argument("--selection-seed", type=int)
    pick.add_argument("--render-seed", type=int)

    commands.add_parser("validate")
    args = parser.parse_args()

    try:
        if args.command == "init":
            initialize(args.force)
        elif args.command == "pick":
            queue_job(args)
        else:
            presets = load_presets()
            counts = {
                category: sum(p["category"] == category for p in presets)
                for category in CATALOG
            }
            print(json.dumps(counts, indent=2))
            if len(presets) != 54 or any(n != 9 for n in counts.values()):
                raise ValueError("Expected exactly 54 presets, 9 per category.")
            print("Catalog structure validated; model compatibility untested.")
        return 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

### 3.4 — Windows runbook

**Generate all 54 JSON files:**

```powershell
Set-Location "D:\AI\ComfyUI_portable\workshop\templates"
$Python = "D:\AI\ComfyUI_portable\python_embeded\python.exe"

& $Python .\template_rotation.py init
& $Python .\template_rotation.py validate
```

Existing presets are preserved. `init --force` overwrites catalog presets; back up edits first.

**Queue a solo scene:**

```powershell
& $Python .\template_rotation.py pick `
    --category environmental `
    --subjects subject_001 `
    --model wan_local `
    --tier A `
    --selection-seed 42 `
    --render-seed 123456
```

**Queue a two-person scene:**

```powershell
& $Python .\template_rotation.py pick `
    --category multi `
    --subjects subject_001 subject_002 `
    --model hunyuan_local `
    --tier B
```

**Queue a four-person scene:**

```powershell
& $Python .\template_rotation.py pick `
    --category group `
    --subjects subject_001 subject_002 subject_003 subject_004 `
    --model ltx_local `
    --tier B
```

Model-profile names above are local labels, not verified compatibility entries.

### 3.5 — Connection to the face-retention audit

After the workflow adapter renders a job, produce the existing `audit_batch.py` manifest:

```json
{
  "jobs": [
    {
      "clip": "D:/AI/ComfyUI_portable/workshop/batch/outputs/render_001.mp4",
      "subject": "subject_001"
    },
    {
      "clip": "D:/AI/ComfyUI_portable/workshop/batch/outputs/render_001.mp4",
      "subject": "subject_002"
    }
  ]
}
```

For a two-person render, **both subjects must pass**. A successful render or high aggregate score does not establish identity retention.

### 3.6 — Failure modes and boundaries

| Condition | Handling |
| --- | --- |
| Wrong subject count | Selection rejected |
| Concurrent selectors | Lock prevents overlapping state updates |
| Crash after reservation | Pending job recovered on next selection |
| Stale lock after crash | Confirm process stopped, then remove lock |
| Edited preset after queuing | Queued snapshot preserves selected settings |
| Unsupported model resolution | Workflow adapter must reject or normalize |
| Negative prompts unsupported | Adapter must omit or translate them |
| Multi-person identity ambiguity | Require association-aware auditing |
| Same selection seed, changed state | Selection can differ; state is part of reproducibility |

**Queue-consumer requirement:** deduplicate on `job_id`. Reservation recovery can republish a job after a crash; a filename alone does not provide exactly-once rendering.

---
