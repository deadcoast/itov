"""Operation-local read receipts with a fresh content check; never a hash cache."""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from itov.catalog import read_document as _read_document

_active: ContextVar[EvidenceReads | None] = ContextVar("itov_evidence_reads", default=None)


@dataclass(frozen=True)
class FileObservation:
    path: Path
    resolved: Path
    sha256: str
    size: int

    def verify(self):
        before = self.path.stat()
        with self.path.open("rb") as source:
            observed = hashlib.file_digest(source, "sha256").hexdigest()
        after = self.path.stat()
        if (
            observed != self.sha256
            or after.st_size != self.size
            or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
            or self.path.resolve() != self.resolved
        ):
            raise ValueError(f"Evidence changed during operation: {self.path}")


class EvidenceReads:
    """Collect already checked inputs, then hash each unique file again at the boundary.

    Context isolation lets nested validators contribute without a process-wide cache.
    An observation never skips a read/check. Nested scopes also feed their parent.
    """

    def __init__(self) -> None:
        self._files: dict[Path, FileObservation] = {}
        self._parent: EvidenceReads | None = None

    @contextmanager
    def capture(self):
        self._parent = _active.get()
        token = _active.set(self)
        try:
            yield self
        finally:
            _active.reset(token)
            self._parent = None

    def add(self, path, digest, size):
        path = Path(path).absolute()
        observation = FileObservation(path, path.resolve(), digest, size)
        previous = self._files.setdefault(path, observation)
        if previous != observation:
            raise ValueError(f"Evidence changed during operation: {path}")
        if self._parent is not None:
            self._parent.add(path, digest, size)

    @property
    def observations(self):
        return tuple(self._files.values())

    def verify(self):
        for observation in self.observations:
            observation.verify()


def observe(path, digest, size):
    current = _active.get()
    if current is not None:
        current.add(path, digest, size)


def read_document(path):
    raw = _read_document(path)
    observe(path, hashlib.sha256(raw).hexdigest(), len(raw))
    return raw
