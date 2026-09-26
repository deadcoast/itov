"""Isolated optional-package metadata diagnostics without importing ML libraries."""

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from itov.comfyui import parse_json
from itov.qualification import safe_path
from itov.training_data import publish, seal

PROBE = """
import importlib.metadata as m, json, sys
values = {}
for name in json.loads(sys.argv[1]):
    try: values[name] = m.version(name)
    except m.PackageNotFoundError: values[name] = None
print(json.dumps({'python': sys.version, 'packages': values}))
"""


def diagnose(config, kind, python=None, *, save=False):
    import json

    if kind == "training":
        from itov.training import PACKAGES, PINNED

        packages, pinned = PACKAGES, PINNED
    else:
        packages, pinned = ("Pillow",), {"Pillow": "12.3.0"}
    interpreter = Path(python or sys.executable).absolute()
    checks, metadata = [], None
    try:
        run = subprocess.run(
            [str(interpreter), "-I", "-c", PROBE, json.dumps(packages)],
            capture_output=True,
            timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if run.returncode:
            raise ValueError(
                "Interpreter probe failed: " + run.stderr.decode(errors="replace")[-2000:]
            )
        metadata = parse_json(run.stdout)
        if (
            not isinstance(metadata, dict)
            or not isinstance(metadata.get("python"), str)
            or not isinstance(metadata.get("packages"), dict)
        ):
            raise ValueError("Interpreter returned invalid package metadata")
        for name in packages:
            version = metadata["packages"].get(name)
            passed = (
                isinstance(version, str)
                and bool(version)
                and (name not in pinned or version == pinned[name])
            )
            checks.append(
                {
                    "name": name,
                    "status": "pass" if passed else "fail",
                    "detail": f"Installed: {version or 'missing'}; required: "
                    + pinned.get(name, "installed (runtime compatibility checked during planning)"),
                }
            )
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        checks.append({"name": "interpreter", "status": "fail", "detail": str(error)})
    value = seal(
        {
            "version": 1,
            "scope": "workspace_dependencies",
            "kind": kind,
            "observed_at": datetime.now(UTC).isoformat(),
            "interpreter": str(interpreter),
            "metadata": metadata,
            "checks": checks,
            "ok": all(r["status"] == "pass" for r in checks),
            "limits": (
                "Package metadata only; no installs, ML imports, CUDA probe or model qualification."
            ),
        },
        "diagnostic_id",
    )
    if save:
        path = safe_path(config.root, f"state/workspace/diagnostics/{value['diagnostic_id']}.json")
        publish(path, value)
        return {**value, "saved_path": str(path)}
    return value
