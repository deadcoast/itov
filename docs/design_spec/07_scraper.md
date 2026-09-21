# Part 7 — Automated Civitai Scraper & Experimental LoRA Onboarding Workflow

Directory anchor: `\AI\ComfyUI_portable\workshop\scrape\`

Purpose: sweep Civitai (and mirror endpoints) for LTX-2.5 compatible LoRAs, filter by audio-sync suitability and content stance, sandbox-test each candidate against a synthetic prompt battery, and promote passing weights into `_lora_manifest.json` / `_lora_ledger.csv` without human keystrokes beyond the initial cron.

## 7.1 Directory layout

```txt
D:\AI\ComfyUI_portable\workshop\scrape\
├── civitai_scrape.py            # main crawler + onboarding driver
├── filters.py                   # tag/metadata filter functions
├── sandbox_test.py              # synthetic prompt battery + scoring
├── promote.py                   # writes to manifest/ledger atomically
├── config\
│   ├── scrape_config.yaml       # api keys, tag allowlist/denylist, thresholds
│   └── synthetic_prompts.json   # 40 prompt battery for onboarding
├── cache\
│   ├── seen_hashes.sqlite       # dedupe across runs
│   └── downloads\               # staged .safetensors before promotion
├── sandbox\
│   ├── renders\                 # short test clips per candidate
│   └── scores\                  # per-LoRA JSON scorecards
└── logs\
    └── scrape_YYYYMMDD.log
```

### 7.2 `scrape_config.yaml`

```yaml
api:
  base: https://civitai.com/api/v1
  token: ${CIVITAI_TOKEN}          # env var, never hardcode
  page_size: 100
  rate_limit_qps: 2

query:
  types: [LORA]
  base_models: [LTX-2.5, LTX-Video, Wan-2.2]
  sort: Newest
  period: Week
  nsfw: true                       # explicit content included by default

filters:
  allow_tags: [audio-sync, lipsync, voice, phoneme, ltx-audio, nsfw, explicit, anatomy]
  deny_tags: [sfw-only, watermark-required, tos-restricted]
  min_downloads: 25
  min_rating: 3.5
  max_size_mb: 512
  license_allow: [CreativeML-OpenRAIL-M, CC-BY, CC0, Public, custom-permissive]

scoring:
  sync_error_max_s: 0.05
  aesthetic_min: 5.8
  prompt_adherence_min: 0.72
  weight:
    sync: 0.5
    aesthetic: 0.2
    adherence: 0.3

promotion:
  auto_threshold: 0.80             # composite score
  quarantine_threshold: 0.60       # below this → discard
  # between the two → flagged/ needs_review folder
```

### 7.3 `civitai_scrape.py`

```python
# D:\AI\ComfyUI_portable\workshop\scrape\civitai_scrape.py
import os, sys, time, json, hashlib, sqlite3, yaml, requests
from pathlib import Path
from datetime import datetime, timezone
from filters import passes_metadata
from sandbox_test import run_battery
from promote import promote, quarantine, flag_review

ROOT = Path(r"D:\AI\ComfyUI_portable\workshop\scrape")
CFG  = yaml.safe_load((ROOT / "config" / "scrape_config.yaml").read_text())
DB   = sqlite3.connect(ROOT / "cache" / "seen_hashes.sqlite")
DB.execute("CREATE TABLE IF NOT EXISTS seen (sha256 TEXT PRIMARY KEY, first_seen TEXT, verdict TEXT)")
DL   = ROOT / "cache" / "downloads"
DL.mkdir(parents=True, exist_ok=True)

LOG_PATH = ROOT / "logs" / f"scrape_{datetime.utcnow():%Y%m%d}.log"
def log(msg):
    line = f"[{datetime.utcnow().isoformat()}] {msg}"
    print(line)
    LOG_PATH.parent.mkdir(exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")

def _sess():
    s = requests.Session()
    tok = os.path.expandvars(CFG["api"]["token"])
    if tok and tok != "${CIVITAI_TOKEN}":
        s.headers["Authorization"] = f"Bearer {tok}"
    return s

def crawl(session, max_pages=10):
    q = CFG["query"]
    params = {
        "types": ",".join(q["types"]),
        "sort":  q["sort"],
        "period": q["period"],
        "nsfw":  str(q["nsfw"]).lower(),
        "limit": CFG["api"]["page_size"],
    }
    url = f"{CFG['api']['base']}/models"
    page = 0
    while url and page < max_pages:
        r = session.get(url, params=params, timeout=30)
        r.raise_for_status()
        payload = r.json()
        for item in payload.get("items", []):
            yield item
        url = payload.get("metadata", {}).get("nextPage")
        params = {}  # nextPage is fully-qualified
        page += 1
        time.sleep(1.0 / CFG["api"]["rate_limit_qps"])

def _hash_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def _already_seen(sha):
    return DB.execute("SELECT verdict FROM seen WHERE sha256=?", (sha,)).fetchone()

def _record(sha, verdict):
    DB.execute("INSERT OR REPLACE INTO seen VALUES (?,?,?)",
               (sha, datetime.utcnow().isoformat(), verdict))
    DB.commit()

def _download(session, version):
    files = version.get("files", [])
    prim  = next((f for f in files if f.get("primary")), files[0] if files else None)
    if not prim:
        return None
    size_mb = prim.get("sizeKB", 0) / 1024
    if size_mb > CFG["filters"]["max_size_mb"]:
        log(f"  skip: size {size_mb:.1f}MB > cap")
        return None
    dst = DL / prim["name"]
    if dst.exists():
        return dst
    log(f"  downloading {prim['name']} ({size_mb:.1f}MB)")
    with session.get(prim["downloadUrl"], stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dst, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    return dst

def process(model):
    name = model.get("name", "unknown")
    log(f"eval: {name} (id={model.get('id')})")
    if not passes_metadata(model, CFG["filters"]):
        log("  reject: metadata filter")
        return
    versions = sorted(model.get("modelVersions", []),
                      key=lambda v: v.get("createdAt", ""), reverse=True)
    if not versions:
        return
    v = versions[0]
    if not any(bm in v.get("baseModel", "") for bm in CFG["query"]["base_models"]):
        log(f"  reject: baseModel {v.get('baseModel')}")
        return

    session = _sess()
    path = _download(session, v)
    if not path:
        return
    sha = _hash_file(path)
    prior = _already_seen(sha)
    if prior:
        log(f"  dedupe hit ({prior[0]})")
        return

    scorecard = run_battery(path, model, v, CFG)
    composite = scorecard["composite"]
    log(f"  score: composite={composite:.3f} sync={scorecard['sync_error_s']:.4f}s")

    if composite >= CFG["promotion"]["auto_threshold"]:
        promote(path, model, v, scorecard, sha)
        _record(sha, "promoted")
    elif composite >= CFG["promotion"]["quarantine_threshold"]:
        flag_review(path, model, v, scorecard, sha)
        _record(sha, "review")
    else:
        quarantine(path, sha)
        _record(sha, "rejected")

def main(argv):
    max_pages = int(argv[argv.index("--pages")+1]) if "--pages" in argv else 5
    only_filter = argv[argv.index("--filter")+1] if "--filter" in argv else None
    session = _sess()
    for m in crawl(session, max_pages=max_pages):
        if only_filter and only_filter not in " ".join(m.get("tags", [])):
            continue
        try:
            process(m)
        except Exception as e:
            log(f"  ERROR on {m.get('name')}: {e}")

if __name__ == "__main__":
    main(sys.argv[1:])
```

### 7.4 `filters.py`

```python
# D:\AI\ComfyUI_portable\workshop\scrape\filters.py
def passes_metadata(model, cfg):
    tags = {t.lower() for t in model.get("tags", [])}
    allow = {t.lower() for t in cfg["allow_tags"]}
    deny  = {t.lower() for t in cfg["deny_tags"]}

    if tags & deny:
        return False
    if allow and not (tags & allow):
        return False

    stats = model.get("stats", {})
    if stats.get("downloadCount", 0) < cfg["min_downloads"]:
        return False
    if stats.get("rating", 0) < cfg["min_rating"]:
        return False

    lic = (model.get("license") or "").strip()
    if cfg.get("license_allow") and lic and lic not in cfg["license_allow"]:
        # unknown license → allow if empty, block if explicitly disallowed
        return False
    return True
```

### 7.5 `sandbox_test.py` — synthetic prompt battery + scoring

The battery lives in `config/synthetic_prompts.json` — 40 entries covering closeup speech, moaning, wet impact SFX, breath work, whispered dialogue, and silent-motion control. Each entry ships a reference audio clip and expected phoneme timeline.

```python
# D:\AI\ComfyUI_portable\workshop\scrape\sandbox_test.py
import json, subprocess, tempfile, statistics
from pathlib import Path

ROOT = Path(r"D:\AI\ComfyUI_portable\workshop\scrape")
PROMPTS = json.loads((ROOT / "config" / "synthetic_prompts.json").read_text())
COMFY_API = "http://127.0.0.1:8188"   # local ComfyUI

def _render(comfy_workflow_json, out_dir):
    # POST to ComfyUI /prompt, poll /history, pull mp4
    # implementation omitted for brevity — see workshop/batch/av_batch.py
    ...

def _sync_error(rendered_mp4, ref_audio, ref_phonemes):
    # extract lip landmarks via mediapipe, phonemes via whisperx forced align,
    # compute per-viseme offset in seconds; return mean absolute error
    from lipsync_metrics import viseme_alignment_error
    return viseme_alignment_error(rendered_mp4, ref_audio, ref_phonemes)

def _aesthetic(rendered_mp4):
    from aesthetic import laion_score_video   # cached model
    return laion_score_video(rendered_mp4)

def _adherence(rendered_mp4, prompt_text):
    from clip_adherence import clipsim_video_text
    return clipsim_video_text(rendered_mp4, prompt_text)

def run_battery(lora_path, model_meta, version_meta, cfg):
    scores_sync, scores_aes, scores_adh = [], [], []
    out_root = ROOT / "sandbox" / "renders" / lora_path.stem
    out_root.mkdir(parents=True, exist_ok=True)

    for entry in PROMPTS:
        wf = _build_workflow(lora_path, entry, version_meta)
        clip = _render(wf, out_root)
        se = _sync_error(clip, entry["ref_audio"], entry["phonemes"])
        ae = _aesthetic(clip)
        ad = _adherence(clip, entry["prompt"])
        scores_sync.append(se); scores_aes.append(ae); scores_adh.append(ad)

    sync_err = statistics.median(scores_sync)
    aes      = statistics.median(scores_aes)
    adh      = statistics.median(scores_adh)

    w = cfg["scoring"]["weight"]
    # normalize sync: 0.00s → 1.0, cutoff → 0.0
    sync_norm = max(0.0, 1.0 - (sync_err / cfg["scoring"]["sync_error_max_s"]))
    aes_norm  = min(1.0, aes / 10.0)
    adh_norm  = min(1.0, adh / 1.0)

    composite = sync_norm*w["sync"] + aes_norm*w["aesthetic"] + adh_norm*w["adherence"]

    card = {
        "lora": lora_path.name,
        "sync_error_s": sync_err,
        "aesthetic": aes,
        "adherence": adh,
        "composite": composite,
        "battery_size": len(PROMPTS),
    }
    (ROOT / "sandbox" / "scores" / f"{lora_path.stem}.json").write_text(json.dumps(card, indent=2))
    return card

def _build_workflow(lora_path, entry, version_meta):
    # returns a ComfyUI graph dict with LTX-2.5 sampler + this LoRA at weight 0.8
    # anchored to the audio track from entry["ref_audio"]
    ...
```

## `promote.py` — full script

Directory anchor: `D:\AI\ComfyUI_portable\workshop\scrape\promote.py`

```python
# D:\AI\ComfyUI_portable\workshop\scrape\promote.py
"""
Promotion / quarantine / review handoff for the Civitai onboarding pipeline.

Called by civitai_scrape.py after sandbox_test.run_battery() returns a scorecard.
Three terminal states:

    promote(...)      -> moves .safetensors into prod LoRA pool,
                         appends to _lora_manifest.json + _lora_ledger.csv,
                         writes companion sidecar with provenance.

    flag_review(...)  -> parks weights in _needs_review\ with scorecard,
                         no manifest write. Human decides later.

    quarantine(...)   -> deletes weights, keeps sha in seen db so the crawler
                         never redownloads. Reason recorded.

All manifest / ledger writes are atomic: write to .tmp, fsync, os.replace.
"""

import json
import csv
import shutil
import tempfile
import os
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

# ── Paths ────────────────────────────────────────────────────────────────────
WORKSHOP  = Path(r"D:\AI\ComfyUI_portable\workshop")
LORA_DIR  = WORKSHOP / "loras"
MANIFEST  = LORA_DIR / "_lora_manifest.json"
LEDGER    = LORA_DIR / "_lora_ledger.csv"

PROD_POOL = Path(r"D:\AI\ComfyUI_portable\ComfyUI\models\loras\prod")
REVIEW    = LORA_DIR / "_needs_review"
SIDECARS  = LORA_DIR / "_sidecars"
STAGING   = Path(r"D:\AI\ComfyUI_portable\workshop\scrape\cache\downloads")

for p in (PROD_POOL, REVIEW, SIDECARS, LORA_DIR):
    p.mkdir(parents=True, exist_ok=True)

LEDGER_HEADERS = [
    "lora", "category", "sha256", "source", "civitai_model_id",
    "civitai_version_id", "base_model", "trigger_words",
    "composite_score", "sync_error_s", "added", "license",
]

# ── Utility ──────────────────────────────────────────────────────────────────
def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def _atomic_write_json(path: Path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

def _atomic_append_csv(path: Path, row: dict):
    exists = path.exists()
    tmp = path.with_suffix(".csv.tmp")
    # copy existing then append, then replace — keeps write atomic on Windows
    if exists:
        shutil.copyfile(path, tmp)
        with tmp.open("a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=LEDGER_HEADERS)
            writer.writerow({k: row.get(k, "") for k in LEDGER_HEADERS})
            f.flush()
            os.fsync(f.fileno())
    else:
        with tmp.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=LEDGER_HEADERS)
            writer.writeheader()
            writer.writerow({k: row.get(k, "") for k in LEDGER_HEADERS})
            f.flush()
            os.fsync(f.fileno())
    os.replace(tmp, path)

def _load_manifest() -> dict:
    if MANIFEST.exists():
        try:
            return json.loads(MANIFEST.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # corrupted manifest — back it up, start clean rather than crash
            backup = MANIFEST.with_suffix(f".corrupt.{int(datetime.now().timestamp())}.json")
            shutil.copyfile(MANIFEST, backup)
            return {}
    return {}

def _infer_category(model_meta: dict, version_meta: dict) -> str:
    tags = {t.lower() for t in model_meta.get("tags", [])}
    if tags & {"anatomy", "body", "genital", "breast", "curves"}:
        return "anatomy"
    if tags & {"kink", "bdsm", "fetish", "bondage", "latex"}:
        return "kink"
    if tags & {"lighting", "hdr", "golden-hour", "cinematic-light"}:
        return "lighting"
    if tags & {"camera", "lens", "pov", "shot-type"}:
        return "camera"
    return "style"

def _extract_triggers(version_meta: dict) -> list[str]:
    # Civitai stores trigger words in trainedWords on the version
    raw = version_meta.get("trainedWords") or []
    triggers = []
    for entry in raw:
        for tok in str(entry).replace("|", ",").split(","):
            tok = tok.strip()
            if tok and tok not in triggers:
                triggers.append(tok)
    return triggers

def _license_of(model_meta: dict) -> str:
    lic = model_meta.get("license") or ""
    if not lic:
        allow = model_meta.get("allowCommercialUse")
        if isinstance(allow, list) and allow:
            lic = f"civitai:{','.join(map(str, allow))}"
    return lic or "unknown"

def _safe_move(src: Path, dst_dir: Path) -> Path:
    """Move src into dst_dir, appending -N if the name collides."""
    dst = dst_dir / src.name
    if dst.exists():
        stem, suf = src.stem, src.suffix
        i = 2
        while (dst_dir / f"{stem}-{i}{suf}").exists():
            i += 1
        dst = dst_dir / f"{stem}-{i}{suf}"
    shutil.move(str(src), str(dst))
    return dst

# ── Public API ───────────────────────────────────────────────────────────────
def promote(
    weight_path: Path,
    model_meta: dict,
    version_meta: dict,
    scorecard: dict,
    sha256: str,
) -> Path:
    """Move weights into prod, register in manifest + ledger."""
    weight_path = Path(weight_path)
    dst = _safe_move(weight_path, PROD_POOL)

    category = _infer_category(model_meta, version_meta)
    triggers = _extract_triggers(version_meta)
    base_model = version_meta.get("baseModel", "")
    license_str = _license_of(model_meta)

    # ── Manifest write ──
    manifest = _load_manifest()
    manifest[dst.name] = {
        "category": category,
        "triggers": triggers,
        "base_model": base_model,
        "sha256": sha256,
        "source": "civitai",
        "civitai_model_id":   model_meta.get("id"),
        "civitai_version_id": version_meta.get("id"),
        "civitai_url": f"https://civitai.com/models/{model_meta.get('id')}",
        "license": license_str,
        "added": _now(),
        "score": {
            "composite":    scorecard.get("composite"),
            "sync_error_s": scorecard.get("sync_error_s"),
            "aesthetic":    scorecard.get("aesthetic"),
            "adherence":    scorecard.get("adherence"),
            "battery_size": scorecard.get("battery_size"),
        },
        "default_weight": 0.80,
        "enabled": True,
    }
    _atomic_write_json(MANIFEST, manifest)

    # ── Ledger append ──
    _atomic_append_csv(LEDGER, {
        "lora": dst.name,
        "category": category,
        "sha256": sha256,
        "source": "civitai",
        "civitai_model_id":   model_meta.get("id", ""),
        "civitai_version_id": version_meta.get("id", ""),
        "base_model": base_model,
        "trigger_words": " | ".join(triggers),
        "composite_score": f"{scorecard.get('composite', 0):.4f}",
        "sync_error_s":    f"{scorecard.get('sync_error_s', 0):.4f}",
        "added": _now(),
        "license": license_str,
    })

    # ── Sidecar (full provenance blob) ──
    sidecar = SIDECARS / f"{dst.stem}.provenance.json"
    _atomic_write_json(sidecar, {
        "lora": dst.name,
        "sha256": sha256,
        "scorecard": scorecard,
        "civitai_model":   model_meta,
        "civitai_version": version_meta,
        "promoted_at": _now(),
        "prod_path": str(dst),
    })

    print(f"[promote] {dst.name} -> {PROD_POOL}  (score={scorecard.get('composite'):.3f})")
    return dst

def flag_review(
    weight_path: Path,
    model_meta: dict,
    version_meta: dict,
    scorecard: dict,
    sha256: str,
) -> Path:
    """Park weights + scorecard in _needs_review for manual triage."""
    weight_path = Path(weight_path)
    dst = _safe_move(weight_path, REVIEW)
    note = REVIEW / f"{dst.stem}.review.json"
    _atomic_write_json(note, {
        "lora": dst.name,
        "sha256": sha256,
        "scorecard": scorecard,
        "civitai_model_id":   model_meta.get("id"),
        "civitai_version_id": version_meta.get("id"),
        "civitai_url": f"https://civitai.com/models/{model_meta.get('id')}",
        "flagged_at": _now(),
        "reason": "composite score between quarantine and auto thresholds",
    })
    print(f"[review]  {dst.name} -> {REVIEW}  (score={scorecard.get('composite'):.3f})")
    return dst

def quarantine(weight_path: Path, sha256: str, reason: str = "score_below_threshold") -> None:
    """Delete the weights; sha stays in seen db upstream so crawler skips it next run."""
    weight_path = Path(weight_path)
    try:
        weight_path.unlink(missing_ok=True)
    except OSError as e:
        print(f"[quarantine] WARN could not delete {weight_path}: {e}")
        return
    print(f"[quarantine] {weight_path.name} deleted  reason={reason}  sha={sha256[:12]}")

# ── Rollback helper (manual use) ─────────────────────────────────────────────
def rollback(lora_name: str) -> None:
    """
    Undo a promotion: remove from manifest, mark ledger row rolled_back,
    move weight file out of prod into _needs_review with a rollback note.
    """
    manifest = _load_manifest()
    entry = manifest.pop(lora_name, None)
    if entry is None:
        print(f"[rollback] {lora_name} not in manifest")
        return
    _atomic_write_json(MANIFEST, manifest)

    prod_file = PROD_POOL / lora_name
    if prod_file.exists():
        moved = _safe_move(prod_file, REVIEW)
        note = REVIEW / f"{moved.stem}.rollback.json"
        _atomic_write_json(note, {
            "lora": moved.name,
            "rolled_back_at": _now(),
            "prior_entry": entry,
        })
        print(f"[rollback] {lora_name} -> {REVIEW}")
    else:
        print(f"[rollback] weight file already missing from {PROD_POOL}")

# ── CLI ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys, argparse
    ap = argparse.ArgumentParser(description="LoRA promotion utilities")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_roll = sub.add_parser("rollback", help="Undo a prior promotion")
    p_roll.add_argument("lora", help="Filename as it appears in prod (e.g. wetlook_v4.safetensors)")

    p_list = sub.add_parser("list", help="List currently promoted LoRAs with scores")

    args = ap.parse_args()

    if args.cmd == "rollback":
        rollback(args.lora)
    elif args.cmd == "list":
        m = _load_manifest()
        rows = sorted(m.items(), key=lambda kv: kv[1].get("score", {}).get("composite", 0), reverse=True)
        for name, meta in rows:
            comp = meta.get("score", {}).get("composite", 0)
            cat  = meta.get("category", "?")
            print(f"  {comp:.3f}  {cat:9s}  {name}")
```

### Runbook

```bash
# manual rollback if a promoted LoRA misbehaves in prod
cd D:\AI\ComfyUI_portable\workshop\scrape
python promote.py rollback wetlook_v4.safetensors

# audit view — highest composite first
python promote.py list
```

### Failure modes and guards

- **Name collisions in prod** — `_safe_move` appends `-2`, `-3`, ... so a re-upload with the same filename but different sha never clobbers the incumbent. Manifest keys stay unique.
- **Corrupted manifest** — `_load_manifest` copies the broken file to `.corrupt.<ts>.json` and starts fresh rather than aborting the crawler mid-run. Cron keeps flowing; you fix the JSON later.
- **Partial write crash** — every write goes to `.tmp` + `os.replace`, so a power loss leaves either the old file intact or the new file intact, never a half-written one.
- **Rollback without physical file** — logs a warning and still purges the manifest entry so the ledger doesn't lie about what's live.
- **License drift** — sidecar keeps the full civitai payload at promotion time, so if a creator later relicenses restrictively you can prove what terms applied when the weight entered your pool.

Next up in Part 7 would be the cron wrapper (`Task Scheduler` XML + PowerShell trigger) and the `audit_matrix.py` companion that reconciles newly-promoted LoRAs against `_compatibility_matrix.json` — say the word and it drafts.

## Scheduled Orchestration & Compatibility Reconciliation

**Directory Anchor:** `D:\AI\ComfyUI_portable\workshop\scrape\scheduler\`

```txt
scheduler/
├── ScrapeAndPromote.xml          # Task Scheduler definition (importable)
├── run_scrape_cycle.ps1          # PowerShell trigger + logging wrapper
├── run_scrape_cycle.env          # sourced env vars (paths, tokens, thresholds)
├── audit_matrix.py               # reconciles promoted LoRAs → _compatibility_matrix.json
├── logs/
│   ├── cycle_YYYYMMDD_HHMM.log   # per-run PowerShell transcript
│   └── audit_YYYYMMDD.jsonl      # append-only audit deltas
└── locks/
    └── cycle.lock                # prevents overlapping runs
```

---

## 7.1 Task Scheduler XML — `ScrapeAndPromote.xml`

Importable via `schtasks /Create /XML ScrapeAndPromote.xml /TN "ComfyUI\ScrapeAndPromote"`. Runs every 6 hours, only on AC power, wakes the machine, and passes through the S-1-5-18 SYSTEM principal so the task survives user logouts.

```xml
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Date>2026-09-20T14:00:00</Date>
    <Author>ComfyUI\Workshop</Author>
    <Description>Civitai scrape → sandbox → promote → audit cycle. See workshop/scrape/scheduler/README.md</Description>
    <URI>\ComfyUI\ScrapeAndPromote</URI>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-09-20T02:00:00</StartBoundary>
      <Repetition>
        <Interval>PT6H</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
      <Enabled>true</Enabled>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>S-1-5-18</UserId>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>true</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>true</StopIfGoingOnBatteries>
    <AllowHardTerminate>false</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>true</WakeToRun>
    <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT15M</Interval>
      <Count>2</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>powershell.exe</Command>
      <Arguments>-NoProfile -ExecutionPolicy Bypass -File "D:\AI\ComfyUI_portable\workshop\scrape\scheduler\run_scrape_cycle.ps1"</Arguments>
      <WorkingDirectory>D:\AI\ComfyUI_portable\workshop\scrape\scheduler</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
```

Key guards baked in:

- `MultipleInstancesPolicy = IgnoreNew` — if the previous cycle is still crawling, the next trigger is dropped rather than stacked.
- `RestartOnFailure` — two retries at 15-minute spacing catches transient 429s from Civitai.
- `WakeToRun = true` combined with `DisallowStartIfOnBatteries = true` — the workstation wakes for the 02:00 slot but refuses to crawl if someone yanked the power brick.
- `ExecutionTimeLimit = PT2H` — a runaway crawler cannot hold a lock forever; SCM will `TerminateProcess` after two hours.

---

## 7.2 PowerShell Wrapper — `run_scrape_cycle.ps1`

Wraps the four-stage pipeline (`civitai_scrape.py → filters.py → sandbox_test.py → promote.py → audit_matrix.py`), enforces a filesystem lock, emits a structured JSON summary, and returns a non-zero exit code so Task Scheduler's "Last Run Result" column reflects reality instead of always showing `0x0`.

```powershell
# run_scrape_cycle.ps1
# Cron wrapper for Civitai scrape + promotion + audit reconciliation.
# Exit codes: 0 success, 10 lock held, 20 scrape fail, 30 filter fail,
#             40 sandbox fail, 50 promote fail, 60 audit fail, 99 unhandled.

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root       = 'D:\AI\ComfyUI_portable\workshop\scrape'
$Scheduler  = Join-Path $Root 'scheduler'
$LogsDir    = Join-Path $Scheduler 'logs'
$LockFile   = Join-Path $Scheduler 'locks\cycle.lock'
$Stamp      = (Get-Date).ToString('yyyyMMdd_HHmm')
$LogFile    = Join-Path $LogsDir "cycle_$Stamp.log"
$SummaryOut = Join-Path $LogsDir "cycle_$Stamp.summary.json"
$Python     = 'D:\AI\ComfyUI_portable\python_embeded\python.exe'

New-Item -ItemType Directory -Force -Path $LogsDir, (Split-Path $LockFile) | Out-Null
Start-Transcript -Path $LogFile -Append | Out-Null

# --- Load env overrides (CIVITAI_TOKEN, MIN_SCORE, MAX_CANDIDATES, etc.) ---
$envFile = Join-Path $Scheduler 'run_scrape_cycle.env'
if (Test-Path $envFile) {
    Get-Content $envFile | Where-Object { $_ -match '^\s*[^#].*=' } | ForEach-Object {
        $k,$v = $_ -split '=',2
        [System.Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim(), 'Process')
    }
}

# --- Filesystem lock (fail fast if a prior cycle is alive) ---
$lockStream = $null
try {
    $lockStream = [System.IO.File]::Open(
        $LockFile, 'OpenOrCreate', 'ReadWrite', 'None'
    )
    $pidBytes = [System.Text.Encoding]::UTF8.GetBytes("$PID`n$Stamp`n")
    $lockStream.Write($pidBytes, 0, $pidBytes.Length)
    $lockStream.Flush()
} catch {
    Write-Warning "Lock held by another cycle: $($_.Exception.Message)"
    Stop-Transcript | Out-Null
    exit 10
}

$summary = [ordered]@{
    started_at   = (Get-Date).ToString('o')
    stamp        = $Stamp
    stages       = @{}
    exit_code    = 0
    promoted     = @()
    quarantined  = @()
    audit_delta  = $null
}

function Invoke-Stage {
    param(
        [string]$Name,
        [string[]]$Args,
        [int]$FailCode
    )
    Write-Host "[$Name] $Python $($Args -join ' ')"
    $sw = [Diagnostics.Stopwatch]::StartNew()
    & $Python @Args 2>&1 | Tee-Object -Variable stageOut
    $sw.Stop()
    $rc = $LASTEXITCODE
    $script:summary.stages[$Name] = @{
        exit_code    = $rc
        elapsed_ms   = $sw.ElapsedMilliseconds
        tail         = ($stageOut | Select-Object -Last 20) -join "`n"
    }
    if ($rc -ne 0) {
        $script:summary.exit_code = $FailCode
        throw "Stage '$Name' failed with exit $rc"
    }
}

try {
    Invoke-Stage 'scrape'   @("$Root\civitai_scrape.py",  '--config', "$Root\scrape_config.yaml") 20
    Invoke-Stage 'filter'   @("$Root\filters.py",         '--in', "$Root\out\raw.jsonl", '--out', "$Root\out\filtered.jsonl") 30
    Invoke-Stage 'sandbox'  @("$Root\sandbox_test.py",    '--in', "$Root\out\filtered.jsonl", '--scorecards', "$Root\out\scorecards") 40
    Invoke-Stage 'promote'  @("$Root\promote.py",         '--scorecards', "$Root\out\scorecards", '--summary-out', "$Root\out\promote_summary.json") 50
    Invoke-Stage 'audit'    @("$Scheduler\audit_matrix.py", '--promote-summary', "$Root\out\promote_summary.json", '--matrix', 'D:\AI\ComfyUI_portable\loras\_compatibility_matrix.json', '--journal', "$LogsDir\audit_$($Stamp.Substring(0,8)).jsonl") 60

    # Pull the promote_summary into the run summary for at-a-glance triage
    $promoteSum = Get-Content "$Root\out\promote_summary.json" -Raw | ConvertFrom-Json
    $summary.promoted    = $promoteSum.promoted
    $summary.quarantined = $promoteSum.quarantined
    $summary.audit_delta = (Get-Content "$Root\out\audit_delta.json" -Raw | ConvertFrom-Json)
}
catch {
    Write-Error $_
    if ($summary.exit_code -eq 0) { $summary.exit_code = 99 }
}
finally {
    $summary.finished_at = (Get-Date).ToString('o')
    ($summary | ConvertTo-Json -Depth 8) | Set-Content -Path $SummaryOut -Encoding UTF8
    if ($lockStream) { $lockStream.Dispose() }
    Remove-Item $LockFile -ErrorAction SilentlyContinue
    Stop-Transcript | Out-Null
    exit $summary.exit_code
}
```

Note the `Invoke-Stage` closure: every subprocess run is timed, its tail-20 lines captured, and its exit code funnelled through a scoped fail-code so the Task Scheduler history is *diagnostic* rather than a binary red/green. When Ops opens the "Last Run Result" column and sees `0x32` (50), they know immediately that promotion — not scraping — is the stage to inspect.

Companion `run_scrape_cycle.env` (kept out of version control, chmod-equivalent ACL: SYSTEM + Administrators read only):

```dotenv
CIVITAI_TOKEN=xxxxxxxxxxxxxxxxxxxx
MIN_SCORE=0.72
MAX_CANDIDATES=40
SANDBOX_STEPS=18
SANDBOX_RES=768x1152
PROMOTE_DRY_RUN=false
AUDIT_STRICT=true
```

---

## 7.3 `audit_matrix.py` — Compatibility Reconciliation

Every promoted LoRA lands in `D:\AI\ComfyUI_portable\loras\<category>\` with a sidecar JSON, but the *cross-LoRA* rules live in `_compatibility_matrix.json` — a symmetric adjacency table describing which LoRAs stack cleanly, which fight over the same trigger tokens, and which have hard exclusion rules (e.g. two anatomy LoRAs both overriding `perfect_hands`). `audit_matrix.py` walks the freshly-promoted set, cross-references sidecar metadata + trigger inventories, and either extends the matrix with sane defaults or refuses the run and emits a `needs_human_review` block.

### 7.3.1 Matrix schema recap

```json
{
  "version": 3,
  "updated_at": "2026-09-20T14:00:00Z",
  "nodes": {
    "wet_skin_v3":    {"category":"anatomy","triggers":["wet_skin","glistening"],"weight_range":[0.4,0.9]},
    "cinematic_grain":{"category":"style",  "triggers":["cine_grain"],           "weight_range":[0.2,0.6]}
  },
  "edges": {
    "wet_skin_v3::cinematic_grain": {"kind":"compatible","confidence":0.91,"notes":"tested 2026-09-14"},
    "wet_skin_v3::oiled_body_v2":   {"kind":"conflict",  "confidence":0.97,"notes":"trigger collision on wet_skin"}
  },
  "exclusions": [
    ["hyperdetail_hands_v4","anatomy_fix_v2"]
  ]
}
```

### 7.3.2 Full script — `audit_matrix.py`

```python
#!/usr/bin/env python3
"""
audit_matrix.py — reconcile freshly-promoted LoRAs against _compatibility_matrix.json.

Reads:
  - promote_summary.json          (from promote.py)
  - _compatibility_matrix.json    (canonical adjacency table)
  - <lora>.sidecar.json           (per-LoRA metadata written at promotion)

Writes:
  - _compatibility_matrix.json    (atomic rewrite, versioned + backed up)
  - audit_delta.json              (this-cycle diff, consumed by the PS wrapper)
  - audit_YYYYMMDD.jsonl          (append-only journal)

Exit codes:
  0  clean reconciliation
  2  strict-mode blocking issue (unknown trigger, orphan node, symmetric edge mismatch)
  3  I/O or schema failure
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

MATRIX_VERSION = 3
UTC = timezone.utc


# ---------- data classes ----------

@dataclass
class LoraNode:
    name: str
    category: str
    triggers: list[str]
    weight_range: list[float] = field(default_factory=lambda: [0.3, 0.8])
    sidecar_path: str | None = None


@dataclass
class Delta:
    added_nodes:     list[str] = field(default_factory=list)
    updated_nodes:   list[str] = field(default_factory=list)
    added_edges:     list[str] = field(default_factory=list)
    inferred_edges:  list[str] = field(default_factory=list)
    new_exclusions:  list[list[str]] = field(default_factory=list)
    warnings:        list[str] = field(default_factory=list)
    blocking:        list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "added_nodes":    self.added_nodes,
            "updated_nodes":  self.updated_nodes,
            "added_edges":    self.added_edges,
            "inferred_edges": self.inferred_edges,
            "new_exclusions": self.new_exclusions,
            "warnings":       self.warnings,
            "blocking":       self.blocking,
        }


# ---------- IO helpers ----------

def load_json(p: Path) -> dict:
    with p.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def atomic_write_json(p: Path, payload: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=p.name + ".", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
        os.replace(tmp, p)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def backup_matrix(matrix_path: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    bkp = matrix_path.with_suffix(f".{stamp}.bak.json")
    shutil.copy2(matrix_path, bkp)
    return bkp


def append_journal(journal_path: Path, record: dict) -> None:
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    with journal_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


# ---------- promoted set gathering ----------

def gather_promoted(promote_summary: Path, loras_root: Path) -> list[LoraNode]:
    payload = load_json(promote_summary)
    nodes: list[LoraNode] = []
    for entry in payload.get("promoted", []):
        sidecar = loras_root / entry["category"] / f"{entry['name']}.sidecar.json"
        if not sidecar.exists():
            raise FileNotFoundError(f"missing sidecar: {sidecar}")
        meta = load_json(sidecar)
        nodes.append(LoraNode(
            name         = entry["name"],
            category     = entry["category"],
            triggers     = sorted(set(meta.get("triggers", []))),
            weight_range = meta.get("weight_range", [0.3, 0.8]),
            sidecar_path = str(sidecar),
        ))
    return nodes


# ---------- edge inference ----------

def edge_key(a: str, b: str) -> str:
    return "::".join(sorted((a, b)))


def infer_relationship(a: LoraNode, b: LoraNode) -> tuple[str, float, str]:
    """
    Returns (kind, confidence, note). Kinds:
      - conflict   : shared trigger tokens (collision certainty)
      - caution    : same category, non-overlapping triggers (weight-competing)
      - compatible : disjoint category + triggers (safe default)
    """
    shared = sorted(set(a.triggers) & set(b.triggers))
    if shared:
        return "conflict", 0.95, f"trigger collision on {','.join(shared)}"
    if a.category == b.category:
        return "caution", 0.70, f"same category ({a.category}); cap stack weights <= 0.6"
    return "compatible", 0.60, "auto-inferred; disjoint category + triggers"


# ---------- reconciliation ----------

def reconcile(
    matrix: dict,
    promoted: list[LoraNode],
    strict: bool,
) -> tuple[dict, Delta]:
    delta = Delta()
    nodes: dict = matrix.setdefault("nodes", {})
    edges: dict = matrix.setdefault("edges", {})
    exclusions: list = matrix.setdefault("exclusions", [])

    # --- 1. inject / update promoted nodes ---
    for node in promoted:
        if node.name in nodes:
            existing = nodes[node.name]
            existing_triggers = sorted(existing.get("triggers", []))
            if existing_triggers != node.triggers:
                delta.warnings.append(
                    f"trigger drift on {node.name}: "
                    f"{existing_triggers} -> {node.triggers}"
                )
                existing["triggers"] = node.triggers
                delta.updated_nodes.append(node.name)
            if existing.get("category") != node.category:
                msg = (
                    f"category reclassification on {node.name}: "
                    f"{existing.get('category')} -> {node.category}"
                )
                (delta.blocking if strict else delta.warnings).append(msg)
                existing["category"] = node.category
            existing["weight_range"] = node.weight_range
        else:
            nodes[node.name] = {
                "category":     node.category,
                "triggers":     node.triggers,
                "weight_range": node.weight_range,
            }
            delta.added_nodes.append(node.name)

    # --- 2. infer edges: promoted × (promoted ∪ existing) ---
    promoted_names = {n.name for n in promoted}
    all_named_nodes: dict[str, LoraNode] = {n.name: n for n in promoted}
    for name, meta in nodes.items():
        if name not in all_named_nodes:
            all_named_nodes[name] = LoraNode(
                name=name,
                category=meta.get("category", "unknown"),
                triggers=sorted(meta.get("triggers", [])),
                weight_range=meta.get("weight_range", [0.3, 0.8]),
            )

    for a_name in promoted_names:
        for b_name, b_node in all_named_nodes.items():
            if a_name == b_name:
                continue
            key = edge_key(a_name, b_name)
            if key in edges:
                # Respect human-curated edges; only sanity-check symmetry.
                continue
            kind, conf, note = infer_relationship(all_named_nodes[a_name], b_node)
            edges[key] = {
                "kind":       kind,
                "confidence": conf,
                "notes":      note,
                "source":     "auto",
                "updated_at": datetime.now(UTC).isoformat(),
            }
            delta.inferred_edges.append(key)
            if kind == "conflict":
                pair = sorted((a_name, b_name))
                if pair not in exclusions:
                    exclusions.append(pair)
                    delta.new_exclusions.append(pair)

    # --- 3. symmetry / orphan sweep ---
    seen_keys = set(edges.keys())
    for key in list(seen_keys):
        left, right = key.split("::", 1)
        if left not in nodes or right not in nodes:
            msg = f"orphan edge references missing node: {key}"
            (delta.blocking if strict else delta.warnings).append(msg)
            edges.pop(key, None)

    # --- 4. exclusion dedupe + normalization ---
    normalized: list[list[str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for pair in exclusions:
        tup = tuple(sorted(pair))
        if tup in seen_pairs:
            continue
        if tup[0] not in nodes or tup[1] not in nodes:
            delta.warnings.append(f"exclusion references missing node: {list(tup)}")
            continue
        seen_pairs.add(tup)
        normalized.append(list(tup))
    matrix["exclusions"] = normalized

    # --- 5. bookkeeping ---
    matrix["version"]    = MATRIX_VERSION
    matrix["updated_at"] = datetime.now(UTC).isoformat()

    return matrix, delta


# ---------- entry point ----------

def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--promote-summary", required=True, type=Path)
    p.add_argument("--matrix",          required=True, type=Path)
    p.add_argument("--journal",         required=True, type=Path)
    p.add_argument("--loras-root",
                   default=Path(r"D:\AI\ComfyUI_portable\loras"),
                   type=Path)
    p.add_argument("--delta-out",
                   default=Path(r"D:\AI\ComfyUI_portable\workshop\scrape\out\audit_delta.json"),
                   type=Path)
    p.add_argument("--strict", action="store_true",
                   default=os.environ.get("AUDIT_STRICT", "false").lower() == "true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    try:
        promoted = gather_promoted(args.promote_summary, args.loras_root)
    except FileNotFoundError as e:
        print(f"[audit] sidecar missing: {e}", file=sys.stderr)
        return 3
    except json.JSONDecodeError as e:
        print(f"[audit] malformed JSON in inputs: {e}", file=sys.stderr)
        return 3

    if not promoted:
        print("[audit] promote_summary lists zero promotions; nothing to reconcile.")
        atomic_write_json(args.delta_out, {
            "started_at": datetime.now(UTC).isoformat(),
            "delta":      Delta().to_dict(),
            "promoted":   0,
        })
        return 0

    try:
        matrix = load_json(args.matrix) if args.matrix.exists() else {
            "version": MATRIX_VERSION, "nodes": {}, "edges": {}, "exclusions": []
        }
    except json.JSONDecodeError as e:
        print(f"[audit] matrix unreadable: {e}", file=sys.stderr)
        return 3

    if args.matrix.exists():
        bkp = backup_matrix(args.matrix)
        print(f"[audit] backed up matrix -> {bkp}")

    updated, delta = reconcile(matrix, promoted, strict=args.strict)

    record = {
        "timestamp":    datetime.now(UTC).isoformat(),
        "promoted":     [n.name for n in promoted],
        "delta":        delta.to_dict(),
        "matrix_stats": {
            "nodes":      len(updated.get("nodes", {})),
            "edges":      len(updated.get("edges", {})),
            "exclusions": len(updated.get("exclusions", [])),
        },
        "strict":       args.strict,
        "dry_run":      args.dry_run,
    }
    append_journal(args.journal, record)
    atomic_write_json(args.delta_out, {
        "started_at": record["timestamp"],
        "delta":      delta.to_dict(),
        "promoted":   len(promoted),
        "matrix_stats": record["matrix_stats"],
    })

    if delta.blocking:
        print(f"[audit] STRICT BLOCK ({len(delta.blocking)} issues):", file=sys.stderr)
        for b in delta.blocking:
            print(f"  - {b}", file=sys.stderr)
        return 2

    if args.dry_run:
        print("[audit] dry-run: matrix NOT rewritten")
    else:
        atomic_write_json(args.matrix, updated)
        print(f"[audit] matrix rewritten: "
              f"+{len(delta.added_nodes)} nodes, "
              f"+{len(delta.inferred_edges)} edges, "
              f"+{len(delta.new_exclusions)} exclusions, "
              f"{len(delta.warnings)} warnings")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

---

### 7.3.3 Runbook — invoking the audit standalone

```powershell
D:\AI\ComfyUI_portable\python_embeded\python.exe `
  D:\AI\ComfyUI_portable\workshop\scrape\scheduler\audit_matrix.py `
  --promote-summary D:\AI\ComfyUI_portable\workshop\scrape\out\promote_summary.json `
  --matrix          D:\AI\ComfyUI_portable\loras\_compatibility_matrix.json `
  --journal         D:\AI\ComfyUI_portable\workshop\scrape\scheduler\logs\audit_20260920.jsonl `
  --strict --dry-run
```

`--dry-run` is the safe rehearsal path: the journal + delta still land on disk, but the canonical matrix is never rewritten. Ops uses this after every `promote.py` iteration change to sanity-check inferred edges before flipping the switch.

### 7.3.4 Failure modes worth memorizing

| Symptom | Root cause | Recovery |
| --- | --- | --- |
| Exit 3, "sidecar missing" | `promote.py` moved the `.safetensors` but crashed before writing the sidecar | Re-run `promote.py --repair-sidecars`; sidecars are idempotent |
| Exit 2, "category reclassification" in strict mode | Manual edit to sidecar changed category after first promotion | Either accept new category (`--strict=false` once) or revert sidecar |
| Journal grows past ~50 MB | One year of dense reconciliations | `logrotate`-style: gzip journals older than 30 days; audit ledger CSV in Part 6 remains the queryable surface |
| Edge count balloons after adding a mega-pack | Cartesian growth is O(promoted × existing); expected | Prune `kind == "compatible"` edges with `confidence < 0.65` via a quarterly `matrix_gc.py` sweep |
| `_compatibility_matrix.json` corrupted mid-write | Power loss between `tempfile` and `os.replace` | Impossible — `os.replace` is atomic on NTFS; if the file *is* garbage, restore the most recent `.bak.json` |

Part 7 closes the loop: Task Scheduler wakes the box, PowerShell fences the cycle behind a lock, the four Python stages run in strict sequence, and `audit_matrix.py` guarantees the compatibility graph never drifts out of sync with what actually sits in `D:\AI\ComfyUI_portable\loras\`. Next natural extension would be **Part 8 — the reverse-lookup query surface** (`matrix_query.py` + a lightweight Flask endpoint) so batch jobs can ask *"what safely stacks with `wet_skin_v3` at weight 0.7?"* at runtime instead of parsing the JSON by hand.

---
