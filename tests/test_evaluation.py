"""Technical integrity and promotion policy fixtures; no actual human acceptance."""

import json
import struct
from pathlib import Path

import pytest
from quality_fixtures import curated_inputs as curated_inputs
from test_training import document, png, save_plan, write
from test_training import training_inputs as training_inputs

from itov import evaluation, quality, training, training_data
from itov.catalog import canonical_bytes, sha256
from itov.catalog_store import CatalogStore
from itov.cli import main


def weights(*, mutate=None, payload=None):
    header = {
        "unet.block.to_q.lora.down.weight": {
            "dtype": "F32",
            "shape": [4, 8],
            "data_offsets": [0, 128],
        },
        "unet.block.to_q.lora.up.weight": {
            "dtype": "F32",
            "shape": [8, 4],
            "data_offsets": [128, 256],
        },
    }
    if mutate:
        mutate(header)
    raw = canonical_bytes(header)
    raw += b" " * (-len(raw) % 8)
    return (
        struct.pack("<Q", len(raw))
        + raw
        + (struct.pack("<64f", *([0.1] * 64)) if payload is None else payload)
    )


@pytest.fixture
def completed(training_inputs):
    item = training_inputs
    return complete(item)


def complete(item, purpose="smoke"):
    item.dataset["purpose"] = purpose
    document(item.dataset_path, item.dataset)
    prepared = training_data.prepare(item.config.root, item.dataset_path)
    dataset_path = Path(prepared["saved_path"])
    item.spec["dataset"] = {
        "path": dataset_path.relative_to(item.config.root).as_posix(),
        "sha256": sha256(dataset_path.read_bytes()),
    }
    item.plan, item.plan_path = save_plan(item)
    folder = training.run_folder(item.config, item.plan)
    result = {
        "version": item.spec["version"],
        "plan_id": item.plan["plan_id"],
        "status": "succeeded",
        "weights": write(folder, "weights.safetensors", weights()),
        "optimizer_steps": 8,
        "training_loss_billionths": [100] * 8,
        "changed_adapter_tensors": 2,
        "trainable_parameters": 64,
        "adapter_only": True,
        "export_reloaded": True,
        "max_memory_allocated": 100,
        "max_memory_reserved": 200,
        "quality_acceptance": "not_established",
        "purpose": purpose,
        "limits": "Synthetic test evidence only",
        "elapsed_ns": 123,
    }
    rows, previews = [], []
    for index, sample in enumerate(item.dataset["samples"][2:]):
        rows.append({"sample": sample["id"], "noise_seed": 100011 + index, "loss_billionths": 100})
        previews.append(
            {
                "sample": sample["id"],
                "seed": 200011 + index,
                "prompt": "testtrigger geometry",
                "baseline": write(folder, f"before-{index}.png", png(index)),
                "candidate": write(folder, f"after-{index}.png", png(index + 1)),
            }
        )
    result.update(heldout_before=rows, heldout_after=rows, previews=previews)
    if item.spec["version"] == 2:
        result["quality_matrix"] = [
            {**row, "image": write(folder, f"quality-{index}.png", png(index))}
            for index, row in enumerate(quality.expected(item.suite))
        ]
    item.result, item.folder = result, folder
    save_result(item)
    CatalogStore(item.config.root).initialize()
    return item


def save_result(item):
    sealed = training_data.seal(item.result, "result_id")
    document(item.folder / "result.json", sealed)
    training._record(
        item.folder,
        {
            "version": 1,
            "status": "succeeded",
            "plan_id": item.plan["plan_id"],
            "result_id": sealed["result_id"],
        },
    )


def approving_fixture_review(item):
    report = evaluation.assess(item.config, item.plan_path)
    evidence = write(
        item.config.root, "review-fixture.txt", b"Synthetic policy test; not a human review."
    )
    value = {
        "version": 1,
        "assessment_id": report["assessment_id"],
        "candidate_id": evaluation.candidate(item.config, item.plan_path)["candidate_id"],
        "reviewer": "automated policy fixture",
        "decision": "approve",
        "notes": "Synthetic policy test, never a qualification receipt",
        "checks": [
            {"criterion": criterion, "passed": True, "evidence": [evidence]}
            for criterion in sorted(evaluation.CRITERIA)
        ],
    }
    if item.spec["version"] == 2:
        packet = quality.packet(item.config, item.plan_path, save=True)
        packet_path = item.config.root / f"state/training/reviews/{packet['packet_id']}.json"
        value.update(
            version=2,
            reviewer_kind="human",
            independent_of_training=True,
            packet={
                "path": packet_path.relative_to(item.config.root).as_posix(),
                "sha256": sha256(packet_path.read_bytes()),
            },
            cases=[
                {
                    "case_id": c["id"],
                    "seed": seed,
                    "verdicts": {key: True for key in quality.CASE_CRITERIA},
                    "notes": "Synthetic policy fixture, not human acceptance",
                }
                for c in item.suite["cases"]
                for seed in c["seeds"]
            ],
        )
    return document(item.config.root / "review.json", value)


def test_finite_safetensors_matrix_pairs(tmp_path):
    path = tmp_path / "lora.safetensors"
    path.write_bytes(weights())
    assert evaluation.inspect_weights(path, 4) == {
        "bytes": path.stat().st_size,
        "tensors": 2,
        "pairs": 1,
        "all_finite": True,
    }


@pytest.mark.parametrize(
    "case", ["nan", "rank", "overlap", "gap", "pair", "dtype", "shape", "trailing", "short"]
)
def test_rejects_unusable_adapter_weights(tmp_path, case):
    def mutate(header):
        down = header["unet.block.to_q.lora.down.weight"]
        up = header["unet.block.to_q.lora.up.weight"]
        if case == "rank":
            down["shape"] = [2, 16]
        if case == "overlap":
            up["data_offsets"] = [0, 128]
        if case == "gap":
            up["data_offsets"] = [132, 260]
        if case == "pair":
            del header["unet.block.to_q.lora.up.weight"]
        if case == "dtype":
            down["dtype"] = "F64"
        if case == "shape":
            down["shape"] = [True, 8]

    payload = None
    if case == "nan":
        payload = struct.pack("<64f", *([float("nan")] + [0.1] * 63))
    if case == "trailing":
        payload = b"\0" * 260
    if case == "short":
        payload = b"\0" * 252
    path = tmp_path / "bad.safetensors"
    path.write_bytes(weights(mutate=mutate, payload=payload))
    with pytest.raises(ValueError):
        evaluation.inspect_weights(path, 4)


def test_candidate_is_immutable_lineage_and_does_not_change_catalog(completed):
    item = completed
    store = CatalogStore(item.config.root)
    before = store.snapshot()
    report = evaluation.assess(item.config, item.plan_path, save=True)
    assert report["technical_pass"] and not report["promotion_eligible"]
    first = evaluation.candidate(item.config, item.plan_path, save=True)
    assert evaluation.candidate(item.config, item.plan_path, save=True) == first
    assert first["entry"]["status"] == "candidate"
    assert store.snapshot() == before
    asset = item.config.root / first["entry"]["asset"]["path"]
    assert sha256(asset.read_bytes()) == first["entry"]["asset"]["sha256"]
    asset.write_bytes(b"changed")
    with pytest.raises(ValueError, match="SHA-256"):
        evaluation.candidate(item.config, item.plan_path, save=True)
    assert store.snapshot() == before


def test_comfy_export_preserves_payload_and_binds_the_mapping(tmp_path):
    path = tmp_path / "source.safetensors"
    original = weights()
    path.write_bytes(original)
    converted, receipt = evaluation.comfy_export(path, 4, sha256(original))
    assert evaluation.comfy_export(path, 4, sha256(original)) == (converted, receipt)
    old_size = struct.unpack("<Q", original[:8])[0]
    new_size = struct.unpack("<Q", converted[:8])[0]
    assert original[8 + old_size :] == converted[8 + new_size :]
    header = json.loads(converted[8 : 8 + new_size])
    assert set(header) == {
        "__metadata__",
        "lora_unet_block_to_q.lora_down.weight",
        "lora_unet_block_to_q.lora_up.weight",
    }
    assert receipt["sha256"] == sha256(converted)
    assert receipt["tensor_payload_sha256"] == sha256(original[8 + old_size :])
    with pytest.raises(ValueError, match="changed"):
        evaluation.comfy_export(path, 4, "0" * 64)


def test_comfy_export_refuses_ambiguous_tensor_name_conversion(tmp_path):
    original = weights()
    size = struct.unpack("<Q", original[:8])[0]
    header = json.loads(original[8 : 8 + size])
    for name, tensor in list(header.items()):
        header[name.replace("block.to_q", "block_to_q")] = {
            **tensor,
            "data_offsets": [n + 256 for n in tensor["data_offsets"]],
        }
    raw = canonical_bytes(header)
    payload = original[8 + size :] * 2
    path = tmp_path / "ambiguous.safetensors"
    path.write_bytes(struct.pack("<Q", len(raw)) + raw + payload)
    with pytest.raises(ValueError, match="collide"):
        evaluation.comfy_export(path, 4, sha256(path.read_bytes()))


@pytest.mark.parametrize(
    "case", ["steps", "loss", "coverage", "seed", "preview", "purpose", "weights", "missing"]
)
def test_assessment_refuses_changed_or_incomplete_evidence(completed, case):
    item = completed
    if case == "steps":
        item.result["optimizer_steps"] = 7
    if case == "loss":
        item.result["training_loss_billionths"][0] = -1
    if case == "coverage":
        item.result["heldout_after"] = []
    if case == "seed":
        item.result["heldout_before"][0]["noise_seed"] += 1
    if case == "preview":
        (item.folder / "after-0.png").write_bytes(b"changed")
    if case == "purpose":
        item.result["purpose"] = "training"
    if case == "weights":
        (item.folder / "weights.safetensors").write_bytes(b"changed")
    if case == "missing":
        del item.result["previews"]
    save_result(item)
    with pytest.raises(ValueError):
        evaluation.assess(item.config, item.plan_path)


def test_smoke_promotion_is_refused_even_with_complete_approval_fixture(completed, capsys):
    item = completed
    review = approving_fixture_review(item)
    before = CatalogStore(item.config.root).snapshot()
    result = evaluation.promotion(item.config, item.plan_path, review, save=True)
    assert (
        not result["ok"] and len(result["blockers"]) == 1 and "Smoke-test" in result["blockers"][0]
    )
    with pytest.raises(ValueError, match="Smoke-test"):
        evaluation.apply_promotion(item.config, item.plan_path, review, before.head, "0" * 64)
    assert (
        main(
            [
                "promotion",
                "prepare",
                str(item.plan_path),
                "--config",
                str(item.config.file),
                "--json",
            ]
        )
        == 1
    )
    assert json.loads(capsys.readouterr().out)["scope"] == "promotion_refused"
    assert CatalogStore(item.config.root).snapshot() == before


def test_explicit_promotion_requires_fresh_complete_review_and_catalog_head(curated_inputs):
    item = complete(curated_inputs, "training")
    store = CatalogStore(item.config.root)
    before = store.snapshot()
    assert not evaluation.promotion(item.config, item.plan_path)["ok"]
    review = approving_fixture_review(item)
    prepared = evaluation.promotion(item.config, item.plan_path, review, save=True)["decision"]
    assert store.snapshot() == before
    with pytest.raises(ValueError, match="stale"):
        evaluation.apply_promotion(
            item.config, item.plan_path, review, "0" * 64, prepared["decision_id"]
        )
    raw = json.loads(review.read_bytes())
    raw["checks"][0]["passed"] = False
    document(review, raw)
    assert not evaluation.promotion(item.config, item.plan_path, review)["ok"]
    raw["checks"][0]["passed"] = True
    document(review, raw)
    result = evaluation.apply_promotion(
        item.config, item.plan_path, review, before.head, prepared["decision_id"]
    )
    snapshot = store.snapshot()
    assert result["catalog_head"] == snapshot.head != before.head
    assert snapshot.to_dict()["catalog"]["loras"][0]["status"] == "active"
    assert snapshot.report()["events"] == before.report()["events"] + 1
    with pytest.raises(ValueError, match="stale"):
        evaluation.apply_promotion(
            item.config, item.plan_path, review, before.head, prepared["decision_id"]
        )


@pytest.mark.parametrize("case", ["stale", "missing", "duplicate", "malformed", "evidence"])
def test_review_refuses_incomplete_or_changed_evidence(completed, case):
    item = completed
    path = approving_fixture_review(item)
    value = json.loads(path.read_bytes())
    if case == "stale":
        value["assessment_id"] = "0" * 64
    if case == "missing":
        value["checks"].pop()
    if case == "duplicate":
        value["checks"][0] = value["checks"][1]
    if case == "malformed":
        value["checks"][0]["criterion"] = []
    if case == "evidence":
        (item.config.root / "review-fixture.txt").write_bytes(b"changed")
    document(path, value)
    with pytest.raises(ValueError):
        evaluation.promotion(item.config, item.plan_path, path)


@pytest.mark.parametrize(
    "command", ["dataset", "plan", "status", "assessment", "candidate", "promotion"]
)
def test_default_text_commands_report_results_without_json_flag(completed, capsys, command):
    item = completed
    commands = {
        "dataset": ["dataset", "validate", str(item.dataset_path)],
        "plan": ["training", "plan", str(item.config.root / "training.json")],
        "status": ["training", "status", str(item.plan_path)],
        "assessment": ["evaluation", "assess", str(item.plan_path)],
        "candidate": ["training", "candidate", str(item.plan_path)],
        "promotion": ["promotion", "prepare", str(item.plan_path)],
    }
    assert main([*commands[command], "--config", str(item.config.file)]) == (
        1 if command == "promotion" else 0
    )
    output = capsys.readouterr().out
    assert not output.startswith("{")
    if command == "promotion":
        assert "REFUSED" in output and "Smoke-test" in output
    elif command == "dataset":
        assert "2 training, 2 held-out" in output
    else:
        assert item.plan["plan_id"] in output
