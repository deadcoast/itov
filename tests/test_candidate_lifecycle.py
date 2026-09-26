"""Lifecycle contracts with synthetic approvals; never model-quality acceptance.

Only the runtime/loader are fixtures. Packet, review, decision, evidence receipts,
catalog, ledger, mutation gates and recovery execute the production implementation.
"""

import copy
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_deployed_review import reviewed as reviewed
from test_training import document

from itov import candidate_lifecycle as lifecycle
from itov import catalog_store, deployed_loader, deployed_review, evaluation_runtime
from itov.catalog_store import CatalogStore
from itov.cli import main
from itov.training_data import file_ref, seal


@pytest.fixture
def candidate(reviewed, monkeypatch):
    config, _, _, _, _, report = reviewed
    store = CatalogStore(config.root)
    store.initialize()
    asset = config.root / "models_shared/trained/fixture.safetensors"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"Synthetic lifecycle fixture; not a model")
    entry = {
        "id": "fixture-candidate",
        "asset": deployed_loader.reference(config, asset),
        "category": "style",
        "slot": "style",
        "base_models": ["sdxl-1.0"],
        "strength_milli": {"min": 500, "recommended": 1000, "max": 1000},
        "rotation_weight_milli": 1000,
        "trigger_words": ["fixture"],
        "status": "candidate",
    }
    runtime = document(config.root / "runtime-fixture.json", {"fixture": "runtime"})
    runtime_ref = deployed_loader.reference(config, runtime)
    report["candidate"].update(entry=entry, purpose="training", export=entry["asset"])
    report.update(
        deployment={"loader_name": asset.name, "asset": entry["asset"]},
        runtime={"fixture_source": runtime_ref},
        technical_pass=True,
    )
    previous = evaluation_runtime.replay

    def replay(*args, **kwargs):
        file_ref(config.root, entry["asset"])
        file_ref(config.root, runtime_ref)
        return previous(*args, **kwargs)

    monkeypatch.setattr(evaluation_runtime, "replay", replay)
    item = SimpleNamespace(config=config, store=store, report=report, asset=asset, runtime=runtime)
    decide(item)
    return item


def decide(item, verdict="pass"):
    config = item.config
    packet = deployed_review.packet(
        config, config.root / "plan.json", config.root / "mapping.json", save=True
    )
    path = config.root / f"state/evaluation/review-packets/{packet['packet_id']}.json"
    review = deployed_review.template(packet)
    review.update(
        reviewer="Synthetic fixture",
        method="Constructed contract assertions",
        limitations="No image quality or trained-model evidence",
    )
    for row in review["observations"] + review["comparisons"]:
        for judgment in row["judgments"].values():
            judgment.update(
                verdict=verdict, notes="Synthetic assertion", uncertainty="Fixture only"
            )
    item.review = document(config.root / "lifecycle-review.json", review)
    item.decision = deployed_review.decide(config, path, item.review, save=True)
    item.path = config.root / f"state/evaluation/decisions/{item.decision['decision_id']}.json"


def activate(item, strength=500):
    preview = lifecycle.preview(item.config, item.path, strength, save=True)
    return lifecycle.apply(item.config, Path(preview["saved_path"]))


def unrelated(item, *, conflict=False, edit_target=False):
    snapshot = item.store.snapshot()
    catalog = snapshot.to_dict()["catalog"]
    if edit_target:
        catalog["loras"][0]["rotation_weight_milli"] += 1
    else:
        asset = item.config.root / "unrelated.safetensors"
        asset.write_bytes(b"Unrelated synthetic asset")
        row = copy.deepcopy(item.report["candidate"]["entry"])
        row.update(id="unrelated", asset=deployed_loader.reference(item.config, asset))
        catalog["loras"].append(row)
        if conflict:
            catalog["compatibility"]["hard_conflicts"] = [["unrelated", "fixture-candidate"]]
    return item.store.import_catalog(catalog, expected_head=snapshot.head)


def test_summary_and_explicit_activation_bind_catalog_and_lineage(candidate, capsys):
    item = candidate
    before = item.store.snapshot()
    for deployment in (False, True):
        value = lifecycle.summary(item.config, item.path, deployment=deployment, save=True)
        assert value["activation_eligible"] and value["technical_pass"]
        assert value["candidate"] == item.report["candidate"]
        assert item.store.snapshot() == before
    preview = lifecycle.preview(item.config, item.path, 250, save=True)
    assert preview["after"]["strength_milli"] == dict.fromkeys(("min", "max", "recommended"), 250)
    assert item.store.snapshot() == before
    command = [
        "candidate",
        "apply",
        preview["saved_path"],
        "--config",
        str(item.config.file),
        "--json",
    ]
    assert main(command) == 0
    result = json.loads(capsys.readouterr().out)
    snapshot = item.store.snapshot()
    assert result["catalog_head"] == snapshot.head != before.head
    ledger = snapshot.to_dict()["ledger"]
    assert ledger[:-1] == before.to_dict()["ledger"]
    assert ledger[-1]["version"] == 2 and ledger[-1]["action"] == "candidate_activate"
    assert lifecycle.replay(item.config, result["operation_id"])["valid"]
    assert len(lifecycle.status(item.config)["operations"]) == 1
    assert main(command) == 2
    assert "Stale catalog head" in capsys.readouterr().out
    assert item.store.snapshot() == snapshot
    assert not item.store.recovery_required


def test_public_text_and_json_lifecycle_sequence(candidate, capsys):
    item = candidate
    config = ["--config", str(item.config.file)]
    assert main(["candidate", "summary", str(item.path), *config]) == 0
    output = capsys.readouterr().out
    assert "Activation eligible: True" in output and "Promotion eligible: False" not in output
    operation = activate(item)
    assert main(["candidate", "replay", operation["operation_id"], *config]) == 0
    assert "candidate_lifecycle_replay" in capsys.readouterr().out
    for action, identity in (("retirement", "fixture-candidate"), ("rollback", None)):
        assert (
            main(
                [
                    "candidate",
                    action,
                    identity or operation["operation_id"],
                    "--reason",
                    "Public CLI fixture",
                    "--save",
                    "--json",
                    *config,
                ]
            )
            == 0
        )
        proposal = json.loads(capsys.readouterr().out)
        assert proposal["eligible"]
        assert main(["candidate", "apply", proposal["saved_path"], "--json", *config]) == 0
        operation = json.loads(capsys.readouterr().out)
    assert main(["candidate", "status", *config]) == 0
    output = capsys.readouterr().out
    assert "Lifecycle operations: 3" in output and "fixture-candidate: active" in output
    assert main(["candidate", "recover", *config]) == 0
    assert "not_needed" in capsys.readouterr().out


@pytest.mark.parametrize("cause", ["rejected", "inconclusive", "smoke", "strength"])
def test_policy_refuses_activation_without_catalog_writes(candidate, cause, capsys):
    item = candidate
    if cause in {"rejected", "inconclusive"}:
        decide(item, "fail" if cause == "rejected" else "uncertain")
    elif cause == "smoke":
        item.report["candidate"]["purpose"] = "smoke_test"
        decide(item)
    before = item.store.snapshot()
    strength = 750 if cause == "strength" else 500
    assert (
        main(
            [
                "candidate",
                "preview",
                str(item.path),
                "--strength-milli",
                str(strength),
                "--save",
                "--config",
                str(item.config.file),
                "--json",
            ]
        )
        == 1
    )
    preview = json.loads(capsys.readouterr().out)
    assert preview["_cli"]["outcome"] == "refused" and not preview["eligible"]
    with pytest.raises(ValueError):
        lifecycle.apply(item.config, Path(preview["saved_path"]))
    assert item.store.snapshot() == before
    assert not item.store.recovery_required


@pytest.mark.parametrize(
    "cause", ["image", "review", "decision", "runtime", "weights", "mapping", "head"]
)
def test_changed_evidence_or_head_refuses_saved_activation(candidate, cause):
    item = candidate
    preview = lifecycle.preview(item.config, item.path, 500, save=True)
    if cause == "head":
        unrelated(item)
    else:
        paths = {
            "image": item.config.root / "image-0.json",
            "review": item.review,
            "decision": item.path,
            "runtime": item.runtime,
            "weights": item.asset,
            "mapping": item.config.root / "mapping.json",
        }
        paths[cause].write_bytes(b"Changed evidence")
    before = item.store.snapshot()
    with pytest.raises(ValueError):
        lifecycle.apply(item.config, Path(preview["saved_path"]))
    assert item.store.snapshot() == before
    assert not item.store.recovery_required


def test_publication_boundary_rechecks_observed_bytes(candidate, monkeypatch):
    item = candidate
    preview = lifecycle.preview(item.config, item.path, 500, save=True)
    before = item.store.snapshot()
    original = CatalogStore.apply_lifecycle

    def change(store, operation, *, guard):
        item.review.write_bytes(b"Changed between validation and catalog lock")
        return original(store, operation, guard=guard)

    monkeypatch.setattr(CatalogStore, "apply_lifecycle", change)
    with pytest.raises(ValueError, match="Evidence changed"):
        lifecycle.apply(item.config, Path(preview["saved_path"]))
    assert item.store.snapshot() == before
    assert not item.store.recovery_required


def test_rollback_preserves_later_unrelated_entries_and_assets(candidate):
    item = candidate
    operation = activate(item)
    later = unrelated(item)
    expected = later.to_dict()["catalog"]
    expected["loras"] = [r for r in expected["loras"] if r["id"] == "unrelated"]
    preview = lifecycle.rollback(
        item.config, operation["operation_id"], "Remove fixture", save=True
    )
    result = lifecycle.apply(item.config, Path(preview["saved_path"]))
    assert item.store.snapshot().to_dict()["catalog"] == expected
    assert item.asset.exists() and item.path.exists()
    assert (
        lifecycle.replay(item.config, result["operation_id"])["operation"]["source_operation"]
        == operation["operation_id"]
    )
    with pytest.raises(ValueError, match="later lifecycle"):
        lifecycle.rollback(item.config, operation["operation_id"], "Duplicate rollback")


@pytest.mark.parametrize("conflict", [False, True])
def test_rollback_refuses_changed_entry_or_references(candidate, conflict):
    operation = activate(candidate)
    unrelated(candidate, conflict=conflict, edit_target=not conflict)
    before = candidate.store.snapshot()
    with pytest.raises(ValueError, match="references|target entry changed"):
        lifecycle.rollback(candidate.config, operation["operation_id"], "Preserve other changes")
    assert candidate.store.snapshot() == before


def test_retirement_and_rollback_require_original_deployed_approval(candidate):
    item = candidate
    activate(item)
    active = item.store.snapshot().to_dict()["catalog"]
    preview = lifecycle.retirement(
        item.config, "fixture-candidate", "Fixture retirement", save=True
    )
    retired = lifecycle.apply(item.config, Path(preview["saved_path"]))
    assert item.store.snapshot().to_dict()["catalog"]["loras"][0]["status"] == "quarantined"
    rollback = lifecycle.rollback(
        item.config, retired["operation_id"], "Restore fixture", save=True
    )
    lifecycle.apply(item.config, Path(rollback["saved_path"]))
    assert item.store.snapshot().to_dict()["catalog"] == active
    retire = lifecycle.retirement(item.config, "fixture-candidate", "Retire again", save=True)
    retired = lifecycle.apply(item.config, Path(retire["saved_path"]))
    item.review.write_bytes(b"Stale approval")
    before = item.store.snapshot()
    with pytest.raises(ValueError):
        lifecycle.rollback(item.config, retired["operation_id"], "Cannot reactivate")
    assert lifecycle.replay(item.config, retired["operation_id"])["valid"]
    assert item.store.snapshot() == before


def test_retirement_can_quarantine_missing_asset_but_legacy_active_cannot_restore(candidate):
    item = candidate
    snapshot = item.store.snapshot()
    catalog = snapshot.to_dict()["catalog"]
    catalog["loras"] = [{**item.report["candidate"]["entry"], "status": "active"}]
    item.store.import_catalog(catalog, expected_head=snapshot.head)
    item.asset.unlink()
    preview = lifecycle.retirement(item.config, "fixture-candidate", "Missing weights", save=True)
    retired = lifecycle.apply(item.config, Path(preview["saved_path"]))
    with pytest.raises(ValueError, match="requires deployed authorization"):
        lifecycle.rollback(
            item.config, retired["operation_id"], "Legacy activation is insufficient"
        )


def interrupt(item, monkeypatch, boundary):
    preview = lifecycle.preview(item.config, item.path, 500, save=True)
    original = catalog_store._atomic_write

    def write(path, raw, **kwargs):
        original(path, raw, **kwargs)
        if (
            boundary == "intent"
            and path.name == "pending.json"
            or boundary == "object"
            and path.parent.name == "objects"
            or boundary == "head"
            and path.name == "HEAD"
        ):
            raise RuntimeError("Injected transaction interruption")

    with monkeypatch.context() as patch:
        patch.setattr(catalog_store, "_atomic_write", write)
        with pytest.raises(RuntimeError, match="Injected"):
            lifecycle.apply(item.config, Path(preview["saved_path"]))
    return preview


@pytest.mark.parametrize("boundary", ["intent", "object", "head"])
def test_interrupted_activation_recovery_and_generic_bypass_refusal(
    candidate, monkeypatch, boundary
):
    item = candidate
    initial = item.store.snapshot()
    preview = interrupt(item, monkeypatch, boundary)
    assert item.store.recovery_required
    pending = (item.store.root / "pending.json").read_bytes()
    with pytest.raises(ValueError, match="requires candidate recover"):
        item.store.recover()
    assert (item.store.root / "pending.json").read_bytes() == pending
    result = lifecycle.recover(item.config)
    assert result["recovery"] == ("already_committed" if boundary == "head" else "completed")
    assert item.store.snapshot().head != initial.head
    assert lifecycle.replay(item.config, preview["operation_id"])["valid"]
    assert not item.store.recovery_required
    assert lifecycle.recover(item.config)["recovery"] == "not_needed"


@pytest.mark.parametrize("boundary", ["intent", "object", "head"])
def test_recovery_stale_approval_and_explicit_abandonment(candidate, monkeypatch, boundary):
    item = candidate
    initial = item.store.snapshot()
    interrupt(item, monkeypatch, boundary)
    pending = (item.store.root / "pending.json").read_bytes()
    item.review.write_bytes(b"Stale after interruption")
    if boundary == "head":
        with pytest.raises(ValueError, match="Only uncommitted"):
            lifecycle.recover(item.config, abandon=True)
        assert lifecycle.recover(item.config)["recovery"] == "already_committed"
        assert item.store.snapshot().head != initial.head
    else:
        with pytest.raises(ValueError):
            lifecycle.recover(item.config)
        assert (item.store.root / "pending.json").read_bytes() == pending
        assert item.store.snapshot() == initial
        result = lifecycle.recover(item.config, abandon=True)
        assert Path(result["archive"]).read_bytes() == pending
        assert item.store.snapshot() == initial
        assert item.asset.exists()
    assert not item.store.recovery_required


# os._exit bypasses all Python cleanup. Activation uses the same synthetic
# runtime/loader seam as the parent; all decision and lifecycle gates run.
CRASH = """
import json, os, sys
from pathlib import Path
from itov import catalog_store, candidate_lifecycle, deployed_loader, evaluation_runtime
from itov.config import load_config
from itov.training_data import file_ref
config_path, preview, boundary, report_path = sys.argv[1:]
config = load_config(Path(config_path))
if report_path != '-':
    report = json.loads(Path(report_path).read_bytes())
    def replay(*args, **kwargs):
        for row in report['matrix']:
            file_ref(config.root, row['image'])
        file_ref(config.root, report['candidate']['entry']['asset'])
        file_ref(config.root, report['runtime']['fixture_source'])
        return report
    evaluation_runtime.replay = replay
    deployed_loader.inspect = lambda *a: {'plan_id': 'a'*64, 'candidate_id': 'b'*64,
                                         'mapping_id': 'd'*64}
original = catalog_store._atomic_write
def write(path, raw, **kwargs):
    original(path, raw, **kwargs)
    if (boundary == 'intent' and path.name == 'pending.json'
        or boundary == 'object' and path.parent.name == 'objects'
        or boundary == 'head' and path.name == 'HEAD'):
        os._exit(73)
catalog_store._atomic_write = write
candidate_lifecycle.apply(config, Path(preview))
"""


@pytest.mark.parametrize("boundary", ["intent", "object", "head"])
@pytest.mark.parametrize("action", ["activate", "retire"])
def test_real_process_death_preserves_journal_and_lineage(candidate, boundary, action):
    item = candidate
    report_path = "-"
    if action == "retire":
        activate(item)
        preview = lifecycle.retirement(
            item.config, "fixture-candidate", "Process crash fixture", save=True
        )
    else:
        preview = lifecycle.preview(item.config, item.path, 500, save=True)
        report_path = str(document(item.config.root / "synthetic-report.json", item.report))
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            CRASH,
            str(item.config.file),
            preview["saved_path"],
            boundary,
            report_path,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert child.returncode == 73, child.stderr
    assert item.store.recovery_required
    assert lifecycle.recover(item.config)["ok"]
    assert item.store.snapshot().to_dict()["catalog"]["loras"][0]["status"] == (
        "quarantined" if action == "retire" else "active"
    )
    assert lifecycle.replay(item.config, preview["operation_id"])["valid"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("before", []),
        ("authorization", {}),
        ("action", []),
        ("source_operation", "forged"),
        ("blockers", [False]),
        ("reason", ""),
        ("eligible", 1),
        ("version", True),
    ],
)
def test_malformed_resealed_previews_fail_without_mutation(candidate, field, value):
    item = candidate
    preview = lifecycle.preview(item.config, item.path, 500)
    preview.pop("ok")
    preview.pop("operation_id")
    preview[field] = value
    path = document(item.config.root / "malformed.json", seal(preview, "operation_id"))
    before = item.store.snapshot()
    with pytest.raises(ValueError):
        lifecycle.apply(item.config, path)
    assert item.store.snapshot() == before


def test_tampered_historical_operation_and_pending_intent_are_preserved(candidate, monkeypatch):
    item = candidate
    preview = interrupt(item, monkeypatch, "intent")
    path = Path(preview["saved_path"])
    raw = path.read_bytes()
    path.write_bytes(raw + b" ")
    pending = (item.store.root / "pending.json").read_bytes()
    with pytest.raises(ValueError, match="SHA-256"):
        lifecycle.recover(item.config)
    assert (item.store.root / "pending.json").read_bytes() == pending
    path.write_bytes(raw)
    lifecycle.recover(item.config)
    path.write_bytes(raw + b" ")
    with pytest.raises(ValueError, match="SHA-256"):
        lifecycle.status(item.config)
    assert path.read_bytes() == raw + b" "
