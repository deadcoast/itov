"""Immutable internal JSON values; wire documents retain their existing versions."""

from dataclasses import dataclass

from itov.catalog import canonical_bytes
from itov.comfyui import parse_json


@dataclass(frozen=True)
class Document:
    """Own canonical bytes, never a mutable alias into a caller's dictionary."""

    raw: bytes

    @classmethod
    def capture(cls, value):
        return cls(canonical_bytes(value))

    def to_dict(self):
        return parse_json(self.raw)
