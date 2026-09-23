"""Bounded full decoding for evaluation PNG outputs, without ML dependencies."""

from __future__ import annotations

import shutil
import struct
import subprocess
from pathlib import Path

from itov.catalog import integer, object_fields, require, sha256


def image_contract(value):
    object_fields(value, {"width", "height"}, "evaluation image contract")
    for key in value:
        integer(value[key], key)
        require(512 <= value[key] <= 1024 and value[key] % 64 == 0, "Unsupported image dimensions")
    return dict(value)


def image_tools():
    from itov.qualification import _file

    executable = shutil.which("ffmpeg")
    require(executable is not None, "Evaluation image validation requires ffmpeg on PATH")
    return _file(Path(executable))


def verify_image(path: Path, expected):
    expected = image_contract(expected)
    require(33 <= path.stat().st_size <= 32 * 1024**2, "Evaluation PNG size is unsupported")
    raw = path.read_bytes()
    require(raw[:16] == b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR", "Evaluation output must be PNG")
    require(
        struct.unpack(">II", raw[16:24]) == (expected["width"], expected["height"]),
        "Evaluation image dimensions differ",
    )
    decoder = image_tools()
    try:
        result = subprocess.run(
            [
                decoder["path"],
                "-nostdin",
                "-v",
                "error",
                "-xerror",
                "-f",
                "png_pipe",
                "-i",
                str(path),
                "-frames:v",
                "2",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "pipe:1",
            ],
            capture_output=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as error:
        raise ValueError("Evaluation image decode exceeded 30 seconds") from error
    require(
        result.returncode == 0 and not result.stderr,
        "Evaluation image decode failed: " + result.stderr.decode(errors="replace")[-2000:],
    )
    require(
        len(result.stdout) == expected["width"] * expected["height"] * 3,
        "Expected exactly one complete RGB evaluation image",
    )
    require(path.read_bytes() == raw, "Evaluation image changed during decode")
    return {
        "scope": "png_full_decode",
        **expected,
        "bytes": len(raw),
        "sha256": sha256(raw),
        "decoded_rgb_sha256": sha256(result.stdout),
        "decoder_sha256": decoder["sha256"],
    }
