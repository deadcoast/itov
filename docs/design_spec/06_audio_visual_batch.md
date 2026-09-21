# Part 6 — Audio-Visual Batch Coupler for Single-Command Batch Jobs

The coupler is the top-level orchestrator that fuses everything from Parts 3-5 into one command. You point it at a YAML batch spec; it pairs scene presets, visual LoRA stacks, voice LoRAs, seeds, and audio conditioning tracks into discrete jobs, launches parallel ComfyUI worker instances, syncs outputs, and writes a metadata ledger for every rendered clip.

---

## 6.1 Directory Anchor

```txt
D:\AI\ComfyUI_portable\batch\
├── specs\
│   ├── nightly_01.yaml
│   ├── voice_stress_test.yaml
│   └── multi_char_scene.yaml
├── workers\
│   ├── worker_0.log          # ComfyUI instance on port 8188
│   ├── worker_1.log          # port 8189
│   └── worker_2.log          # port 8190
├── outputs\
│   └── <run_id>\
│       ├── 0001_<preset>_<lorastack>_<voice>_<seed>.mp4
│       ├── 0001_<...>.wav
│       ├── 0001_<...>.json   # per-clip metadata
│       └── run_ledger.csv
├── queue\
│   ├── pending.jsonl
│   ├── active.jsonl
│   └── done.jsonl
└── coupler\
    ├── couple.py             # main entry
    ├── worker_pool.py        # parallel ComfyUI API client
    ├── audio_sync.py         # ffmpeg-based mux + validation
    ├── spec_expander.py      # YAML → cartesian job list
    └── ledger_writer.py
```

---

## 6.2 Batch Spec Schema — `specs\<run>.yaml`

The spec is where the whole system converges. Every axis (scene, visual LoRAs, voice, audio track, seed) is expressed as a list; the expander computes the cartesian product with optional constraints.

```yaml
run_id: nightly_01_20260920
output_root: D:\AI\ComfyUI_portable\batch\outputs
comfy_root: D:\AI\ComfyUI_portable
workers:
  count: 3
  ports: [8188, 8189, 8190]
  gpu_mem_reserve_gb: 8       # leaves 24GB per worker on 5090

axes:
  scene_presets:              # from Part 3 rotation
    - body/close_intimate_01
    - body/close_intimate_04
    - fluid/heavy_finish_02
    - group/threeway_switch_01
  visual_lora_stacks:         # from Part 4 rotation, named stack IDs
    - stack_realism_a
    - stack_realism_b
    - stack_stylized_noir
  voice_loras:                # from Part 5, path relative to ltx_lora\voice\
    - eva_noir_01
    - riley_bright_02
    - null                    # allows unvoiced clips too
  audio_tracks:               # optional conditioning wavs
    - null
    - conditioning\breathwork_loop_a.wav
    - conditioning\dialogue_scripted_01.wav
  seeds:
    strategy: sweep           # sweep | random | fixed
    count: 4
    base: 202609200

constraints:
  # skip nonsensical combos
  - if: {voice_loras: null}
    then_skip_axes: [audio_tracks]
  - if: {scene_presets: "group/*"}
    then_require: {visual_lora_stacks: ["stack_realism_a","stack_realism_b"]}
  - max_jobs: 240              # hard ceiling

render:
  base_model: ltx-video-2.5
  resolution: [1216, 704]
  frames: 121                  # ~5s at 24fps
  fps: 24
  steps: 28
  cfg: 3.2
  block_swap: true
  voice_lora_weight: 0.85

post:
  mux_audio: true              # ffmpeg combine video+wav
  normalize_audio_lufs: -16
  extract_thumbnail: true
  validate_sync: true          # runs Part 5.8 metrics on each output
  min_lip_r: 0.65              # flag anything below in ledger
```

---

## 6.3 Spec Expander — `coupler\spec_expander.py`

```python
import itertools, fnmatch, yaml, hashlib
from pathlib import Path

def expand(spec_path: Path) -> list[dict]:
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    axes = spec["axes"]
    
    # seed strategy
    if axes["seeds"]["strategy"] == "sweep":
        seeds = [axes["seeds"]["base"] + i for i in range(axes["seeds"]["count"])]
    elif axes["seeds"]["strategy"] == "random":
        import random
        seeds = [random.randint(1, 2**31) for _ in range(axes["seeds"]["count"])]
    else:
        seeds = [axes["seeds"]["base"]]
    
    keys = ["scene_presets","visual_lora_stacks","voice_loras","audio_tracks"]
    lists = [axes[k] for k in keys] + [seeds]
    
    jobs = []
    for combo in itertools.product(*lists):
        job = dict(zip(keys + ["seed"], combo))
        if not passes_constraints(job, spec.get("constraints", [])):
            continue
        job["job_id"] = hashlib.md5(repr(job).encode()).hexdigest()[:10]
        job["run_id"] = spec["run_id"]
        jobs.append(job)
    
    max_jobs = next((c["max_jobs"] for c in spec.get("constraints",[]) if "max_jobs" in c), None)
    if max_jobs:
        jobs = jobs[:max_jobs]
    return jobs

def passes_constraints(job, rules):
    for rule in rules:
        if "max_jobs" in rule: continue
        if "if" not in rule: continue
        match = True
        for k, v in rule["if"].items():
            jv = job.get(k)
            if v is None:
                if jv is not None: match = False
            elif isinstance(v, str) and "*" in v:
                if not (jv and fnmatch.fnmatch(jv, v)): match = False
            elif jv != v:
                match = False
        if not match: continue
        if "then_skip_axes" in rule:
            for ax in rule["then_skip_axes"]:
                if job.get(ax) is not None:
                    return False
        if "then_require" in rule:
            for k, allowed in rule["then_require"].items():
                if job.get(k) not in allowed:
                    return False
    return True
```

---

## 6.4 Worker Pool — `coupler\worker_pool.py`

Talks to N running ComfyUI instances over their HTTP APIs. Each worker is bound to a fixed port; the pool assigns jobs by shortest queue.

```python
import asyncio, aiohttp, json, uuid
from pathlib import Path

class ComfyWorker:
    def __init__(self, host: str, port: int, gpu_index: int = 0):
        self.base = f"http://{host}:{port}"
        self.gpu = gpu_index
        self.active = 0
    
    async def submit(self, session, workflow_json: dict) -> str:
        client_id = str(uuid.uuid4())
        payload = {"prompt": workflow_json, "client_id": client_id}
        async with session.post(f"{self.base}/prompt", json=payload) as r:
            data = await r.json()
        return data["prompt_id"]
    
    async def poll(self, session, prompt_id: str, timeout=900) -> dict:
        for _ in range(timeout):
            async with session.get(f"{self.base}/history/{prompt_id}") as r:
                hist = await r.json()
            if prompt_id in hist and hist[prompt_id].get("status",{}).get("completed"):
                return hist[prompt_id]
            await asyncio.sleep(1)
        raise TimeoutError(prompt_id)

class WorkerPool:
    def __init__(self, workers: list[ComfyWorker]):
        self.workers = workers
        self.sem = asyncio.Semaphore(len(workers))
    
    def pick(self) -> ComfyWorker:
        return min(self.workers, key=lambda w: w.active)
    
    async def run(self, workflow_json: dict) -> dict:
        async with self.sem:
            w = self.pick()
            w.active += 1
            try:
                async with aiohttp.ClientSession() as s:
                    pid = await w.submit(s, workflow_json)
                    return await w.poll(s, pid)
            finally:
                w.active -= 1
```

---

## 6.5 Workflow Assembly

Each job needs to be turned into a ComfyUI workflow graph JSON. The coupler holds a template graph (exported from a working manual setup) and patches specific nodes per job. Node IDs are stable because the template is version-controlled.

```python
import json, copy
from pathlib import Path

TEMPLATE = Path(r"D:\AI\ComfyUI_portable\batch\coupler\template_ltx25_audio.json")

# node id map (edit once when template changes)
NODE_IDS = {
    "checkpoint":     "3",
    "positive_clip":  "7",
    "negative_clip":  "8",
    "visual_lora_1":  "11",
    "visual_lora_2":  "12",
    "visual_lora_3":  "13",
    "visual_lora_4":  "14",
    "voice_lora":     "21",
    "audio_input":    "22",
    "sampler":        "30",
    "video_out":      "40",
}

def build_workflow(job: dict, scene_preset: dict, lora_stack: dict, render_cfg: dict) -> dict:
    wf = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    n = NODE_IDS
    
    # scene preset → prompts + resolution
    wf[n["positive_clip"]]["inputs"]["text"] = scene_preset["positive"]
    wf[n["negative_clip"]]["inputs"]["text"] = scene_preset["negative"]
    
    # visual LoRA stack (up to 4)
    for i, entry in enumerate(lora_stack["loras"][:4], start=1):
        node = wf[n[f"visual_lora_{i}"]]
        node["inputs"]["lora_name"] = entry["file"]
        node["inputs"]["strength_model"] = entry["strength"]
        node["inputs"]["strength_clip"]  = entry.get("strength_clip", entry["strength"])
    # zero out unused slots
    for i in range(len(lora_stack["loras"]) + 1, 5):
        wf[n[f"visual_lora_{i}"]]["inputs"]["strength_model"] = 0.0
    
    # voice LoRA
    if job["voice_loras"]:
        wf[n["voice_lora"]]["inputs"]["lora_name"] = f"voice\\{job['voice_loras']}.safetensors"
        wf[n["voice_lora"]]["inputs"]["strength"] = render_cfg["voice_lora_weight"]
    else:
        wf[n["voice_lora"]]["inputs"]["strength"] = 0.0
    
    # audio conditioning track
    if job["audio_tracks"]:
        wf[n["audio_input"]]["inputs"]["audio"] = job["audio_tracks"]
    else:
        wf[n["audio_input"]]["inputs"]["bypass"] = True
    
    # sampler
    s = wf[n["sampler"]]["inputs"]
    s["seed"]  = job["seed"]
    s["steps"] = render_cfg["steps"]
    s["cfg"]   = render_cfg["cfg"]
    s["width"], s["height"] = render_cfg["resolution"]
    s["length"] = render_cfg["frames"]
    
    # output filename
    wf[n["video_out"]]["inputs"]["filename_prefix"] = (
        f"{job['run_id']}/{job['job_id']}_"
        f"{Path(job['scene_presets']).stem}_"
        f"{job['visual_lora_stacks']}_"
        f"{job['voice_loras'] or 'silent'}_"
        f"{job['seed']}"
    )
    return wf
```

---

## 6.6 Audio Sync & Post — `coupler\audio_sync.py`

Once the raw video and generated audio come out of the worker, this step muxes, normalizes, and validates.

```python
import subprocess, json
from pathlib import Path

def mux(video: Path, audio: Path, out: Path, lufs: float = -16.0):
    """Combine video + audio, loudness-normalize to target LUFS."""
    cmd = [
        "ffmpeg","-y","-i",str(video),"-i",str(audio),
        "-c:v","copy",
        "-af",f"loudnorm=I={lufs}:TP=-1.5:LRA=11",
        "-c:a","aac","-b:a","192k",
        "-map","0:v:0","-map","1:a:0",
        "-shortest", str(out)
    ]
    subprocess.run(cmd, check=True, capture_output=True)

def extract_thumbnail(video: Path, out: Path, at_sec: float = 2.0):
    subprocess.run([
        "ffmpeg","-y","-ss",str(at_sec),"-i",str(video),
        "-frames:v","1","-q:v","2",str(out)
    ], check=True, capture_output=True)

def validate(video: Path, audio: Path, transcript: str = None) -> dict:
    """Return sync metrics for ledger. Uses Part 5.8 utilities."""
    from validate_sync import lip_correlation, ecapa_cos, onset_delta
    metrics = {}
    try:
        metrics["lip_r"] = lip_correlation(video, audio)
    except Exception as e:
        metrics["lip_r"] = None
        metrics["lip_r_err"] = str(e)
    if transcript:
        try:
            metrics["onset_drift_ms"] = onset_delta(audio, transcript) * 1000
        except Exception as e:
            metrics["onset_drift_ms"] = None
    return metrics
```

---

## 6.7 Main Entry — `coupler\couple.py`

```python
import asyncio, argparse, json, csv, time
from pathlib import Path
from spec_expander import expand
from worker_pool import ComfyWorker, WorkerPool
from workflow_assembly import build_workflow
from audio_sync import mux, extract_thumbnail, validate
import yaml

async def run_job(job, pool, spec, ledger_rows):
    scene = json.loads(Path(spec["comfy_root"], "templates", job["scene_presets"] + ".json").read_text())
    stack = json.loads(Path(spec["comfy_root"], "templates", "loras", "stacks", job["visual_lora_stacks"] + ".json").read_text())
    wf = build_workflow(job, scene, stack, spec["render"])
    t0 = time.time()
    result = await pool.run(wf)
    elapsed = time.time() - t0
    
    out_dir = Path(spec["output_root"]) / spec["run_id"]
    prefix = out_dir / f"{job['job_id']}"
    video = next(out_dir.glob(f"{job['job_id']}*.mp4"), None)
    audio = next(out_dir.glob(f"{job['job_id']}*.wav"), None)
    
    row = {
        "job_id": job["job_id"],
        "scene": job["scene_presets"],
        "lora_stack": job["visual_lora_stacks"],
        "voice": job["voice_loras"] or "silent",
        "audio_track": job["audio_tracks"] or "none",
        "seed": job["seed"],
        "elapsed_s": round(elapsed, 1),
        "video_path": str(video) if video else "",
        "flagged": False,
    }
    
    if spec["post"]["mux_audio"] and video and audio:
        muxed = prefix.with_name(prefix.name + "_muxed.mp4")
        mux(video, audio, muxed, spec["post"]["normalize_audio_lufs"])
        row["muxed_path"] = str(muxed)
        if spec["post"]["extract_thumbnail"]:
            extract_thumbnail(muxed, prefix.with_suffix(".jpg"))
        if spec["post"]["validate_sync"]:
            m = validate(muxed, audio)
            row.update(m)
            if m.get("lip_r") is not None and m["lip_r"] < spec["post"]["min_lip_r"]:
                row["flagged"] = True
    
    ledger_rows.append(row)
    (out_dir / f"{job['job_id']}.json").write_text(json.dumps(row, indent=2))

async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    args = ap.parse_args()
    spec = yaml.safe_load(Path(args.spec).read_text(encoding="utf-8"))
    jobs = expand(Path(args.spec))
    print(f"[coupler] expanded {len(jobs)} jobs")
    
    workers = [ComfyWorker("127.0.0.1", p) for p in spec["workers"]["ports"]]
    pool = WorkerPool(workers)
    ledger_rows = []
    
    out_dir = Path(spec["output_root"]) / spec["run_id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    
    tasks = [run_job(j, pool, spec, ledger_rows) for j in jobs]
    for i, coro in enumerate(asyncio.as_completed(tasks), 1):
        await coro
        print(f"[coupler] {i}/{len(jobs)} done")
    
    # write consolidated ledger
    ledger = out_dir / "run_ledger.csv"
    if ledger_rows:
        with ledger.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(ledger_rows[0].keys()))
            w.writeheader()
            w.writerows(ledger_rows)
    print(f"[coupler] ledger → {
```

## 6.7 — Trigger Conflict Resolver (completion)

Directory anchor: `D:\AI\ComfyUI_portable\workshop\batch\`

### 6.7.1 Conflict taxonomy

Trigger collisions surface in three flavors when the batch coupler stacks LoRAs from the ledger:

1. **Lexical duplicates** — two LoRAs both claim `wet` or `pov`. Prompt gets the token once, but attribution is ambiguous and weight math double-counts.
2. **Semantic antagonists** — `soft_lighting_v3` ships `golden hour, hazy` while `harsh_flash_v2` ships `direct flash, blown highlights`. Both fire, image goes muddy.
3. **Positional dependents** — anatomy LoRAs that require their trigger *before* style tokens (kohya training order artifact); if the injector prepends style last, anatomy weight collapses.

The resolver is a priority queue keyed on `(manifest_timestamp, category_rank, user_pin)` with a conflict map derived from `_compatibility_matrix.json`.

### 6.7.2 `resolve_triggers.py`

```python
# D:\AI\ComfyUI_portable\workshop\batch\resolve_triggers.py
import json, csv, heapq, re
from pathlib import Path
from datetime import datetime

ROOT = Path(r"D:\AI\ComfyUI_portable\workshop")
MANIFEST = ROOT / "loras" / "_lora_manifest.json"
LEDGER   = ROOT / "loras" / "_lora_ledger.csv"
MATRIX   = ROOT / "loras" / "_compatibility_matrix.json"

CATEGORY_RANK = {
    "anatomy":   0,   # must land first — training-order dependent
    "kink":      1,
    "style":     2,
    "lighting":  3,
    "camera":    4,
}

def _load():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    matrix   = json.loads(MATRIX.read_text(encoding="utf-8"))
    ledger   = {}
    with LEDGER.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ledger[row["lora"]] = row
    return manifest, matrix, ledger

def _tokenize(trigger_str):
    # comma or pipe delimited, strip whitespace, lower for compare only
    return [t.strip() for t in re.split(r"[|,]", trigger_str) if t.strip()]

def resolve(active_loras, user_pins=None):
    """
    active_loras: list[str] — lora filenames selected for this job
    user_pins:    dict[str,int] — optional {lora: -N} to force earlier placement
    returns: ordered list of (lora, [triggers]) with duplicates removed and
             antagonists dropped by priority
    """
    manifest, matrix, ledger = _load()
    user_pins = user_pins or {}
    heap = []

    for lora in active_loras:
        meta = manifest.get(lora, {})
        cat  = meta.get("category", "style")
        ts   = meta.get("added", "2099-01-01T00:00:00")
        try:
            ts_key = datetime.fromisoformat(ts).timestamp()
        except ValueError:
            ts_key = 4102444800.0
        pin = user_pins.get(lora, 0)
        # lower tuple = higher priority
        priority = (pin, CATEGORY_RANK.get(cat, 9), ts_key)
        triggers = _tokenize(
            meta.get("triggers") or ledger.get(lora, {}).get("trigger_words", "")
        )
        heapq.heappush(heap, (priority, lora, cat, triggers))

    seen_tokens = {}          # lowercase token -> owning lora
    hard_conflicts = matrix.get("hard_conflicts", [])
    dropped = []
    ordered = []

    active_set = set(active_loras)
    for pair in hard_conflicts:
        a, b = pair["a"], pair["b"]
        if a in active_set and b in active_set:
            # keep the higher-priority one, drop the other
            pri_a = next(h for h in heap if h[1] == a)[0]
            pri_b = next(h for h in heap if h[1] == b)[0]
            loser = b if pri_a < pri_b else a
            active_set.discard(loser)
            dropped.append((loser, f"hard_conflict_with_{a if loser==b else b}"))

    while heap:
        priority, lora, cat, triggers = heapq.heappop(heap)
        if lora not in active_set:
            continue
        deduped = []
        for tok in triggers:
            key = tok.lower()
            if key in seen_tokens:
                continue
            seen_tokens[key] = lora
            deduped.append(tok)
        ordered.append((lora, deduped))

    return ordered, dropped

if __name__ == "__main__":
    import sys
    loras = sys.argv[1:]
    order, dropped = resolve(loras)
    for lora, toks in order:
        print(f"{lora}: {', '.join(toks)}")
    for lora, reason in dropped:
        print(f"# DROPPED {lora} :: {reason}")
```

### 6.7.3 Integration with `av_batch.py`

Inside the batch coupler’s workflow assembly step, replace the naive trigger concat with:

```python
from resolve_triggers import resolve

ordered, dropped = resolve(job["lora_stack"], user_pins=job.get("pin_overrides"))
positive_prompt = ", ".join(tok for _, toks in ordered for tok in toks) + ", " + job["scene_prompt"]
job["_dropped_loras"] = dropped   # surfaces in run manifest for audit
```

### 6.7.4 Runbook

```bash
cd D:\AI\ComfyUI_portable\workshop\batch
python resolve_triggers.py wetlook_v4.safetensors harsh_flash_v2.safetensors anatomy_curvy_v7.safetensors
# expect anatomy_curvy_v7 first, wetlook second, harsh_flash dropped if matrix flags it vs soft_lighting active
```

### 6.7.5 Failure modes

- **Empty triggers after resolve** — a LoRA whose tokens were all claimed by a higher-priority sibling contributes zero prompt weight. Log at WARN, keep the LoRA loaded (its UNet delta still applies).
- **Matrix stale** — new LoRA added to ledger but not to `_compatibility_matrix.json`. Resolver treats it as neutral; run `python audit_matrix.py` weekly to flag orphans.
- **Circular pins** — user pins both `a` and `b` to `-1`. Tie-break falls to timestamp; document this in the batch spec header.

---
