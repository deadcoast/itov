"""Start the configured local runtime with explicit workspace I/O directories."""

from __future__ import annotations

from urllib.parse import urlsplit

from itov.config import Config


def launch_command(config: Config, *, custom_nodes: bool = False) -> list[str]:
    url = urlsplit(config.url)
    if url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost", "::1"} or url.path:
        raise ValueError("Local server launch requires a loopback HTTP URL without a path prefix")
    python = config.python
    if python is None or not python.is_file() or not (config.comfyui_root / "main.py").is_file():
        raise ValueError("Configured ComfyUI program or interpreter is missing; run itov doctor")
    for name in ("input", "output"):
        directory = config.root / name
        if not directory.is_dir() or not directory.resolve().is_relative_to(config.root):
            raise ValueError(f"Missing or redirected workspace directory: {directory}")
    command = [
        str(python),
        "-s",
        str(config.comfyui_root / "main.py"),
        "--disable-auto-launch",
        "--listen",
        url.hostname,
        "--port",
        str(url.port or 80),
        "--input-directory",
        str(config.root / "input"),
        "--output-directory",
        str(config.root / "output"),
    ]
    if not custom_nodes:
        command.append("--disable-all-custom-nodes")
    return command
