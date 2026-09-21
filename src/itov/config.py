"""Explicit workspace configuration, independent of the working directory."""

from __future__ import annotations

import json
import math
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

DIRECTORIES = ("input", "output", "models_shared", "templates", "workflows", "logs", "state")
DEFAULT_URL = "http://127.0.0.1:8188"


def validate_url(value: str) -> str:
    if not isinstance(value, str) or any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError("ComfyUI URL must be an HTTP(S) URL without whitespace")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("ComfyUI URL must be HTTP(S), without credentials, query, or fragment")
    if parsed.port == 0:
        raise ValueError("ComfyUI URL port must be between 1 and 65535")
    return value.rstrip("/")


def validate_timeout(value: float) -> float:
    if not math.isfinite(value) or value <= 0 or value > 60:
        raise ValueError("Timeout must be greater than 0 and at most 60 seconds")
    return value


def _resolve(base: Path, value: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Configured paths must be nonempty strings")
    path = Path(value).expanduser()
    return (path if path.is_absolute() else base / path).resolve()


def normalize_comfyui_root(path: Path) -> Path:
    """Accept the program directory or the outer portable directory."""
    path = path.resolve()
    if not (path / "main.py").is_file() and (path / "ComfyUI" / "main.py").is_file():
        return path / "ComfyUI"
    return path


@dataclass(frozen=True)
class Config:
    file: Path
    comfyui_root: Path
    comfyui_python: Path | None
    url: str

    @property
    def root(self) -> Path:
        return self.file.parent

    @property
    def python(self) -> Path | None:
        if self.comfyui_python is not None:
            return self.comfyui_python
        embedded = self.comfyui_root.parent / "python_embeded" / "python.exe"
        return embedded if embedded.is_file() else None


def load_config(path: Path) -> Config:
    path = path.resolve()
    with path.open("rb") as source:
        data = tomllib.load(source)
    if type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError("Configuration must declare version = 1")
    if set(data) != {"version", "comfyui"}:
        raise ValueError("Configuration accepts only version and [comfyui]")
    comfy = data.get("comfyui")
    if not isinstance(comfy, dict) or not {"root", "url"} <= comfy.keys():
        raise ValueError("Configuration requires [comfyui] root and url")
    if set(comfy) - {"root", "url", "python"}:
        raise ValueError("Unknown [comfyui] configuration key")
    return Config(
        file=path,
        comfyui_root=normalize_comfyui_root(_resolve(path.parent, comfy["root"])),
        comfyui_python=_resolve(path.parent, comfy["python"]) if "python" in comfy else None,
        url=validate_url(comfy["url"]),
    )


def initialize(
    root: Path,
    comfyui_root: Path,
    *,
    python: Path | None = None,
    url: str = DEFAULT_URL,
) -> Config:
    root = root.resolve()
    url = validate_url(url)
    config_file = root / "itov.toml"
    if config_file.exists():
        raise FileExistsError(f"Workspace already has a configuration: {config_file}")
    # Check every destination before creating anything. Never follow child redirects.
    for directory in (root, *(root / name for name in DIRECTORIES)):
        if directory.is_symlink() or not directory.resolve().is_relative_to(root):
            raise ValueError(f"Workspace directory redirects outside its location: {directory}")
        if directory.exists() and not directory.is_dir():
            raise ValueError(f"Workspace directory is occupied by a file: {directory}")
    comfyui_root = normalize_comfyui_root(comfyui_root)

    def relative(path: Path) -> str:
        try:
            return os.path.relpath(path.resolve(), root)
        except ValueError:  # Windows paths on separate drives.
            return str(path.resolve())

    content = (
        "version = 1\n\n[comfyui]\n"
        f"root = {json.dumps(relative(comfyui_root))}\n"
        f"url = {json.dumps(url)}\n"
    )
    if python is not None:
        content += f"python = {json.dumps(relative(python))}\n"
    root.mkdir(parents=True, exist_ok=True)
    with config_file.open("x", encoding="utf-8", newline="\n") as target:
        target.write(content)
    for name in DIRECTORIES:
        (root / name).mkdir(exist_ok=True)
    return load_config(config_file)
