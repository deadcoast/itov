"""Object boundaries reject malformed documents without weakening generic JSON parsing."""

import pytest

from itov.catalog_store import Snapshot
from itov.comfyui import parse_json, parse_json_object
from itov.records import Document
from itov.training_data import check_seal, seal
from itov.training_results import boundary


@pytest.mark.parametrize("raw", ["null", "[]", "1", "true", '"text"'])
def test_object_boundaries_reject_other_valid_json_values(raw):
    value = parse_json(raw)
    with pytest.raises(ValueError, match="Expected a JSON object"):
        parse_json_object(raw)
    with pytest.raises(ValueError, match="Expected a sealed object"):
        check_seal(value, "record_id")
    with pytest.raises(ValueError, match="Document requires a JSON object"):
        Document.capture(value)
    for record in (Document(raw.encode()), Snapshot("unused", raw.encode())):
        with pytest.raises(ValueError, match="Expected a JSON object"):
            record.to_dict()


@pytest.mark.parametrize(
    "raw",
    ['{"key": 1, "key": 2}', '{"nested": {"key": 1, "key": 2}}', '{"n": NaN}', '{"n": 1e999}'],
)
def test_object_decoder_keeps_duplicate_and_nonfinite_rejections(raw):
    with pytest.raises(ValueError):
        parse_json_object(raw)


def test_captured_object_copies_and_seal_validation_remain_independent():
    value = seal({"nested": {"items": [1, 2]}}, "record_id")
    record = Document.capture(value)
    value["nested"]["items"].append(3)
    restored = record.to_dict()
    assert check_seal(restored, "record_id")["nested"]["items"] == [1, 2]
    restored["nested"]["items"].append(4)
    with pytest.raises(ValueError, match="Document hash mismatch"):
        check_seal(restored, "record_id")
    assert record.to_dict()["nested"]["items"] == [1, 2]


def test_object_decoder_preserves_caller_error_context():
    with pytest.raises(ValueError, match="Invalid safetensors header"):
        parse_json_object("[]", message="Invalid safetensors header")


def test_interruption_keeps_original_exception_and_boundary():
    interruption = KeyboardInterrupt("cancelled")
    with pytest.raises(KeyboardInterrupt) as caught, boundary("weights"):
        raise interruption
    assert caught.value is interruption
    assert vars(caught.value)["boundary"] == "weights"
