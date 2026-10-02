"""Immutable internal JSON values; wire documents retain their existing versions."""

from dataclasses import dataclass

from itov.catalog import canonical_bytes
from itov.comfyui import parse_json_object


@dataclass(frozen=True)
class Document:
    """Own canonical bytes, never a mutable alias into a caller's dictionary."""

    raw: bytes

    @classmethod
    def capture(cls, value: dict):
        if not isinstance(value, dict):
            raise ValueError("Document requires a JSON object")
        return cls(canonical_bytes(value))

    def to_dict(self) -> dict:
        return parse_json_object(self.raw)
