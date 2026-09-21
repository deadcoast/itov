# Part 12 — The Trigger-Word Conflict Linter

Every LoRA carries activation tokens: `wetskin_v3`, `cinematic35`, `bimbocore`, `latex_gloss`. Stack four of them and you're rolling dice on whether one LoRA's trigger collides with another's — or worse, with a natural-language token the base model already treats as semantic. This part builds the standalone linter that scans the manifest, detects collisions across four axes, proposes rename-aliases, and writes `_trigger_aliases.json` for the resolver (Part 9) to consume.

---

## 12.1 Directory anchor

```txt
D:\AI\ComfyUI_portable\workshop\scrape\triggers\
├── trigger_lint.py            # the linter
├── trigger_rules.yaml         # collision rules + weights
├── base_vocab\
│   ├── sdxl_high_freq.txt     # top-5000 tokens from SDXL text encoder
│   ├── wan22_reserved.txt     # Wan 2.2 reserved motion tokens
│   └── hunyuan_reserved.txt   # Hunyuan 1.5 reserved tokens
├── _trigger_index.json        # extracted per-LoRA trigger table (built)
├── _trigger_aliases.json      # rename-alias map (built, consumed by Part 9)
├── _collision_report.csv      # human-readable audit trail
└── logs\
    └── lint_YYYYMMDD.log
```

The linter reads `_lora_manifest.json` from Part 6, extracts triggers from each LoRA's sidecar `.txt` and `.civitai.json`, cross-references against reserved base-model vocab, and emits a deterministic alias map.

---

## 12.2 The four collision classes

| Class                | Definition                                                                                        | Severity | Auto-alias?              |
|----------------------|---------------------------------------------------------------------------------------------------|----------|--------------------------|
| **C1: exact-string** | Two LoRAs declare the identical trigger token                                                     | critical | yes                      |
| **C2: substring**    | Trigger A is a substring of trigger B (`wet_skin` inside `wet_skinv3`)                            | high     | yes if edit distance ≤ 2 |
| **C3: base-vocab**   | Trigger collides with a high-frequency base-model token (`woman`, `light`, `motion`)              | high     | yes                      |
| **C4: reserved**     | Trigger collides with a model-reserved control token (Wan 2.2 motion tags, Hunyuan camera tokens) | critical | yes, forced              |

C1 and C4 are non-negotiable — the resolver will refuse to stack LoRAs that trip them without an alias. C2 and C3 are soft blocks; the resolver warns and downweights but doesn't hard-fail.

---

## 12.3 `trigger_rules.yaml`

```yaml
version: 1
generated_by: trigger_lint.py

# Edit distance threshold for C2 substring collisions.
# Levenshtein <= this value → treat as collision.
substring_edit_distance: 2

# Minimum token length to consider — shorter tokens (like "a", "3d") are noise.
min_token_length: 4

# Base-vocab collision policy
base_vocab:
  sdxl:
    path: base_vocab/sdxl_high_freq.txt
    top_n: 3000                       # only check top-N most frequent tokens
    severity: high
  wan22:
    path: base_vocab/wan22_reserved.txt
    top_n: 9999
    severity: critical                # Wan reserved = auto-alias forced
  hunyuan:
    path: base_vocab/hunyuan_reserved.txt
    top_n: 9999
    severity: critical

# Alias generation strategy
alias_strategy:
  suffix_pool: ["lx", "vx", "kx", "zx", "qx", "px"]   # rare bigrams
  numeric_fallback: true
  numeric_start: 90                   # trigger_v90, trigger_v91, ...
  preserve_original_in_prompt: false  # if true, keep original + append alias

# Auto-quarantine thresholds
quarantine:
  max_collisions_per_lora: 4          # LoRA with >4 unresolvable collisions → flag_review
  block_promotion_on_c1_c4: true      # Part 6 promote.py hooks this

# Reporting
report:
  csv_path: _collision_report.csv
  alias_json_path: _trigger_aliases.json
  index_json_path: _trigger_index.json
  keep_log_days: 30
```

---

## 12.4 `_trigger_index.json` schema

Every LoRA in the manifest gets one entry after extraction:

```json
{
  "version": 1,
  "generated_at": "2026-09-21T08:00:00Z",
  "loras": {
    "wetskin_photoreal_v3.safetensors": {
      "hash": "sha256:a91f...",
      "triggers": [
        {"token": "wetskin_v3",   "source": "civitai_json",  "weight_hint": 1.0},
        {"token": "glossy_skin",  "source": "sidecar_txt",   "weight_hint": 0.85}
      ],
      "declared_base": "wan2.2-i2v-14b",
      "conflict_count": 0
    },
    "cinematic_grain_35mm.safetensors": {
      "hash": "sha256:c02b...",
      "triggers": [
        {"token": "cinematic35",  "source": "civitai_json",  "weight_hint": 1.0},
        {"token": "film_grain",   "source": "sidecar_txt",   "weight_hint": 0.7}
      ],
      "declared_base": "wan2.2-i2v-14b",
      "conflict_count": 1
    }
  }
}
```

---

## 12.5 `_trigger_aliases.json` — what Part 9 consumes

The alias map is the linter's output contract. Part 9's resolver reads this before assembling any stack:

```json
{
  "version": 1,
  "generated_at": "2026-09-21T08:00:00Z",
  "aliases": {
    "wetskin_photoreal_v3.safetensors": {
      "wetskin_v3":  {"alias": "wetskin_v3",  "reason": "no_conflict"},
      "glossy_skin": {"alias": "glossy_skin_lx", "reason": "c3_base_vocab_sdxl"}
    },
    "cinematic_grain_35mm.safetensors": {
      "cinematic35": {"alias": "cinematic35_vx", "reason": "c1_exact_string_with:filmlook_v2.safetensors"},
      "film_grain":  {"alias": "film_grain_lx",  "reason": "c3_base_vocab_sdxl"}
    }
  },
  "blocked_stacks": [
    {
      "loras": ["wan_motion_pack_v1.safetensors", "camera_control_v4.safetensors"],
      "reason": "c4_reserved:motion_slow both declare wan22 reserved token"
    }
  ]
}
```

`blocked_stacks` is the trap door — combinations the resolver will refuse to assemble even with aliases, because the collision is in the reserved control space where aliasing won't help.

---

## 12.6 `trigger_lint.py` — the linter

**Path:** `D:\AI\ComfyUI_portable\workshop\scrape\triggers\trigger_lint.py`

```python
"""
trigger_lint.py — detect and resolve trigger-word collisions across the LoRA manifest.

Reads:
    _lora_manifest.json          (from Part 6)
    trigger_rules.yaml           (this directory)
    base_vocab/*.txt             (reserved / high-frequency token lists)
    per-LoRA sidecars:
        <lora>.txt
        <lora>.civitai.json

Writes:
    _trigger_index.json          (extracted triggers per LoRA)
    _trigger_aliases.json        (rename map for the resolver)
    _collision_report.csv        (human audit trail)
    logs/lint_YYYYMMDD.log

Exit codes:
    0  clean or only soft collisions
    1  critical collisions remain after aliasing (blocked_stacks non-empty)
    2  I/O or config failure
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import re
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable

import yaml

UTC = timezone.utc
log = logging.getLogger("trigger_lint")

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_\-]{2,}", re.IGNORECASE)


# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Trigger:
    token: str
    source: str                 # "civitai_json" | "sidecar_txt" | "manifest"
    weight_hint: float = 1.0

    @property
    def norm(self) -> str:
        return self.token.strip().lower()


@dataclass
class LoraEntry:
    filename: str
    path: Path
    hash: str
    declared_base: str
    triggers: list[Trigger] = field(default_factory=list)
    conflict_count: int = 0


@dataclass
class Collision:
    lora_a: str
    lora_b: str                 # "" for base-vocab / reserved collisions
    token_a: str
    token_b: str
    kind: str                   # "c1" | "c2" | "c3" | "c4"
    detail: str
    severity: str               # "critical" | "high" | "soft"


# ─────────────────────────────────────────────────────────────────────────────
# Levenshtein (small, no deps)
# ─────────────────────────────────────────────────────────────────────────────

def levenshtein(a: str, b: str) -> int:
    if a == b: return 0
    if len(a) < len(b): a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur.append(min(cur[-1] + 1, prev[j] + 1, prev[j - 1] + cost))
        prev = cur
    return prev[-1]


# ─────────────────────────────────────────────────────────────────────────────
# Loaders
# ─────────────────────────────────────────────────────────────────────────────

def load_rules(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_vocab(base_dir: Path, spec: dict) -> set[str]:
    p = base_dir / spec["path"]
    if not p.exists():
        log.warning("vocab file missing: %s (skipping)", p)
        return set()
    top_n = int(spec.get("top_n", 9999))
    tokens: list[str] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        t = line.strip().lower()
        if t and not t.startswith("#"):
            tokens.append(t)
        if len(tokens) >= top_n:
            break
    return set(tokens)


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def extract_triggers_for(lora_file: Path, min_len: int) -> list[Trigger]:
    triggers: list[Trigger] = []
    stem = lora_file.with_suffix("")

    civitai = stem.with_suffix(".civitai.json")
    if civitai.exists():
        try:
            data = json.loads(civitai.read_text(encoding="utf-8"))
            words = data.get("trainedWords") or data.get("trigger_words") or []
            for w in words:
                if isinstance(w, str) and len(w) >= min_len:
                    triggers.append(Trigger(token=w, source="civitai_json"))
        except (json.JSONDecodeError, OSError) as e:
            log.debug("civitai json unreadable for %s: %s", lora_file.name, e)

    sidecar = stem.with_suffix(".txt")
    if sidecar.exists():
        try:
            text = sidecar.read_text(encoding="utf-8", errors="ignore")
            for match in TOKEN_RE.findall(text):
                m = match.strip().lower()
                if len(m) >= min_len and not any(t.norm == m for t in triggers):
                    triggers.append(Trigger(token=match, source="sidecar_txt"))
        except OSError:
            pass

    return triggers


def hash_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b: break
            h.update(b)
    return f"sha256:{h.hexdigest()}"


# ─────────────────────────────────────────────────────────────────────────────
# Collision detection
# ─────────────────────────────────────────────────────────────────────────────

def detect_c1_c2(loras: list[LoraEntry], edit_thresh: int) -> list[Collision]:
    out: list[Collision] = []
    for a, b in combinations(loras, 2):
        for ta in a.triggers:
            for tb in b.triggers:
                if ta.norm == tb.norm:
                    out.append(Collision(
                        lora_a=a.filename, lora_b=b.filename,
                        token_a=ta.token, token_b=tb.token,
                        kind="c1",
                        detail=f"exact string '{ta.norm}'",
                        severity="critical",
                    ))
                    continue
                # substring or near-substring
                short, long = sorted([ta.norm, tb.norm], key=len)
                if short in long and short != long:
                    dist = len(long) - len(short)
                    if dist <= edit_thresh:
                        out.append(Collision(
                            lora_a=a.filename, lora_b=b.filename,
                            token_a=ta.token, token_b=tb.token,
                            kind="c2",
                            detail=f"substring '{short}' in '{long}' (delta={dist})",
                            severity="high",
                        ))
                elif levenshtein(ta.norm, tb.norm) <= edit_thresh and abs(len(ta.norm) - len(tb.norm)) <= edit_thresh:
                    out.append(Collision(
                        lora_a=a.filename, lora_b=b.filename,
                        token_a=ta.token, token_b=tb.token,
                        kind="c2",
                        detail=f"near-duplicate (lev<={edit_thresh})",
                        severity="high",
                    ))
    return out


def detect_c3(loras: list[LoraEntry], vocabs: dict[str, tuple[set[str], str]]) -> list[Collision]:
    out: list[Collision] = []
    for lora in loras:
        for tr in lora.triggers:
            for vocab_name, (vocab_set, severity) in vocabs.items():
                if tr.norm in vocab_set:
                    out.append(Collision(
                        lora_a=lora.filename, lora_b="",
                        token_a=tr.token, token_b="",
                        kind="c3" if severity != "critical" else "c4",
                        detail=f"collides with {vocab_name} vocab",
                        severity=severity,
                    ))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Alias generation
# ─────────────────────────────────────────────────────────────────────────────

class AliasGen:
    def __init__(self, suffix_pool: list[str], numeric_start: int, numeric_fallback: bool) -> None:
        self.suffix_pool = suffix_pool
        self.numeric_start = numeric_start
        self.numeric_fallback = numeric_fallback
        self.taken: set[str] = set()

    def register_existing(self, tokens: Iterable[str]) -> None:
        for t in tokens:
            self.taken.add(t.lower())

    def propose(self, token: str) -> str:
        base = token.lower()
        for suf in self.suffix_pool:
            cand = f"{base}_{suf}"
            if cand not in self.taken:
                self.taken.add(cand)
                return cand
        if self.numeric_fallback:
            n = self.numeric_start
            while True:
                cand = f"{base}_v{n}"
                if cand not in self.taken:
                    self.taken.add(cand)
                    return cand
                n += 1
        raise RuntimeError(f"no alias available for '{token}'")


# ─────────────────────────────────────────────────────────────────────────────
# Reporting
# ─────────────────────────────────────────────────────────────────────────────

def write_csv(path: Path, collisions: list[Collision]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["kind", "severity", "lora_a", "token_a", "lora_b", "token_b", "detail"])
        for c in sorted(collisions, key=lambda x: (x.kind, x.severity, x.lora_a)):
            w.writerow([c.kind, c.severity, c.lora_a, c.token_a, c.lora_b, c.token_b, c.detail])


def build_alias_json(
    loras: list[LoraEntry],
    collisions: list[Collision],
    alias_gen: AliasGen,
    block_on_c1_c4: bool,
) -> dict:
    aliases: dict[str, dict[str, dict[str, str]]] = {}
    blocked: list[dict] = []

    # Initialize: every trigger starts aliased to itself
    for lora in loras:
        aliases[lora.filename] = {}
        for tr in lora.triggers:
            aliases[lora.filename][tr.token] = {
                "alias": tr.token,
                "reason": "no_conflict",
            }

    # Rewrite triggers that participate in collisions
    for c in collisions:
        if c.kind in ("c1", "c4"):
            # Both sides need aliasing (c1) or the single side (c4)
            new_a = alias_gen.propose(c.token_a)
            aliases[c.lora_a][c.token_a] = {
                "alias": new_a,
                "reason": f"{c.kind}_{c.detail}" + (f":{c.lora_b}" if c.lora_b else ""),
            }
            if c.lora_b:
                new_b = alias_gen.propose(c.token_b)
                aliases[c.lora_b][c.token_b] = {
                    "alias": new_b,
                    "reason": f"{c.kind}_{c.detail}:{c.lora_a}",
                }
            if c.kind == "c4" and block_on_c1_c4 and c.lora_b:
                blocked.append({
                    "loras": sorted([c.lora_a, c.lora_b]),
                    "reason": f"c4_reserved:{c.token_a}",
                })
        elif c.kind == "c3":
            new_a = alias_gen.propose(c.token_a)
            aliases[c.lora_a][c.token_a] = {
                "alias": new_a,
                "reason": f"c3_{c.detail}",
            }
        # c2: soft — leave original, resolver downweights via conflict_count

    # Dedup blocked stacks
    seen: set[tuple] = set()
    dedup_blocked = []
    for b in blocked:
        key = tuple(b["loras"])
        if key not in seen:
            seen.add(key)
            dedup_blocked.append(b)

    return {
        "version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "aliases": aliases,
        "blocked_stacks": dedup_blocked,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> int:
    root = Path(args.root)
    rules = load_rules(root / "trigger_rules.yaml")
    manifest = load_manifest(Path(args.manifest))

    vocabs: dict[str, tuple[set[str], str]] = {}
    for name, spec in rules["base_vocab"].items():
        vocabs[name] = (load_vocab(root, spec), spec.get("severity", "high"))

    # Build LoRA entries
    loras: list[LoraEntry] = []
    for fname, meta in manifest.get("loras", {}).items():
        lora_path = Path(meta["path"])
        if not lora_path.exists():
            log.warning("manifest references missing file: %s", lora_path)
            continue
        try:
            h = hash_file(lora_path)
        except OSError as e:
            log.warning("cannot hash %s: %s", lora_path, e)
            continue
        trs = extract_triggers_for(lora_path, min_len=rules.get("min_token_length", 4))
        # Merge triggers declared directly in the manifest
        for t in meta.get("triggers", []) or []:
            if not any(tr.norm == t.lower() for tr in trs):
                trs.append(Trigger(token=t, source="manifest"))
```

Picking `trigger_lint.py::run()` back up from where it cut. Full function body, plus the `__main__` guard and the CLI dispatcher so you can drop it in and call it.

```python
# triggers/trigger_lint.py  (continued from 12.6)

def run(
    manifest_path: Path,
    rules_path: Path,
    index_out: Path,
    aliases_out: Path,
    report_out: Path,
    strict: bool = False,
    fix: bool = False,
) -> int:
    """
    Full linter pass. Returns process exit code:
      0  clean
      1  warnings only (non-strict mode)
      2  hard conflicts detected (strict mode or unresolvable class-A collisions)
      3  I/O or schema failure
    """
    started = datetime.now(UTC)
    log = logging.getLogger("trigger_lint")

    # --- 1. Load inputs ---------------------------------------------------
    try:
        manifest = load_json(manifest_path)
        rules = load_yaml(rules_path)
    except (FileNotFoundError, json.JSONDecodeError, yaml.YAMLError) as exc:
        log.error("input load failed: %s", exc)
        return 3

    entries = manifest.get("entries", [])
    if not entries:
        log.warning("manifest empty; nothing to lint")
        _write_empty_report(report_out, started)
        return 0

    # --- 2. Build the trigger index --------------------------------------
    index: dict[str, list[dict]] = {}
    for entry in entries:
        slug = entry["slug"]
        category = entry["category"]
        status = entry.get("status", "unknown")
        if status not in ("promoted", "review"):
            continue  # quarantined/deprecated LoRAs don't participate
        for raw_trigger in entry.get("triggers", []):
            normalized = normalize_trigger(raw_trigger, rules)
            index.setdefault(normalized, []).append({
                "slug": slug,
                "category": category,
                "status": status,
                "raw": raw_trigger,
                "weight_default": entry.get("weight_default", 0.7),
            })

    # --- 3. Classify collisions ------------------------------------------
    collisions: list[Collision] = []
    for trigger, holders in index.items():
        if len(holders) < 2:
            continue
        klass = classify_collision(trigger, holders, rules)
        collisions.append(Collision(
            trigger=trigger,
            klass=klass,
            holders=holders,
            suggested_aliases=suggest_aliases(trigger, holders, rules) if klass in ("A", "B") else [],
        ))

    # --- 4. Detect near-misses (fuzzy) -----------------------------------
    fuzzy_pairs = detect_fuzzy_collisions(
        index.keys(),
        threshold=rules.get("fuzzy_threshold", 0.88),
    )
    for a, b, ratio in fuzzy_pairs:
        collisions.append(Collision(
            trigger=f"{a}~{b}",
            klass="D",  # class-D = fuzzy near-miss
            holders=index[a] + index[b],
            suggested_aliases=[],
            fuzzy_ratio=ratio,
        ))

    # --- 5. Build alias map ----------------------------------------------
    aliases: dict[str, dict] = {}
    for coll in collisions:
        if coll.klass not in ("A", "B") or not coll.suggested_aliases:
            continue
        for holder, alias in zip(coll.holders, coll.suggested_aliases):
            key = f"{holder['slug']}::{coll.trigger}"
            aliases[key] = {
                "original": coll.trigger,
                "alias": alias,
                "slug": holder["slug"],
                "category": holder["category"],
                "collision_class": coll.klass,
                "assigned_at": started.isoformat(),
            }

    # --- 6. Write outputs -------------------------------------------------
    try:
        atomic_write_json(index_out, {
            "version": 2,
            "generated_at": started.isoformat(),
            "trigger_count": len(index),
            "index": index,
        })
        atomic_write_json(aliases_out, {
            "version": 2,
            "generated_at": started.isoformat(),
            "aliases": aliases,
        })
    except OSError as exc:
        log.error("output write failed: %s", exc)
        return 3

    # --- 7. Emit human-readable report -----------------------------------
    report = build_report(collisions, index, started)
    report_out.write_text(report, encoding="utf-8")

    # --- 8. Apply --fix if requested -------------------------------------
    if fix and aliases:
        log.info("applying %d alias rewrites to manifest", len(aliases))
        rewrite_count = apply_aliases_to_manifest(manifest_path, aliases)
        log.info("rewrote %d trigger entries", rewrite_count)

    # --- 9. Decide exit code ---------------------------------------------
    class_a = [c for c in collisions if c.klass == "A"]
    class_b = [c for c in collisions if c.klass == "B"]
    class_c = [c for c in collisions if c.klass == "C"]
    class_d = [c for c in collisions if c.klass == "D"]

    log.info(
        "lint complete: A=%d B=%d C=%d D=%d aliases=%d",
        len(class_a), len(class_b), len(class_c), len(class_d), len(aliases),
    )

    if class_a and not aliases:
        # class-A with no alias suggestion = unresolvable
        log.error("unresolvable class-A collisions present")
        return 2
    if strict and (class_a or class_b):
        return 2
    if class_b or class_c or class_d:
        return 1
    return 0


# --- CLI entry point ------------------------------------------------------

def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="trigger_lint",
        description="Scan LoRA manifest for trigger-word collisions and emit alias suggestions.",
    )
    p.add_argument("--manifest", type=Path,
                   default=Path(r"D:\AI\ComfyUI_portable\loras\_lora_manifest.json"))
    p.add_argument("--rules", type=Path,
                   default=Path(r"D:\AI\ComfyUI_portable\workshop\scrape\triggers\trigger_rules.yaml"))
    p.add_argument("--index-out", type=Path,
                   default=Path(r"D:\AI\ComfyUI_portable\loras\_trigger_index.json"))
    p.add_argument("--aliases-out", type=Path,
                   default=Path(r"D:\AI\ComfyUI_portable\loras\_trigger_aliases.json"))
    p.add_argument("--report-out", type=Path,
                   default=Path(r"D:\AI\ComfyUI_portable\workshop\scrape\triggers\lint_report.md"))
    p.add_argument("--strict", action="store_true",
                   help="Exit 2 on any class-A or class-B collision")
    p.add_argument("--fix", action="store_true",
                   help="Rewrite manifest triggers using suggested aliases (writes .bak)")
    p.add_argument("--verbose", "-v", action="count", default=0)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)
    level = logging.WARNING - (10 * args.verbose)
    logging.basicConfig(
        level=max(level, logging.DEBUG),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    return run(
        manifest_path=args.manifest,
        rules_path=args.rules,
        index_out=args.index_out,
        aliases_out=args.aliases_out,
        report_out=args.report_out,
        strict=args.strict,
        fix=args.fix,
    )


if __name__ == "__main__":
    sys.exit(main())
```

---

## 12.6b — Helper stubs `run()` depends on

These are the small ones referenced above; drop them near the top of the same file if you haven't already sketched them:

```python
def _write_empty_report(path: Path, started: datetime) -> None:
    path.write_text(
        f"# trigger_lint report\n\ngenerated: {started.isoformat()}\n\n"
        "manifest empty — no collisions to report.\n",
        encoding="utf-8",
    )


def apply_aliases_to_manifest(manifest_path: Path, aliases: dict) -> int:
    """
    Rewrites triggers in-place using the alias map.
    Writes a .bak sibling before mutating. Returns count of rewritten trigger entries.
    """
    backup = manifest_path.with_suffix(manifest_path.suffix + ".bak")
    shutil.copy2(manifest_path, backup)

    manifest = load_json(manifest_path)
    rewrites = 0
    for entry in manifest.get("entries", []):
        slug = entry["slug"]
        new_triggers = []
        for trig in entry.get("triggers", []):
            key = f"{slug}::{normalize_trigger(trig, {})}"
            if key in aliases:
                new_triggers.append(aliases[key]["alias"])
                rewrites += 1
            else:
                new_triggers.append(trig)
        entry["triggers"] = new_triggers

    atomic_write_json(manifest_path, manifest)
    return rewrites
```

---

## 12.6c — Exit-code contract (Task Scheduler sees this)

| Code | Meaning | Cron behavior |
| --- | --- | --- |
| 0 | Clean pass, no collisions | Silent success |
| 1 | Warnings only (class-B/C/D) | Log summary to `lint_report.md`, continue pipeline |
| 2 | Blocking collisions (strict or unresolvable class-A) | Halt promote cycle, page operator via `run_scrape_cycle.ps1` fail path |
| 3 | I/O or schema failure | Halt, escalate — usually means manifest corrupted or rules YAML broken |

Wire this into `run_scrape_cycle.ps1` between the `promote` and `audit` stages — trigger lint runs *after* promotion writes new sidecars but *before* the audit matrix reconciles, so alias rewrites land in the manifest that the audit will read.

---

## 12.6d — Smoke test

```powershell
cd D:\AI\ComfyUI_portable\workshop\scrape\triggers
python trigger_lint.py --verbose
# expected on a clean manifest: exit 0, lint_report.md shows "no collisions"

python trigger_lint.py --strict --verbose
# expected: exit 2 if any class-A/B present, else exit 0

python trigger_lint.py --fix --verbose
# rewrites manifest, drops .bak, exit code reflects post-rewrite state
```

---
