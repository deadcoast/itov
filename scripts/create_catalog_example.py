"""Create a neutral catalog and pin the copied workflow's actual checkout bytes."""

from __future__ import annotations

import argparse
from pathlib import Path

from itov.catalog import canonical_bytes, empty_catalog, require, sha256, verify_assets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", nargs="?", type=Path, default=Path("workspace"))
    args = parser.parse_args()
    root = args.workspace.resolve()
    workflow = root / "workflows/catalog-copy.api.json"
    target = root / "templates/neutral.catalog.json"
    for path in (workflow, target):
        require(path.resolve() == path.absolute(), f"Destination redirects: {path}")
        require(not path.exists(), f"Refusing to overwrite {path}")
    source = Path(__file__).resolve().parents[1] / "examples/image-copy.api.json"
    raw = source.read_bytes()
    catalog = empty_catalog()
    catalog["presets"] = [
        {
            "id": "neutral-copy",
            "category": "neutral",
            "tags": ["image-copy"],
            "workflow": {"path": "workflows/catalog-copy.api.json", "sha256": sha256(raw)},
            "base_model": None,
            "rotation_weight_milli": 1000,
            "seed": None,
        }
    ]
    workflow.parent.mkdir(parents=True, exist_ok=True)
    with workflow.open("xb") as out:
        out.write(raw)
    verify_assets(catalog, root)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as out:
        out.write(canonical_bytes(catalog) + b"\n")
    print(f"Created {target}")


if __name__ == "__main__":
    main()
