"""Packaged neutral inputs and explicit catalog-bound requests; no runtime work."""

import struct
import zlib

from itov.batch_request import neutral_request, validate_bindings, validate_request
from itov.catalog import canonical_bytes, empty_catalog, require, sha256
from itov.catalog_store import CatalogStore, _atomic_write
from itov.comfyui import parse_json
from itov.locking import file_lock
from itov.qualification import safe_path
from itov.training_data import file_ref, publish, seal


def png_bytes():
    colors = [
        (0, 0, 0),
        (255, 0, 0),
        (0, 255, 0),
        (0, 0, 255),
        (255, 255, 0),
        (255, 0, 255),
        (0, 255, 255),
        (255, 255, 255),
    ]
    rows = b"".join(
        b"\0" + bytes(c for x in range(64) for c in colors[(x // 8 + y // 8) % 8])
        for y in range(64)
    )

    def chunk(kind, value):
        return (
            struct.pack(">I", len(value))
            + kind
            + value
            + struct.pack(">I", zlib.crc32(kind + value))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 64, 64, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def starter(config):
    graph = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "itov-starter.png"}},
        "2": {
            "class_type": "SaveImage",
            "inputs": {"images": ["1", 0], "filename_prefix": "itov/starter"},
        },
    }
    raw = canonical_bytes(graph) + b"\n"
    catalog = empty_catalog()
    catalog["presets"] = [
        {
            "id": "itov-starter",
            "category": "neutral",
            "tags": ["image-copy"],
            "workflow": {"path": "workflows/itov-starter.api.json", "sha256": sha256(raw)},
            "base_model": None,
            "rotation_weight_milli": 1000,
            "seed": None,
        }
    ]
    payloads = {
        "input/itov-starter.png": png_bytes(),
        "workflows/itov-starter.api.json": raw,
        "templates/itov-starter.catalog.json": canonical_bytes(catalog) + b"\n",
    }
    lock = safe_path(config.root, "state/workspace/starter.lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(lock):
        for name, payload in payloads.items():
            path = safe_path(config.root, name)
            require(
                not path.exists() or path.read_bytes() == payload,
                f"Preserve changed starter file: {path}",
            )
        for name, payload in payloads.items():
            path = safe_path(config.root, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                _atomic_write(path, payload, exclusive=True)
        value = seal(
            {
                "version": 1,
                "scope": "workspace_starter",
                "files": [{"path": name, "sha256": sha256(raw)} for name, raw in payloads.items()],
                "limits": "Neutral image I/O only; no model, catalog import, job or acceptance.",
            },
            "starter_id",
        )
        for ref in value["files"]:
            file_ref(config.root, ref)
        destination = safe_path(config.root, f"state/workspace/starters/{value['starter_id']}.json")
        publish(destination, value)
    return {
        **value,
        "ok": True,
        "saved_path": str(destination),
        "artifacts": {name: str(config.root / name) for name in payloads},
    }


def request(config, preset, *, count=1, seed=0, save=False):
    store = CatalogStore(config.root)
    snapshot = store.snapshot(require_clean=True)
    catalog = snapshot.to_dict()["catalog"]
    value = validate_request(
        neutral_request(snapshot.head, preset, count=count, seed=seed), catalog
    )
    entry = next(row for row in catalog["presets"] if row["id"] == preset)
    path, _ = file_ref(config.root, entry["workflow"])
    validate_bindings(entry, value["bindings"][preset], parse_json(path.read_bytes()))
    store.snapshot(expected_head=snapshot.head, require_clean=True)
    result = {
        "scope": "workspace_batch_request",
        "ok": True,
        "request": value,
        "limits": "Neutral presets without seed/LoRA bindings only. Planning submits nothing.",
    }
    if save:
        path = safe_path(
            config.root, f"state/workspace/requests/{sha256(canonical_bytes(value))}.json"
        )
        publish(path, value)
        result["saved_path"] = str(path)
    return result
