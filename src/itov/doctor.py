"""Observable preflight results; no installs, process signals, or rendering."""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass

from itov.comfyui import ComfyUIClient, ComfyUIError
from itov.config import DIRECTORIES, Config


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


def _tool_check(name: str, args: list[str], timeout: float) -> Check:
    executable = shutil.which(name)
    if not executable:
        return Check(name, "fail", f"{name} was not found on PATH")
    try:
        result = subprocess.run(
            [executable, *args], capture_output=True, text=True, errors="replace", timeout=timeout
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return Check(name, "fail", str(error))
    lines = (result.stdout or result.stderr).strip().splitlines()
    count = 1 if name == "ffmpeg" else 4
    detail = " | ".join(lines[:count]) or f"No output; exit code {result.returncode}"
    return Check(name, "pass" if result.returncode == 0 and lines else "fail", detail)


def diagnose(config: Config, *, offline: bool = False, timeout: float = 3.0) -> dict:
    checks = [Check("itov.python", "pass", sys.version.split()[0])]
    for name in DIRECTORIES:
        directory = config.root / name
        valid = directory.is_dir() and directory.resolve().is_relative_to(config.root)
        checks.append(Check(f"workspace.{name}", "pass" if valid else "fail", str(directory)))
    main = config.comfyui_root / "main.py"
    checks.append(Check("comfyui.installation", "pass" if main.is_file() else "fail", str(main)))
    python = config.python
    checks.append(
        Check(
            "comfyui.python",
            "pass" if python and python.is_file() else "fail",
            str(python)
            if python
            else "No embedded Python; set [comfyui] python for a manual install",
        )
    )
    checks.append(_tool_check("ffmpeg", ["-version"], timeout))
    checks.append(
        _tool_check(
            "nvidia-smi",
            ["--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"],
            timeout,
        )
    )
    server = None
    if offline:
        checks.append(Check("comfyui.api", "skip", "Offline mode; server and CUDA are unverified"))
    else:
        client = ComfyUIClient(config.url, timeout=timeout)
        try:
            stats = client.system_stats()
            registry = client.object_info()
            server = {
                "system": stats["system"],
                "devices": stats["devices"],
                "node_classes": len(registry),
            }
            checks.append(
                Check("comfyui.api", "pass", f"{config.url}; {len(registry)} node classes")
            )
            cuda = any(
                isinstance(device, dict) and device.get("type") == "cuda"
                for device in stats["devices"]
            )
            checks.append(
                Check(
                    "comfyui.cuda",
                    "pass" if cuda else "fail",
                    "CUDA device reported" if cuda else "Server does not report a CUDA device",
                )
            )
        except ComfyUIError as error:
            checks.append(Check("comfyui.api", "fail", str(error)))
    return {
        "ok": all(check.status != "fail" for check in checks),
        "scope": "local" if offline else "live",
        "config": str(config.file),
        "checks": [asdict(check) for check in checks],
        "server": server,
        "limits": (
            "Preflight only; model compatibility, CUDA execution, and rendering are unverified."
        ),
    }
