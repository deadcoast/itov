"""Create neutral procedural PNG/caption pairs for a smoke test, never quality training."""

import argparse
import json
import struct
import zlib
from pathlib import Path

from itov.catalog import canonical_bytes, relative_path, sha256
from itov.config import load_config
from itov.qualification import safe_path


def geometry(index, size=512):
    rows = []
    center_x, center_y = 130 + index * 7, 160 + index * 9
    square_x, square_y = 290 - index * 4, 280 + index * 3
    radius = 42 + index
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            color = (245, 245, 240)
            if (x - center_x) ** 2 + (y - center_y) ** 2 <= radius**2:
                color = (210, 40, 30)
            if square_x <= x < square_x + 86 and square_y <= y < square_y + 86:
                color = (35, 70, 205)
            row.extend(color)
        rows.append(row)

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + chunk(b"IEND", b"")
    )


def create(config, relative="training/data/neutral-geometry-v1"):
    relative_path(relative, "fixture directory")
    folder = safe_path(config.root, relative)
    if folder.exists():
        raise ValueError("Fixture directory already exists; preserve its data")
    payloads = []
    samples = []
    for index in range(10):
        name = f"geometry-{index:02d}"
        image = geometry(index)
        caption = (
            b"itovgeom flat geometric composition, a red disk and a blue square "
            b"on an ivory background\n"
        )
        image_ref = {"path": relative + "/" + name + ".png", "sha256": sha256(image)}
        caption_ref = {"path": relative + "/" + name + ".txt", "sha256": sha256(caption)}
        samples.append(
            {
                "id": name,
                "split": "train" if index < 8 else "validation",
                "group": name,
                "source": image_ref,
                "image": image_ref,
                "caption": caption_ref,
            }
        )
        payloads.extend([(name + ".png", image), (name + ".txt", caption)])
    manifest = {
        "version": 1,
        "id": "neutral-geometry-v1",
        "purpose": "smoke",
        "origin": {
            "title": "ITOV procedural geometric test images",
            "reference": "scripts/create_training_fixture.py sha256:"
            + sha256(Path(__file__).read_bytes()),
        },
        "rights": {
            "basis": "Generated project test fixtures; no external media",
            "reference": "scripts/create_training_fixture.py",
            "training_permitted": True,
        },
        "preprocessing": "prepared-square-rgb-png-v1",
        "samples": samples,
    }
    folder.mkdir(parents=True)
    for name, raw in payloads + [("dataset.json", canonical_bytes(manifest) + b"\n")]:
        with (folder / name).open("xb") as output:
            output.write(raw)
    return {
        "manifest": str(folder / "dataset.json"),
        "train": 8,
        "validation": 2,
        "purpose": "smoke",
        "limits": (
            "Procedural variants share one generator; split groups do not establish "
            "natural-data generalization. Never production promotion evidence."
        ),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("workspace/itov.toml"))
    args = parser.parse_args()
    print(json.dumps(create(load_config(args.config)), indent=2))
