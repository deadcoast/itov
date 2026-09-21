import copy
import json
from pathlib import Path

import pytest

from itov.catalog import (
    canonical_bytes,
    empty_catalog,
    load_catalog,
    sha256,
    validate_catalog,
    verify_assets,
)


@pytest.fixture
def catalog_assets(tmp_path):
    root = tmp_path / "workspace"
    (root / "workflows").mkdir(parents=True)
    (root / "models_shared").mkdir()
    raw = Path("examples/image-copy.api.json").read_bytes()
    (root / "workflows/copy.json").write_bytes(raw)
    catalog = empty_catalog()
    catalog["presets"] = [
        {
            "id": "copy",
            "category": "neutral",
            "tags": ["test"],
            "workflow": {"path": "workflows/copy.json", "sha256": sha256(raw)},
            "base_model": "fixture-model",
            "rotation_weight_milli": 1000,
            "seed": {"base": 42, "step": 7},
        }
    ]
    for name, slot in (("grain", "style"), ("light", "lighting"), ("camera", "camera")):
        # Deliberate plain-byte fixtures, not actual LoRA or inference qualification.
        data = f"fixture {name}".encode()
        path = f"models_shared/{name}.bin"
        (root / path).write_bytes(data)
        catalog["loras"].append(
            {
                "id": name,
                "asset": {"path": path, "sha256": sha256(data)},
                "category": slot,
                "slot": slot,
                "base_models": ["fixture-model"],
                "strength_milli": {"min": 100, "recommended": 500, "max": 900},
                "rotation_weight_milli": 1000,
                "trigger_words": [name],
                "status": "candidate",
            }
        )
    catalog["compatibility"] = {
        "hard_conflicts": [["grain", "light"]],
        "soft_conflicts": [["grain", "camera"]],
        "synergies": [{"loras": ["light", "camera"], "weight_milli": 1500}],
        "preset_pairings": [{"preset": "copy", "loras": ["light", "camera"]}],
    }
    return root, catalog


def test_catalog_round_trip_unicode_and_pinned_files(catalog_assets, tmp_path):
    root, catalog = catalog_assets
    catalog["presets"][0]["tags"].append("日本語")
    raw = canonical_bytes(catalog)
    path = tmp_path / "catalog.json"
    path.write_bytes(raw)
    assert load_catalog(path) == catalog
    assert len(verify_assets(catalog, root)) == 4
    assert b"\\u65e5" not in raw


@pytest.mark.parametrize("value", [0.1, float("nan"), float("inf"), {1: "key"}, 2**64])
def test_canonical_rejects_ambiguous_or_out_of_range_values(value):
    with pytest.raises(ValueError):
        canonical_bytes(value)


def test_integer_encoding_does_not_round_strengths():
    assert canonical_bytes({"weight": 1001, "label": "é"}) == b'{"label":"\xc3\xa9","weight":1001}'
    assert canonical_bytes({"a": 1, "b": 2}) == canonical_bytes({"b": 2, "a": 1})


@pytest.mark.parametrize(
    "path",
    [
        "../outside",
        "/root/file",
        "C:/file",
        "one\\two",
        "file:stream",
        "a//b",
        "a/./b",
        "a/../b",
        "CON.txt",
        "a/NUL",
        "a/b.",
        "a/b ",
        "a/*",
        "a/\u0000b",
    ],
)
def test_asset_path_rejects_portability_and_traversal_traps(catalog_assets, path):
    _, catalog = catalog_assets
    catalog["presets"][0]["workflow"]["path"] = path
    with pytest.raises(ValueError):
        validate_catalog(catalog)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda c: c.update(version=True),
        lambda c: c.update(unknown="key"),
        lambda c: c["presets"].append(copy.deepcopy(c["presets"][0])),
        lambda c: c["loras"].append(copy.deepcopy(c["loras"][0])),
        lambda c: c["presets"][0].update(rotation_weight_milli=True),
        lambda c: c["presets"][0].update(rotation_weight_milli=0),
        lambda c: c["presets"][0]["seed"].update(base=-1),
        lambda c: c["presets"][0]["seed"].update(step=0),
        lambda c: c["loras"][0]["strength_milli"].update(recommended=901),
        lambda c: c["loras"][0]["strength_milli"].update(recommended=0.5),
        lambda c: c["loras"][0].update(status="approved-by-tests"),
        lambda c: c["loras"][0].update(base_models=[]),
        lambda c: c["loras"][1]["asset"].update(path="MODELS_SHARED/GRAIN.BIN"),
        lambda c: c["compatibility"]["hard_conflicts"].append(["grain", "missing"]),
        lambda c: c["compatibility"]["hard_conflicts"].append(["light", "grain"]),
        lambda c: c["compatibility"]["soft_conflicts"].append(["light", "grain"]),
        lambda c: c["compatibility"]["synergies"][0].update(loras=["grain", "light"]),
        lambda c: c["compatibility"]["preset_pairings"][0].update(preset="missing"),
        lambda c: c["presets"][0].update(base_model="another-model"),
        lambda c: c["presets"][0]["workflow"].update(sha256="A" * 64),
        lambda c: c["presets"][0].update(tags=["test", "test"]),
    ],
)
def test_invalid_contracts_are_rejected(catalog_assets, mutation):
    _, catalog = catalog_assets
    mutation(catalog)
    with pytest.raises(ValueError):
        validate_catalog(catalog)


def test_bad_file_hash_and_invalid_workflow_rejected(catalog_assets):
    root, catalog = catalog_assets
    path = root / "workflows/copy.json"
    path.write_bytes(b'{"nodes":[]}')
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        verify_assets(catalog, root)
    catalog["presets"][0]["workflow"]["sha256"] = sha256(path.read_bytes())
    with pytest.raises(ValueError, match="Invalid API workflow"):
        verify_assets(catalog, root)


@pytest.mark.parametrize(
    "raw",
    [
        '{"version":1,"version":1}',
        '{"number": NaN}',
        '{"number": 1e999}',
        '{"version":1,"presets":[],"loras":[],"compatibility":null}',
    ],
)
def test_invalid_json_documents_do_not_load(tmp_path, raw):
    path = tmp_path / "catalog.json"
    path.write_text(raw)
    with pytest.raises(ValueError):
        load_catalog(path)


def test_catalog_input_size_limit(tmp_path, monkeypatch):
    import itov.catalog as module

    monkeypatch.setattr(module, "MAX_DOCUMENT_BYTES", 10)
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(empty_catalog()))
    with pytest.raises(ValueError, match="exceeds"):
        load_catalog(path)
