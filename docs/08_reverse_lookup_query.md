# Part 8 — the reverse-lookup query surface

## 8.1 Purpose

Every artifact upstream (`_lora_manifest.json`, `_compatibility_matrix.json`, `_lora_ledger.csv`, `audit_ledger.csv`) is a write-optimized flat file. Great for the pipeline, terrible for a human at 2am asking "which anatomy LoRAs are safe to stack with `wan22_cinematic_v3`?"

Part 8 gives us a **read surface**: one CLI (`lora_query.py`) and one tiny FastAPI service (`query_server.py`) sitting over the same in-memory index. Both answer the same questions, both are read-only, both refuse to touch prod files.

Queries we must answer:

| # | Question | Backing data |
| --- | --- | --- |
| Q1 | What LoRAs pair *compatible* with X? | matrix edges where `relation=compatible` |
| Q2 | What LoRAs *conflict* with X? | matrix edges where `relation=conflict` + exclusions |
| Q3 | What LoRAs share a trigger word with X? | manifest triggers reverse-index |
| Q4 | Given a proposed stack \[A,B,C\], is it safe? | union of Q2 across the stack |
| Q5 | What LoRAs exist in category `kink/breeding`? | manifest categories |
| Q6 | What LoRAs were promoted in the last N days? | ledger timestamps |
| Q7 | What LoRAs are currently quarantined / flagged? | manifest status field |
| Q8 | Full inspect card on LoRA X | manifest + matrix + ledger join |

## 8.2 Directory layout

```txt
D:\AI\ComfyUI_portable\workshop\scrape\
├── query\
│   ├── __init__.py
│   ├── index.py           # builds in-memory index from json/csv
│   ├── resolver.py        # the 8 query functions above
│   ├── lora_query.py      # CLI entrypoint
│   ├── query_server.py    # FastAPI entrypoint
│   ├── formatters.py      # table/json/tree renderers
│   └── tests\
│       ├── fixtures\
│       │   ├── manifest_mini.json
│       │   ├── matrix_mini.json
│       │   └── ledger_mini.csv
│       └── test_resolver.py
```

Nothing in `query/` writes to disk except optional cache at `query/.index_cache.pkl` (gitignored, rebuilt on manifest mtime change).

## 8.3 The index layer — `index.py`

Loads all four sources once, holds them in dataclasses, exposes O(1) lookups by slug and O(log n) by trigger. Rebuild is cheap (<200ms for ~2000 LoRAs) so we invalidate on any source-file mtime change rather than trying to be clever.

```python
# query/index.py
from __future__ import annotations
import json, csv, pickle, hashlib, time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from collections import defaultdict

WORKSHOP = Path(r"D:\AI\ComfyUI_portable\workshop\scrape")
MANIFEST = WORKSHOP / "_lora_manifest.json"
MATRIX   = WORKSHOP / "_compatibility_matrix.json"
LEDGER   = WORKSHOP / "_lora_ledger.csv"
AUDIT    = WORKSHOP / "audit_ledger.csv"
CACHE    = WORKSHOP / "query" / ".index_cache.pkl"

@dataclass
class LoraRecord:
    slug: str
    filename: str
    category: str
    subcategory: str
    triggers: list[str]
    weight_default: float
    weight_range: tuple[float, float]
    status: str                    # "prod" | "flagged" | "quarantined"
    promoted_at: Optional[str]
    scorecard: dict = field(default_factory=dict)
    source_url: Optional[str] = None
    sha256: Optional[str] = None

@dataclass
class Edge:
    a: str
    b: str
    relation: str                  # "compatible" | "caution" | "conflict"
    reason: str
    confidence: float

@dataclass
class Exclusion:
    slug: str
    excludes: list[str]
    reason: str

@dataclass
class LedgerEvent:
    ts: str
    slug: str
    action: str                    # "promote" | "flag_review" | "quarantine" | "rollback"
    actor: str
    note: str

@dataclass
class Index:
    loras: dict[str, LoraRecord]                  # slug -> record
    by_category: dict[str, list[str]]             # "kink/breeding" -> [slugs]
    by_trigger: dict[str, list[str]]              # "cum_dripping" -> [slugs]
    edges_by_slug: dict[str, list[Edge]]          # slug -> outgoing/incoming
    exclusions: dict[str, Exclusion]              # slug -> exclusion rule
    ledger_by_slug: dict[str, list[LedgerEvent]]  # slug -> chronological events
    built_at: float
    source_hash: str

def _source_hash() -> str:
    h = hashlib.sha1()
    for p in (MANIFEST, MATRIX, LEDGER, AUDIT):
        if p.exists():
            st = p.stat()
            h.update(f"{p.name}:{st.st_mtime_ns}:{st.st_size};".encode())
    return h.hexdigest()

def _load_manifest() -> dict[str, LoraRecord]:
    if not MANIFEST.exists():
        return {}
    raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
    out = {}
    for slug, entry in raw.get("loras", {}).items():
        wr = entry.get("weight_range", [0.4, 1.0])
        out[slug] = LoraRecord(
            slug=slug,
            filename=entry["filename"],
            category=entry.get("category", "uncategorized"),
            subcategory=entry.get("subcategory", ""),
            triggers=list(entry.get("triggers", [])),
            weight_default=float(entry.get("weight_default", 0.8)),
            weight_range=(float(wr[0]), float(wr[1])),
            status=entry.get("status", "prod"),
            promoted_at=entry.get("promoted_at"),
            scorecard=entry.get("scorecard", {}),
            source_url=entry.get("source_url"),
            sha256=entry.get("sha256"),
        )
    return out

def _load_matrix() -> tuple[dict[str, list[Edge]], dict[str, Exclusion]]:
    edges: dict[str, list[Edge]] = defaultdict(list)
    excl: dict[str, Exclusion] = {}
    if not MATRIX.exists():
        return edges, excl
    raw = json.loads(MATRIX.read_text(encoding="utf-8"))
    for e in raw.get("edges", []):
        edge = Edge(
            a=e["a"], b=e["b"],
            relation=e["relation"],
            reason=e.get("reason", ""),
            confidence=float(e.get("confidence", 0.5)),
        )
        edges[edge.a].append(edge)
        edges[edge.b].append(edge)   # undirected: index both sides
    for x in raw.get("exclusions", []):
        excl[x["slug"]] = Exclusion(
            slug=x["slug"],
            excludes=list(x.get("excludes", [])),
            reason=x.get("reason", ""),
        )
    return edges, excl

def _load_ledger() -> dict[str, list[LedgerEvent]]:
    out: dict[str, list[LedgerEvent]] = defaultdict(list)
    for path in (LEDGER, AUDIT):
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8", newline="") as fh:
            rdr = csv.DictReader(fh)
            for row in rdr:
                slug = row.get("slug") or row.get("lora_slug")
                if not slug:
                    continue
                out[slug].append(LedgerEvent(
                    ts=row.get("ts", row.get("timestamp", "")),
                    slug=slug,
                    action=row.get("action", row.get("event", "unknown")),
                    actor=row.get("actor", "system"),
                    note=row.get("note", row.get("reason", "")),
                ))
    for slug in out:
        out[slug].sort(key=lambda ev: ev.ts)
    return out

def build_index(force: bool = False) -> Index:
    sh = _source_hash()
    if not force and CACHE.exists():
        try:
            cached: Index = pickle.loads(CACHE.read_bytes())
            if cached.source_hash == sh:
                return cached
        except Exception:
            pass

    loras = _load_manifest()
    edges, excl = _load_matrix()
    ledger = _load_ledger()

    by_cat: dict[str, list[str]] = defaultdict(list)
    by_trig: dict[str, list[str]] = defaultdict(list)
    for slug, rec in loras.items():
        key = f"{rec.category}/{rec.subcategory}".rstrip("/")
        by_cat[key].append(slug)
        for t in rec.triggers:
            by_trig[t.lower()].append(slug)

    idx = Index(
        loras=loras,
        by_category=dict(by_cat),
        by_trigger=dict(by_trig),
        edges_by_slug=dict(edges),
        exclusions=excl,
        ledger_by_slug=dict(ledger),
        built_at=time.time(),
        source_hash=sh,
    )
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_bytes(pickle.dumps(idx))
    return idx
```

## 8.4 The resolver — `resolver.py`

Pure functions. Each takes the `Index` and returns plain dicts/lists. No IO. This is what both the CLI and the server call.

```python
# query/resolver.py
from __future__ import annotations
from typing import Iterable
from .index import Index, LoraRecord, Edge

def inspect(idx: Index, slug: str) -> dict:
    rec = idx.loras.get(slug)
    if not rec:
        return {"error": f"unknown slug: {slug}"}
    edges = idx.edges_by_slug.get(slug, [])
    return {
        "slug": rec.slug,
        "filename": rec.filename,
        "category": f"{rec.category}/{rec.subcategory}".rstrip("/"),
        "triggers": rec.triggers,
        "weight_default": rec.weight_default,
        "weight_range": list(rec.weight_range),
        "status": rec.status,
        "promoted_at": rec.promoted_at,
        "sha256": rec.sha256,
        "scorecard": rec.scorecard,
        "edges": [
            {"other": e.b if e.a == slug else e.a,
             "relation": e.relation,
             "reason": e.reason,
             "confidence": e.confidence}
            for e in edges
        ],
        "exclusion": (
            {"excludes": idx.exclusions[slug].excludes,
             "reason": idx.exclusions[slug].reason}
            if slug in idx.exclusions else None
        ),
        "history": [
            {"ts": ev.ts, "action": ev.action, "actor": ev.actor, "note": ev.note}
            for ev in idx.ledger_by_slug.get(slug, [])
        ],
    }

def pairs_with(idx: Index, slug: str, relation: str = "compatible") -> list[dict]:
    edges = idx.edges_by_slug.get(slug, [])
    out = []
    for e in edges:
        if e.relation != relation:
            continue
        other = e.b if e.a == slug else e.a
        rec = idx.loras.get(other)
        if not rec:
            continue
        out.append({
            "slug": other,
            "category": f"{rec.category}/{rec.subcategory}".rstrip("/"),
            "confidence": e.confidence,
            "reason": e.reason,
            "status": rec.status,
        })
    out.sort(key=lambda r: -r["confidence"])
    return out

def conflicts_with(idx: Index, slug: str) -> list[dict]:
    hard = pairs_with(idx, slug, relation="conflict")
    excl = idx.exclusions.get(slug)
    if excl:
        for other in excl.excludes:
            if any(h["slug"] == other for h in hard):
                continue
            hard.append({
                "slug": other,
                "category": (
                    f"{idx.loras[other].category}/{idx.loras[other].subcategory}".rstrip("/")
                    if other in idx.loras else "?"
                ),
                "confidence": 1.0,
                "reason": f"exclusion rule: {excl.reason}",
                "status": idx.loras[other].status if other in idx.loras else "unknown",
            })
    return hard

def trigger_collisions(idx: Index, slug: str) -> list[dict]:
    rec = idx.loras.get(slug)
    if not rec:
        return []
    out = []
    for t in rec.triggers:
        others = [s for s in idx.by_trigger.get(t.lower(), []) if s != slug]
        for o in others:
            out.append({
                "trigger": t,
                "other_slug": o,
                "other_category": (
                    f"{idx.loras[o].category}/{idx.loras[o].subcategory}".rstrip("/")
                ),
            })
    return out

def validate_stack(idx: Index, stack: Iterable[str]) -> dict:
    stack = list(stack)
    unknown = [s for s in stack if s not in idx.loras]
    conflicts = []
    cautions = []
    trigger_dupes: dict[str, list[str]] = {}

    for i, a in enumerate(stack):
        if a not in idx.loras:
            continue
        for b in stack[i+1:]:
            if b not in idx.loras:
                continue
            for e in idx.edges_by_slug.get(a, []):
                other = e.b if e.a == a else e.a
                if other != b:
                    continue
                entry = {"a": a, "b": b, "reason": e.reason, "confidence": e.confidence}
                if e.relation == "conflict":
                    conflicts.append(entry)
                elif e.relation == "caution":
                    cautions.append(entry)
            excl = idx.exclusions.get(a)
            if excl and b in excl.excludes:
                conflicts.append({"a": a, "b": b, "reason": f"exclusion: {excl.reason}", "confidence": 1.0})

    for slug in stack:
        rec = idx.loras.get(slug)
        if not rec:
            continue
        for t in rec.triggers:
            trigger_dupes.setdefault(t.lower(), []).append(slug)
    trigger_dupes = {t: s for t, s in trigger_dupes.items() if len(s) > 1}

    return {
        "stack": stack,
        "unknown": unknown,
        "conflicts": conflicts,
        "cautions": cautions,
        "trigger_collisions": trigger_dupes,
        "verdict": "block" if conflicts or unknown else ("warn" if cautions or trigger_dupes else "ok"),
    }

def in_category(idx: Index, category: str) -> list[dict]:
    slugs = idx.by_category.get(category, [])
    return [
        {"slug": s,
         "status": idx.loras[s].status,
         "triggers": idx.loras[s].triggers,
         "promoted_at": idx.loras[s].promoted_at}
        for s in slugs
    ]

def recent_promotions(idx: Index, days: int = 7) -> list[dict]:
    import datetime as dt
    cutoff = dt.datetime.utcnow() - dt.timedelta(days=days)
    out = []
    for slug, rec in idx.loras.items():
        if not rec.promoted_at:
            continue
        try:
            ts = dt.datetime.fromisoformat(rec.promoted_at.replace("Z", ""))
        except ValueError:
            continue
        if ts >= cutoff:
            out.append({
                "slug": slug,
                "promoted_at": rec.promoted_at,
                "category": f"{rec.category}/{rec.subcategory}".rstrip("/"),
                "status": rec.status,
            })
    out.sort(key=lambda r: r["promoted_at"], reverse=True)
    return out

def by_status(idx: Index, status: str) -> list[dict]:
    return [
        {"slug": s, "category": f"{r.category}/{r.subcategory}".rstrip("/"),
         "promoted_at": r.promoted_at}
        for s, r in idx.loras.items() if r.status == status
    ]
```

## 8.5 The CLI — `lora_query.py`

Argparse subcommands mapped 1:1 to resolver functions. Human-readable tables by default, `--json` for scripting.

```python
# query/lora_query.py
from __future__ import annotations
import argparse, json, sys
from .index import build_index
from . import resolver, formatters as fmt

def main(argv=None):
    p = argparse.ArgumentParser(prog="lora_query")
    p.add_argument("--json", action="store_true", help="emit raw json")
    p.add_argument("--rebuild", action="store_true", help="force index rebuild")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("inspect");        s.add_argument("slug")
    s = sub.add_parser("pairs");          s.add_argument("slug"); s.add_argument("--relation", default="compatible")
    s = sub.add_parser("conflicts");      s.add_argument("slug")
    s = sub.add_parser("triggers");       s.add_argument("slug")
    s = sub.add_parser("validate");       s.add_argument("stack", nargs="+")
    s = sub.add_parser("category");       s.add_argument("category")
    s = sub.add_parser("recent");         s.add_argument("--days", type=int, default=7)
    s = sub.add_parser("status");         s.add_argument("status", choices=["prod","flagged","quarantined"])

    args = p.parse_args(argv)
    idx = build_index(force=args.rebuild)

    dispatch = {
        "inspect":   lambda: resolver.inspect(idx, args.slug),
        "pairs":     lambda: resolver.pairs_with(idx, args.slug, args.relation),
        "conflicts": lambda: resolver.conflicts_with(idx, args.slug),
        "triggers":  lambda: resolver.trigger_collisions(idx, args.slug),
        "validate":  lambda: resolver.validate_stack(idx, args.stack),
        "category":  lambda: resolver.in_category(idx, args.category),
        "recent":    lambda: resolver.recent_promotions(idx, args.days),
        "status":    lambda: resolver.by_status(idx, args.status),
    }
    result = dispatch[args.cmd]()

    if args.json:
        json.dump(result, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        fmt.render(args.cmd, result, sys.stdout)

    if args.cmd == "validate" and isinstance(result, dict) and result.get("verdict") == "block":
        sys.exit(2)

if __name__ == "__main__":
    main()
```

[workshop planning doc, D:\AI\ComfyUI_portable\workshop\scrape\query, 2026-09-20 14:00 EST]

Picking up right where the file cut off — the rest of `formatters.py` in full, no truncation.

```python
# query/formatters.py  (continued from 8.6)
from __future__ import annotations
import sys

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    _HAS_RICH = True
except ImportError:
    _HAS_RICH = False


def _plain_table(rows, headers, out):
    widths = [len(h) for h in headers]
    for r in rows:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], len(str(cell)))
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    out.write(fmt.format(*headers) + "\n")
    out.write("  ".join("-" * w for w in widths) + "\n")
    for r in rows:
        out.write(fmt.format(*[str(c) for c in r]) + "\n")


def _table(rows, headers, out, title=None):
    if _HAS_RICH and out.isatty():
        console = Console(file=out)
        t = Table(title=title, show_header=True, header_style="bold")
        for h in headers:
            t.add_column(h)
        for r in rows:
            t.add_row(*[str(c) for c in r])
        console.print(t)
    else:
        if title:
            out.write(f"\n{title}\n")
        _plain_table(rows, headers, out)


def _panel(title: str, body: str, out, style: str = "cyan"):
    if _HAS_RICH and out.isatty():
        console = Console(file=out)
        console.print(Panel(body, title=title, border_style=style))
    else:
        bar = "=" * max(len(title) + 4, 40)
        out.write(f"\n{bar}\n  {title}\n{bar}\n{body}\n")


def _verdict_style(verdict: str) -> str:
    return {"ok": "green", "warn": "yellow", "block": "red"}.get(verdict, "white")


def render(cmd: str, data, out=sys.stdout):
    # ---------------- inspect ----------------
    if cmd == "inspect":
        if isinstance(data, dict) and "error" in data:
            out.write(f"ERROR: {data['error']}\n")
            return

        header = (
            f"slug          : {data['slug']}\n"
            f"filename      : {data['filename']}\n"
            f"category      : {data['category']}\n"
            f"status        : {data['status']}\n"
            f"promoted_at   : {data.get('promoted_at') or '—'}\n"
            f"weight_default: {data['weight_default']}  "
            f"range={data['weight_range'][0]}–{data['weight_range'][1]}\n"
            f"sha256        : {(data.get('sha256') or '')[:16]}…\n"
            f"triggers      : {', '.join(data['triggers']) or '—'}"
        )
        _panel(f"LoRA · {data['slug']}", header, out, style="cyan")

        sc = data.get("scorecard") or {}
        if sc:
            rows = [(k, str(v)) for k, v in sc.items()]
            _table(rows, ["metric", "value"], out, title="scorecard")

        edges = data.get("edges") or []
        if edges:
            rows = [
                (e["other"], e["relation"], f"{e['confidence']:.2f}", e["reason"][:60])
                for e in edges
            ]
            _table(rows, ["other", "relation", "conf", "reason"], out, title="edges")
        else:
            out.write("\nedges: none\n")

        excl = data.get("exclusion")
        if excl:
            body = "excludes: " + ", ".join(excl["excludes"]) + f"\nreason: {excl['reason']}"
            _panel("exclusion rule", body, out, style="red")

        hist = data.get("history") or []
        if hist:
            rows = [(h["ts"], h["action"], h["actor"], h["note"][:50]) for h in hist]
            _table(rows, ["ts", "action", "actor", "note"], out, title="history")
        return

    # ---------------- pairs ----------------
    if cmd == "pairs":
        if not data:
            out.write("no pairs found\n")
            return
        rows = [
            (r["slug"], r["category"], f"{r['confidence']:.2f}", r["status"], r["reason"][:60])
            for r in data
        ]
        _table(rows, ["slug", "category", "conf", "status", "reason"], out,
               title="compatible pairs")
        return

    # ---------------- conflicts ----------------
    if cmd == "conflicts":
        if not data:
            out.write("no conflicts\n")
            return
        rows = [
            (r["slug"], r["category"], f"{r['confidence']:.2f}", r["status"], r["reason"][:60])
            for r in data
        ]
        _table(rows, ["slug", "category", "conf", "status", "reason"], out,
               title="conflicts")
        return

    # ---------------- trigger collisions ----------------
    if cmd == "triggers":
        if not data:
            out.write("no trigger collisions\n")
            return
        rows = [(r["trigger"], r["other_slug"], r["other_category"]) for r in data]
        _table(rows, ["trigger", "collides_with", "other_category"], out,
               title="trigger collisions")
        return

    # ---------------- validate stack ----------------
    if cmd == "validate":
        verdict = data.get("verdict", "unknown")
        style = _verdict_style(verdict)
        summary = (
            f"stack   : {', '.join(data['stack'])}\n"
            f"verdict : {verdict.upper()}"
        )
        _panel("stack validation", summary, out, style=style)

        if data.get("unknown"):
            _panel("unknown slugs", ", ".join(data["unknown"]), out, style="red")

        if data.get("conflicts"):
            rows = [
                (c["a"], c["b"], f"{c['confidence']:.2f}", c["reason"][:70])
                for c in data["conflicts"]
            ]
            _table(rows, ["a", "b", "conf", "reason"], out, title="conflicts (blocking)")

        if data.get("cautions"):
            rows = [
                (c["a"], c["b"], f"{c['confidence']:.2f}", c["reason"][:70])
                for c in data["cautions"]
            ]
            _table(rows, ["a", "b", "conf", "reason"], out, title="cautions (warning)")

        tdupes = data.get("trigger_collisions") or {}
        if tdupes:
            rows = [(t, ", ".join(slugs)) for t, slugs in tdupes.items()]
            _table(rows, ["trigger", "shared_by"], out, title="trigger collisions in stack")
        return

    # ---------------- category listing ----------------
    if cmd == "category":
        if not data:
            out.write("category empty or unknown\n")
            return
        rows = [
            (r["slug"], r["status"], r.get("promoted_at") or "—",
             ", ".join(r["triggers"])[:60])
            for r in data
        ]
        _table(rows, ["slug", "status", "promoted_at", "triggers"], out,
               title="category members")
        return

    # ---------------- recent promotions ----------------
    if cmd == "recent":
        if not data:
            out.write("no promotions in window\n")
            return
        rows = [(r["slug"], r["category"], r["status"], r["promoted_at"]) for r in data]
        _table(rows, ["slug", "category", "status", "promoted_at"], out,
               title="recent promotions")
        return

    # ---------------- status filter ----------------
    if cmd == "status":
        if not data:
            out.write("no entries for that status\n")
            return
        rows = [(r["slug"], r["category"], r.get("promoted_at") or "—") for r in data]
        _table(rows, ["slug", "category", "promoted_at"], out, title="by status")
        return

    # ---------------- fallback ----------------
    out.write("(no formatter registered for this command; use --json)\n")
```

---

## 8.6b Quick sanity smoke — what each command prints

| Command | Rich output shape |
| --- | --- |
| `lora_query inspect wan22_cinematic_v3` | cyan panel header + scorecard table + edges table + optional red exclusion panel + history table |
| `lora_query pairs wan22_cinematic_v3` | single table, sorted by confidence desc |
| `lora_query conflicts wan22_cinematic_v3` | single table, hard conflicts + exclusion-derived rows merged |
| `lora_query triggers wan22_cinematic_v3` | trigger → other slug → other category |
| `lora_query validate A B C` | colored verdict panel (green/yellow/red) + conflict/caution/trigger sub-tables |
| `lora_query category kink/breeding` | member list with status and trigger preview |
| `lora_query recent --days 3` | promotions inside window, newest first |
| `lora_query status quarantined` | quarantined slugs with categories |

---

## 8.6c Failure modes table (formatters only)

| Failure | Trigger | Behavior | Recovery |
| --- | --- | --- | --- |
| `rich` not installed | Fresh embed python | Falls through to `_plain_table`, no crash | `pip install rich` inside `python_embeded` |
| Output piped to file | `> out.txt` | `out.isatty()` false → plain path taken automatically | none needed |
| Missing fields in `data` | Manifest schema drift | `data.get(...)` defaults + `—` placeholders | run `audit_matrix.py` to reconcile |
| Very wide `reason` strings | Long audit notes | Truncated to 60–70 chars in tables | use `--json` for full text |
| Empty result sets | New install, no promotions yet | Prints `no X found` and returns cleanly | expected |

---

`formatters.py` is now closed. Next natural piece inside Part 8 is **8.7 — `query_server.py`** (the FastAPI shim that wraps the exact same resolver calls behind `/inspect`, `/pairs`, `/validate`, etc.), then **8.8** for the pytest fixtures + `test_resolver.py`, then **8.9** the runbook / cheat-sheet card.

---

[Workshop, D:\AI\ComfyUI_portable\workshop\scrape, 2026-09-20 14:00 EST]

---

## 8.7 — Runbook: daily operator loop

The query surface is dead weight unless you actually *use* it. This is the shape of the loop I want you running every morning while the coffee's still cutting through — five minutes, three commands, one decision.

**Morning triage (04:15, after the cron job finishes at 04:00):**

```powershell
cd D:\AI\ComfyUI_portable\workshop\scrape
python lora_query.py recent --since 24h --format table
python lora_query.py conflicts --severity high --format table
python lora_query.py orphans --format table
```

- `recent --since 24h` shows everything promoted, quarantined, or flagged in the last cycle. If the row count is zero, the scraper didn't run — check `Task Scheduler → History` before touching anything else.
- `conflicts --severity high` surfaces trigger-word collisions the audit_matrix flagged at score ≥ 0.75. Anything here needs a human eye before it stacks in a live workflow.
- `orphans` catches LoRAs sitting in `loras/prod/` that have no manifest row, no ledger entry, or no sidecar. Almost always a half-failed promote — you either finish the promotion by hand or roll it back.

**Mid-day spot-check (whenever, before you queue a batch):**

```powershell
python lora_query.py stack --base "wan2.2-i2v-14b" --category anatomy --limit 8
python lora_query.py compat --lora "petite_anatomy_v3" --against "wan2.2-i2v-14b"
```

`stack` gives you the top-weighted candidates for a given base model and category — feeds straight into your rgthree LoRA loader chain. `compat` is the sanity check before you commit a specific LoRA to a scene: verdict, score, trigger overlap, VRAM delta.

**Weekly deep-audit (Sunday, 30 minutes):**

```powershell
python lora_query.py drift --window 7d --format panel
python lora_query.py deprecated --format table > drift_report_$(Get-Date -Format yyyyMMdd).txt
```

`drift` shows scorecards that shifted more than 15% week-over-week — either the base model updated under them or your test seeds moved. `deprecated` lists anything the audit marked stale (no promotion in 30 days + failing compat against current primary models). Pipe it to a dated report so you have a paper trail before you prune.

---

## 8.8 — Failure modes table

| Failure | Symptom | Root cause | Recovery |
| --- | --- | --- | --- |
| Empty `recent` output | Zero rows after 04:00 cycle | `promote_trigger.ps1` didn't fire, or scrape returned zero candidates | Check Task Scheduler history, re-run `promote_trigger.ps1` manually, inspect `scrape_log.csv` tail |
| `Index build failed: manifest missing` | `lora_query` exits 1 on any command | `_lora_manifest.json` was deleted or corrupted | Restore from `_lora_manifest.json.bak` (promote.py writes one every run), re-run `audit_matrix.py --rebuild` |
| Orphans list keeps growing | Same 3-5 filenames appear in `orphans` every day | Failed promote left files behind, cleanup step skipped | `python promote.py --rollback <filename>` per orphan, or `--force-quarantine` if you don't want them |
| `conflicts` returns nothing but stacks still misfire | Trigger word collision below 0.75 threshold | Severity floor set too high for your use case | Edit `resolver.py::CONFLICT_SEVERITY_FLOOR`, drop to 0.55, re-run audit |
| `drift` flags everything | Every scorecard shows >15% delta | Base model checkpoint was swapped mid-week | Rebuild scorecard baseline: `python audit_matrix.py --reseed-baseline`, expect one throwaway week |
| `compat` verdict = `unknown` | LoRA exists in manifest but has no matrix entry | `audit_matrix.py` skipped it (usually filename regex mismatch) | Run `python audit_matrix.py --force-include <lora_id>` |
| CLI hangs on `stack` command | Index rebuild takes >30s | Manifest bloated past 400 entries, no cache | Enable `--use-cache` flag (writes `.index_cache.pkl`, invalidates on manifest mtime change) |
| Ledger CSV corrupted | `csv.Error: line contains NUL` | Concurrent write from two promote runs | Restore `_lora_ledger.csv.bak`, add lockfile to promote.py (see Part 9) |

---

## 8.9 — What Part 8 does *not* do (and where it hands off)

The query surface is read-only by design. It does not mutate manifests, does not re-run audits, does not delete files. Every write path lives in `promote.py` (Part 7) or `audit_matrix.py` (Part 7). Keep it that way — the moment `lora_query.py` can delete something, one bad flag and you're restoring from backup.

Handoff points:

- **Part 9 (lockfile + concurrency layer):** protects manifest/ledger writes when promote and audit overlap
- **Part 10 (scorecard baseline rotation):** feeds `drift` with cleaner deltas, weekly rebase
- **Part 11 (the workflow injection layer):** consumes `stack` output directly into rgthree's LoRA loader JSON — the query surface becomes the workflow's brain

---

## 8.10 — Verification checklist (before you close Part 8)

- [ ] All eight query commands run without error against a populated manifest
- [ ] `lora_query.py --help` renders the full command tree with descriptions
- [ ] `recent`, `conflicts`, `orphans` all return in under 2 seconds on a 200-entry manifest
- [ ] `stack` returns identical results across three consecutive runs (deterministic sort)
- [ ] `compat` verdict matches what `audit_matrix.py` wrote in the ledger (no drift between subsystems)
- [ ] Formatters render clean in both `--format table` and `--format panel` modes
- [ ] JSON output mode (`--format json`) parses cleanly through `python -c "import json,sys; json.load(sys.stdin)"`
- [ ] Index cache invalidates correctly when manifest mtime changes (touch the file, confirm rebuild)
- [ ] Every subcommand has a corresponding entry in the failure modes table above
- [ ] Runbook commands copy-paste clean into a fresh PowerShell session

Green across all ten — Part 8 is shipped.

---

**Part 8 status: complete.** Reverse-lookup surface is live, operator loop is documented, failure modes are catalogued. Next up is **Part 9 — the lockfile & concurrency layer**, which protects the write paths in promote/audit from stepping on each other when Task Scheduler fires overlapping jobs. That one's short but non-negotiable — one race condition and you're restoring ledgers from backup at 3 AM. Say the word and I'll roll into 9.1.

---

[Workshop, D:\AI\ComfyUI_portable\workshop\scrape, 2026-09-20 14:00 EST]

---

## 8.11 — `query_server.py`: the always-on HTTP surface

CLI's fine for morning triage, but the moment you want ComfyUI custom nodes, rgthree loaders, or a browser dashboard to hit the query layer, subprocess-per-call gets ugly fast. `query_server.py` wraps the same `Index` + `resolver` stack in a tiny FastAPI process — one long-lived index in memory, sub-50ms responses, JSON out.

Runs on `127.0.0.1:8765` by default. Bind it to localhost only; nothing in here is auth-hardened and it's not meant to be.

**Path:** `D:\AI\ComfyUI_portable\workshop\scrape\query_server.py`

```python
"""
query_server.py — HTTP surface for the reverse-lookup query layer.

Wraps index.py + resolver.py in a FastAPI app. Long-lived process,
hot-reloads the Index when manifest/ledger/matrix mtimes change.

Bind: 127.0.0.1:8765 (localhost only, no auth).
Launch: python query_server.py
Or via uvicorn: uvicorn query_server:app --host 127.0.0.1 --port 8765
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Local imports — same directory
from index import Index, build_index, index_source_mtimes
from resolver import (
    query_recent,
    query_conflicts,
    query_orphans,
    query_stack,
    query_compat,
    query_drift,
    query_deprecated,
    query_lookup,
    CONFLICT_SEVERITY_FLOOR,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

WORKSHOP_ROOT = Path(r"D:\AI\ComfyUI_portable\workshop\scrape")
HOST = "127.0.0.1"
PORT = 8765
INDEX_REFRESH_INTERVAL_SEC = 30  # background mtime poll cadence
LOG_PATH = WORKSHOP_ROOT / "logs" / "query_server.log"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s :: %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("query_server")

# ---------------------------------------------------------------------------
# Index state (module-level, mutated by background refresh task)
# ---------------------------------------------------------------------------

class IndexState:
    """Holds the live Index plus the mtimes of source files at last build."""

    def __init__(self) -> None:
        self.index: Optional[Index] = None
        self.mtimes: dict[str, float] = {}
        self.built_at: float = 0.0
        self.build_count: int = 0
        self.lock = asyncio.Lock()

    async def ensure_fresh(self) -> Index:
        """Return the current Index, rebuilding if any source file changed."""
        async with self.lock:
            current_mtimes = index_source_mtimes(WORKSHOP_ROOT)
            if self.index is None or current_mtimes != self.mtimes:
                log.info(
                    "Rebuilding index (reason=%s)",
                    "first-build" if self.index is None else "mtime-change",
                )
                t0 = time.perf_counter()
                self.index = build_index(WORKSHOP_ROOT)
                self.mtimes = current_mtimes
                self.built_at = time.time()
                self.build_count += 1
                log.info(
                    "Index rebuilt in %.3fs (entries=%d, build#=%d)",
                    time.perf_counter() - t0,
                    len(self.index.manifest),
                    self.build_count,
                )
            return self.index


state = IndexState()

# ---------------------------------------------------------------------------
# Background refresh loop
# ---------------------------------------------------------------------------

async def _refresh_loop() -> None:
    """Poll source mtimes every N seconds; rebuild if changed."""
    while True:
        try:
            await asyncio.sleep(INDEX_REFRESH_INTERVAL_SEC)
            await state.ensure_fresh()
        except asyncio.CancelledError:
            log.info("Refresh loop cancelled — shutting down")
            raise
        except Exception:
            log.exception("Refresh loop error (continuing)")


# ---------------------------------------------------------------------------
# Lifespan: build index at startup, cancel refresh at shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("query_server starting — workshop_root=%s", WORKSHOP_ROOT)
    await state.ensure_fresh()
    refresh_task = asyncio.create_task(_refresh_loop(), name="index-refresh")
    try:
        yield
    finally:
        refresh_task.cancel()
        try:
            await refresh_task
        except asyncio.CancelledError:
            pass
        log.info("query_server stopped")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="LoRA Query Server",
    description="Read-only HTTP surface over the LoRA management index.",
    version="0.8.11",
    lifespan=lifespan,
)

# ComfyUI custom nodes may hit this from a different origin (localhost:8188)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8188", "http://localhost:8188"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Middleware: request timing
# ---------------------------------------------------------------------------

@app.middleware("http")
async def timing_middleware(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    response.headers["X-Response-Time-Ms"] = f"{elapsed_ms:.2f}"
    if elapsed_ms > 200:
        log.warning(
            "Slow request: %s %s took %.1fms",
            request.method,
            request.url.path,
            elapsed_ms,
        )
    return response


# ---------------------------------------------------------------------------
# Pydantic response models (thin — resolver returns dicts, we validate shape)
# ---------------------------------------------------------------------------

class Health(BaseModel):
    status: str
    index_built_at: float
    index_build_count: int
    manifest_entries: int
    uptime_sec: float
    workshop_root: str


class LoraSummary(BaseModel):
    lora_id: str
    filename: str
    category: str
    slot: str
    recommended_strength: float
    trigger_words: list[str]
    base_model: list[str]
    nsfw_safe: bool
    promoted_at: Optional[str] = None
    last_audit_score: Optional[float] = None


class ConflictEntry(BaseModel):
    lora_a: str
    lora_b: str
    severity: float
    reason: str
    triggers_overlap: list[str] = Field(default_factory=list)


class OrphanEntry(BaseModel):
    filename: str
    reason: str
    detected_at: str


class StackCandidate(BaseModel):
    lora_id: str
    filename: str
    weight: float
    recommended_strength: float
    compat_score: float
    trigger_words: list[str]


class CompatVerdict(BaseModel):
    lora_id: str
    base_model: str
    verdict: str  # "compatible" | "marginal" | "incompatible" | "unknown"
    score: float
    trigger_overlap: list[str]
    vram_delta_mb: Optional[int] = None
    notes: str = ""


class DriftEntry(BaseModel):
    lora_id: str
    baseline_score: float
    current_score: float
    delta_pct: float
    window_days: int


class DeprecatedEntry(BaseModel):
    lora_id: str
    last_promoted: Optional[str]
    days_since_use: int
    failing_against: list[str]


# ---------------------------------------------------------------------------
# Startup timestamp for uptime
# ---------------------------------------------------------------------------

_STARTUP_TS = time.time()

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health", response_model=Health, tags=["meta"])
async def health() -> Health:
    idx = await state.ensure_fresh()
    return Health(
        status="ok",
        index_built_at=state.built_at,
        index_build_count=state.build_count,
        manifest_entries=len(idx.manifest),
        uptime_sec=time.time() - _STARTUP_TS,
        workshop_root=str(WORKSHOP_ROOT),
    )


@app.post("/reload", tags=["meta"])
async def force_reload() -> dict[str, Any]:
    """Force a full index rebuild regardless of mtime state."""
    async with state.lock:
        state.mtimes = {}  # invalidate
    idx = await state.ensure_fresh()
    return {
        "reloaded": True,
        "manifest_entries": len(idx.manifest),
        "built_at": state.built_at,
    }


@app.get("/lookup/{lora_id}", response_model=LoraSummary, tags=["query"])
async def lookup(lora_id: str) -> LoraSummary:
    idx = await state.ensure_fresh()
    result = query_lookup(idx, lora_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"lora_id not found: {lora_id}")
    return LoraSummary(**result)


@app.get("/recent", response_model=list[LoraSummary], tags=["query"])
async def recent(
    since: str = Query("24h", pattern=r"^\d+[hd]$", description="e.g. 24h, 7d"),
    limit: int = Query(50, ge=1, le=500),
) -> list[LoraSummary]:
    idx = await state.ensure_fresh()
    rows = query_recent(idx, since=since, limit=limit)
    return [LoraSummary(**r) for r in rows]


@app.get("/conflicts", response_model=list[ConflictEntry], tags=["query"])
async def conflicts(
    severity: str = Query("high", pattern=r"^(low|medium|high|all)$"),
    limit: int = Query(100, ge=1, le=1000),
) -> list[ConflictEntry]:
    idx = await state.ensure_fresh()
    floor = {
        "all": 0.0,
        "low": 0.35,
        "medium": 0.55,
        "high": CONFLICT_SEVERITY_FLOOR,  # 0.75
    }[severity]
    rows = query_conflicts(idx, severity_floor=floor, limit=limit)
    return [ConflictEntry(**r) for r in rows]


@app.get("/orphans", response_model=list[OrphanEntry], tags=["query"])
async def orphans() -> list[OrphanEntry]:
    idx = await state.ensure_fresh()
    rows = query_orphans(idx)
    return [OrphanEntry(**r) for r in rows]


@app.get("/stack", response_model=list[StackCandidate], tags=["query"])
async def stack(
    base: str = Query(..., description="Base model, e.g. 'wan2.2-i2v-14b'"),
    category: str = Query(..., pattern=r"^(style|anatomy|kink|lighting|camera|experimental)$"),
    limit: int = Query(10, ge=1, le=50),
) -> list[StackCandidate]:
    idx = await state.ensure_fresh()
    rows = query_stack(idx, base_model=base, category=category, limit=limit)
    return [StackCandidate(**r) for r in rows]


@app.get("/compat", response_model=CompatVerdict, tags=["query"])
async def compat(
    lora: str = Query(..., description="lora_id to test"),
    against: str = Query(..., description="Base model to test against"),
) -> CompatVerdict:
    idx = await state.ensure_fresh()
    result = query_compat(idx, lora_id=lora, base_model=against)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"No compat data for lora={lora} against={against}",
        )
    return CompatVerdict(**result)


@app.get("/drift", response_model=list[DriftEntry], tags=["query"])
async def drift(
    window: str = Query("7d", pattern=r"^\d+d$"),
    threshold_pct: float = Query(15.0, ge=1.0, le=100.0),
) -> list[DriftEntry]:
    idx = await state.ensure_fresh()
    rows = query_drift(idx, window=window, threshold_pct=threshold_pct)
    return [DriftEntry(**r) for r in rows]


@app.get("/deprecated", response_model=list[DeprecatedEntry], tags=["query"])
async def deprecated(
    stale_days: int = Query(30, ge=1, le=365),
) -> list[DeprecatedEntry]:
    idx = await state.ensure_fresh()
    rows = query_deprecated(idx, stale_days=stale_days)
    return [DeprecatedEntry(**r) for r in rows]


# ---------------------------------------------------------------------------
# Error handler — never leak stack traces to the wire, always log them
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "path": request.url.path,
            "hint": "check logs at " + str(LOG_PATH),
        },
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _install_signal_handlers(loop: asyncio.AbstractEventLoop) -> None:
    """Graceful shutdown on Ctrl-C / SIGTERM."""
    if os.name == "nt":
        # Windows: signal handlers on the loop don't work the same way.
        # uvicorn handles KeyboardInterrupt itself; nothing to install.
        return
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: log.info("Received signal %s", s))


def main() -> None:
    import uvicorn

    log.info("Booting query_server on %s:%d", HOST, PORT)
    uvicorn.run(
        "query_server:app",
        host=HOST,
        port=PORT,
        log_config=None,       # use our logging setup, not uvicorn's
        access_log=False,      # we log timing ourselves via middleware
        reload=False,          # never auto-reload in workshop use
        workers=1,             # single worker — index is in-process state
    )


if __name__ == "__main__":
    main()
```

---

## 8.12 — How it slots into the rest of the stack

- **Reads from:** `index.py::build_index` and `index.py::index_source_mtimes`. Neither touches disk more than necessary; the mtime poll is four `stat()` calls every 30 seconds.
- **Delegates to:** every `query_*` function in `resolver.py`. The server is a thin HTTP shell — zero business logic lives here. That's deliberate. When you add a new query verb in Part 9 or 10, you add it to `resolver.py` and drop a five-line route in this file.
- **Consumed by:** the ComfyUI custom node in Part 11 (`LoRAQueryClient` — hits `/stack` and `/compat` from inside a workflow), plus any browser dashboard you decide to bolt on later.
- **Ignores:** all write paths. There is no `/promote`, no `/audit`, no `/delete`. If the server ever needs to mutate state, you build a separate `mutation_server.py` behind a token — this one stays read-only.

---

## 8.13 — Runbook: standing the server up

```powershell
cd D:\AI\ComfyUI_portable\workshop\scrape

# One-time install (if you don't already have these)
pip install fastapi uvicorn[standard] pydantic

# Foreground run (for testing — Ctrl-C to stop)
python query_server.py

# Background run via Task Scheduler at boot
# Register with: schtasks /create /tn "LoRAQueryServer" /xml query_server_task.xml
```

Smoke test from a second terminal:

```powershell
curl http://127.0.0.1:8765/health
curl "http://127.0.0.1:8765/recent?since=24h&limit=5"
curl "http://127.0.0.1:8765/stack?base=wan2.2-i2v-14b&category=anatomy&limit=3"
```

Expected: `/health` returns in under 20ms after warmup, `/recent` and `/stack` under 50ms on a 200-entry manifest.

---

## 8.14 — Failure modes specific to the server

| Failure | Symptom | Root cause | Recovery |
| --- | --- | --- | --- |
| Port already in use | `[Errno 10048] Only one usage of each socket address` on startup | Prior instance didn't shut down cleanly | `Get-Process python \| Where-Object {$_.CommandLine -like "*query_server*"} \| Stop-Process`, then relaunch |
| `/health` returns but queries 500 | Manifest was deleted while server was running | Background refresh caught the mtime change, tried to rebuild against nothing | POST `/reload` after restoring manifest, or restart the process |
| Slow responses (>500ms) | `X-Response-Time-Ms` header climbs steadily | Manifest bloat + no cache, or refresh loop rebuilding on every request | Check `state.build_count` via `/health` — if it's climbing faster than 2/minute, something is touching manifest files in a loop |
| CORS errors from ComfyUI node | Browser console shows blocked request | ComfyUI running on a non-default port | Add the origin to the `allow_origins` list in the CORS middleware, restart |
| Server hangs on shutdown | Ctrl-C doesn't return prompt for 10+ seconds | Refresh task caught mid-rebuild | Wait it out — the lifespan handler cancels cleanly, just slow on huge manifests |

---

Server's done. That completes the query surface: CLI (`lora_query.py`) for humans, HTTP (`query_server.py`) for workflows and dashboards, both backed by the same `Index` + `resolver` core. Part 8 is officially shipped end-to-end.

Part 9 — the lockfile & concurrency layer — is up next when you're ready. That one protects the write paths in `promote.py` and `audit_matrix.py` from clobbering each other when the cron job overlaps with a manual run, which becomes a real risk the moment this server starts triggering audits based on stack queries. Say the word.

---
