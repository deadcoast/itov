"""Prepare the inspected eight-work pilot from retained Met JPEG/metadata files.

Run with the optional training Python (Pillow). No network or model execution.
Refuses existing prepared files; original sources remain untouched.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from itov import curation, training_data
from itov.catalog import sha256

SELECTION = {
    11737: (
        "validation",
        "oil painting of a plate of sliced cake, grapes and a glass on a table, "
        "dark brown background",
    ),
    11939: (
        "train",
        "oil painting of an abundant arrangement of grapes, peaches and other fruit "
        "in several bowls on a table, dark foliage behind",
    ),
    16590: (
        "train",
        "oil painting of pale grapes, peaches, a bowl of red fruit and a tall pitcher "
        "on a draped table against a dark background",
    ),
    16592: (
        "train",
        "oil painting of one hanging bunch of red grapes against a muted green background",
    ),
    436305: (
        "train",
        "oil painting of a brown ceramic jug, a glass, sliced lemon, bread and walnuts "
        "on a gray tabletop against a dark background",
    ),
    436450: (
        "validation",
        "oil painting of several pears and a green bottle on a white cloth, "
        "warm textured background",
    ),
    488147: (
        "train",
        "colorful angular oil painting of a green pitcher, a bowl of fruit and a "
        "small glass on a patterned table",
    ),
    898372: (
        "train",
        "oil painting of blue flowers and green fern leaves against a dark brown background",
    ),
}


def prepare(folder, root):
    from PIL import Image, ImageOps

    folder, root = folder.resolve(), root.resolve()
    folder.relative_to(root)
    prepared = folder / "prepared"
    prepared.mkdir()  # Exclusive: do not silently regenerate or alter a frozen dataset.

    def ref(path):
        return {"path": path.relative_to(root).as_posix(), "sha256": sha256(path.read_bytes())}

    samples, works, decodes = [], [], []
    for oid, (split, description) in SELECTION.items():
        metadata_path = folder / "metadata" / f"{oid}.json"
        metadata = json.loads(metadata_path.read_bytes())
        assert metadata["objectID"] == oid and metadata["isPublicDomain"] is True
        source = folder / "sources" / f"{oid}.jpg"
        with Image.open(source) as image:
            image.verify()
        with Image.open(source) as image:
            image.load()
            size = image.size
            fitted = ImageOps.contain(
                ImageOps.exif_transpose(image).convert("RGB"), (512, 512), Image.Resampling.LANCZOS
            )
        canvas = Image.new("RGB", (512, 512), (245, 240, 225))
        canvas.paste(fitted, ((512 - fitted.width) // 2, (512 - fitted.height) // 2))
        target = prepared / f"{oid}.png"
        canvas.save(target)
        caption = prepared / f"{oid}.txt"
        caption.write_text("itovstill " + description + "\n", encoding="utf-8")
        sample = {
            "id": f"met-{oid}",
            "group": f"met-{oid}",
            "split": split,
            "source": ref(source),
            "image": ref(target),
            "caption": ref(caption),
        }
        samples.append(sample)
        works.append(
            {
                "sample": sample["id"],
                "object_id": oid,
                "metadata": ref(metadata_path),
                "image_url": metadata["primaryImageSmall"],
                "caption_note": "Assistant description after source contact-sheet inspection; "
                "no artist-name trigger or claim of independent human validation.",
                "selection_note": "Color oil still life; no people. Complete composition "
                "preserved by fit and ivory padding. Varied painting styles retained.",
            }
        )
        decodes.append(
            {
                "object_id": oid,
                "source_size": list(size),
                "fitted_size": list(fitted.size),
                "decoded_rgb_sha256": sha256(canvas.tobytes()),
                "full_decode": True,
            }
        )
    dataset = {
        "version": 1,
        "id": "met-still-life-pilot-v1",
        "purpose": "training",
        "origin": {"title": "Eight-work Met still-life pilot", "reference": curation.POLICY},
        "rights": {
            "basis": "Met Open Access CC0 declaration and isPublicDomain metadata",
            "reference": curation.POLICY,
            "training_permitted": True,
        },
        "preprocessing": "prepared-square-rgb-png-v1",
        "samples": samples,
    }
    training_data.publish(folder / "dataset.json", dataset)
    report = training_data.prepare(root, folder / "dataset.json")
    declaration = {
        "version": 1,
        "dataset": ref(Path(report["saved_path"])),
        "curator": "Codex assistant",
        "selection_policy": "Bounded color oil still-life "
        "pilot, six train/two validation works, artist-disjoint locally. Excluded "
        "monochrome reproduction 10895 and fish/vanitas/trompe-l'oeil subjects. "
        "Provider access limits prevented expanding the pilot; no population claim.",
        "rights": {
            "provider": "met-open-access",
            "policy_url": curation.POLICY,
            "policy_snapshot": ref(folder / "policy-observation.json"),
        },
        "transform": curation.TRANSFORM,
        "works": works,
    }
    training_data.publish(folder / "curation.json", declaration)
    verified = curation.validate(root, folder / "curation.json", save=True)
    training_data.publish(
        folder / "decode-receipt.json",
        {
            "scope": "Pillow full decode and deterministic fit-pad observations",
            "images": decodes,
            "pillow_version": Image.__version__,
            "script_sha256": sha256(Path(__file__).read_bytes()),
            "dataset_id": report["dataset_id"],
            "curation_id": verified["curation_id"],
        },
    )
    print(
        json.dumps(
            {
                "dataset_id": report["dataset_id"],
                "curation_id": verified["curation_id"],
                "counts": report["counts"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--workspace", type=Path, default=Path("workspace"))
    args = parser.parse_args()
    prepare(args.folder, args.workspace)
