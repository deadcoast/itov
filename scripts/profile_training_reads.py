"""Measure read-only public assessment/packet commands without ML or server access.

Wall-time samples are uninstrumented; a separate sample records Python call cost
and file_digest byte volume. No persistent cache or application state is written.
"""

import argparse
import cProfile
import hashlib
import io
import json
import pstats
import statistics
import time
from contextlib import redirect_stdout
from pathlib import Path

from itov.catalog import canonical_bytes, sha256
from itov.cli import main


def measure(arguments, repeats):
    def invoke():
        output = io.StringIO()
        start = time.perf_counter_ns()
        with redirect_stdout(output):
            code = main(arguments)
        elapsed = time.perf_counter_ns() - start
        if code:
            raise ValueError(f"Command refused ({code}): {output.getvalue()}")
        return elapsed, sha256(canonical_bytes(json.loads(output.getvalue())))

    samples = [invoke() for _ in range(repeats)]
    counts = {}
    original = hashlib.file_digest

    def observed(source, *args, **kwargs):
        name = str(source.name)
        row = counts.setdefault(name, {"calls": 0, "bytes": 0})
        row["calls"] += 1
        row["bytes"] += Path(name).stat().st_size
        return original(source, *args, **kwargs)

    profile = cProfile.Profile()
    try:
        hashlib.file_digest = observed
        profile.enable()
        _, result_hash = invoke()
    finally:
        profile.disable()
        hashlib.file_digest = original
    assert all(value == result_hash for _, value in samples), (
        "Command results changed between samples"
    )
    stats = pstats.Stats(profile)
    functions = []
    for (path, line, function), (primitive, calls, own, total, _) in stats.stats.items():
        if "/itov/" in path.replace("\\", "/"):
            functions.append(
                {
                    "module": Path(path).name,
                    "line": line,
                    "function": function,
                    "calls": calls,
                    "primitive_calls": primitive,
                    "own_seconds": own,
                    "cumulative_seconds": total,
                }
            )
    return {
        "arguments": arguments,
        "repeats": repeats,
        "wall_ns": [ns for ns, _ in samples],
        "median_wall_ns": int(statistics.median(ns for ns, _ in samples)),
        "output_sha256": result_hash,
        "profile_functions": sorted(functions, key=lambda r: -r["cumulative_seconds"]),
        "file_digest": {
            "calls": sum(r["calls"] for r in counts.values()),
            "bytes": sum(r["bytes"] for r in counts.values()),
            "files": counts,
        },
        "limits": "Warm local files; wall samples exclude profiling. file_digest counts are "
        "only those hash reads, not all I/O. Profiling adds overhead. No model render.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("assess", "packet"))
    parser.add_argument("plan", type=Path)
    parser.add_argument("--config", type=Path, default=Path("workspace/itov.toml"))
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 10:
        parser.error("repeats must be 1..10")
    value = measure(
        ["evaluation", args.action, str(args.plan), "--config", str(args.config), "--json"],
        args.repeats,
    )
    with args.output.open("x", encoding="utf-8") as target:
        json.dump(value, target, indent=2)
        target.write("\n")
    print(
        json.dumps(
            {k: v for k, v in value.items() if k not in ("profile_functions", "file_digest")}
        )
    )
