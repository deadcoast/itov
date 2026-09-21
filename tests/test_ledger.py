import copy
import json

import pytest

from itov.catalog import canonical_bytes, empty_catalog, sha256
from itov.ledger import GENESIS, new_event, row_hash, verify_ledger


def test_hash_golden_vector():
    # Frozen external representation makes byte/order/hex-vs-binary drift visible.
    body = {
        "version": 1,
        "sequence": 1,
        "event_id": "00000000-0000-4000-8000-000000000001",
        "created_at": "2026-09-21T00:00:00.000000Z",
        "action": "initialize",
        "catalog_sha256": "1" * 64,
    }
    fixture = json.loads(open("tests/fixtures/ledger-v1-vector.json", encoding="utf-8").read())
    assert canonical_bytes(body).decode() == fixture["canonical_body"]
    assert row_hash(body, GENESIS) == fixture["row_hash"]
    assert row_hash(body, "a" * 64) == fixture["nonzero_predecessor_hash"]


def test_ledger_rejects_changed_reordered_duplicated_and_truncated_rows():
    catalog = empty_catalog()
    first = new_event(catalog, [])
    ledger = [first, new_event(catalog, [first])]
    assert verify_ledger(ledger, catalog) == ledger[-1]["row_hash"]
    changed = copy.deepcopy(ledger)
    changed[0]["created_at"] = "2026-01-01T00:00:00.000000Z"
    for broken in (changed, list(reversed(ledger)), [first, first], ledger[1:], []):
        with pytest.raises(ValueError):
            verify_ledger(broken, catalog)


def test_catalog_tail_mismatch_is_detected():
    catalog = empty_catalog()
    ledger = [new_event(catalog, [])]
    catalog["presets"] = [{"changed": True}]
    assert sha256(canonical_bytes(catalog)) != ledger[-1]["catalog_sha256"]
    with pytest.raises(ValueError, match="tail does not match"):
        verify_ledger(ledger, catalog)


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", True),
        ("sequence", True),
        ("sequence", 2),
        ("event_id", "bad"),
        ("created_at", "2026-09-21T00:00:00Z"),
        ("created_at", "2026-99-99T00:00:00.000000Z"),
        ("action", "promote"),
        ("catalog_sha256", "no"),
        ("previous_hash", "f" * 64),
    ],
)
def test_ledger_schema_is_checked_before_trust(field, value):
    catalog = empty_catalog()
    row = new_event(catalog, [])
    row[field] = value
    with pytest.raises(ValueError):
        verify_ledger([row], catalog)
