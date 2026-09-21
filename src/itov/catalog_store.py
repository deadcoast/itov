"""Copy-on-write catalog generations, a single commit pointer, and redo recovery."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from itov.catalog import (
    MAX_DOCUMENT_BYTES,
    canonical_bytes,
    digest,
    empty_catalog,
    object_fields,
    read_document,
    require,
    sha256,
    validate_catalog,
    verify_assets,
)
from itov.comfyui import parse_json
from itov.ledger import new_event, verify_ledger
from itov.locking import file_lock


def _encoded(value) -> bytes:
    raw = canonical_bytes(value) + b"\n"
    require(len(raw) <= MAX_DOCUMENT_BYTES, "Catalog store document exceeds size limit")
    return raw


def _atomic_write(path: Path, raw: bytes, *, exclusive: bool = False):
    """Same-directory fsynced temp; the authoritative name is never partly written."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".pending-", delete=False) as out:
            temporary = Path(out.name)
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
        if exclusive:
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class Snapshot:
    """Only immutable bytes are retained; callers receive independent parsed copies."""

    head: str
    raw: bytes

    def to_dict(self) -> dict:
        return parse_json(self.raw)

    def report(self) -> dict:
        value = self.to_dict()
        return {
            "ok": True,
            "head": self.head,
            "ledger_head": value["ledger"][-1]["row_hash"],
            "events": len(value["ledger"]),
            "presets": len(value["catalog"]["presets"]),
            "loras": len(value["catalog"]["loras"]),
        }


def _snapshot(raw: bytes, head: str) -> Snapshot:
    require(sha256(raw) == head, "Snapshot SHA-256 mismatch")
    value = parse_json(raw)
    object_fields(value, {"version", "catalog", "ledger"}, "snapshot")
    require(type(value["version"]) is int and value["version"] == 1, "Invalid snapshot version")
    validate_catalog(value["catalog"])
    verify_ledger(value["ledger"], value["catalog"])
    require(_encoded(value) == raw, "Snapshot is not canonically encoded")
    return Snapshot(head, raw)


class CatalogStore:
    def __init__(self, workspace: Path, *, lock_timeout: float = 5):
        self.workspace = workspace.resolve()
        self.root = self.workspace / "state" / "catalog"
        self.lock_timeout = lock_timeout

    def _path(self, relative: str) -> Path:
        path = self.root / relative
        require(
            path.resolve() == path.absolute() and not path.is_symlink(),
            f"Catalog store path redirects: {path}",
        )
        return path

    def _prepare(self):
        self._path("objects").mkdir(parents=True, exist_ok=True)

    def _head(self, *, missing_ok: bool = False) -> str | None:
        path = self._path("HEAD")
        try:
            raw = read_document(path)
        except FileNotFoundError:
            if missing_ok:
                return None
            raise ValueError(
                "Catalog HEAD is missing; initialize a new store or inspect recovery"
            ) from None
        value = raw.decode("ascii").removesuffix("\n")
        digest(value, "HEAD")
        require(raw == (value + "\n").encode("ascii"), "Invalid HEAD encoding")
        return value

    @property
    def recovery_required(self) -> bool:
        return self._path("pending.json").exists()

    def _clean(self):
        require(not self.recovery_required, "Pending catalog transaction; run catalog recover")

    def _load(self, head: str) -> Snapshot:
        digest(head, "snapshot head")
        return _snapshot(read_document(self._path(f"objects/{head}.json")), head)

    def snapshot(self) -> Snapshot:
        require(self.root.is_dir(), "Catalog is not initialized")
        # Protect the short HEAD read from Windows replacement/share conflicts.
        # Load immutable bytes after releasing ownership; generations are never deleted.
        with file_lock(self._path("catalog.lock"), timeout=self.lock_timeout):
            head = self._head()
        return self._load(head)

    def _publish_object(self, snapshot: Snapshot):
        path = self._path(f"objects/{snapshot.head}.json")
        if path.exists():
            require(
                read_document(path) == snapshot.raw,
                "Existing snapshot differs; preserve and inspect",
            )
        else:
            _atomic_write(path, snapshot.raw, exclusive=True)

    def _commit(self, before: str | None, catalog: dict, ledger: list) -> Snapshot:
        value = {"version": 1, "catalog": catalog, "ledger": [*ledger, new_event(catalog, ledger)]}
        raw = _encoded(value)
        snapshot = _snapshot(raw, sha256(raw))
        # Full redo intent is durable before any generation or HEAD is published.
        intent = {"version": 1, "before": before, "after": snapshot.head, "snapshot": value}
        _atomic_write(self._path("pending.json"), _encoded(intent), exclusive=True)
        self._publish_object(snapshot)
        _atomic_write(self._path("HEAD"), (snapshot.head + "\n").encode("ascii"))
        self._path("pending.json").unlink()
        return snapshot

    def initialize(self) -> Snapshot:
        self._prepare()
        with file_lock(self._path("catalog.lock"), timeout=self.lock_timeout):
            self._clean()
            require(self._head(missing_ok=True) is None, "Catalog is already initialized")
            require(
                not any(self._path("objects").iterdir()),
                "Snapshots exist without HEAD; preserve the store and inspect recovery",
            )
            return self._commit(None, empty_catalog(), [])

    def import_catalog(self, catalog: dict, *, expected_head: str) -> Snapshot:
        digest(expected_head, "expected_head")
        # Make an independent copy before validation or waiting for the lock.
        catalog = validate_catalog(parse_json(canonical_bytes(catalog)))
        require(self.root.is_dir(), "Catalog is not initialized")
        with file_lock(self._path("catalog.lock"), timeout=self.lock_timeout):
            self._clean()
            current = self._load(self._head())
            require(
                current.head == expected_head, "Stale catalog head; review the current snapshot"
            )
            verify_assets(catalog, self.workspace)
            value = current.to_dict()
            if canonical_bytes(value["catalog"]) == canonical_bytes(catalog):
                return current
            return self._commit(current.head, catalog, value["ledger"])

    def recover(self) -> dict:
        require(self.root.is_dir(), "Catalog is not initialized")
        with file_lock(self._path("catalog.lock"), timeout=self.lock_timeout):
            if not self.recovery_required:
                return {**self._load(self._head()).report(), "recovery": "not_needed"}
            raw = read_document(self._path("pending.json"))
            intent = parse_json(raw)
            object_fields(intent, {"version", "before", "after", "snapshot"}, "pending transaction")
            require(
                type(intent["version"]) is int and intent["version"] == 1,
                "Invalid transaction version",
            )
            require(_encoded(intent) == raw, "Transaction is not canonically encoded")
            before, after = intent["before"], digest(intent["after"], "transaction.after")
            if before is not None:
                digest(before, "transaction.before")
            target = _snapshot(_encoded(intent["snapshot"]), after)
            value = target.to_dict()
            if before is None:
                require(
                    len(value["ledger"]) == 1 and value["catalog"] == empty_catalog(),
                    "Invalid initialization transaction",
                )
            else:
                previous = self._load(before).to_dict()["ledger"]
                require(
                    value["ledger"][:-1] == previous, "Transaction does not extend prior history"
                )
            head = self._head(missing_ok=True)
            require(
                head in {before, after},
                "HEAD diverged from pending transaction; preserve and inspect",
            )
            self._publish_object(target)
            if head != after:
                _atomic_write(self._path("HEAD"), (after + "\n").encode("ascii"))
            self._path("pending.json").unlink()
            return {
                **target.report(),
                "recovery": "completed" if head != after else "already_committed",
            }
