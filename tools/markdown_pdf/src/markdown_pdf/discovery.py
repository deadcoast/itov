"""Deterministic discovery; excluded directories are pruned before descent."""

from __future__ import annotations

import fnmatch
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path

MARKDOWN_SUFFIXES = {".md", ".markdown", ".mdown", ".mkd"}
PRIVATE_WORDS = {"sensitive", "private", "secret", "secrets", "credentials", "confidential"}
EXCLUDED_DIRS = {
    "node_modules",
    "vendor",
    "venv",
    "env",
    "__pycache__",
    "site-packages",
    "build",
    "dist",
    "target",
    "coverage",
    "htmlcov",
    "output",
    "tmp",
    "temp",
    "workspace",
    "$recycle.bin",
    "system volume information",
}


class ConversionError(Exception):
    """An actionable error that should not produce a CLI traceback."""


@dataclass
class Discovery:
    root: Path
    files: list[Path] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)


def private_name(name: str) -> bool:
    return bool(PRIVATE_WORDS.intersection(re.split(r"[\W_]+", name.casefold())))


def linked(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def natural_key(path: Path) -> tuple:
    # Tuple tags prevent comparing integers with strings. README sorts first per folder.
    parts = []
    for part in path.parts:
        readme = Path(part).stem.casefold() == "readme"
        chunks = tuple(
            (0, int(piece)) if piece.isdigit() else (1, piece.casefold())
            for piece in re.split(r"(\d+)", part)
        )
        parts.append((not readme, chunks, part))
    return tuple(parts)


def discover(directory: Path, excludes: list[str] | None = None) -> Discovery:
    directory = directory.expanduser().absolute()
    if not directory.is_dir():
        raise ConversionError(f"Not a directory: {directory}")
    for part in (directory, *directory.parents):
        if linked(part):
            raise ConversionError(f"The input path passes through a link or junction: {part}")
        if private_name(part.name):
            raise ConversionError(f"The input path is inside an excluded private directory: {part}")
    root = directory.resolve()
    result = Discovery(root)
    patterns = [pattern.replace("\\", "/").casefold().rstrip("/") for pattern in excludes or []]

    def reason(path: Path, is_directory: bool) -> str | None:
        relative = path.relative_to(root).as_posix()
        name = path.name.casefold()
        if name.startswith("."):
            return "hidden name"
        if private_name(name):
            return "private name"
        if is_directory and name in EXCLUDED_DIRS:
            return "dependency/generated directory"
        if any(
            fnmatch.fnmatchcase(relative.casefold(), pattern) or fnmatch.fnmatchcase(name, pattern)
            for pattern in patterns
        ):
            return "--exclude pattern"
        return None

    def walk(folder: Path) -> None:
        try:
            with os.scandir(folder) as entries:
                for entry in sorted(entries, key=lambda item: natural_key(Path(item.name))):
                    path = Path(entry.path)
                    # Check names before touching the entry's target or opening it.
                    why = reason(path, True)
                    if why:
                        result.skipped.append((path.relative_to(root).as_posix(), why))
                        continue
                    if linked(path):
                        result.skipped.append((path.relative_to(root).as_posix(), "link/junction"))
                    elif entry.is_dir(follow_symlinks=False):
                        walk(path)
                    elif entry.is_file(follow_symlinks=False):
                        if path.suffix.casefold() in MARKDOWN_SUFFIXES:
                            result.files.append(path)
        except OSError as exc:
            raise ConversionError(f"Cannot scan {folder}: {exc}") from exc

    walk(root)
    result.files.sort(key=lambda path: natural_key(path.relative_to(root)))
    if not result.files:
        raise ConversionError("No Markdown files remain after exclusions.")
    return result
