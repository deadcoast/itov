"""One versioned hash-chain definition shared by catalog writers and readers."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from itov.catalog import canonical_bytes, digest, object_fields, require, sha256

GENESIS = "0" * 64
DOMAIN = b"ITOV-LEDGER-v1\0"
BODY_FIELDS = {"version", "sequence", "event_id", "created_at", "action", "catalog_sha256"}


def row_hash(body: dict, previous_hash: str) -> str:
    digest(previous_hash, "previous_hash")
    return sha256(DOMAIN + bytes.fromhex(previous_hash) + canonical_bytes(body))


def new_event(catalog: dict, ledger: list[dict]) -> dict:
    body = {
        "version": 1,
        "sequence": len(ledger) + 1,
        "event_id": str(uuid.uuid4()),
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "action": "catalog_import" if ledger else "initialize",
        "catalog_sha256": sha256(canonical_bytes(catalog)),
    }
    previous = ledger[-1]["row_hash"] if ledger else GENESIS
    return {**body, "previous_hash": previous, "row_hash": row_hash(body, previous)}


def verify_ledger(ledger, catalog: dict) -> str:
    require(
        isinstance(ledger, list) and bool(ledger), "Ledger must contain an initialization event"
    )
    previous = GENESIS
    seen = set()
    for sequence, row in enumerate(ledger, 1):
        location = f"Ledger row {sequence}"
        object_fields(row, BODY_FIELDS | {"previous_hash", "row_hash"}, location)
        require(type(row["version"]) is int and row["version"] == 1, f"{location}: invalid version")
        require(
            type(row["sequence"]) is int and row["sequence"] == sequence,
            f"{location}: sequence mismatch",
        )
        event_id = row["event_id"]
        require(isinstance(event_id, str), f"{location}: invalid event ID")
        require(
            str(uuid.UUID(event_id)) == event_id and event_id not in seen,
            f"{location}: invalid or duplicate event ID",
        )
        seen.add(event_id)
        stamp = row["created_at"]
        require(
            isinstance(stamp, str)
            and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z", stamp)),
            f"{location}: timestamp must be UTC with six fractional digits",
        )
        datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%fZ")
        require(
            row["action"] == ("initialize" if sequence == 1 else "catalog_import"),
            f"{location}: invalid action",
        )
        digest(row["catalog_sha256"], location + ".catalog_sha256")
        digest(row["row_hash"], location + ".row_hash")
        require(row["previous_hash"] == previous, f"{location}: predecessor mismatch")
        body = {key: row[key] for key in BODY_FIELDS}
        require(row["row_hash"] == row_hash(body, previous), f"{location}: hash mismatch")
        previous = row["row_hash"]
    require(
        ledger[-1]["catalog_sha256"] == sha256(canonical_bytes(catalog)),
        "Ledger tail does not match the catalog",
    )
    return previous
