import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from itov.batch import create_plan, save_plan, verify_plan
from itov.batch_request import neutral_request
from itov.catalog import MAX_INTEGER, canonical_bytes, empty_catalog, sha256
from itov.catalog_store import CatalogStore
from itov.config import initialize
from itov.rotation import Draws, PlanningError, feasible_stacks, select_jobs


@pytest.fixture
def planning_case(tmp_path):
    config = initialize(tmp_path / "workspace", tmp_path / "comfy")
    root = config.root
    # Structural protocol fixture; these are not loaded checkpoints or qualified inference graphs.
    graph = {
        "1": {"class_type": "FixtureModel", "inputs": {"checkpoint": "fixture.bin"}},
        "2": {
            "class_type": "LoraLoader",
            "inputs": {
                "model": ["1", 0],
                "clip": ["1", 1],
                "lora_name": "old-style",
                "strength_model": 0.5,
                "strength_clip": 0.5,
            },
        },
        "3": {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {"model": ["2", 0], "lora_name": "old-light", "strength_model": 0.5},
        },
        "4": {
            "class_type": "FixtureSampler",
            "inputs": {
                "model": ["3", 0],
                "seed": 42,
                "cfg": 7.2,
                "steps": 20,
                "prompt": "Neutral color study",
            },
        },
        "5": {"class_type": "SaveImage", "inputs": {"images": ["4", 0], "filename_prefix": "test"}},
    }
    raw = json.dumps(graph, ensure_ascii=False).encode()
    (root / "workflows/fixture.json").write_bytes(raw)
    catalog = empty_catalog()
    for key, category in (("alpha", "landscape"), ("beta", "still-life")):
        catalog["presets"].append(
            {
                "id": key,
                "category": category,
                "tags": ["fixture"],
                "workflow": {"path": "workflows/fixture.json", "sha256": sha256(raw)},
                "base_model": "fixture-model",
                "rotation_weight_milli": 1000 if key == "alpha" else 2000,
                "seed": {"base": 100, "step": 7},
            }
        )
    for key, slot, weight in (
        ("style-a", "style", 1000),
        ("style-b", "style", 3000),
        ("light-a", "light", 2000),
        ("light-b", "light", 1000),
    ):
        data = ("plain-byte test fixture " + key).encode()
        asset = {"path": f"models_shared/{key}.bin", "sha256": sha256(data)}
        (root / asset["path"]).write_bytes(data)
        catalog["loras"].append(
            {
                "id": key,
                "asset": asset,
                "category": slot,
                "slot": slot,
                "base_models": ["fixture-model"],
                "strength_milli": {"min": 200, "recommended": 600, "max": 900},
                "rotation_weight_milli": weight,
                "trigger_words": [key],
                "status": "active",
            }
        )
    catalog["compatibility"] = {
        "hard_conflicts": [["style-a", "light-a"]],
        "soft_conflicts": [["style-a", "light-b"]],
        "synergies": [{"loras": ["style-b", "light-b"], "weight_milli": 1500}],
        "preset_pairings": [{"preset": "alpha", "loras": ["style-b", "light-b"]}],
    }
    store = CatalogStore(root)
    initial = store.initialize()
    snapshot = store.import_catalog(catalog, expected_head=initial.head)
    request = neutral_request(snapshot.head, "alpha", count=8, seed=19)
    request.update(presets=["alpha", "beta"], no_repeat_within=1, category_cooldown=1)
    request["lora_policy"] = {
        "ids": [item["id"] for item in catalog["loras"]],
        "slots": ["style", "light"],
        "max_strength_milli": 1250,
        "strength_mode": "uniform",
        "soft_conflicts": "allow",
        "no_repeat_within": 0,
        "preferred_multiplier_milli": 1500,
        "loader_names": {item["id"]: item["id"] + ".safetensors" for item in catalog["loras"]},
    }
    binding = {
        "seed_inputs": [{"node": "4", "class_type": "FixtureSampler", "input": "seed"}],
        "lora_slots": [{"slot": "style", "node": "2"}, {"slot": "light", "node": "3"}],
    }
    request["bindings"] = {key: copy.deepcopy(binding) for key in request["presets"]}
    return config, catalog, request, graph


def reimport(config, catalog, request):
    snapshot = CatalogStore(config.root).import_catalog(
        catalog, expected_head=request["catalog_head"]
    )
    request["catalog_head"] = snapshot.head


def test_repeatable_expansion_preserves_source_and_enforces_constraints(planning_case):
    config, catalog, request, graph = planning_case
    before = (config.root / "workflows/fixture.json").read_bytes()
    original_request = copy.deepcopy(request)
    plan = create_plan(config.root, request)
    assert canonical_bytes(plan) == canonical_bytes(create_plan(config.root, request))
    assert request == original_request
    assert (config.root / "workflows/fixture.json").read_bytes() == before
    assert CatalogStore(config.root).snapshot().head == request["catalog_head"]
    assert not (config.root / "state/plans").exists()
    assert not (config.root / "state/jobs").exists()
    assert len({job["seed"] for job in plan["jobs"]}) == request["count"]
    for index, job in enumerate(plan["jobs"]):
        if index:
            assert job["preset"] != plan["jobs"][index - 1]["preset"]
            assert job["category"] != plan["jobs"][index - 1]["category"]
        ids = {item["id"] for item in job["loras"]}
        assert not {"style-a", "light-a"} <= ids
        assert len({item["slot"] for item in job["loras"]}) == 2
        assert (
            sum(item["strength_milli"] for item in job["loras"])
            == job["total_strength_milli"]
            <= 1250
        )
        assert all(200 <= item["strength_milli"] <= 900 for item in job["loras"])
        expanded = json.loads(job["workflow_json"])
        assert expanded["1"] == graph["1"] and expanded["5"] == graph["5"]
        assert expanded["4"]["inputs"] == {**graph["4"]["inputs"], "seed": job["seed"]}
        for item in job["loras"]:
            node = expanded["2" if item["slot"] == "style" else "3"]
            assert node["inputs"]["lora_name"] == item["loader_name"]
            assert node["inputs"]["strength_model"] == item["strength_milli"] / 1000
            if item["slot"] == "style":
                assert node["inputs"]["strength_clip"] == item["strength_milli"] / 1000
        assert sha256(job["workflow_json"].encode()) == job["workflow_sha256"]


def test_prefix_and_catalog_iteration_order_do_not_change_picks(planning_case):
    config, catalog, request, _ = planning_case
    plan = create_plan(config.root, request)
    short = copy.deepcopy(request)
    short["count"] = 3
    assert create_plan(config.root, short)["jobs"] == plan["jobs"][:3]
    catalog["presets"].reverse()
    catalog["loras"].reverse()
    request["presets"].reverse()
    request["lora_policy"]["ids"].reverse()
    request["lora_policy"]["slots"].reverse()
    reimport(config, catalog, request)
    assert create_plan(config.root, request)["jobs"] == plan["jobs"]


def test_plan_persistence_replay_and_external_hash_seed(planning_case, tmp_path):
    config, _, request, _ = planning_case
    plan = create_plan(config.root, request)
    path = save_plan(config.root, plan)
    assert save_plan(config.root, plan) == path
    assert len(list(path.parent.glob("*.json"))) == 1
    assert verify_plan(config.root, path)["jobs"] == 8
    incoming = tmp_path / "request.json"
    incoming.write_bytes(canonical_bytes(request))
    script = (
        "from pathlib import Path; import sys; from itov.batch import create_plan,load_request; "
        "print(create_plan(Path(sys.argv[1]),load_request(Path(sys.argv[2])))['plan_id'])"
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(config.root), str(incoming)],
        capture_output=True,
        text=True,
        timeout=10,
        env={**os.environ, "PYTHONHASHSEED": "1234"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == plan["plan_id"]


def test_strength_budget_never_scales_below_declared_minima(planning_case):
    config, _, request, _ = planning_case
    request["lora_policy"]["max_strength_milli"] = 400
    plan = create_plan(config.root, request)
    assert all(job["total_strength_milli"] == 400 for job in plan["jobs"])
    request["lora_policy"]["max_strength_milli"] = 399
    with pytest.raises(PlanningError, match="No next pick") as error:
        create_plan(config.root, request)
    assert error.value.index == 0
    request["lora_policy"].update(strength_mode="recommended", max_strength_milli=1199)
    with pytest.raises(PlanningError):
        create_plan(config.root, request)
    request["lora_policy"]["max_strength_milli"] = 1200
    assert all(
        job["total_strength_milli"] == 1200 for job in create_plan(config.root, request)["jobs"]
    )


def test_active_model_slot_filters_and_soft_conflict_policy(planning_case):
    config, catalog, request, _ = planning_case
    for lora in catalog["loras"]:
        if lora["id"] == "style-b":
            lora["status"] = "quarantined"
    reimport(config, catalog, request)
    request["lora_policy"]["soft_conflicts"] = "exclude"
    with pytest.raises(PlanningError):
        create_plan(config.root, request)
    request["lora_policy"]["soft_conflicts"] = "allow"
    plan = create_plan(config.root, request)
    assert all(job["soft_conflicts"] == [["light-b", "style-a"]] for job in plan["jobs"])
    assert all(
        {item["id"] for item in job["loras"]} == {"style-a", "light-b"} for job in plan["jobs"]
    )
    assert any(
        item["lora"] == "style-b" and "inactive" in item["reasons"] for item in plan["exclusions"]
    )
    # Ineligible/quarantined files are not prospective inputs and need not be read.
    (config.root / "models_shared/style-b.bin").unlink()
    assert create_plan(config.root, request)["plan_id"] == plan["plan_id"]


@pytest.mark.parametrize(
    "change",
    [
        lambda r: r.update(no_repeat_within=2),
        lambda r: r.update(category_cooldown=2),
        lambda r: r["lora_policy"].update(no_repeat_within=2),
    ],
)
def test_exhaustion_never_relaxes_constraints_or_saves_partial_plan(planning_case, change):
    config, _, request, _ = planning_case
    change(request)
    with pytest.raises(PlanningError) as error:
        create_plan(config.root, request)
    assert error.value.code == "rotation_exhausted"
    assert error.value.index > 0
    assert not (config.root / "state/plans").exists()


def test_seed_overflow_and_collision_handling(planning_case):
    config, catalog, request, _ = planning_case
    request["seed"] = MAX_INTEGER
    with pytest.raises(PlanningError) as error:
        create_plan(config.root, request)
    assert error.value.code == "seed_overflow"
    request["seed"] = 0
    request["count"] = 2
    stacks, _, _ = feasible_stacks(catalog, request)
    first = select_jobs(catalog, request, stacks)
    for preset in catalog["presets"]:
        if preset["id"] == first[1]["preset"]:
            preset["seed"]["base"] = first[0]["seed"] - preset["seed"]["step"]
    second = select_jobs(catalog, request, stacks)
    assert second[1]["seed"] == second[0]["seed"] + 7


@pytest.mark.parametrize(
    "change",
    [
        lambda r: r.update(version=True),
        lambda r: r.update(count=0),
        lambda r: r.update(count=1001),
        lambda r: r.update(seed=-1),
        lambda r: r.update(unknown=1),
        lambda r: r.update(presets=["missing"]),
        lambda r: r["lora_policy"].update(ids=["missing"]),
        lambda r: r["lora_policy"].update(max_strength_milli=1.0),
        lambda r: r["lora_policy"].update(preferred_multiplier_milli=0),
        lambda r: r["lora_policy"].update(strength_mode="scale"),
        lambda r: r["lora_policy"]["loader_names"].update({"style-a": "../escape"}),
        lambda r: r["lora_policy"]["loader_names"].update({"style-a": "style-b.safetensors"}),
        lambda r: r["bindings"]["alpha"]["seed_inputs"][0].update(node="absent"),
        lambda r: r["bindings"]["alpha"]["seed_inputs"][0].update(input="steps"),
        lambda r: r["bindings"]["alpha"]["seed_inputs"][0].update(class_type="ChangedClass"),
        lambda r: r["bindings"]["alpha"]["lora_slots"][0].update(node="4"),
        lambda r: r["bindings"]["alpha"]["lora_slots"][0].update(node="3"),
    ],
)
def test_invalid_requests_and_bindings_fail_before_persistence(planning_case, change):
    config, _, request, _ = planning_case
    change(request)
    with pytest.raises(ValueError):
        create_plan(config.root, request)
    assert not (config.root / "state/plans").exists()


def test_stale_head_asset_tampering_and_rehashed_plan_tampering(planning_case):
    config, catalog, request, _ = planning_case
    plan = create_plan(config.root, request)
    path = save_plan(config.root, plan)
    forged = copy.deepcopy(plan)
    forged["jobs"][0]["seed"] += 1
    path.write_bytes(canonical_bytes(forged) + b"\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_plan(config.root, path)
    forged["plan_id"] = sha256(canonical_bytes({k: v for k, v in forged.items() if k != "plan_id"}))
    path.write_bytes(canonical_bytes(forged) + b"\n")
    with pytest.raises(ValueError, match="deterministic replay"):
        verify_plan(config.root, path)
    with pytest.raises(ValueError, match="Existing plan differs"):
        save_plan(config.root, plan)
    assert path.read_bytes() == canonical_bytes(forged) + b"\n"
    catalog["presets"][0]["tags"].append("revision")
    old = copy.deepcopy(request)
    reimport(config, catalog, request)
    with pytest.raises(ValueError, match="Stale"):
        create_plan(config.root, old)
    with pytest.raises(ValueError, match="Stale"):
        save_plan(config.root, plan)
    (config.root / "models_shared/light-b.bin").write_bytes(b"changed")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        create_plan(config.root, request)


def test_catalog_change_during_planning_is_rejected(planning_case, monkeypatch):
    import itov.batch as module

    config, catalog, request, _ = planning_case
    original = module.select_jobs

    def changed(*args):
        catalog["presets"][0]["tags"].append("concurrent-edit")
        CatalogStore(config.root).import_catalog(catalog, expected_head=request["catalog_head"])
        return original(*args)

    monkeypatch.setattr(module, "select_jobs", changed)
    with pytest.raises(ValueError, match="Stale"):
        create_plan(config.root, request)


def test_pending_transaction_is_never_used_for_planning(planning_case):
    config, _, request, _ = planning_case
    pending = config.root / "state/catalog/pending.json"
    pending.write_bytes(b"preserve unresolved intent")
    with pytest.raises(ValueError, match="Pending"):
        create_plan(config.root, request)
    assert pending.read_bytes() == b"preserve unresolved intent"


def test_combination_limits_fail_explicitly(planning_case, monkeypatch):
    config, _, request, _ = planning_case
    monkeypatch.setattr("itov.rotation.MAX_COMBINATIONS", 1)
    with pytest.raises(ValueError, match="combination limit"):
        create_plan(config.root, request)


def test_frozen_rotation_vector(planning_case):
    config, catalog, request, _ = planning_case
    vector = json.loads(Path("tests/fixtures/rotation-v1-vector.json").read_text())
    stacks, _, _ = feasible_stacks(catalog, request)
    picks = select_jobs(catalog, request, stacks)
    observed = [
        {
            "preset": job["preset"],
            "seed": job["seed"],
            "loras": [[item["id"], item["strength_milli"]] for item in job["loras"]],
        }
        for job in picks
    ]
    assert observed == [
        {k: v for k, v in pick.items() if k != "workflow_sha256"} for pick in vector["picks"]
    ]
    plan = create_plan(config.root, request)
    assert [job["workflow_sha256"] for job in plan["jobs"]] == [
        pick["workflow_sha256"] for pick in vector["picks"]
    ]
    draws = Draws(19)
    assert [draws.below(bound) for bound in vector["bounds"]] == vector["draws"]


def test_weights_include_exact_preference_and_synergy_factors(planning_case):
    _, catalog, request, _ = planning_case
    stacks, _, _ = feasible_stacks(catalog, request)
    weights = {key: {stack.ids: stack.weight for stack in values} for key, values in stacks.items()}
    assert weights["alpha"] == {
        ("light-a", "style-b"): 9_000_000,
        ("light-b", "style-a"): 1_500_000,
        ("light-b", "style-b"): 10_125_000,
    }
    assert weights["beta"] == {
        ("light-a", "style-b"): 6_000_000,
        ("light-b", "style-a"): 1_000_000,
        ("light-b", "style-b"): 4_500_000,
    }


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("status", "candidate", "inactive"),
        ("status", "flagged", "inactive"),
        ("base_models", ["another-model"], "base_model"),
        ("slot", "unused", "slot"),
        ("strength_milli", {"min": 0, "recommended": 600, "max": 100001}, "loader_strength_range"),
    ],
)
def test_candidate_exclusion_reasons_are_visible(planning_case, field, value, reason):
    config, catalog, request, _ = planning_case
    next(item for item in catalog["loras"] if item["id"] == "style-a")[field] = value
    reimport(config, catalog, request)
    plan = create_plan(config.root, request)
    assert any(
        item["lora"] == "style-a" and reason in item["reasons"] for item in plan["exclusions"]
    )
    assert all(item["id"] != "style-a" for job in plan["jobs"] for item in job["loras"])


def test_unbound_seed_and_loader_inputs_are_rejected(planning_case):
    config, catalog, request, graph = planning_case
    request["bindings"]["alpha"]["seed_inputs"] = []
    with pytest.raises(ValueError, match="seed metadata"):
        create_plan(config.root, request)
    request["bindings"]["alpha"]["seed_inputs"] = [
        {"node": "4", "class_type": "FixtureSampler", "input": "seed"}
    ]
    graph["6"] = copy.deepcopy(graph["2"])
    raw = json.dumps(graph).encode()
    (config.root / "workflows/fixture.json").write_bytes(raw)
    for preset in catalog["presets"]:
        preset["workflow"]["sha256"] = sha256(raw)
    reimport(config, catalog, request)
    with pytest.raises(ValueError, match="every built-in"):
        create_plan(config.root, request)


def test_incomplete_save_preserves_existing_state_and_cleans_temp(planning_case, monkeypatch):
    import itov.catalog_store as store_module

    config, _, request, _ = planning_case
    plan = create_plan(config.root, request)

    def fail(*_args):
        raise OSError("simulated publication failure")

    monkeypatch.setattr(store_module.os, "link", fail)
    with pytest.raises(OSError, match="publication failure"):
        save_plan(config.root, plan)
    assert not list((config.root / "state/plans").iterdir())


@pytest.mark.parametrize(
    "node,name,value",
    [
        ("4", "seed", ["1", 0]),
        ("2", "strength_model", ["1", 0]),
        ("2", "strength_clip", True),
        ("2", "lora_name", ["1", 0]),
        ("2", "model", None),
        ("2", "clip", None),
    ],
)
def test_bound_inputs_must_have_supported_literal_and_link_types(planning_case, node, name, value):
    config, catalog, request, graph = planning_case
    graph[node]["inputs"][name] = value
    raw = json.dumps(graph).encode()
    (config.root / "workflows/fixture.json").write_bytes(raw)
    for preset in catalog["presets"]:
        preset["workflow"]["sha256"] = sha256(raw)
    reimport(config, catalog, request)
    with pytest.raises(ValueError, match="[Bb]ound"):
        create_plan(config.root, request)


def test_multiple_seed_bindings_receive_the_same_explicit_seed(planning_case):
    config, catalog, request, graph = planning_case
    graph["6"] = {"class_type": "RandomNoise", "inputs": {"noise_seed": 0}}
    raw = json.dumps(graph).encode()
    (config.root / "workflows/fixture.json").write_bytes(raw)
    for preset in catalog["presets"]:
        preset["workflow"]["sha256"] = sha256(raw)
        request["bindings"][preset["id"]]["seed_inputs"].append(
            {"node": "6", "class_type": "RandomNoise", "input": "noise_seed"}
        )
    reimport(config, catalog, request)
    for job in create_plan(config.root, request)["jobs"]:
        graph = json.loads(job["workflow_json"])
        assert graph["6"]["inputs"]["noise_seed"] == graph["4"]["inputs"]["seed"] == job["seed"]
