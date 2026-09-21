# Face-Retention Audit Subsystem

## Directory anchor

```txt
.AI\ComfyUI_portable\workshop\audit\face_retention\
├── audit_clip.py                  # main scorer, one clip in → one scorecard out
├── audit_batch.py                 # walks a batch directory, scores every clip, writes ledger
├── retention_config.yaml          # thresholds, weights, sampling policy
├── retention_ledger.csv           # append-only per-clip results
├── retention_summary.jsonl        # per-batch rollups
├── scorecards\                    # one JSON per clip, human-readable
│   └── {batch_id}\{clip_id}.json
└── rejects\                       # symlinks (or copies) of clips that failed hard gate
    └── {batch_id}\
```

The subsystem is deliberately decoupled from the render pipeline. It reads finished MP4s off disk, never touches ComfyUI state, and writes append-only ledgers so a rerun never corrupts prior data.

---

## Scoring model — what "retention" actually means

Four independent signals, weighted, then collapsed to a single **Retention Score (RS)** in `[0.0, 1.0]`:

| Signal | Weight | What it measures | Extractor |
| --- | --- | --- | --- |
| **ArcFace similarity to subject bank** | 0.45 | Does the face across sampled frames still match the subject's identity_manifest mean embedding? | InsightFace ArcFace (buffalo_l) |
| **Intra-clip face stability** | 0.25 | Do the sampled frames match *each other* — i.e. face doesn't morph mid-clip | ArcFace pairwise cosine |
| **Landmark geometry drift** | 0.20 | Do eye/nose/mouth relative positions stay consistent (catches subtle warp the embedding smooths over) | MediaPipe FaceMesh 468-pt |
| **Detection continuity** | 0.10 | Fraction of sampled frames where a face was detected at all | InsightFace det |

Final:

```txt
RS = 0.45 * arc_subject + 0.25 * arc_intra + 0.20 * geom_stability + 0.10 * detect_rate
```

### Gates (per-clip verdict)

| Verdict | Rule | Action |
| --- | --- | --- |
| `pass` | `RS >= 0.82` **AND** `arc_subject >= 0.78` **AND** `detect_rate >= 0.90` | keep, log to ledger |
| `soft_fail` | `0.70 <= RS < 0.82` | keep but flag, log with reason string |
| `hard_fail` | `RS < 0.70` **OR** `arc_subject < 0.65` **OR** `detect_rate < 0.75` | move to `rejects/`, log with reason string, do not include in downstream compilations |

The two AND-clauses on `pass` are non-negotiable: a clip can score 0.83 overall and still fail if the *subject-match* component alone is weak, because a stable-but-wrong face is worse than a jittery-but-right one.

---

## Sampling policy (`retention_config.yaml`)

```yaml
# .AI\ComfyUI_portable\workshop\audit\face_retention\retention_config.yaml

sampling:
  # frames pulled per clip for scoring
  mode: "uniform_plus_endpoints"      # options: uniform, uniform_plus_endpoints, dense_head_tail
  n_frames: 9                          # for a 48fps 2s clip → ~every 12th frame
  always_include: ["first", "last", "middle"]
  min_face_size_px: 96                 # skip frames where largest face bbox is smaller

weights:
  arc_subject: 0.45
  arc_intra:   0.25
  geom_stability: 0.20
  detect_rate: 0.10

thresholds:
  pass:
    rs_min: 0.82
    arc_subject_min: 0.78
    detect_rate_min: 0.90
  soft_fail:
    rs_min: 0.70
  hard_fail:
    rs_max: 0.70
    arc_subject_max: 0.65
    detect_rate_max: 0.75

models:
  arcface_pack: "buffalo_l"
  arcface_ctx_id: 0                    # CUDA device
  mediapipe_static_image: false        # video mode = temporal smoothing
  mediapipe_max_faces: 1

paths:
  subjects_root: "D:/AI/ComfyUI_portable/workshop/face_bank/subjects"
  ledger: "D:/AI/ComfyUI_portable/workshop/audit/face_retention/retention_ledger.csv"
  summary: "D:/AI/ComfyUI_portable/workshop/audit/face_retention/retention_summary.jsonl"
  scorecards: "D:/AI/ComfyUI_portable/workshop/audit/face_retention/scorecards"
  rejects: "D:/AI/ComfyUI_portable/workshop/audit/face_retention/rejects"

behavior:
  move_hard_fails: true                # if false, only symlink/log, don't relocate
  overwrite_scorecards: false          # rerun-safe by default
```

---

## `audit_clip.py` — single-clip scorer (full script)

```python
# .AI\ComfyUI_portable\workshop\audit\face_retention\audit_clip.py

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import torch
import yaml
from insightface.app import FaceAnalysis
import mediapipe as mp


CONFIG_PATH = Path(__file__).parent / "retention_config.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_subject_bank(subjects_root: Path, subject_id: str):
    subj_dir = subjects_root / subject_id
    emb_path = subj_dir / "embeddings.pt"
    if not emb_path.exists():
        raise FileNotFoundError(f"no embeddings.pt for subject '{subject_id}' at {emb_path}")
    bank = torch.load(emb_path, map_location="cpu")
    mean = bank["arcface_mean"].numpy().astype(np.float32)
    mean = mean / (np.linalg.norm(mean) + 1e-9)
    return mean


def sample_frame_indices(total_frames: int, cfg: dict) -> list:
    n = cfg["sampling"]["n_frames"]
    if total_frames <= n:
        return list(range(total_frames))
    step = total_frames / n
    idxs = [int(i * step) for i in range(n)]
    if "first" in cfg["sampling"]["always_include"]:
        idxs[0] = 0
    if "last" in cfg["sampling"]["always_include"]:
        idxs[-1] = total_frames - 1
    if "middle" in cfg["sampling"]["always_include"]:
        idxs[len(idxs) // 2] = total_frames // 2
    return sorted(set(idxs))


def extract_frames(video_path: Path, cfg: dict):
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video {video_path}")
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    idxs = sample_frame_indices(total, cfg)

    frames = []
    for i in idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, frame = cap.read()
        if not ok:
            continue
        frames.append((i, frame))
    cap.release()
    return frames, total


def score_arcface(face_app, frames, subject_mean, min_face_px):
    per_frame_emb = []
    per_frame_detected = []
    for idx, frame in frames:
        faces = face_app.get(frame)
        if not faces:
            per_frame_detected.append(False)
            continue
        # pick largest face
        faces.sort(key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]), reverse=True)
        top = faces[0]
        w = top.bbox[2] - top.bbox[0]
        h = top.bbox[3] - top.bbox[1]
        if min(w, h) < min_face_px:
            per_frame_detected.append(False)
            continue
        emb = top.embedding.astype(np.float32)
        emb = emb / (np.linalg.norm(emb) + 1e-9)
        per_frame_emb.append(emb)
        per_frame_detected.append(True)

    detect_rate = sum(per_frame_detected) / max(len(frames), 1)

    if len(per_frame_emb) < 2:
        return {
            "arc_subject": 0.0,
            "arc_intra": 0.0,
            "detect_rate": detect_rate,
            "n_valid": len(per_frame_emb),
        }

    embs = np.stack(per_frame_emb)
    arc_subject = float(np.mean(embs @ subject_mean))

    sim_matrix = embs @ embs.T
    n = sim_matrix.shape[0]
    triu = sim_matrix[np.triu_indices(n, k=1)]
    arc_intra = float(np.mean(triu))

    return {
        "arc_subject": arc_subject,
        "arc_intra": arc_intra,
        "detect_rate": detect_rate,
        "n_valid": len(per_frame_emb),
    }


def score_geometry(frames, cfg):
    mp_face_mesh = mp.solutions.face_mesh
    facemesh = mp_face_mesh.FaceMesh(
        static_image_mode=cfg["models"]["mediapipe_static_image"],
        max_num_faces=cfg["models"]["mediapipe_max_faces"],
        refine_landmarks=True,
        min_detection_confidence=0.5,
    )

    # key indices: left eye outer/inner, right eye outer/inner, nose tip, mouth L/R corner
    key_idx = [33, 133, 362, 263, 1, 61, 291]
    per_frame_geom = []

    for _, frame in frames:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        res = facemesh.process(rgb)
        if not res.multi_face_landmarks:
            continue
        lm = res.multi_face_landmarks[0].landmark
        pts = np.array([[lm[i].x, lm[i].y] for i in key_idx], dtype=np.float32)
        # normalize by inter-ocular distance so scale/position don't confound
        iod = np.linalg.norm(pts[0] - pts[3]) + 1e-9
        pts_norm = (pts - pts.mean(axis=0)) / iod
        per_frame_geom.append(pts_norm.flatten())

    facemesh.close()

    if len(per_frame_geom) < 2:
        return {"geom_stability": 0.0, "n_geom": len(per_frame_geom)}

    G = np.stack(per_frame_geom)
    ref = G.mean(axis=0)
    dists = np.linalg.norm(G - ref, axis=1)
    # convert mean drift (in IOD units) into a 0..1 stability score
    # drift of 0.05 IOD = perfect (1.0), drift of 0.30 IOD = zero (0.0)
    mean_drift = float(np.mean(dists))
    stability = float(np.clip(1.0 - (mean_drift - 0.05) / 0.25, 0.0, 1.0))

    return {
        "geom_stability": stability,
        "geom_mean_drift_iod": mean_drift,
        "n_geom": len(per_frame_geom),
    }


def compute_rs(arc_scores, geom_scores, weights):
    rs = (
        weights["arc_subject"] * arc_scores["arc_subject"]
        + weights["arc_intra"] * arc_scores["arc_intra"]
        + weights["geom_stability"] * geom_scores["geom_stability"]
        + weights["detect_rate"] * arc_scores["detect_rate"]
    )
    return float(np.clip(rs, 0.0, 1.0))


def verdict_for(rs, arc_subject, detect_rate, cfg):
    t = cfg["thresholds"]
    if rs < t["hard_fail"]["rs_max"] or arc_subject < t["hard_fail"]["arc_subject_max"] or detect_rate < t["hard_fail"]["detect_rate_max"]:
        return "hard_fail"
    if rs >= t["pass"]["rs_min"] and arc_subject >= t["pass"]["arc_subject_min"] and detect_rate >= t["pass"]["detect_rate_min"]:
        return "pass"
    return "soft_fail"


def reason_string(rs, arc_scores, geom_scores, cfg):
    reasons = []
    t = cfg["thresholds"]
    if arc_scores["arc_subject"] < t["pass"]["arc_subject_min"]:
        reasons.append(f"subject_match_low({arc_scores['arc_subject']:.3f})")
    if arc_scores["arc_intra"] < 0.80:
        reasons.append(f"intra_drift({arc_scores['arc_intra']:.3f})")
    if geom_scores["geom_stability"] < 0.70:
        reasons.append(f"geom_warp({geom_scores['geom_stability']:.3f})")
    if arc_scores["detect_rate"] < t["pass"]["detect_rate_min"]:
        reasons.append(f"detect_rate_low({arc_scores['detect_rate']:.2f})")
    if rs < t["pass"]["rs_min"]:
        reasons.append(f"rs_below_pass({rs:.3f})")
    return ";".join(reasons) if reasons else "ok"


def audit_one_clip(video_path: Path, subject_id: str, batch_id: str, cfg: dict, face_app) -> dict:
    subjects_root = Path(cfg["paths"]["subjects_root"])
    subject_mean = load_subject_bank(subjects_root, subject_id)

    frames, total_frames = extract_frames(video_path, cfg)
    if not frames:
        raise RuntimeError(f"no frames sampled from {video_path}")

    arc_scores = score_arcface(face_app, frames, subject_mean, cfg["sampling"]["min_face_size_px"])
    geom_scores = score_geometry(frames, cfg)
    rs = compute_rs(arc_scores, geom_scores, cfg["weights"])
    verdict = verdict_for(rs, arc_scores["arc_subject"], arc_scores["detect_rate"], cfg)
    reason = reason_string(rs, arc_scores, geom_scores, cfg)

    scorecard = {
        "clip_path": str(video_path),
        "clip_id": video_path.stem,
        "batch_id": batch_id,
        "subject_id": subject_id,
        "timestamp": datetime.now().isoformat(),
        "total_frames": total_frames,
        "sampled_frames": [i for i, _ in frames],
        "retention_score": round(rs, 4),
        "components": {
            "arc_subject": round(arc_scores["arc_subject"], 4),
            "arc_intra": round(arc_scores["arc_intra"], 4),
            "geom_stability": round(geom_scores["geom_stability"], 4),
            "detect_rate": round(arc_scores["detect_rate"], 4),
        },
        "diagnostics": {
            "n_valid_arcface": arc_scores["n_valid"],
            "n_valid_geom": geom_scores["n_geom"],
            "geom_mean_drift_iod": round(geom_scores.get("geom_mean_drift_iod", 0.0), 4),
        },
        "verdict": verdict,
        "reason": reason,
    }
    return scorecard


def write_scorecard(scorecard: dict, cfg: dict):
    out_dir = Path(cfg["paths"]["scorecards"]) / scorecard["batch_id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{scorecard['clip_id']}.json"
    if out_path.exists() and not cfg["behavior"]["overwrite_scorecards"]:
        return out_path
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(scorecard, f, indent=2)
    return out_path


def main():
    ap = argparse.ArgumentParser(description="Score a single clip for face retention.")
    ap.add_argument("--clip", required=True, type=Path)
    ap.add_argument("--subject", required=True, type=str)
    ap.add_argument("--batch", required=True, type=str, help="batch_id for grouping")
    args = ap.parse_args()

    cfg = load_config()
    face_app = FaceAnalysis(name=cfg["models"]["arcface_pack"])
    face_app.prepare(ctx_id=cfg["models"]["arcface_ctx_id"], det_size=(640, 640))

    scorecard = audit_one_clip(args.clip, args.subject, args.batch, cfg, face_app)
    path = write_scorecard(scorecard, cfg)
    print(json.dumps(scorecard, indent=2))
    print(f"[ok] scorecard: {path}")


if __name__ == "__main__":
    main()
```

---

## `audit_batch.py` — batch walker + ledger writer (full script)

```python
# .AI\ComfyUI_portable\workshop\audit\face_retention\audit_batch.py

import argparse
import csv
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

import yaml
from insightface.app import FaceAnalysis

from audit_clip import (
    load_config,
    audit_one_clip,
    write_scorecard,
)


LEDGER_HEADERS = [
    "timestamp", "batch_id", "clip_id", "subject_id", "verdict",
    "retention_score", "arc_subject", "arc_intra", "geom_stability",
    "detect_rate", "reason", "clip_path",
]


def ensure_ledger(ledger_path: Path):
    if ledger_path.exists():
        return
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with open(ledger_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(LEDGER_HEADERS)


def append_ledger(ledger_path: Path, scorecard: dict):
    row = [
        scorecard["timestamp"],
        scorecard["batch_id"],
        scorecard["clip_id"],
        scorecard["subject_id"],
        scorecard["verdict"],
        scorecard["retention_score"],
        scorecard["components"]["arc_subject"],
        scorecard["components"]["arc_intra"],
        scorecard["components"]["geom_stability"],
        scorecard["components"]["detect_rate"],
        scorecard["reason"],
        scorecard["clip_path"],
    ]
    with open(ledger_path, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(row)


def relocate_hard_fail(clip_path: Path, batch_id: str, cfg: dict):
    rej_dir = Path(cfg["paths"]["rejects"]) / batch_id
    rej_dir.mkdir(parents=True, exist_ok=True)
    dst = rej_dir / clip_path.name
    if cfg["behavior"]["move_hard_fails"]:
        shutil.move(str(clip_path), str(dst))
    return dst


def summarize_batch(batch_id: str, results: list, cfg: dict):
    total = len(results)
    counts = {"pass": 0, "soft_fail": 0, "hard_fail": 0}
    rs_values = []
    for r in results:
        counts[r["verdict"]] += 1
        rs_values.append(r["retention_score"])

    summary = {
        "batch_id": batch_id,
        "timestamp": datetime.now().isoformat(),
        "total_clips": total,
        "pass": counts["pass"],
        "soft_fail": counts["soft_fail"],
        "hard_fail": counts["hard_fail"],
        "pass_rate": round(counts["pass"] / total, 4) if total else 0.0,
        "rs_mean": round(sum(rs_values) / total, 4) if total else 0.0,
        "rs_min": round(min(rs_values), 4) if rs_values else 0.0,
        "rs_max": round(max(rs_values), 4) if rs_values else 0.0,
    }

    summary_path = Path(cfg["paths"]["summary"])
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with open(summary_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(summary
# GENERATION CUT OFF HERE
```

## Part 2 — Face-retention audit: batch runner

**File:** `.AI\ComfyUI_portable\workshop\identity\audit_batch.py`

The exact earlier `audit_clip.py` interface isn’t visible here, so this runner uses an **explicit adapter contract** rather than assuming its argument names. If your clip auditor differs, update only `build_command()` and `read_result()` below.

### 2.1 — Expected clip-auditor interface

```powershell
python audit_clip.py `
  --clip ".renders\clip_001.mp4" `
  --subject "subject_001" `
  --config "retention_config.yaml" `
  --output ".audits\clip_001.json"
```

Expected output:

```json
{
  "score": 87.4,
  "decision": "pass",
  "metrics": {
    "identity_similarity": 0.83,
    "face_detection_rate": 0.98
  }
}
```

Contract:

- `score`: finite number from `0` through `100`.
- `decision`: `pass`, `review`, or `fail`.
- Exit code `0` means the audit executed successfully—even if its quality decision is `fail`.
- Nonzero exit codes indicate execution errors.
- Metrics remain in the per-clip report; the batch runner does not reinterpret the scoring formula.

### 2.2 — Complete `audit_batch.py`

Uses only Python’s standard library. Jobs run **sequentially by default**, avoiding multiple face-analysis processes competing for your 5090’s VRAM.

```python
#!/usr/bin/env python3
"""Run face-retention audits from an explicit JSON job manifest."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


DECISIONS = {"pass", "review", "fail"}

CSV_FIELDS = [
    "job_id",
    "clip",
    "subject",
    "status",
    "decision",
    "score",
    "duration_seconds",
    "report",
    "log",
    "error",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_text(path: Path, text: str) -> None:
    """Replace a file atomically; temporary file stays on the same volume."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temp_path = Path(temp_name)

    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def write_json(path: Path, value: object) -> None:
    atomic_text(
        path,
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)
        + "\n",
    )


def resolve_path(value: str, base: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def load_jobs(manifest: Path) -> list[dict]:
    data = json.loads(manifest.read_text(encoding="utf-8-sig"))

    if not isinstance(data, dict):
        raise ValueError("Manifest must be a JSON object.")

    raw_jobs = data.get("jobs")
    if not isinstance(raw_jobs, list) or not raw_jobs:
        raise ValueError("Manifest requires a nonempty 'jobs' list.")

    jobs = []
    seen = set()

    for index, entry in enumerate(raw_jobs, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"Job {index}: expected an object.")

        clip_value = entry.get("clip")
        subject = entry.get("subject")

        if not isinstance(clip_value, str) or not clip_value.strip():
            raise ValueError(f"Job {index}: missing clip path.")
        if not isinstance(subject, str) or not subject.strip():
            raise ValueError(f"Job {index}: missing subject.")

        subject = subject.strip()
        clip = resolve_path(clip_value, manifest.parent)

        # Windows normcase prevents duplicate jobs from path case changes.
        key = (os.path.normcase(str(clip)), subject)
        if key in seen:
            raise ValueError(
                f"Job {index}: duplicate clip/subject pair: {clip}"
            )
        seen.add(key)

        digest = hashlib.sha256(
            json.dumps(key, ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:16]

        jobs.append({
            "job_id": f"{index:05d}_{digest}",
            "clip": str(clip),
            "subject": subject,
        })

    return jobs


def build_command(
    python: Path,
    auditor: Path,
    config: Path,
    job: dict,
    report: Path,
) -> list[str]:
    """Adapter: change argument names here if audit_clip.py differs."""
    return [
        str(python),
        str(auditor),
        "--clip", job["clip"],
        "--subject", job["subject"],
        "--config", str(config),
        "--output", str(report),
    ]


def read_result(report: Path) -> tuple[float, str]:
    """Adapter: change field mappings here if audit_clip.py differs."""
    data = json.loads(report.read_text(encoding="utf-8-sig"))

    if not isinstance(data, dict):
        raise ValueError("Clip report must be a JSON object.")

    score = data.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise ValueError("Report score must be numeric.")
    score = float(score)

    if not math.isfinite(score) or not 0 <= score <= 100:
        raise ValueError("Report score must be finite and within 0–100.")

    decision = data.get("decision")
    if not isinstance(decision, str) or decision not in DECISIONS:
        raise ValueError("Report decision must be pass, review, or fail.")

    return score, decision


def run_job(
    job: dict,
    python: Path,
    auditor: Path,
    config: Path,
    run_dir: Path,
    timeout: float,
) -> dict:
    started = time.monotonic()
    report = run_dir / "reports" / f"{job['job_id']}.json"
    pending = report.with_name(f"{report.stem}.pending.json")
    log_path = run_dir / "logs" / f"{job['job_id']}.log"

    row = {
        **job,
        "status": "error",
        "decision": "",
        "score": None,
        "duration_seconds": 0,
        "report": "",
        "log": str(log_path),
        "error": "",
    }

    try:
        if not Path(job["clip"]).is_file():
            raise FileNotFoundError(f"Clip not found: {job['clip']}")

        command = build_command(
            python, auditor, config, job, pending
        )

        # Stream output to disk instead of holding long logs in memory.
        with log_path.open("w", encoding="utf-8") as log:
            log.write(
                "Command: " + json.dumps(command, ensure_ascii=False) + "\n"
            )
            log.flush()

            completed = subprocess.run(
                command,
                cwd=str(auditor.parent),
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
                shell=False,
            )

        if completed.returncode != 0:
            raise RuntimeError(
                f"Clip auditor exited with code {completed.returncode}; "
                "see log."
            )

        if not pending.is_file():
            raise RuntimeError("Clip auditor did not write its JSON report.")

        score, decision = read_result(pending)

        # Publish only a validated report.
        os.replace(pending, report)
        row.update({
            "status": "ok",
            "decision": decision,
            "score": score,
            "report": str(report),
        })

    except subprocess.TimeoutExpired:
        row["error"] = f"Clip audit exceeded {timeout:g} seconds."
    except Exception as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        # Invalid or incomplete output is retained as *.pending.json.
        row["duration_seconds"] = round(time.monotonic() - started, 3)
        if row["error"]:
            with log_path.open("a", encoding="utf-8") as log:
                log.write("\nBatch error: " + row["error"] + "\n")

    return row


def save_progress(
    run_dir: Path,
    metadata: dict,
    rows: list[dict],
    state: str,
) -> dict:
    counts = {
        "pass": 0,
        "review": 0,
        "fail": 0,
        "error": 0,
    }

    for row in rows:
        bucket = row["decision"] if row["status"] == "ok" else "error"
        counts[bucket] += 1

    scores = [
        row["score"] for row in rows if row["status"] == "ok"
    ]

    summary = {
        **metadata,
        "updated_at": utc_now(),
        "state": state,
        "completed_jobs": len(rows),
        "remaining_jobs": metadata["total_jobs"] - len(rows),
        "counts": counts,
        # Descriptive only: this average is not a promotion gate.
        "mean_score": round(sum(scores) / len(scores), 3) if scores else None,
        "results": rows,
    }

    write_json(run_dir / "batch_summary.json", summary)

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    atomic_text(run_dir / "batch_ledger.csv", buffer.getvalue())

    return summary


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--config", type=Path, default=root / "retention_config.yaml"
    )
    parser.add_argument(
        "--auditor", type=Path, default=root / "audit_clip.py"
    )
    parser.add_argument(
        "--python", type=Path, default=Path(sys.executable)
    )
    parser.add_argument(
        "--out", type=Path, default=root / "audits" / "batches"
    )
    parser.add_argument(
        "--timeout", type=float, default=1800,
        help="Maximum seconds per clip audit; default: 1800.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not math.isfinite(args.timeout) or args.timeout <= 0:
        print("ERROR: --timeout must be positive and finite.", file=sys.stderr)
        return 2

    try:
        manifest = args.manifest.resolve()
        config = args.config.resolve()
        auditor = args.auditor.resolve()
        python = args.python.resolve()

        for label, path in [
            ("manifest", manifest),
            ("config", config),
            ("auditor", auditor),
            ("Python executable", python),
        ]:
            if not path.is_file():
                raise FileNotFoundError(f"{label}: {path}")

        jobs = load_jobs(manifest)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "_" + uuid.uuid4().hex[:8]
    )
    run_dir = args.out.resolve() / run_id
    (run_dir / "reports").mkdir(parents=True)
    (run_dir / "logs").mkdir()

    # Snapshot actual inputs for diagnosis. No cross-run cache is used.
    write_json(run_dir / "jobs_snapshot.json", {"jobs": jobs})
    config_snapshot = run_dir / "retention_config.snapshot.yaml"
    config_snapshot.write_bytes(config.read_bytes())

    metadata = {
        "run_id": run_id,
        "started_at": utc_now(),
        "manifest": str(manifest),
        "config": str(config),
        "config_sha256": hashlib.sha256(
            config_snapshot.read_bytes()
        ).hexdigest(),
        "auditor": str(auditor),
        "auditor_sha256": hashlib.sha256(auditor.read_bytes()).hexdigest(),
        "python": str(python),
        "total_jobs": len(jobs),
    }

    rows = []
    save_progress(run_dir, metadata, rows, "running")
    print(f"Batch output: {run_dir}")

    try:
        for index, job in enumerate(jobs, start=1):
            row = run_job(
                job, python, auditor, config, run_dir, args.timeout
            )
            rows.append(row)
            save_progress(run_dir, metadata, rows, "running")

            outcome = (
                f"{row['decision']} ({row['score']:.2f})"
                if row["status"] == "ok"
                else f"error: {row['error']}"
            )
            print(f"[{index}/{len(jobs)}] {job['job_id']}: {outcome}",
                  flush=True)

    except KeyboardInterrupt:
        save_progress(run_dir, metadata, rows, "interrupted")
        print("\nInterrupted; completed results are preserved.")
        return 130

    summary = save_progress(run_dir, metadata, rows, "complete")
    print(json.dumps(summary["counts"], indent=2))

    if summary["counts"]["error"]:
        return 2
    if summary["counts"]["fail"] or summary["counts"]["review"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

### 2.3 — Batch manifest

**File:** `identity\audit_jobs.json`

Relative clip paths resolve against the **manifest’s directory**, not the shell’s working directory.

```json
{
  "jobs": [
    {
      "clip": "../batch/outputs/clip_001.mp4",
      "subject": "subject_001"
    },
    {
      "clip": "../batch/outputs/clip_002.mp4",
      "subject": "subject_001"
    },
    {
      "clip": "../batch/outputs/clip_003.mp4",
      "subject": "subject_002"
    }
  ]
}
```

For multi-person clips, separate subject entries are supported. **Your clip auditor must actually associate detections with the requested subject**; merely choosing the largest face is not sufficient.

### 2.4 — Windows runbook

Use the Python environment containing your face-audit dependencies:

```powershell
Set-Location ".AI\ComfyUI_portable\workshop\identity"

$Python = ".AI\ComfyUI_portable\python_embeded\python.exe"

& $Python .\audit_batch.py `
    --manifest .\audit_jobs.json `
    --config .\retention_config.yaml `
    --out .\audits\batches `
    --timeout 1800

$AuditExit = $LASTEXITCODE
Write-Host "Audit exit code: $AuditExit"
```

| Exit | Meaning | Pipeline action |
| --- | --- | --- |
| `0` | Every job passed | Eligible for the next gate |
| `1` | At least one review or quality failure | Inspect per-clip decisions |
| `2` | Configuration or execution error | Repair and rerun |
| `130` | Interrupted | Completed reports preserved |

**Do not promote an entire batch using its mean score.** Read each result and require `status == "ok"` and `decision == "pass"`.

### 2.5 — Output and failure modes

```text
identity\audits\batches\<run_id>\
├── jobs_snapshot.json
├── retention_config.snapshot.yaml
├── batch_summary.json
├── batch_ledger.csv
├── reports\
│   └── <job_id>.json
└── logs\
    └── <job_id>.log
```

| Failure | Behavior |
| --- | --- |
| Missing clip | Records error; continues other jobs |
| Auditor crash or VRAM exhaustion | Captures log; records error |
| Timeout | Stops the direct auditor process; continues |
| Missing or malformed report | Records error; does not publish a valid report |
| Review or failed quality gate | Preserves score and decision; continues |
| Repeated run | Creates a separate directory; never reuses stale reports |

**Operational limits:** keep the config and face bank unchanged during a batch. The timeout controls the direct subprocess, not an arbitrary tree of worker processes. The summary and CSV are individually atomic, not a two-file transaction; treat `batch_summary.json` as authoritative.

This completes the **batch orchestration layer**. Face detection, identity association, temporal scoring, and quality thresholds remain the responsibility of `audit_clip.py`.
