"""Optional, isolated Pillow worker for the declared dataset transform.

Executed as a file by the chosen Python; the core CLI never imports Pillow.
"""

from __future__ import annotations

import hashlib
import io
import json
import platform
import sys
import warnings
from pathlib import Path

PILLOW = "12.3.0"
MAX_PIXELS = 32_000_000
PROFILE = "rgb-fit-pad-512-lanczos-ivory-v1"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def engine():
    import PIL
    from PIL import features

    if PIL.__version__ != PILLOW:
        raise ValueError(f"Dataset preparation requires Pillow {PILLOW}; found {PIL.__version__}")
    folder = Path(PIL.__file__).parent
    files = {}
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() in {".py", ".pyd", ".so", ".dll"}:
            if path.is_symlink():
                raise ValueError("Pillow implementation redirects")
            files[path.name] = digest(path.read_bytes())
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "python_sha256": digest(Path(sys.executable).read_bytes()),
        "pillow": PIL.__version__,
        "pillow_files": files,
        "codecs": {name: features.version_codec(name) for name in ("jpg", "zlib")},
        "worker_sha256": digest(Path(__file__).read_bytes()),
        "profile": PROFILE,
    }


def transform(source, destination, expected):
    from PIL import Image, ImageFile, ImageOps

    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    ImageFile.LOAD_TRUNCATED_IMAGES = False
    warnings.simplefilter("error", Image.DecompressionBombWarning)
    with source.open("rb") as handle:
        raw = handle.read(32 * 1024**2 + 1)
    if not 0 < len(raw) <= 32 * 1024**2 or digest(raw) != expected:
        raise ValueError("Source image size/hash changed before decoding")
    with Image.open(io.BytesIO(raw), formats=["JPEG", "PNG"]) as image:
        if image.width * image.height > MAX_PIXELS or getattr(image, "n_frames", 1) != 1:
            raise ValueError("Source requires one image with at most 32 million pixels")
        if image.mode not in {"RGB", "L"}:
            raise ValueError("Source must be RGB or grayscale JPEG/PNG; alpha/palette/CMYK refused")
        image.verify()
    with Image.open(io.BytesIO(raw), formats=["JPEG", "PNG"]) as image:
        image.load()
        original_size, mode, format_name = list(image.size), image.mode, image.format
        orientation = image.getexif().get(274, 1)
        if type(orientation) is not int or orientation not in range(1, 9):
            raise ValueError("Invalid EXIF orientation")
        rgb = ImageOps.exif_transpose(image).convert("RGB")
        oriented_size = list(rgb.size)
        source_pixels = digest(rgb.tobytes())
        fitted = ImageOps.contain(rgb, (512, 512), Image.Resampling.LANCZOS)
    offset = [(512 - fitted.width) // 2, (512 - fitted.height) // 2]
    canvas = Image.new("RGB", (512, 512), (245, 240, 225))
    canvas.paste(fitted, (offset[0], offset[1]))
    # A fresh canvas strips source EXIF/ICC metadata; no ICC color conversion is claimed.
    with destination.open("xb") as target:
        canvas.save(target, format="PNG")
        target.flush()
        import os

        os.fsync(target.fileno())
    output = destination.read_bytes()
    with Image.open(io.BytesIO(output)) as checked:
        checked.verify()
    with Image.open(io.BytesIO(output)) as checked:
        checked.load()
        if checked.mode != "RGB" or checked.size != (512, 512):
            raise ValueError("Derived image differs from the declared transform")
        pixels = digest(checked.tobytes())
    if pixels != digest(canvas.tobytes()):
        raise ValueError("Derived PNG decode differs from transformed pixels")
    return {
        "engine": engine(),
        "source_sha256": expected,
        "format": format_name,
        "source_mode": mode,
        "source_size": original_size,
        "exif_orientation": orientation,
        "oriented_size": oriented_size,
        "oriented_rgb_sha256": source_pixels,
        "fitted_size": list(fitted.size),
        "offset": offset,
        "background": [245, 240, 225],
        "output_size": [512, 512],
        "output_sha256": digest(output),
        "output_bytes": len(output),
        "decoded_rgb_sha256": pixels,
        "full_decode": True,
    }


def main():
    try:
        value = (
            engine()
            if sys.argv[1:] == ["--probe"]
            else transform(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])
        )
        print(json.dumps({"ok": True, "value": value}))
        return 0
    except (OSError, ValueError, ImportError, IndexError, Warning) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
