import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from test_catalog import catalog_assets as catalog_assets

from itov.catalog import canonical_bytes, empty_catalog, sha256
from itov.catalog_store import CatalogStore
from itov.locking import file_lock


def test_immutable_snapshots_and_stale_updates(catalog_assets):
    root, catalog = catalog_assets
    store = CatalogStore(root)
    initial = store.initialize()
    imported = store.import_catalog(catalog, expected_head=initial.head)
    assert imported.report()["events"] == 2
    assert initial.to_dict()["catalog"] == empty_catalog()
    assert store.snapshot().head == imported.head
    copy = imported.to_dict()
    copy["catalog"]["loras"].clear()
    assert len(imported.to_dict()["catalog"]["loras"]) == 3
    catalog["presets"][0]["tags"].append("edited")
    with pytest.raises(ValueError, match="Stale"):
        store.import_catalog(catalog, expected_head=initial.head)
    assert store.snapshot().head == imported.head
    assert len(list((store.root / "objects").glob("*.json"))) == 2


def test_same_import_is_idempotent_but_still_checks_assets(catalog_assets):
    root, catalog = catalog_assets
    store = CatalogStore(root)
    initial = store.initialize()
    imported = store.import_catalog(catalog, expected_head=initial.head)
    assert store.import_catalog(catalog, expected_head=imported.head) == imported
    (root / catalog["loras"][0]["asset"]["path"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        store.import_catalog(catalog, expected_head=imported.head)
    assert store.snapshot() == imported
    assert not store.recovery_required


def test_missing_head_never_silently_reinitializes(catalog_assets):
    root, _ = catalog_assets
    store = CatalogStore(root)
    store.initialize()
    (store.root / "HEAD").unlink()
    with pytest.raises(ValueError, match="HEAD is missing"):
        store.snapshot()
    with pytest.raises(ValueError, match="Snapshots exist"):
        store.initialize()


def test_snapshot_tampering_and_torn_head_are_reported(catalog_assets):
    root, _ = catalog_assets
    store = CatalogStore(root)
    initial = store.initialize()
    path = store.root / "objects" / f"{initial.head}.json"
    path.write_bytes(initial.raw[:-4])
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        store.snapshot()
    assert path.read_bytes() == initial.raw[:-4]
    (store.root / "HEAD").write_text("torn")
    with pytest.raises(ValueError, match="SHA-256"):
        store.snapshot()


def test_recomputed_snapshot_digest_cannot_hide_ledger_edit(catalog_assets):
    root, _ = catalog_assets
    store = CatalogStore(root)
    initial = store.initialize()
    value = initial.to_dict()
    value["ledger"][0]["created_at"] = "2025-01-01T00:00:00.000000Z"
    raw = canonical_bytes(value) + b"\n"
    head = sha256(raw)
    (store.root / "objects" / f"{head}.json").write_bytes(raw)
    (store.root / "HEAD").write_bytes((head + "\n").encode())
    with pytest.raises(ValueError, match="hash mismatch"):
        store.snapshot()


# Exit after completed durable write boundaries, bypassing Python cleanup/finally.
CRASH_SCRIPT = """
import os, sys
from pathlib import Path
from itov.catalog import load_catalog
import itov.catalog_store as module
store = module.CatalogStore(Path(sys.argv[1]))
original = module._atomic_write
def crash(path, raw, **kwargs):
    boundary = sys.argv[4]
    if ((boundary == 'partial_object' and path.parent.name == 'objects') or
        (boundary == 'partial_head' and path.name == 'HEAD')):
        with (path.parent / '.pending-interrupted').open('wb') as out:
            out.write(raw[:len(raw)//2])
            out.flush()
            os.fsync(out.fileno())
        os._exit(91)
    original(path, raw, **kwargs)
    boundary = sys.argv[4]
    if ((boundary == 'intent' and path.name == 'pending.json') or
        (boundary == 'object' and path.parent.name == 'objects') or
        (boundary == 'head' and path.name == 'HEAD')):
        os._exit(91)
module._atomic_write = crash
if sys.argv[2] == 'init':
    store.initialize()
else:
    store.import_catalog(load_catalog(Path(sys.argv[2])), expected_head=sys.argv[3])
"""


@pytest.mark.parametrize("boundary", ["intent", "object", "head", "partial_object", "partial_head"])
@pytest.mark.parametrize("initializing", [False, True])
def test_process_crash_recovery_at_each_commit_boundary(catalog_assets, boundary, initializing):
    root, catalog = catalog_assets
    store = CatalogStore(root)
    if initializing:
        head, source = "unused", "init"
    else:
        head = store.initialize().head
        source = str(root / "incoming.json")
        Path(source).write_bytes(canonical_bytes(catalog))
    child = subprocess.run(
        [sys.executable, "-c", CRASH_SCRIPT, str(root), source, head, boundary],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert child.returncode == 91, child.stderr
    assert store.recovery_required
    intent_before = (store.root / "pending.json").read_bytes()
    intent = json.loads(intent_before)
    if not initializing:
        assert store.snapshot().head == (intent["after"] if boundary == "head" else head)
        with pytest.raises(ValueError, match="Pending"):
            store.import_catalog(catalog, expected_head=head)
    result = store.recover()
    assert result["recovery"] == ("already_committed" if boundary == "head" else "completed")
    assert result["events"] == (1 if initializing else 2)
    assert result["head"] == intent["after"]
    assert not store.recovery_required
    assert store.recover()["recovery"] == "not_needed"
    assert store.snapshot().to_dict()["catalog"] == (empty_catalog() if initializing else catalog)
    assert (store.root / "catalog.lock").exists()


def _leave_pending(store, catalog, monkeypatch):
    def unavailable(_snapshot):
        raise OSError("simulated disk failure")

    with monkeypatch.context() as patch:
        patch.setattr(store, "_publish_object", unavailable)
        with pytest.raises(OSError, match="disk failure"):
            store.import_catalog(catalog, expected_head=store.snapshot().head)


def test_invalid_or_diverged_intent_is_preserved(catalog_assets, monkeypatch):
    root, catalog = catalog_assets
    store = CatalogStore(root)
    store.initialize()
    _leave_pending(store, catalog, monkeypatch)
    path = store.root / "pending.json"
    raw = path.read_bytes()
    path.write_bytes(raw[:-3])
    with pytest.raises(ValueError):
        store.recover()
    assert path.read_bytes() == raw[:-3]
    path.write_bytes(raw)
    (store.root / "HEAD").write_bytes(("f" * 64 + "\n").encode())
    with pytest.raises(ValueError, match="diverged"):
        store.recover()
    assert path.read_bytes() == raw


def test_recovery_will_not_overwrite_corrupt_snapshot(catalog_assets, monkeypatch):
    root, catalog = catalog_assets
    store = CatalogStore(root)
    store.initialize()
    _leave_pending(store, catalog, monkeypatch)
    intent = json.loads((store.root / "pending.json").read_bytes())
    path = store.root / "objects" / f"{intent['after']}.json"
    path.write_bytes(b"preserve me")
    with pytest.raises(ValueError, match="Existing snapshot differs"):
        store.recover()
    assert path.read_bytes() == b"preserve me"
    assert store.recovery_required


def test_failure_before_intent_publication_leaves_previous_head(catalog_assets, monkeypatch):
    import itov.catalog_store as module

    root, catalog = catalog_assets
    store = CatalogStore(root)
    initial = store.initialize()
    original = module.os.link

    def fail(source, destination):
        if Path(destination).name == "pending.json":
            raise OSError("disk full")
        return original(source, destination)

    monkeypatch.setattr(module.os, "link", fail)
    with pytest.raises(OSError, match="disk full"):
        store.import_catalog(catalog, expected_head=initial.head)
    assert store.snapshot() == initial
    assert not store.recovery_required
    assert not list(store.root.glob(".pending-*"))


def test_two_process_writers_cannot_lose_a_revision(catalog_assets):
    root, catalog = catalog_assets
    store = CatalogStore(root)
    initial = store.initialize()
    source = root / "incoming.json"
    source.write_bytes(canonical_bytes(catalog))
    script = """
import sys
from pathlib import Path
from itov.catalog import load_catalog
from itov.catalog_store import CatalogStore
print('ready', flush=True)
sys.stdin.read(1)
try:
    snapshot = CatalogStore(Path(sys.argv[1])).import_catalog(
        load_catalog(Path(sys.argv[2])), expected_head=sys.argv[3])
    print(snapshot.head)
except ValueError as error:
    print(str(error))
    sys.exit(2)
"""
    children = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(root), str(source), initial.head],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    try:
        for child in children:
            assert child.stdout.readline().strip() == "ready"
        for child in children:
            child.stdin.write("x")
            child.stdin.flush()
        outputs = [child.communicate(timeout=10) for child in children]
        assert sorted(child.returncode for child in children) == [0, 2], outputs
        assert any("Stale catalog head" in stdout for stdout, _ in outputs)
        assert store.snapshot().report()["events"] == 2
        assert not store.recovery_required
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)


def test_lock_timeout_is_bounded_and_does_not_steal(catalog_assets):
    root, _ = catalog_assets
    store = CatalogStore(root, lock_timeout=0.1)
    store.initialize()
    lock = store.root / "catalog.lock"
    with file_lock(lock):
        started = time.monotonic()
        with pytest.raises(ValueError, match="Another process"):
            store.recover()
        assert time.monotonic() - started < 2
        assert lock.is_file()
    assert store.recover()["recovery"] == "not_needed"


def test_readers_keep_consistent_generations_during_imports(catalog_assets):
    root, catalog = catalog_assets
    store = CatalogStore(root)
    current = store.initialize()
    script = """
import sys, time
from pathlib import Path
from itov.catalog_store import CatalogStore
store = CatalogStore(Path(sys.argv[1]))
print('ready', flush=True)
sys.stdin.read(1)
for _ in range(80):
    snap = store.snapshot()
    value = snap.to_dict()
    assert len(value['ledger']) == snap.report()['events']
    time.sleep(0.002)
print('consistent', flush=True)
"""
    with subprocess.Popen(
        [sys.executable, "-c", script, str(root)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as child:
        assert child.stdout.readline().strip() == "ready"
        child.stdin.write("x")
        child.stdin.flush()
        for index in range(12):
            catalog["presets"][0]["tags"] = [f"revision-{index}"]
            prior = current
            current = store.import_catalog(catalog, expected_head=prior.head)
            assert prior.report()["events"] == index + 1
        output, error = child.communicate(timeout=10)
        assert child.returncode == 0 and "consistent" in output, error
    assert store.snapshot().report()["events"] == 13
    assert not store.recovery_required


@pytest.mark.skipif(os.name != "nt", reason="Windows junction qualification")
def test_windows_junction_cannot_redirect_catalog_or_assets(catalog_assets, tmp_path):
    root, catalog = catalog_assets
    outside = tmp_path / "outside"
    outside.mkdir()
    junction = root / "redirect"
    # mklink creates only this owned test junction; no deletion/move shell composition.
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    try:
        catalog["loras"][0]["asset"]["path"] = "redirect/asset.bin"
        store = CatalogStore(root)
        initial = store.initialize()
        with pytest.raises(ValueError, match="escapes workspace"):
            store.import_catalog(catalog, expected_head=initial.head)
        redirected = CatalogStore(root)
        redirected.root = junction / "catalog"
        with pytest.raises(ValueError, match="redirects"):
            redirected.initialize()
        assert not list(outside.iterdir())
    finally:
        junction.rmdir()  # Remove the link itself, never its target.
