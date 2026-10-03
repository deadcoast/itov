"""Isolated optional decoder for review fingerprints, never a duplicate verdict."""

from __future__ import annotations

import io
import json
import sys
import warnings
from pathlib import Path

# -I excludes the script directory. Resolve our decoder through its packaged name.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from itov.dataset_images import MAX_PIXELS, digest
from itov.dataset_images import engine as decode_engine

PROFILE = "oriented-rgb-dhash64-ahash64-v1"


def engine():
    return {
        "profile": PROFILE,
        "worker_sha256": digest(Path(__file__).read_bytes()),
        "decoder": decode_engine(),
    }


def describe(path, expected):
    from PIL import Image, ImageFile, ImageOps

    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    ImageFile.LOAD_TRUNCATED_IMAGES = False
    warnings.simplefilter("error", Image.DecompressionBombWarning)
    with path.open("rb") as source:
        raw = source.read(32 * 1024**2 + 1)
    if not 0 < len(raw) <= 32 * 1024**2 or digest(raw) != expected:
        raise ValueError("Review image size/hash differs")
    with Image.open(io.BytesIO(raw), formats=["JPEG", "PNG"]) as image:
        if image.width * image.height > MAX_PIXELS or getattr(image, "n_frames", 1) != 1:
            raise ValueError("Review needs a single image of at most 32 million pixels")
        if image.mode not in {"RGB", "L"}:
            raise ValueError("Review supports RGB/L JPEG/PNG only")
        image.verify()
    with Image.open(io.BytesIO(raw), formats=["JPEG", "PNG"]) as image:
        image.load()
        original = list(image.size)
        orientation = image.getexif().get(274, 1)
        if type(orientation) is not int or orientation not in range(1, 9):
            raise ValueError("Invalid review EXIF orientation")
        rgb = ImageOps.exif_transpose(image).convert("RGB")
    gray = rgb.convert("L")
    # L-mode bytes are the same scalar 8-bit intensities used by these hashes.
    d = gray.resize((9, 8), Image.Resampling.LANCZOS).tobytes()
    a = gray.resize((8, 8), Image.Resampling.LANCZOS).tobytes()
    dhash = sum(
        (d[y * 9 + x] > d[y * 9 + x + 1]) << (y * 8 + x) for y in range(8) for x in range(8)
    )
    ahash = sum((n * 64 >= sum(a)) << i for i, n in enumerate(a))
    low, high = gray.getextrema()
    if not isinstance(low, int) or not isinstance(high, int):
        raise ValueError("Expected grayscale intensity extrema")
    return {
        "source_sha256": expected,
        "source_size": original,
        "oriented_size": list(rgb.size),
        "rgb_sha256": digest(rgb.tobytes()),
        "dhash": f"{dhash:016x}",
        "ahash": f"{ahash:016x}",
        "luma_range": high - low,
        "engine": engine(),
    }


def main():
    try:
        value = (
            engine() if sys.argv[1:] == ["--probe"] else describe(Path(sys.argv[1]), sys.argv[2])
        )
        print(json.dumps({"ok": True, "value": value}))
        return 0
    except (OSError, ValueError, ImportError, IndexError, Warning) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
