"""Start the configured local runtime with explicit workspace I/O directories."""

from __future__ import annotations

from pathlib import Path
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
        directory = config.runtime_root / name
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
        str(config.runtime_root / "input"),
        "--output-directory",
        str(config.runtime_root / "output"),
    ]
    if not custom_nodes:
        command.append("--disable-all-custom-nodes")
    return command


def profile_launch_command(config: Config) -> list[str]:
    command = launch_command(config)
    directory = config.runtime_root / "state/vram/telemetry"
    if directory.resolve() != directory.absolute():
        raise ValueError("VRAM telemetry directory redirects")
    return (
        command[:2]
        + [str(Path(__file__).with_name("vram_runtime.py")), str(directory), "--"]
        + profile_main_argv(config)
    )


def profile_main_argv(config: Config) -> list[str]:
    directory = config.runtime_root / "state/vram"
    if directory.resolve() != directory.absolute():
        raise ValueError("VRAM runtime directory redirects")
    for name in (
        "user",
        "scratch",
        "scratch/temp",
        "asset-index.sqlite",
        "asset-index.sqlite-wal",
        "asset-index.sqlite-shm",
    ):
        path = directory / name
        if path.resolve() != path.absolute() or path.is_symlink():
            raise ValueError("VRAM runtime data path redirects")
    return launch_command(config)[2:] + [
        "--user-directory",
        str(directory / "user"),
        "--temp-directory",
        str(directory / "scratch"),
        "--database-url",
        "sqlite:///" + (directory / "asset-index.sqlite").as_posix(),
    ]
