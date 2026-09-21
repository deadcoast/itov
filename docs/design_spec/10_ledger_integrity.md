# Part 10 — Ledger Integrity & Rolling Checksums

**Directory Anchor:** `D:\AI\ComfyUI_portable\workshop\scrape\integrity\`

```txt
integrity/
├── verify_ledger.py              # full-chain + rolling verification
├── seal_ledger.py                # appends chained SHA-256 to new rows
├── repair_ledger.py              # interactive recovery from backup + journal replay
├── backup_rotate.py              # nightly grandfather-father-son rotation
├── config/
│   └── integrity.yaml            # paths, retention, alert thresholds
├── snapshots/
│   ├── daily/                    # 14 rolling daily snapshots
│   ├── weekly/                   # 8 rolling weekly snapshots
│   └── monthly/                  # 12 rolling monthly snapshots
├── journal/
│   └── ledger_ops_YYYYMMDD.jsonl # append-only op journal (pre-image + post-image)
└── logs/
    └── verify_YYYYMMDD.log
```

---

## 10.1 Threat Model — What We're Actually Defending Against

The ledger (`_lora_ledger.csv`) is the pipeline's ground truth. Every promotion, rotation pick, and audit lookup treats it as canonical. Three classes of corruption can silently poison downstream logic:

1. **Truncation** — a crashed writer leaves the file with a torn final row. Naive CSV readers skip it; the row is *silently lost*, and the LoRA it references gets re-promoted next cycle as if it were new.
2. **Row tampering** — a manual edit (fat-fingered strength, wrong preset_id) sails through unnoticed because nothing verifies row-level integrity. The compatibility matrix drifts out of sync over weeks.
3. **Reordering / duplication** — a script bug appends a row twice, or a merge from a stale backup interleaves history. Seed collisions and phantom promotions follow.

The defense is a **chained SHA-256 checksum column** — each row's `row_hash` is the SHA-256 of `(previous_row_hash || canonical_row_bytes)`. Any tamper anywhere in the chain surfaces as a mismatch at the first affected row and every row after it. This is the same rolling-hash discipline used by Merkle logs, rsync's block matcher, and transaction ledgers — cheap to compute, impossible to forge without recomputing the entire tail.

---

## 10.2 Ledger Schema Extension

The Part 4 ledger schema gains two columns appended to the right (backward-compatible — old rows get sealed retroactively on first verify run):

| Column      | Type   | Purpose                                                              |
|-------------|--------|----------------------------------------------------------------------|
| `prev_hash` | hex-64 | SHA-256 of the previous row's `row_hash`. Genesis row uses 64 zeros. |
| `row_hash`  | hex-64 | SHA-256 of `prev_hash canonical_serialization(row_without_hashes)`   |

**Canonical serialization** is critical — two writers must produce byte-identical inputs for the hash to be reproducible. Rules:

- Fields joined with `\x1f` (ASCII unit separator, never appears in prompts or filenames)
- Numeric fields formatted as `f"{v:.4f}"` for floats, `str(int(v))` for ints
- Empty strings preserved as empty (not `None`, not `"null"`)
- No trailing newline in the hashed bytes
- UTF-8 encoding, no BOM

---

## 10.3 `config/integrity.yaml`

```yaml
paths:
  ledger:      D:\AI\ComfyUI_portable\workshop\loras\_lora_ledger.csv
  manifest:    D:\AI\ComfyUI_portable\workshop\loras\_lora_manifest.json
  matrix:      D:\AI\ComfyUI_portable\workshop\loras\_compatibility_matrix.json
  snapshots:   D:\AI\ComfyUI_portable\workshop\scrape\integrity\snapshots
  journal:     D:\AI\ComfyUI_portable\workshop\scrape\integrity\journal
  logs:        D:\AI\ComfyUI_portable\workshop\scrape\integrity\logs

hashing:
  algorithm:        sha256
  field_separator:  "\x1f"
  genesis_hash:     "0000000000000000000000000000000000000000000000000000000000000000"
  float_precision:  4

retention:
  daily_snapshots:   14
  weekly_snapshots:  8
  monthly_snapshots: 12

alerts:
  operator_email:    "${PIPELINE_OPERATOR_EMAIL}"
  event_source:      "ComfyUI-Integrity"
  event_id_ok:       9000
  event_id_warn:     9001
  event_id_fail:     9002

thresholds:
  max_chain_break_before_halt: 1     # any break halts pipeline
  max_missing_rows_before_halt: 0
  stale_snapshot_hours:         30   # warn if newest daily snapshot > 30h old

verify:
  rolling_window_size: 500           # rows verified per rolling pass (fast path)
  full_scan_interval:  86400         # full-chain scan every 24h
```

---

## 10.4 `seal_ledger.py` — Append-Path Hash Writer

Every writer to the ledger (`promote.py`, `rotate_loras.py`, `flag_review`) routes through `seal_row()` instead of raw `csv.writer.writerow()`. The seal is computed *before* the row hits disk, and the write is atomic via tempfile-swap on the last row.

```python
# D:\AI\ComfyUI_portable\workshop\scrape\integrity\seal_ledger.py
"""
seal_ledger.py — canonical row hashing + append-only sealing for _lora_ledger.csv.

Public API:
    seal_row(row_dict, ledger_path) -> dict     # returns row with prev_hash + row_hash filled
    tail_hash(ledger_path) -> str               # last row_hash or genesis
    canonical_bytes(row_dict, fields) -> bytes  # deterministic serialization
"""
from __future__ import annotations

import csv
import hashlib
import os
import tempfile
import yaml
from pathlib import Path
from typing import Iterable

CFG_PATH = Path(r"D:\AI\ComfyUI_portable\workshop\scrape\integrity\config\integrity.yaml")
_CFG     = yaml.safe_load(CFG_PATH.read_text(encoding="utf-8"))
SEP      = _CFG["hashing"]["field_separator"].encode("utf-8")
GENESIS  = _CFG["hashing"]["genesis_hash"]
PRECISION = _CFG["hashing"]["float_precision"]

HASH_COLS = ("prev_hash", "row_hash")


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.{PRECISION}f}"
    if isinstance(v, bool):
        return "1" if v else "0"
    return str(v)


def canonical_bytes(row: dict, fields: Iterable[str]) -> bytes:
    """Deterministic serialization: sorted-by-schema, SEP-joined, UTF-8, no trailing newline."""
    parts = [_fmt(row.get(f, "")).encode("utf-8") for f in fields if f not in HASH_COLS]
    return SEP.join(parts)


def tail_hash(ledger_path: Path) -> str:
    """Return the row_hash of the last sealed row, or genesis if file empty/missing."""
    if not ledger_path.exists() or ledger_path.stat().st_size == 0:
        return GENESIS
    with ledger_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        last = None
        for row in reader:
            last = row
        if last is None or not last.get("row_hash"):
            return GENESIS
        return last["row_hash"]


def seal_row(row: dict, ledger_path: Path, fieldnames: list[str]) -> dict:
    """
    Compute prev_hash + row_hash, return the augmented row.
    Caller is responsible for writing the returned dict to the CSV.
    """
    prev = tail_hash(ledger_path)
    body = canonical_bytes(row, fieldnames)
    h    = hashlib.sha256()
    h.update(bytes.fromhex(prev))
    h.update(SEP)
    h.update(body)
    row_out = dict(row)
    row_out["prev_hash"] = prev
    row_out["row_hash"]  = h.hexdigest()
    return row_out


def append_sealed(row: dict, ledger_path: Path, fieldnames: list[str]) -> dict:
    """
    Atomic append: seal → write → fsync. Journal the pre/post image for repair_ledger.
    """
    from .journal import record_op   # local import to avoid cycle

    sealed = seal_row(row, ledger_path, fieldnames)
    exists = ledger_path.exists() and ledger_path.stat().st_size > 0

    # Journal first, then write. If the write fails, the journal has the intended row.
    record_op(
        op="append",
        ledger=str(ledger_path),
        pre_tail=sealed["prev_hash"],
        post_tail=sealed["row_hash"],
        row=sealed,
    )

    mode = "a" if exists else "w"
    with ledger_path.open(mode, encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        writer.writerow(sealed)
        fh.flush()
        os.fsync(fh.fileno())

    return sealed
```

Every existing writer (`promote.py`, `rotate_loras.py`) now calls `append_sealed(row, LEDGER, FIELDNAMES)` in place of the raw `csv.DictWriter.writerow`. Legacy rows without `prev_hash`/`row_hash` are back-filled on first `verify_ledger.py --seal-legacy` run — see 10.6.

---

## 10.5 `verify_ledger.py` — Full-Chain & Rolling Verification

Two modes. **Rolling** verifies the last N rows (fast, runs after every pipeline cycle). **Full** walks the entire chain from genesis (slow, runs nightly via scheduled task). Both emit structured JSON so downstream tooling can consume.

```python
#!/usr/bin/env python3
# D:\AI\ComfyUI_portable\workshop\scrape\integrity\verify_ledger.py
"""
verify_ledger.py — chained SHA-256 verification for _lora_ledger.csv.

Modes:
  --rolling       verify only the last N rows (config.verify.rolling_window_size)
  --full          walk from genesis to tail, verify every link
  --seal-legacy   one-shot: back-fill prev_hash/row_hash on unsealed rows
  --repair        interactive: consult journal + snapshots to restore chain

Exit codes:
  0  clean
  1  warnings (stale snapshot, unsealed rows in --rolling mode)
  2  chain break detected
  3  I/O / schema failure
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import yaml
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

CFG_PATH = Path(r"D:\AI\ComfyUI_portable\workshop\scrape\integrity\config\integrity.yaml")
_CFG     = yaml.safe_load(CFG_PATH.read_text(encoding="utf-8"))
SEP      = _CFG["hashing"]["field_separator"].encode("utf-8")
GENESIS  = _CFG["hashing"]["genesis_hash"]
PRECISION = _CFG["hashing"]["float_precision"]
UTC      = timezone.utc


@dataclass
class Break:
    row_index:     int
    row_id:        str
    expected_prev: str
    actual_prev:   str
    expected_hash: str
    actual_hash:   str
    kind:          str    # "prev_mismatch" | "hash_mismatch" | "unsealed" | "truncation"


@dataclass
class Report:
    started_at:      str
    finished_at:     str = ""
    mode:            str = "rolling"
    rows_scanned:    int = 0
    rows_verified:   int = 0
    rows_unsealed:   int = 0
    chain_breaks:    list[Break] = field(default_factory=list)
    warnings:        list[str] = field(default_factory=list)
    tail_hash:       str = ""
    exit_code:       int = 0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["chain_breaks"] = [asdict(b) for b in self.chain_breaks]
        return d


def _fmt(v) -> str:
    if v is None or v == "":
        return ""
    try:
        f = float(v)
        if "." in str(v) or "e" in str(v).lower():
            return f"{f:.{PRECISION}f}"
    except (ValueError, TypeError):
        pass
    return str(v)


def _canonical(row: dict, fields: list[str]) -> bytes:
    parts = [_fmt(row.get(f, "")).encode("utf-8") for f in fields
             if f not in ("prev_hash", "row_hash")]
    return SEP.join(parts)


def _compute_hash(prev: str, body: bytes) -> str:
    h = hashlib.sha256()
    h.update(bytes.fromhex(prev))
    h.update(SEP)
    h.update(body)
    return h.hexdigest()


def _iter_rows(ledger_path: Path) -> Iterator[tuple[int, dict, list[str]]]:
    with ledger_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames or []
        for i, row in enumerate(reader):
            yield i, row, fields


def verify_rolling(ledger_path: Path, window: int) -> Report:
    rep = Report(started_at=datetime.now(UTC).isoformat(), mode="rolling")
    all_rows = list(_iter_rows(ledger_path))
    rep.rows_scanned = len(all_rows)
    if not all_rows:
        rep.warnings.append("ledger empty")
        rep.finished_at = datetime.now(UTC).isoformat()
        return rep

    fields = all_rows[0][2]
    start  = max(0, len(all_rows) - window)

    # anchor: the row immediately before the window must be sealed
    if start > 0:
        anchor = all_rows[start - 1][1]
        expected_prev = anchor.get("row_hash", "")
        if not expected_prev:
            rep.warnings.append(f"anchor row {start-1} unsealed; rolling verify unreliable")
            rep.exit_code = max(rep.exit_code, 1)
    else:
        expected_prev = GENESIS

    for idx, row, _ in all_rows[start:]:
        rep.rows_scanned  # counted above; use rows_verified for in-window
        prev = row.get("prev_hash", "")
        got  = row.get("row_hash", "")
        if not prev or not got:
            rep.rows_unsealed += 1
            rep.chain_breaks.append(Break(
                row_index=idx, row_id=row.get("lora_id", "?"),
                expected_prev=expected_prev, actual_prev=prev,
                expected_hash="", actual_hash=got, kind="unsealed",
            ))
            rep.exit_code = max(rep.exit_code, 2)
            expected_prev = got or expected_prev
            continue
        if prev != expected_prev:
            rep.chain_breaks.append(Break(
                row_index=idx, row_id=row.get("lora_id", "?"),
                expected_prev=expected_prev, actual_prev=prev,
                expected_hash="", actual_hash=got, kind="prev_mismatch",
            ))
            rep.exit_code = max(rep.exit_code, 2)
        recomputed = _compute_hash(prev, _canonical(row, fields))
        if recomputed != got:
            rep.chain_breaks.append(Break(
                row_index=idx, row_id=row.get("lora_id", "?"),
                expected_prev=expected_prev, actual_prev=prev,
                expected_hash=recomputed, actual_hash=got, kind="hash_mismatch",
            ))
            rep.exit_code = max(rep.exit_code, 2)
        rep.rows_verified += 1
        expected_prev = got

    rep.tail_hash   = expected_prev
    rep.finished_at = datetime.now(UTC).isoformat()
    return rep


def verify_full(ledger_path: Path) -> Report:
    rep = Report(started_at=datetime.now(UTC).isoformat(), mode="full")
    expected_prev = GENESIS
    fields_captured: list[str] = []

    for idx, row, fields in _iter_rows(ledger_path):
        rep.rows_scanned += 1
        fields_captured = fields
        prev = row.get("prev_hash", "")
        got  = row.get("row_hash", "")
        if not prev or not got:
            rep.rows_unsealed += 1
            rep.chain_breaks.append(Break(
                row_index=idx, row_id=row.get("lora_id", "?"),
                expected_prev=expected_prev, actual_prev=prev,
                expected_hash="", actual_hash=got, kind="unsealed",
            ))
            rep.exit_code = max(rep.exit_code, 2)
            expected_prev = got or expected_prev
            continue
        if prev != expected_prev:
            rep.chain_breaks.append(Break(
                row_index=idx, row_id=row.get("lora_id", "?"),
                expected_prev=expected_prev, actual_prev=prev,
                expected_hash="", actual_hash=got, kind="prev_mismatch",
            ))
            rep.exit_code = max(rep.exit_code, 2)
        recomputed = _compute_hash(prev, _canonical(row, fields))
        if recomputed != got:
            rep.chain_breaks.append(Break(
                row_index=idx, row_id=row.get("lora_id", "?"),
                expected_prev=expected_prev, actual_prev=prev,
                expected_hash=recomputed, actual_hash=got, kind="hash_mismatch",
            ))
            rep.exit_code = max(rep.exit_code, 2)
        rep.rows_verified += 1
        expected_prev = got

    rep.tail_hash   = expected_prev
    rep.finished_at = datetime.now(UTC).isoformat()
    return rep


def seal_legacy(ledger_path: Path) -> Report:
    """
    One-shot: walk the ledger, compute prev_hash + row_hash for any row missing them,
    rewrite the file atomically. Journals the operation.
    """
    from journal import record_op

    rep = Report(started_at=datetime.now(UTC).isoformat(), mode="seal-legacy")
    all_rows = list(_iter_rows(ledger_path))
    if not all_rows:
        rep.warnings.append("ledger empty; nothing to seal")
        rep.finished_at = datetime.now(UTC).isoformat()
        return rep

    fields = list(all_rows[0][2])
    if "prev_hash" not in fields:
        fields.append("prev_hash")
    if "row_hash" not in fields:
        fields.append("row_hash")

    expected_prev = GENESIS
    sealed_rows: list[dict] = []
    for idx, row, _ in all_rows:
        rep.rows_scanned += 1
        if not row.get("prev_hash") or not row.get("row_hash"):
            row["prev_hash"] = expected_prev
            row["row_hash"]  = _compute_hash(expected_prev, _canonical(row, fields))
            rep.rows_unsealed += 1
        expected_prev = row["row_hash"]
        sealed_rows.append(row)

    # atomic rewrite
    tmp = ledger_path.with_suffix(ledger_path.suffix + ".sealing")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(sealed_rows)
    tmp.replace(ledger_path)

    record_op(op="seal_legacy", ledger=str(ledger_path),
              pre_tail=GENESIS, post_tail=expected_prev,
              row={"sealed_count": rep.rows_unsealed})

    rep.tail_hash   = expected_prev
    rep.rows_verified = rep.rows_scanned - rep.rows_unsealed
```

[workshop desk, D:\AI\ComfyUI_portable\workshop\scrape\integrity\, 2026-09-20 17:00 EST]

### `verify_ledger.py` — resuming from the cutoff in `seal_legacy()`

```python
    rep.tail_hash    = expected_prev
    rep.rows_verified = rep.rows_scanned - rep.rows_unsealed
    rep.finished_at  = datetime.now(UTC).isoformat()
    return rep


# ── CLI ──────────────────────────────────────────────────────────────────────

def _write_report(rep: Report, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path  = out_dir / f"verify_{rep.mode}_{stamp}.json"
    path.write_text(json.dumps(rep.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return path


def _emit_event(rep: Report) -> None:
    """Windows EventLog emitter — matches Part 9 severity ladder."""
    try:
        import win32evtlogutil, win32evtlog
    except ImportError:
        return  # pywin32 not installed on dev boxes; scheduled task host has it

    alerts = _CFG["alerts"]
    source = alerts["event_source"]
    if rep.exit_code == 0:
        eid, etype = alerts["event_id_ok"],   win32evtlog.EVENTLOG_INFORMATION_TYPE
    elif rep.exit_code == 1:
        eid, etype = alerts["event_id_warn"], win32evtlog.EVENTLOG_WARNING_TYPE
    else:
        eid, etype = alerts["event_id_fail"], win32evtlog.EVENTLOG_ERROR_TYPE

    msg = (
        f"mode={rep.mode} scanned={rep.rows_scanned} verified={rep.rows_verified} "
        f"unsealed={rep.rows_unsealed} breaks={len(rep.chain_breaks)} "
        f"tail={rep.tail_hash[:12]} exit={rep.exit_code}"
    )
    win32evtlogutil.ReportEvent(source, eid, eventType=etype, strings=[msg])


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--rolling",     action="store_true", help="verify last N rows (fast)")
    mode.add_argument("--full",        action="store_true", help="walk from genesis (nightly)")
    mode.add_argument("--seal-legacy", action="store_true", help="back-fill unsealed rows")
    mode.add_argument("--repair",      action="store_true", help="interactive recovery")

    p.add_argument("--ledger",  type=Path,
                   default=Path(_CFG["paths"]["ledger"]))
    p.add_argument("--out-dir", type=Path,
                   default=Path(_CFG["paths"]["logs"]))
    p.add_argument("--window",  type=int,
                   default=_CFG["verify"]["rolling_window_size"])
    p.add_argument("--quiet",   action="store_true", help="suppress stdout summary")
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    if not args.ledger.exists():
        print(f"[verify] ledger missing: {args.ledger}", file=sys.stderr)
        return 3

    try:
        if args.rolling:
            rep = verify_rolling(args.ledger, args.window)
        elif args.full:
            rep = verify_full(args.ledger)
        elif args.seal_legacy:
            rep = seal_legacy(args.ledger)
        elif args.repair:
            from repair_ledger import interactive_repair
            rep = interactive_repair(args.ledger)
        else:
            print("[verify] no mode selected", file=sys.stderr)
            return 3
    except (OSError, csv.Error, json.JSONDecodeError) as e:
        print(f"[verify] I/O or schema failure: {e}", file=sys.stderr)
        return 3

    report_path = _write_report(rep, args.out_dir)
    _emit_event(rep)

    if not args.quiet:
        print(
            f"[verify] mode={rep.mode} scanned={rep.rows_scanned} "
            f"verified={rep.rows_verified} unsealed={rep.rows_unsealed} "
            f"breaks={len(rep.chain_breaks)} tail={rep.tail_hash[:12]} "
            f"report={report_path.name} exit={rep.exit_code}"
        )
        for b in rep.chain_breaks[:5]:
            print(f"  ! row {b.row_index} ({b.row_id}) {b.kind}: "
                  f"expected_prev={b.expected_prev[:12]} actual={b.actual_prev[:12]}",
                  file=sys.stderr)
        if len(rep.chain_breaks) > 5:
            print(f"  ... {len(rep.chain_breaks) - 5} more breaks in {report_path}",
                  file=sys.stderr)

    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

---

## 10.6 `journal.py` — Append-Only Operations Journal

Every mutating call routes through `record_op()` *before* the CSV is touched. If the write later fails or corrupts, the journal holds enough state to replay or reconstruct.

```python
# D:\AI\ComfyUI_portable\workshop\scrape\integrity\journal.py
"""
journal.py — append-only JSONL journal of every ledger mutation.

One file per UTC day. Each line is a self-contained record with pre-image tail,
post-image tail, and the full sealed row. repair_ledger.py consumes these to
rebuild a torn chain without touching snapshots.
"""
from __future__ import annotations

import json
import os
import yaml
from datetime import datetime, timezone
from pathlib import Path

CFG_PATH = Path(r"D:\AI\ComfyUI_portable\workshop\scrape\integrity\config\integrity.yaml")
_CFG     = yaml.safe_load(CFG_PATH.read_text(encoding="utf-8"))
JOURNAL_DIR = Path(_CFG["paths"]["journal"])
UTC = timezone.utc


def _today_journal() -> Path:
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return JOURNAL_DIR / f"ledger_ops_{stamp}.jsonl"


def record_op(op: str, ledger: str, pre_tail: str, post_tail: str, row: dict) -> None:
    """Append one op record. Fsync forced — this is the durability boundary."""
    record = {
        "ts":        datetime.now(UTC).isoformat(),
        "op":        op,
        "ledger":    ledger,
        "pre_tail":  pre_tail,
        "post_tail": post_tail,
        "row":       row,
        "pid":       os.getpid(),
    }
    path = _today_journal()
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def iter_journal(since: datetime | None = None):
    """Yield journal records across all daily files, oldest first, optionally filtered."""
    for path in sorted(JOURNAL_DIR.glob("ledger_ops_*.jsonl")):
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if since and datetime.fromisoformat(rec["ts"]) < since:
                    continue
                yield rec
```

---

## 10.7 `backup_rotate.py` — Grandfather-Father-Son Snapshots

Nightly job. Copies the ledger + manifest + matrix into `snapshots/daily/`, promotes on schedule, prunes past retention. Every snapshot carries its own `verify_full` report so restore-time you know *exactly* which snapshots are trustworthy.

```python
#!/usr/bin/env python3
# D:\AI\ComfyUI_portable\workshop\scrape\integrity\backup_rotate.py
"""
backup_rotate.py — GFS rotation for ledger/manifest/matrix snapshots.

Runs nightly at 03:30 (before Part 7's 04:00 promote cycle).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import yaml
from datetime import datetime, timezone
from pathlib import Path

CFG_PATH = Path(r"D:\AI\ComfyUI_portable\workshop\scrape\integrity\config\integrity.yaml")
_CFG     = yaml.safe_load(CFG_PATH.read_text(encoding="utf-8"))
UTC      = timezone.utc

SNAP_ROOT = Path(_CFG["paths"]["snapshots"])
DAILY     = SNAP_ROOT / "daily"
WEEKLY    = SNAP_ROOT / "weekly"
MONTHLY   = SNAP_ROOT / "monthly"
ARTIFACTS = ("ledger", "manifest", "matrix")


def _snapshot_one(tier: Path, stamp: str) -> Path:
    dst = tier / stamp
    dst.mkdir(parents=True, exist_ok=True)
    for key in ARTIFACTS:
        src = Path(_CFG["paths"][key])
        if src.exists():
            shutil.copy2(src, dst / src.name)
    return dst


def _verify_snapshot(snapshot_dir: Path) -> int:
    """Run verify_ledger --full against the snapshotted ledger; write report inline."""
    ledger = snapshot_dir / Path(_CFG["paths"]["ledger"]).name
    if not ledger.exists():
        return 3
    result = subprocess.run(
        [sys.executable,
         str(Path(__file__).with_name("verify_ledger.py")),
         "--full", "--ledger", str(ledger),
         "--out-dir", str(snapshot_dir), "--quiet"],
        capture_output=True, text=True,
    )
    (snapshot_dir / "verify_stdout.txt").write_text(result.stdout, encoding="utf-8")
    (snapshot_dir / "verify_stderr.txt").write_text(result.stderr, encoding="utf-8")
    return result.returncode


def _prune(tier: Path, keep: int) -> list[Path]:
    """Keep newest `keep` subdirs; return list of pruned paths."""
    subs = sorted([p for p in tier.iterdir() if p.is_dir()], reverse=True)
    pruned = []
    for old in subs[keep:]:
        shutil.rmtree(old, ignore_errors=True)
        pruned.append(old)
    return pruned


def main() -> int:
    now   = datetime.now(UTC)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")

    # daily always
    daily_dir = _snapshot_one(DAILY, stamp)
    rc = _verify_snapshot(daily_dir)
    print(f"[backup] daily -> {daily_dir.name} (verify exit={rc})")

    # weekly on Sunday
    if now.weekday() == 6:
        weekly_dir = _snapshot_one(WEEKLY, stamp)
        _verify_snapshot(weekly_dir)
        print(f"[backup] weekly -> {weekly_dir.name}")

    # monthly on the 1st
    if now.day == 1:
        monthly_dir = _snapshot_one(MONTHLY, stamp)
        _verify_snapshot(monthly_dir)
        print(f"[backup] monthly -> {monthly_dir.name}")

    # prune
    for pruned in _prune(DAILY,   _CFG["retention"]["daily_snapshots"]):
        print(f"[backup] pruned daily   {pruned.name}")
    for pruned in _prune(WEEKLY,  _CFG["retention"]["weekly_snapshots"]):
        print(f"[backup] pruned weekly  {pruned.name}")
    for pruned in _prune(MONTHLY, _CFG["retention"]["monthly_snapshots"]):
        print(f"[backup] pruned monthly {pruned.name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

---

## 10.8 `repair_ledger.py` — Interactive Chain Recovery

When `verify_ledger --full` returns exit 2, ops runs this. It surfaces every break, proposes a repair path per break kind, and requires explicit `y/n` confirmation before touching the canonical file. The repair itself always goes: **snapshot restore → journal replay → re-seal → re-verify**.

```python
#!/usr/bin/env python3
# D:\AI\ComfyUI_portable\workshop\scrape\integrity\repair_ledger.py
"""
repair_ledger.py — interactive chain recovery.

Strategy:
  1. Run verify_full, capture all breaks.
  2. Locate newest daily snapshot whose verify exit==0.
  3. Diff current ledger against snapshot; identify rows added since snapshot.
  4. Cross-reference journal for those rows; confirm each was recorded.
  5. Rebuild ledger = snapshot rows + journal-confirmed rows, re-seal in order.
  6. Atomic swap; re-run verify_full; abort on any residual break.
"""
from __future__ import annotations

import csv
import shutil
import sys
import yaml
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from verify_ledger import verify_full, _compute_hash, _canonical, GENESIS, Report
from journal import iter_journal
from seal_ledger import canonical_bytes

CFG_PATH = Path(r"D:\AI\ComfyUI_portable\workshop\scrape\integrity\config\integrity.yaml")
_CFG     = yaml.safe_load(CFG_PATH.read_text(encoding="utf-8"))
UTC      = timezone.utc


def _newest_clean_snapshot() -> Path | None:
    daily = Path(_CFG["paths"]["snapshots"]) / "daily"
    if not daily.exists():
        return None
    for snap in sorted(daily.iterdir(), reverse=True):
        stderr = snap / "verify_stderr.txt"
        stdout = snap / "verify_stdout.txt"
        if stdout.exists() and "exit=0" in stdout.read_text(encoding="utf-8"):
            return snap
    return None


def _confirm(prompt: str) -> bool:
    ans = input(f"{prompt} [y/N]: ").strip().lower()
    return ans == "y"


def interactive_repair(ledger_path: Path) -> Report:
    print(f"[repair] verifying {ledger_path.name} ...")
    pre = verify_full(ledger_path)
    if pre.exit_code == 0:
        print("[repair] ledger already clean; nothing to do.")
        return pre

    print(f"[repair] {len(pre.chain_breaks)} chain break(s) detected.")
    for b in pre.chain_breaks[:10]:
        print(f"  row {b.row_index} ({b.row_id}) — {b.kind}")

    snap = _newest_clean_snapshot()
    if snap is None:
        print("[repair] FATAL: no clean snapshot available. Escalate to manual restore.",
              file=sys.stderr)
        pre.warnings.append("no_clean_snapshot")
        pre.exit_code = 3
        return pre
    print(f"[repair] newest clean snapshot: {snap.name}")

    snap_ledger = snap / ledger_path.name
    with snap_ledger.open("r", encoding="utf-8", newline="") as fh:
        reader   = csv.DictReader(fh)
        fields   = list(reader.fieldnames or [])
        snap_rows = list(reader)
    snap_tail = snap_rows[-1]["row_hash"] if snap_rows else GENESIS
    print(f"[repair] snapshot has {len(snap_rows)} rows, tail={snap_tail[:12]}")

    snap_ts = datetime.strptime(snap.name, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    replay: list[dict] = []
    for rec in iter_journal(since=snap_ts):
        if rec["op"] != "append":
            continue
        if rec["pre_tail"] not in (snap_tail, *[r["row_hash"] for r in replay]):
            print(f"[repair] WARN journal record at {rec['ts']} does not chain; skipping")
            continue
        replay.append(rec["row"])
    print(f"[repair] {len(replay)} journal-confirmed rows to replay")

    if not _confirm(f"Rebuild ledger from snapshot + {len(replay)} replayed rows?"):
        print("[repair] aborted by operator.")
        pre.warnings.append("operator_aborted")
        return pre

    # Rebuild: snapshot rows as-is, then re-seal each replay row against the running tail.
    rebuilt = list(snap_rows)
    prev = snap_tail
    for row in replay:
        row_clean = {k: v for k, v in row.items() if k not in ("prev_hash", "row_hash")}
        row_clean["prev_hash"] = prev
        row_clean["row_hash"]  = _compute_hash(prev, canonical_bytes(row_clean, fields))
        rebuilt.append(row_clean)
        prev = row_clean["row_hash"]

    # Safety copy of the broken original, then atomic swap.
    quarantine = ledger_path.with_suffix(
        ledger_path.suffix + f".broken.{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    )
    shutil.copy2(ledger_path, quarantine)
    print(f"[repair] quarantined broken ledger -> {quarantine.name}")

    tmp = ledger_path.with_suffix(ledger_path.suffix + ".repair")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rebuilt)
    tmp.replace(ledger_path)

    post = verify_full(ledger_path)
    if post.exit_code == 0:
        print(f"[repair] SUCCESS — {len(rebuilt)} rows, tail={post.tail_hash[:12]}")
    else:
        print(f"[repair] RESIDUAL BREAKS after repair; escalate. See report.", file=sys.stderr)
    post.mode = "repair"
    return post
```

---

## 10.9 Scheduled Task — `verify_task.xml`

Wire into Task Scheduler alongside Part 7's promote job. Two triggers: hourly rolling verify + nightly full-chain verify at 03:00 (before the 03:30 backup and the 04:00 promote).

```xml
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>ComfyUI ledger integrity — rolling hourly + full nightly</Description>
    <Author>workshop</Author>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <Repetition>
        <Interval>PT1H</Interval>
        <Duration>P1D</Duration>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <StartBoundary>2026-09-20T00:15:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
    <CalendarTrigger>
      <StartBoundary>2026-09-20T03:00:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>S-1-5-18</UserId>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings
```

---

## Ledger Integrity & Rolling Checksums (continued)

Picking up from the `verify_ledger.py` / `journal.py` / `backup_rotate.py` / `repair_ledger.py` skeleton — here's the rest of the flesh: full scripts, the scheduled-task XML, failure modes, and the runbook.

---

## 10.7 `verify_ledger.py` — full script

```python
#!/usr/bin/env python3
"""
verify_ledger.py — chain verification for _lora_ledger.csv

Modes:
  --rolling N     verify last N rows against their chained hashes (fast, hourly)
  --full          verify entire chain from genesis (nightly)
  --seal-legacy   back-fill prev_hash/row_hash on a legacy ledger (one-shot)
  --repair        interactive: reconcile against latest clean snapshot + journal

Exit codes:
  0  clean
  2  break detected (see report json)
  3  I/O or schema failure
  4  repair required, operator abort
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import yaml

UTC = timezone.utc
GENESIS = "0" * 64
FIELD_SEP = "\x1f"

# --- canonical serialization ---------------------------------------------

def canonical_row(row: dict, columns: list[str], float_precision: int = 4) -> str:
    parts = []
    for col in columns:
        v = row.get(col, "")
        if v is None:
            parts.append("")
            continue
        if isinstance(v, float):
            parts.append(f"{v:.{float_precision}f}")
        else:
            parts.append(str(v))
    return FIELD_SEP.join(parts)

def row_digest(prev_hash: str, canonical: str) -> str:
    h = hashlib.sha256()
    h.update(prev_hash.encode("utf-8"))
    h.update(FIELD_SEP.encode("utf-8"))
    h.update(canonical.encode("utf-8"))
    return h.hexdigest()

# --- data classes --------------------------------------------------------

@dataclass
class Break:
    row_index: int
    row_id: str
    kind: str            # "hash_mismatch" | "prev_mismatch" | "missing_field" | "truncation"
    expected: str
    got: str
    detail: str = ""

@dataclass
class Report:
    started_at: str
    finished_at: str = ""
    mode: str = ""
    rows_checked: int = 0
    breaks: list[Break] = field(default_factory=list)
    tail_hash: str = ""
    ok: bool = True

    def to_dict(self) -> dict:
        d = asdict(self)
        d["breaks"] = [asdict(b) for b in self.breaks]
        return d

# --- core walker ---------------------------------------------------------

DATA_COLS_EXCLUDE = {"prev_hash", "row_hash"}

def walk_chain(
    ledger_path: Path,
    start_index: int = 0,
    start_prev: str = GENESIS,
    float_precision: int = 4,
) -> Iterable[tuple[int, dict, str, str]]:
    """
    Yields (row_index, row_dict, computed_hash, stored_hash) for each row
    beginning at start_index. Caller decides what to do with mismatches.
    """
    with ledger_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            return
        data_cols = [c for c in reader.fieldnames if c not in DATA_COLS_EXCLUDE]
        prev = start_prev
        for idx, row in enumerate(reader):
            if idx < start_index:
                # still advance prev from stored values so we can resume mid-file
                prev = row.get("row_hash", prev)
                continue
            stored_prev = row.get("prev_hash", "")
            stored_hash = row.get("row_hash", "")
            canonical = canonical_row(row, data_cols, float_precision)
            computed = row_digest(stored_prev or prev, canonical)
            yield idx, row, computed, stored_hash
            prev = stored_hash or computed

# --- modes ---------------------------------------------------------------

def mode_rolling(cfg: dict, n: int) -> Report:
    ledger = Path(cfg["paths"]["ledger"])
    report = Report(started_at=datetime.now(UTC).isoformat(), mode=f"rolling:{n}")
    if not ledger.exists():
        report.ok = False
        report.breaks.append(Break(-1, "", "truncation", "exists", "missing", str(ledger)))
        report.finished_at = datetime.now(UTC).isoformat()
        return report

    # count rows first to compute start index cheaply
    with ledger.open("r", encoding="utf-8", newline="") as fh:
        total = sum(1 for _ in fh) - 1  # minus header
    start = max(0, total - n)

    # seed prev_hash by scanning to start
    prev = GENESIS
    with ledger.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for idx, row in enumerate(reader):
            if idx >= start:
                break
            prev = row.get("row_hash", prev)

    for idx, row, computed, stored in walk_chain(
        ledger, start_index=start, start_prev=prev,
        float_precision=cfg["hashing"]["float_precision"],
    ):
        report.rows_checked += 1
        if computed != stored:
            report.breaks.append(Break(
                row_index=idx,
                row_id=row.get("lora_id", row.get("id", "")),
                kind="hash_mismatch",
                expected=stored,
                got=computed,
            ))
            report.ok = False
        report.tail_hash = stored or computed

    report.finished_at = datetime.now(UTC).isoformat()
    return report

def mode_full(cfg: dict) -> Report:
    ledger = Path(cfg["paths"]["ledger"])
    report = Report(started_at=datetime.now(UTC).isoformat(), mode="full")
    if not ledger.exists():
        report.ok = False
        report.breaks.append(Break(-1, "", "truncation", "exists", "missing", str(ledger)))
        report.finished_at = datetime.now(UTC).isoformat()
        return report

    prev = GENESIS
    for idx, row, computed, stored in walk_chain(
        ledger, start_index=0, start_prev=prev,
        float_precision=cfg["hashing"]["float_precision"],
    ):
        report.rows_checked += 1
        stored_prev = row.get("prev_hash", "")
        if stored_prev != prev:
            report.breaks.append(Break(
                row_index=idx,
                row_id=row.get("lora_id", ""),
                kind="prev_mismatch",
                expected=prev,
                got=stored_prev,
            ))
            report.ok = False
        if computed != stored:
            report.breaks.append(Break(
                row_index=idx,
                row_id=row.get("lora_id", ""),
                kind="hash_mismatch",
                expected=stored,
                got=computed,
            ))
            report.ok = False
        prev = stored or computed
        report.tail_hash = prev

    report.finished_at = datetime.now(UTC).isoformat()
    return report

def mode_seal_legacy(cfg: dict) -> Report:
    """One-shot: read a legacy ledger with no hash columns, rewrite with chain."""
    import tempfile, os, shutil
    ledger = Path(cfg["paths"]["ledger"])
    report = Report(started_at=datetime.now(UTC).isoformat(), mode="seal-legacy")

    with ledger.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        cols = list(reader.fieldnames or [])
        data_cols = [c for c in cols if c not in DATA_COLS_EXCLUDE]
        out_cols = data_cols + ["prev_hash", "row_hash"]
        rows_out = []
        prev = GENESIS
        for row in reader:
            canonical = canonical_row(row, data_cols, cfg["hashing"]["float_precision"])
            row["prev_hash"] = prev
            row["row_hash"] = row_digest(prev, canonical)
            prev = row["row_hash"]
            rows_out.append(row)
            report.rows_checked += 1
        report.tail_hash = prev

    # atomic rewrite
    fd, tmp = tempfile.mkstemp(prefix=ledger.name + ".", dir=str(ledger.parent))
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=out_cols)
        w.writeheader()
        w.writerows(rows_out)
    shutil.copy2(ledger, ledger.with_suffix(".pre-seal.bak"))
    os.replace(tmp, ledger)
    report.finished_at = datetime.now(UTC).isoformat()
    return report

# --- entrypoint ----------------------------------------------------------

def emit_report(report: Report, out_path: Path | None) -> None:
    payload = json.dumps(report.to_dict(), indent=2)
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload, encoding="utf-8")
    print(payload)

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=r"D:\AI\ComfyUI_portable\workshop\scrape\integrity\config\integrity.yaml")
    ap.add_argument("--rolling", type=int, default=0)
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--seal-legacy", action="store_true")
    ap.add_argument("--repair", action="store_true")
    ap.add_argument("--report-out", default="")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))

    if args.seal_legacy:
        r = mode_seal_legacy(cfg)
    elif args.full:
        r = mode_full(cfg)
    elif args.rolling:
        r = mode_rolling(cfg, args.rolling)
    elif args.repair:
        from repair_ledger import interactive_repair
        return interactive_repair(cfg)
    else:
        print("must specify --rolling N, --full, --seal-legacy, or --repair", file=sys.stderr)
        return 3

    out = Path(args.report_out) if args.report_out else None
    emit_report(r, out)
    return 0 if r.ok else 2

if __name__ == "__main__":
    sys.exit(main())
```

The walker is a generator on purpose — a nightly full-chain run on a ledger with 40k rows should never load the whole thing into memory, and the same walker feeds `--rolling` by seeding `prev` from a cheap forward-scan to the start index.

---

## 10.8 `journal.py` — append-only mutation log

```python
#!/usr/bin/env python3
"""
journal.py — append-only JSONL journal of every ledger mutation.

One file per UTC day: journal/YYYY-MM-DD.jsonl
Each line: {ts, actor, action, row_hash, prev_hash, payload}
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc

class Journal:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, ts: datetime) -> Path:
        return self.root / f"{ts.strftime('%Y-%m-%d')}.jsonl"

    def append(
        self,
        actor: str,
        action: str,
        row_hash: str,
        prev_hash: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        ts = datetime.now(UTC)
        record = {
            "ts": ts.isoformat(),
            "actor": actor,
            "action": action,
            "row_hash": row_hash,
            "prev_hash": prev_hash,
            "payload": payload or {},
        }
        line = json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n"
        p = self._path_for(ts)
        # O_APPEND on Windows is atomic for writes < PIPE_BUF; JSONL lines
        # are small enough that fsync-per-line is affordable.
        with p.open("a", encoding="utf-8", newline="") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())

    def replay(self, since: datetime | None = None):
        """Yield records ordered by day, then file order."""
        for p in sorted(self.root.glob("*.jsonl")):
            with p.open("r", encoding="utf-8") as fh:
                for line in fh:
                    rec = json.loads(line)
                    if since and datetime.fromisoformat(rec["ts"]) < since:
                        continue
                    yield rec
```

Every caller — `seal_ledger.py`, `promote.py`, `repair_ledger.py` — imports this and calls `journal.append(...)` in the same atomic critical section that writes the CSV row. If the CSV write succeeds but the journal write fails, the row is rolled back (the journal is the source of truth for "did this actually happen").

---

## 10.9 `backup_rotate.py` — GFS snapshot rotation

```python
#!/usr/bin/env python3
"""
backup_rotate.py — Grandfather-Father-Son snapshot rotation.

Layout under snapshots_root:
  daily/    YYYY-MM-DD/   ledger.csv  manifest.json  matrix.json  MANIFEST.json
  weekly/   YYYY-Www/     ...
  monthly/  YYYY-MM/      ...

Retention (from config):
  daily:   7
  weekly:  8
  monthly: 12

Rules:
  - Nightly run creates today's daily snapshot.
  - Sunday's daily gets copied to weekly.
  - Last daily of the month gets copied to monthly.
  - Old snapshots beyond retention are pruned.
  - Every snapshot dir gets MANIFEST.json with file hashes + tail_hash of the ledger.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

UTC = timezone.utc

def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def snapshot_files(sources: dict[str, Path], dest: Path) -> dict:
    dest.mkdir(parents=True, exist_ok=True)
    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "files": {},
    }
    for name, src in sources.items():
        if not src.exists():
            manifest["files"][name] = {"present": False}
            continue
        target = dest / src.name
        shutil.copy2(src, target)
        manifest["files"][name] = {
            "present":   True,
            "src":       str(src),
            "size":      target.stat().st_size,
            "sha256":    sha256_file(target),
        }
    # capture the current tail_hash of the ledger for cross-reference
    ledger = dest / sources["ledger"].name
    if ledger.exists():
        import csv
        with ledger.open("r", encoding="utf-8", newline="") as fh:
            last = None
            for row in csv.DictReader(fh):
                last = row
            manifest["tail_hash"] = last.get("row_hash") if last else None
    (dest / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return manifest

def prune(dir_: Path, keep: int) -> list[str]:
    if not dir_.exists():
        return []
    children = sorted([p for p in dir_.iterdir() if p.is_dir()])
    to_delete = children[:-keep] if keep > 0 else []
    removed = []
    for p in to_delete:
        shutil.rmtree(p, ignore_errors=True)
        removed.append(p.name)
    return removed

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=r"D:\AI\ComfyUI_portable\workshop\scrape\integrity\config\integrity.yaml")
    args = ap.parse_args()
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))

    snap_root = Path(cfg["paths"]["snapshots_root"])
    sources = {
        "ledger":   Path(cfg["paths"]["ledger"]),
        "manifest": Path(cfg["paths"]["manifest"]),
        "matrix":   Path(cfg["paths"]["matrix"]),
    }
    retention = cfg["retention"]
    now = datetime.now(UTC)

    daily_dir   = snap_root / "daily"   / now.strftime("%Y-%m-%d")
    weekly_dir  = snap_root / "weekly"  / f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"
    monthly_dir = snap_root / "monthly" / now.strftime("%Y-%m")

    report = {"created": [], "pruned": {}, "errors": []}
    try:
        snapshot_files(sources, daily_dir)
        report["created"].append(str(daily_dir))

        # Sunday → weekly promotion (Python's weekday(): Monday=0..Sunday=6)
        if now.weekday() == 6 and not weekly_dir.exists():
            shutil.copytree(daily_dir, weekly_dir)
            report["created"].append(str(weekly_dir))

        # Last day of month → monthly promotion
        tomorrow = now + timedelta(days=1)
        if tomorrow.month != now.month and not monthly_dir.exists():
            shutil.copytree(daily_dir, monthly_dir)
            report["created"].append(str(monthly_dir))

        report["pruned"]["daily"]   = prune(snap_root / "daily",   retention["daily"])
        report["pruned"]["weekly"]  = prune(snap_root / "weekly",  retention["weekly"])
        report["pruned"]["monthly"] = prune(snap_root / "monthly", retention["monthly"])
    except Exception as exc:
        report["errors"].append(str(exc))

    out = snap_root / "rotation_report.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if not report["errors"] else 3

if __name__ == "__main__":
    sys.exit(main())
```

The `MANIFEST.json` inside each snapshot dir is the anchor `repair_ledger.py` uses to prove a snapshot is intact before it will restore from it — a snapshot whose ledger `sha256` doesn't match its recorded tail hash is treated as corrupt and skipped.

---

Picking up mid-function in `repair_ledger.py` — completing 10.10, then rolling into the scheduled-task XML, failure-mode table, and the operator runbook that closes Part 10.

---

## 10.10 `repair_ledger.py` — full script

```python
#!/usr/bin/env python3
"""
repair_ledger.py — interactive chain recovery.

Strategy:
  1. Verify current ledger; identify first broken row index B.
  2. Locate most recent clean snapshot whose tail_hash matches a row
     at index < B in the current ledger.
  3. Replay journal entries from snapshot timestamp forward, applying
     only 'append' actions that carry a matching prev_hash.
  4. Present operator with a diff summary; require explicit YES to commit.
  5. On commit: atomic rewrite of ledger, append repair record to journal.
"""
from __future__ import annotations

import csv
import json
import shutil
import sys
import tempfile
import os
from datetime import datetime, timezone
from pathlib import Path

import yaml

from journal import Journal
from verify_ledger import (
    canonical_row, row_digest, walk_chain, GENESIS, DATA_COLS_EXCLUDE,
)

UTC = timezone.utc


# ─── discovery helpers ────────────────────────────────────────────────────

def _find_first_break(ledger: Path, float_precision: int) -> int:
    """Return row index of first broken row, or -1 if chain is clean."""
    prev = GENESIS
    for idx, row, computed, stored in walk_chain(ledger, 0, prev, float_precision):
        stored_prev = row.get("prev_hash", "")
        if stored_prev != prev or computed != stored:
            return idx
        prev = stored or computed
    return -1


def _load_snapshot_manifest(snap_dir: Path) -> dict | None:
    m = snap_dir / "MANIFEST.json"
    if not m.exists():
        return None
    try:
        return json.loads(m.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _snapshot_is_clean(snap_dir: Path) -> bool:
    """A snapshot is clean iff its recorded sha256 matches its file on disk."""
    manifest = _load_snapshot_manifest(snap_dir)
    if not manifest:
        return False
    ledger_meta = manifest.get("files", {}).get("ledger")
    if not ledger_meta or not ledger_meta.get("present"):
        return False
    ledger_file = snap_dir / Path(ledger_meta["src"]).name
    if not ledger_file.exists():
        return False
    import hashlib
    h = hashlib.sha256()
    with ledger_file.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest() == ledger_meta.get("sha256")


def _iter_snapshots_newest_first(snap_root: Path):
    """Walk daily → weekly → monthly, newest first within each tier."""
    for tier in ("daily", "weekly", "monthly"):
        tier_dir = snap_root / tier
        if not tier_dir.exists():
            continue
        for snap in sorted(tier_dir.iterdir(), reverse=True):
            if snap.is_dir():
                yield tier, snap


def _tail_hash_of(ledger_file: Path) -> str | None:
    if not ledger_file.exists():
        return None
    with ledger_file.open("r", encoding="utf-8", newline="") as fh:
        last = None
        for row in csv.DictReader(fh):
            last = row
        return last.get("row_hash") if last else None


def _find_recovery_anchor(
    current_ledger: Path,
    snap_root: Path,
    first_break: int,
) -> tuple[Path, int] | None:
    """
    Locate the newest clean snapshot whose tail_hash exists in the current
    ledger at an index strictly less than first_break. Returns
    (snapshot_ledger_path, row_index_in_current_ledger) or None.
    """
    # Build hash → index map for rows before the break in current ledger.
    hash_to_idx: dict[str, int] = {}
    with current_ledger.open("r", encoding="utf-8", newline="") as fh:
        for idx, row in enumerate(csv.DictReader(fh)):
            if idx >= first_break:
                break
            rh = row.get("row_hash", "")
            if rh:
                hash_to_idx[rh] = idx

    for tier, snap in _iter_snapshots_newest_first(snap_root):
        if not _snapshot_is_clean(snap):
            continue
        snap_ledger = snap / "ledger.csv"  # backup_rotate preserves basename
        if not snap_ledger.exists():
            # fall back: any *.csv in the dir named like a ledger
            candidates = list(snap.glob("*ledger*.csv"))
            if not candidates:
                continue
            snap_ledger = candidates[0]
        tail = _tail_hash_of(snap_ledger)
        if tail and tail in hash_to_idx:
            return snap_ledger, hash_to_idx[tail]
    return None


# ─── replay engine ────────────────────────────────────────────────────────

def _replay_journal_after(
    journal_root: Path,
    anchor_row_hash: str,
    data_cols: list[str],
    float_precision: int,
) -> list[dict]:
    """
    Walk the journal chronologically and collect every 'append' action whose
    prev_hash chains forward starting from anchor_row_hash. Rows whose
    prev_hash doesn't match the current expected tail are skipped with a
    warning, not silently dropped — the operator sees them in the diff.
    """
    j = Journal(journal_root)
    expected_prev = anchor_row_hash
    replayed: list[dict] = []
    skipped: list[dict] = []

    for rec in j.replay():
        if rec.get("action") != "append":
            continue
        payload = rec.get("payload") or {}
        row = payload.get("row")
        if not row:
            continue
        # normalize to a plain dict of strings
        row = {k: ("" if v is None else str(v)) for k, v in row.items()}
        if rec.get("prev_hash") != expected_prev:
            skipped.append({"ts": rec["ts"], "reason": "prev_hash mismatch",
                            "expected": expected_prev, "got": rec.get("prev_hash")})
            continue
        canonical = canonical_row(row, data_cols, float_precision)
        computed = row_digest(expected_prev, canonical)
        if computed != rec.get("row_hash"):
            skipped.append({"ts": rec["ts"], "reason": "row_hash mismatch on replay",
                            "expected": rec.get("row_hash"), "got": computed})
            continue
        row["prev_hash"] = expected_prev
        row["row_hash"] = computed
        replayed.append(row)
        expected_prev = computed

    if skipped:
        print(f"[repair] {len(skipped)} journal record(s) skipped during replay:")
        for s in skipped[:10]:
            print(f"    - {s['ts']}  {s['reason']}")
        if len(skipped) > 10:
            print(f"    ... {len(skipped) - 10} more")
    return replayed


# ─── commit path ──────────────────────────────────────────────────────────

def _atomic_rewrite_ledger(
    ledger: Path,
    header: list[str],
    kept_rows: list[dict],
    replayed_rows: list[dict],
) -> None:
    fd, tmp = tempfile.mkstemp(prefix=ledger.name + ".", dir=str(ledger.parent))
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=header)
        w.writeheader()
        for r in kept_rows:
            w.writerow({k: r.get(k, "") for k in header})
        for r in replayed_rows:
            w.writerow({k: r.get(k, "") for k in header})
        fh.flush()
        os.fsync(fh.fileno())
    # keep a pre-repair copy alongside the .pre-seal.bak convention
    shutil.copy2(ledger, ledger.with_suffix(".pre-repair.bak"))
    os.replace(tmp, ledger)


def _confirm(prompt: str) -> bool:
    try:
        answer = input(f"{prompt} type YES to proceed: ").strip()
    except EOFError:
        return False
    return answer == "YES"


# ─── entrypoint ───────────────────────────────────────────────────────────

def interactive_repair(cfg: dict) -> int:
    ledger = Path(cfg["paths"]["ledger"])
    snap_root = Path(cfg["paths"]["snapshots_root"])
    journal_root = Path(cfg["paths"]["journal_root"])
    float_precision = int(cfg["hashing"]["float_precision"])

    if not ledger.exists():
        print(f"[repair] ledger not found at {ledger}", file=sys.stderr)
        return 3

    print(f"[repair] scanning {ledger} …")
    first_break = _find_first_break(ledger, float_precision)
    if first_break < 0:
        print("[repair] ledger chain is clean; nothing to repair.")
        return 0

    print(f"[repair] first break at row index {first_break}")
    anchor = _find_recovery_anchor(ledger, snap_root, first_break)
    if not anchor:
        print("[repair] no clean snapshot anchors before the break.", file=sys.stderr)
        print("[repair] widen retention or restore from off-box backup.", file=sys.stderr)
        return 4
    snap_ledger, anchor_idx = anchor
    print(f"[repair] anchor: snapshot {snap_ledger}  → current row {anchor_idx}")

    # Read header + kept rows [0 .. anchor_idx] from current ledger.
    with ledger.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        header = list(reader.fieldnames or [])
        data_cols = [c for c in header if c not in DATA_COLS_EXCLUDE]
        kept_rows: list[dict] = []
        for idx, row in enumerate(reader):
            if idx > anchor_idx:
                break
            kept_rows.append(row)

    anchor_row_hash = kept_rows[-1].get("row_hash", GENESIS) if kept_rows else GENESIS
    print(f"[repair] anchor row_hash = {anchor_row_hash[:16]}…")
    print(f"[repair] replaying journal after anchor …")
    replayed = _replay_journal_after(
        journal_root, anchor_row_hash, data_cols, float_precision
    )

    # Diff summary
    with ledger.open("r", encoding="utf-8", newline="") as fh:
        current_total = sum(1 for _ in fh) - 1
    kept = len(kept_rows)
    added = len(replayed)
    dropped = current_total - kept
    print("\n─── repair diff ─────────────────────────────────")
    print(f"  current rows : {current_total}")
    print(f"  keep         : {kept}   (0 .. {anchor_idx})")
    print(f"  drop         : {dropped}   (indices {anchor_idx + 1} .. {current_total - 1})")
    print(f"  replay       : {added}   (from journal after anchor)")
    print(f"  final rows   : {kept + added}")
    print("──────────────────────────────────────────────────\n")

    if not _confirm("[repair] commit rewrite?"):
        print("[repair] aborted by operator.")
        return 4

    _atomic_rewrite_ledger(ledger, header, kept_rows, replayed)
    print(f"[repair] ledger rewritten atomically; backup at {ledger.with_suffix('.pre-repair.bak')}")

    # journal the repair itself
    j = Journal(journal_root)
    final_tail = (replayed[-1]["row_hash"] if replayed
                  else (kept_rows[-1]["row_hash"] if kept_rows else GENESIS))
    j.append(
        actor="repair_ledger",
        action="repair",
        row_hash=final_tail,
        prev_hash=anchor_row_hash,
        payload={
            "anchor_snapshot": str(snap_ledger),
            "anchor_index": anchor_idx,
            "dropped_rows": dropped,
            "replayed_rows": added,
        },
    )
    print("[repair] journal record appended; done.")
    return 0


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=r"D:\AI\ComfyUI_portable\workshop\scrape\integrity\config\integrity.yaml")
    args = ap.parse_args()
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    return interactive_repair(cfg)


if __name__ == "__main__":
    sys.exit(main())
```

Two things worth flagging about the repair path. First — the anchor search deliberately walks *daily → weekly → monthly*, newest first, so a same-day break is patched with minimal replay while a break that predates all daily snapshots still has a fighting chance against the weekly and monthly tiers. Second — the operator confirmation is not decorative: any repair that would drop more than a handful of rows should be inspected by a human against the journal skip list, because a large drop plus a small replay usually means the journal itself was truncated and off-box backup is the correct answer instead.

---

## 10.11 `verify_task.xml` — Windows scheduled task

Two triggers on one task: hourly rolling verify, nightly full-chain verify plus snapshot rotation. SYSTEM account so ComfyUI's own service account can't accidentally tamper with its auditor.

```xml
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Author>workshop\integrity</Author>
    <Description>Ledger chain verification + nightly snapshot rotation.</Description>
    <URI>\Workshop\LedgerIntegrity</URI>
  </RegistrationInfo>

  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-09-20T00:15:00</StartBoundary>
      <Repetition>
        <Interval>PT1H</Interval>
        <Duration>P1D</Duration>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
      <Enabled>true</Enabled>
    </CalendarTrigger>
    <CalendarTrigger>
      <StartBoundary>2026-09-20T03:30:00</StartBoundary>
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
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>true</WakeToRun>
    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>

  <Actions Context="Author">
    <Exec>
      <Command>powershell.exe</Command>
      <Arguments>-NoProfile -ExecutionPolicy Bypass -File "D:\AI\ComfyUI_portable\workshop\scrape\integrity\bin\verify_trigger.ps1"</Arguments>
      <WorkingDirectory>D:\AI\ComfyUI_portable\workshop\scrape\integrity</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
```

Backing PowerShell wrapper (`bin\verify_trigger.ps1`) — decides rolling-vs-full by hour, fences with a lockfile, and pipes stdout/stderr into date-stamped logs:

```powershell
$ErrorActionPreference = "Stop"
$root    = "D:\AI\ComfyUI_portable\workshop\scrape\integrity"
$py      = "D:\AI\ComfyUI_portable\python_embeded\python.exe"
$cfg     = "$root\config\integrity.yaml"
$logdir  = "$root\logs"
$lock    = "$root\.verify.lock"
$stamp   = (Get-Date -Format "yyyyMMdd-HHmmss")
$hour    = (Get-Date).Hour

New-Item -ItemType Directory -Force -Path $logdir | Out-Null

if (Test-Path $lock) {
    $age = (New-TimeSpan -Start (Get-Item $lock).LastWriteTime -End (Get-Date)).TotalMinutes
    if ($age -lt 55) { Write-Host "[verify] lock held ($([int]$age)m); skipping."; exit 0 }
    Remove-Item $lock -Force
}
New-Item -ItemType File -Path $lock | Out-Null

try {
    if ($hour -eq 3) {
        & $py "$root\verify_ledger.py" --config $cfg --full `
            --report-out "$logdir\full-$stamp.json" 2>&1 |
            Tee-Object -FilePath "$logdir\full-$stamp.log"
        $verifyExit = $LASTEXITCODE
        & $py "$root\backup_rotate.py" --config $cfg 2>&1 |
            Tee-Object -FilePath "$logdir\rotate-$stamp.log"
        if ($verifyExit -ne 0) { exit $verifyExit }
    } else {
        & $py "$root\verify_ledger.py" --config $cfg --rolling 500 `
            --report-out "$logdir\rolling-$stamp.json" 2>&1 |
            Tee-Object -FilePath "$logdir\rolling-$stamp.log"
        exit $LASTEXITCODE
    }
} finally {
    Remove-Item $lock -Force -ErrorAction SilentlyContinue
}
```

Registration one-liner (elevated PowerShell):

```powershell
schtasks /Create /XML "D:\AI\ComfyUI_portable\workshop\scrape\integrity\bin\verify_task.xml" `
    /TN "Workshop\LedgerIntegrity" /RU SYSTEM /F
```

---

## 10.12 Failure modes

| Symptom                                                      | Root cause                                                 | First response                                                                                   | Escalation                                                                 |
|--------------------------------------------------------------|------------------------------------------------------------|--------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------|
| Exit 2 from rolling verify, single `hash_mismatch` at tail   | Concurrent writer raced the seal step                      | Re-run `--rolling 50`; if it clears, the writer already fixed itself                             | If persistent, run `--repair`                                              |
| Exit 2 from full verify, contiguous block of `prev_mismatch` | Row reordering (someone opened the CSV in Excel and saved) | Run `--repair`; anchor will be the last snapshot before the save                                 | Retrain the operator; revoke Excel file association for `.csv` in this dir |
| Exit 2, `hash_mismatch` scattered across ancient rows        | Float precision drift from a schema change                 | Run `--seal-legacy` **only** after diffing against the last clean snapshot; otherwise `--repair` | If unresolved, restore from monthly snapshot                               |
| Exit 3, `ledger missing`                                     | Antivirus quarantined the file                             | Recover the ledger from quarantine, then run `--rolling 50`                                      | If verification still fails, restore from the latest clean snapshot        |

---

[workshop planning doc, D:\AI\ComfyUI_portable\workshop\scrape\integrity, 2026-09-20 17:00 EST]

Picking up mid-table and closing out Part 10 clean. No truncation, promise.

---

## 10.9 Failure modes (continued)

| #  | Failure                                                  | Root cause                                                                                                 | First response                                                                              | Escalation                                                                                                               |
|----|----------------------------------------------------------|------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------|
| 6  | `verify --rolling` returns non-zero every hour           | Ledger tail rewritten by hand or by a bad `promote.py` patch                                               | Read `integrity/logs/verify_*.log`, note the offending `row_no`                             | Run `verify_ledger.py --mode full`; if chain break confirmed, invoke `repair_ledger.py --interactive`                    |
| 7  | `verify --full` clean but Task Scheduler shows `0x41306` | PowerShell wrapper exited non-zero on lock contention                                                      | Check `integrity/logs/lock.log` for overlapping runs                                        | Extend `verify_trigger.ps1` `Wait-Lock` timeout from 90s to 300s; confirm no runaway `python.exe` from prior invocation  |
| 8  | Snapshot rotation skipping days                          | `backup_rotate.py` never fires; nightly branch of PS wrapper gated on `$hour -eq 3` and machine was asleep | Confirm laptop/desktop wake schedule; check Task Scheduler history for missed triggers      | Set `<WakeToRun>true</WakeToRun>` in `verify_task.xml`, re-register task                                                 |
| 9  | `MANIFEST.json` sha mismatch on a weekly snapshot        | Snapshot file touched post-creation (AV scanner, indexer, cloud sync)                                      | Exclude `integrity\snapshots\` from Defender + OneDrive/Dropbox scopes                      | Restore that week's snapshot from monthly tier; regenerate manifest with `backup_rotate.py --reseal <path>`              |
| 10 | `repair_ledger.py` cannot find a clean anchor            | All snapshots within retention are downstream of the corruption                                            | Widen search: `repair_ledger.py --interactive --search-months 6`                            | If still nothing, fall back to `--from-journal-only` mode; expect data loss window equal to oldest journal day → present |
| 11 | Journal file exceeds 200 MB in a single day              | Runaway promoter or audit loop writing duplicate mutations                                                 | Stop scheduler, tail `journal/YYYY-MM-DD.jsonl`, grep for repeated `op` values              | Deduplicate journal with `journal.py --compact <date>`; add rate-limit guard in caller                                   |
| 12 | Repair completes but next `verify --full` still fails    | Operator confirmed rewrite against wrong anchor; new chain diverges from live state                        | Do NOT re-repair. Stash current ledger to `_lora_ledger.diverged.csv`                       | Roll ledger back to `repair_ledger.py`'s `.pre_repair.bak` sidecar, retry with correct snapshot                          |
| 13 | `.pre_repair.bak` missing after crash                    | Repair killed between rename and journal flush                                                             | Check `integrity/journal/` for the pending `repair_start` entry with no `repair_commit`     | Manually restore ledger from newest snapshot in `integrity/snapshots/daily/`; log incident                               |
| 14 | Verify passes locally, fails on second machine           | Line-ending drift (CRLF vs LF) after a git pull or share sync                                              | `git config core.autocrlf false` in the workshop repo; re-checkout ledger                   | Add `.gitattributes` pinning `*.csv text eol=lf`                                                                         |
| 15 | Sha column present but zero-length on new rows           | `promote.py` running an older build that pre-dates the sha field                                           | Pin `promote.py` version in `requirements.lock`; bump the ledger schema version field       | Regenerate shas for the affected tail via `verify_ledger.py --mode seal --from-row <N>`                                  |
| 16 | Task Scheduler task disappears                           | Group Policy or a cleanup script removed SYSTEM-owned tasks                                                | Re-register via the block in §10.7; store the XML in source control                         | Move task registration into an idempotent bootstrap script under `bin\bootstrap_integrity.ps1`                           |
| 17 | `verify --rolling` slow (>30s)                           | Ledger crossed ~500k rows; rolling window still scanning full tail because `--tail` env var missing        | Set `INTEGRITY_ROLLING_TAIL=2000` in the PS wrapper                                         | Long-term: shard ledger by year (`_lora_ledger.2026.csv`) once row count > 1M                                            |
| 18 | Snapshot dir on separate drive goes offline              | External SSD unmounted, network share down                                                                 | `backup_rotate.py` should raise `SnapshotTargetUnavailable`; wrapper logs and exits nonzero | Fail closed: alert via console bell + write `integrity/ALERT.flag`; next Part 19 dashboard surfaces it                   |

---

## 10.10 Runbook — daily operator loop

Short, printable. Tape it to the monitor.

> **Morning (2 min)**

1. `type integrity\logs\verify_full_last.log` — expect `OK chain_len=N sha_head=…`
2. `dir integrity\snapshots\daily\` — expect a folder dated yesterday
3. `type integrity\ALERT.flag` — expect "file not found." If it exists, drop everything and open §10.9

> **After any manual ledger edit**

1. `python bin\verify_ledger.py --mode full` before you walk away
2. If clean → `python bin\backup_rotate.py --force-daily` to capture a fresh anchor
3. If broken → do NOT run promote/audit again until repaired

> **Weekly (Sunday, 5 min)**

1. `python bin\verify_ledger.py --mode full --deep` (recomputes every row sha, not just chain links)
2. Spot-check one monthly snapshot: `python bin\backup_rotate.py --verify-manifest integrity\snapshots\monthly\<latest>`
3. Prune journal: `python bin\journal.py --compact --older-than 45d`

> **Monthly**

1. Cold-restore drill: pick any snapshot, restore to `sandbox\`, run `verify --full` against the restored copy
2. If drill fails, escalate to §10.11 disaster-recovery

---

## 10.11 Disaster recovery — the four scenarios

Every branch below assumes you've already confirmed the failure with `verify_ledger.py --mode full` and captured `integrity/logs/verify_full_last.log` for postmortem.

**Scenario A — chain break, snapshot clean**
This is the happy path for a bad path.

```txt
python bin\repair_ledger.py --interactive
  → picks newest clean daily snapshot as anchor
  → replays journal entries after anchor
  → shows diff of proposed rewrite
  → operator types "COMMIT" to confirm
  → writes .pre_repair.bak, atomic rename, journal-commits
python bin\verify_ledger.py --mode full  # must pass
python bin\backup_rotate.py --force-daily  # fresh anchor post-repair
```

> **Scenario B — chain break, snapshots also compromised**

```txt
python bin\repair_ledger.py --interactive --search-months 6
  → walks monthly tier looking for any snapshot whose MANIFEST.json verifies
  → if found, treats it as anchor; expect wider replay window
  → if not found, falls to Scenario C
```

**Scenario C — no clean anchor anywhere**
Journal-only reconstruction. Data loss window = oldest journal day → now, minus whatever the journal replayed.

```txt
python bin\repair_ledger.py --from-journal-only --since 2026-06-01
  → seeds an empty ledger with genesis row
  → replays every journal entry it can parse
  → any rows referenced by journal but never written are logged to integrity\logs\unrecoverable.csv
```

After this, `unrecoverable.csv` is the manual review queue. Each row lands in Part 16's human-review UI as `quarantined_unrecoverable`.

> **Scenario D — ledger file itself missing/deleted**

```txt
copy integrity\snapshots\daily\<newest>\_lora_ledger.csv D:\AI\ComfyUI_portable\workshop\scrape\_lora_ledger.csv
python bin\verify_ledger.py --mode full
python bin\repair_ledger.py --interactive   # replays journal since snapshot
```

Zero data loss if the journal survived. If journal is also gone, you're on Scenario C.

---

## 10.12 Verification checklist — Part 10 sign-off

Tick every box before moving to Part 11.

- [ ] `integrity/config/integrity.yaml` present, `snapshot_root` on a drive with ≥ 20GB free
- [ ] `bin\verify_ledger.py`, `bin\journal.py`, `bin\backup_rotate.py`, `bin\repair_ledger.py` all import cleanly under `python_embeded`
- [ ] Fresh install: `python bin\verify_ledger.py --mode seal` on the current ledger, then `--mode full` returns OK
- [ ] Task Scheduler shows `LoRA Integrity Verify` registered, running as SYSTEM, `WakeToRun=true`
- [ ] Manually trigger the task from Task Scheduler; `integrity\logs\verify_rolling_last.log` updates within 30s
- [ ] Snapshot smoke: `python bin\backup_rotate.py --force-daily` creates a dated folder with a valid `MANIFEST.json`
- [ ] Corruption drill: append a garbage row to a copy of the ledger, run `verify --mode full`, confirm it flags the exact `row_no`
- [ ] Repair drill: on that same corrupted copy, run `repair_ledger.py --interactive`, confirm `.pre_repair.bak` sidecar exists and post-repair verify passes
- [ ] Journal size after one full day of normal ops is under 20 MB
- [ ] `integrity\ALERT.flag` gets created on simulated snapshot-drive offline and cleared on next successful run
- [ ] Defender / OneDrive / Dropbox exclusions cover `integrity\snapshots\` and `integrity\journal\`
- [ ] Runbook card from §10.10 printed and taped somewhere visible (or pinned in Obsidian, whatever you actually read)

---

## 10.13 Handoff to Part 11

Part 10 gives every downstream part a trustworthy ledger substrate. Specifically:

- Part 11 (VRAM budget planner) can now `SELECT` from `_lora_ledger.csv` with confidence that the row set matches the physical LoRA files — sha column is authoritative
- Part 14 (batch render orchestrator) will consult the journal to detect mid-render promotions that could invalidate an in-flight queue
- Part 15 (provenance sidecars) will embed the current `sha_head` from the ledger into every rendered video's `.provenance.json`, giving each render a cryptographic anchor to the exact ledger state at render time
- Part 17 (nightly integrity sweep) is a sibling of Part 10, not a replacement — Part 10 protects the ledger, Part 17 protects the actual LoRA blobs on disk

Next up if you want it: **Part 11 — the VRAM budget planner**. Static analyzer over a proposed stack, predicts peak VRAM against the 5090's 32GB ceiling using per-LoRA memory profiles cached during sandbox testing. Blocks OOM-bound compositions before ComfyUI ever loads the model. Say the word and I'll open it.

---
