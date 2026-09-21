import json

from test_catalog import catalog_assets as catalog_assets

from itov.catalog import canonical_bytes
from itov.cli import main
from itov.config import initialize


def test_catalog_cli_import_verify_show_and_recover(catalog_assets, capsys):
    root, catalog = catalog_assets
    config = initialize(root, root.parent / "comfy")
    source = root / "catalog.json"
    source.write_bytes(canonical_bytes(catalog))
    flags = ["--config", str(config.file), "--json"]
    assert main(["catalog", "validate", str(source), "--check-files", *flags]) == 0
    assert len(json.loads(capsys.readouterr().out)["assets"]) == 4
    assert main(["catalog", "init", *flags]) == 0
    initial = json.loads(capsys.readouterr().out)
    assert main(["catalog", "import", str(source), "--expected-head", initial["head"], *flags]) == 0
    imported = json.loads(capsys.readouterr().out)
    assert imported["events"] == 2
    assert (
        main(["catalog", "verify", "--check-files", "--expected-head", imported["head"], *flags])
        == 0
    )
    assert json.loads(capsys.readouterr().out)["head"] == imported["head"]
    assert main(["catalog", "show", *flags]) == 0
    assert json.loads(capsys.readouterr().out)["snapshot"]["catalog"] == catalog
    assert main(["catalog", "recover", *flags]) == 0
    assert json.loads(capsys.readouterr().out)["recovery"] == "not_needed"
    assert main(["catalog", "verify", "--expected-head", initial["head"], *flags]) == 2
    assert "differs" in json.loads(capsys.readouterr().out)["error"]
    assert main(["catalog", "import", str(source), "--expected-head", initial["head"], *flags]) == 2
    assert "Stale" in json.loads(capsys.readouterr().out)["error"]
    assert main(["catalog", "init", *flags]) == 2
    assert "already initialized" in json.loads(capsys.readouterr().out)["error"]


def test_schema_validation_does_not_require_config_or_write_state(catalog_assets, capsys):
    root, catalog = catalog_assets
    source = root / "catalog.json"
    source.write_bytes(canonical_bytes(catalog))
    assert main(["catalog", "validate", str(source), "--config", "absent.toml"]) == 0
    assert "PASS catalog validate" in capsys.readouterr().out
    assert not (root / "state").exists()
    source.write_text('{"version":99}')
    assert main(["catalog", "validate", str(source), "--json"]) == 2
    assert not json.loads(capsys.readouterr().out)["ok"]


def test_verify_reports_pending_and_recovery_remains_explicit(catalog_assets, capsys, monkeypatch):
    import itov.catalog_store as module

    root, catalog = catalog_assets
    config = initialize(root, root.parent / "comfy")
    flags = ["--config", str(config.file), "--json"]
    assert main(["catalog", "init", *flags]) == 0
    initial = json.loads(capsys.readouterr().out)
    source = root / "catalog.json"
    source.write_bytes(canonical_bytes(catalog))

    def fail(*_args):
        raise OSError("simulated device failure")

    with monkeypatch.context() as patch:
        patch.setattr(module.CatalogStore, "_publish_object", fail)
        assert (
            main(["catalog", "import", str(source), "--expected-head", initial["head"], *flags])
            == 2
        )
    assert "device failure" in json.loads(capsys.readouterr().out)["error"]
    pending = root / "state/catalog/pending.json"
    before = pending.read_bytes()
    assert main(["catalog", "verify", *flags]) == 1
    verified = json.loads(capsys.readouterr().out)
    assert verified["recovery_required"] and verified["head"] == initial["head"]
    assert pending.read_bytes() == before
    assert main(["catalog", "recover", *flags]) == 0
    assert json.loads(capsys.readouterr().out)["recovery"] == "completed"
