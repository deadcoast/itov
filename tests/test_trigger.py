import copy
import itertools
import json
from pathlib import Path

import pytest
from test_batch import planning_case as planning_case
from test_batch import reimport

from itov import linting, trigger
from itov.batch import create_plan, save_plan
from itov.catalog import canonical_bytes, sha256
from itov.catalog_store import CatalogStore
from itov.cli import main

ORIGIN = {"title": "Neutral test policy", "reference": "test fixture; not tokenizer vocabulary"}


def write(path, value):
    path.write_bytes(canonical_bytes(value) + b"\n")
    return path


def rules_file(root, *, kind="base", words=(), models=("fixture-model",), distance=2):
    vocab = write(
        root / "vocab.json",
        {
            "version": 1,
            "origin": ORIGIN,
            "kind": kind,
            "base_models": list(models),
            "terms": list(words),
        },
    )
    return write(
        root / "rules.json",
        {
            "version": 1,
            "origin": ORIGIN,
            "near_distance": distance,
            "vocabularies": [{"path": vocab.name, "sha256": sha256(vocab.read_bytes())}],
        },
    )


def codes(report):
    return [finding["code"] for finding in report["findings"]]


@pytest.mark.parametrize(
    "tokens,expected",
    [
        (["SAME", "same"], "C1_EXACT"),
        (["café", "cafe\u0301"], "C1_EXACT"),
        (["a", "a"], "C1_EXACT"),
        (["lighting", "lightin"], "C2_NEAR"),
        (["silk texture", "silk  texture"], "C1_EXACT"),
    ],
)
def test_normalized_collisions_preserve_activation_and_report_aliases(
    planning_case, tokens, expected
):
    config, catalog, request, _ = planning_case
    catalog["loras"][0]["trigger_words"] = [tokens[0]]
    catalog["loras"][1]["trigger_words"] = [tokens[1]]
    reimport(config, catalog, request)
    source = rules_file(config.root)
    before = CatalogStore(config.root).snapshot().raw
    report = trigger.lint(config, source)
    assert expected in codes(report)
    rows = {row["lora"]: row for row in report["details"]["index"]}
    assert rows["style-a"]["text"] == tokens[0]
    assert rows["style-a"]["alias"] != rows["style-b"]["alias"]
    assert all(row["alias_use"] == "report_label_only" for row in rows.values())
    assert not report["details"]["aliases_change_activation"]
    if expected == "C1_EXACT":
        assert not report["ok"]
    assert CatalogStore(config.root).snapshot().raw == before


def test_same_lora_duplicate_and_cross_model_scope(planning_case):
    config, catalog, request, _ = planning_case
    catalog["loras"][0]["trigger_words"] = ["x", "X"]
    catalog["loras"][1].update(trigger_words=["x"], base_models=["other-model"])
    catalog["compatibility"]["preset_pairings"] = []
    catalog["loras"][2].update(trigger_words=["x"], status="quarantined")
    catalog["loras"][3].update(trigger_words=["x"], status="flagged")
    reimport(config, catalog, request)
    result = trigger.lint(config, rules_file(config.root, distance=0))
    assert codes(result).count("C0_DUPLICATE") == 1
    assert codes(result).count("C1_EXACT") == 2
    assert result["details"]["excluded"] == [{"lora": "light-a", "reason": "quarantined"}]
    assert "VOCABULARY_UNCOVERED" in codes(result)


@pytest.mark.parametrize(
    "kind,code,severity", [("base", "C3_BASE", "warning"), ("reserved", "C4_RESERVED", "error")]
)
def test_single_holder_vocabulary_collision(planning_case, kind, code, severity):
    config, _, _, _ = planning_case
    source = rules_file(config.root, kind=kind, words=["STYLE-A"], distance=0)
    report = trigger.lint(config, source)
    assert codes(report) == [code]
    assert report["findings"][0]["severity"] == severity
    assert len(report["findings"][0]["holders"]) == 1
    assert report["ok"] == (kind == "base")
    assert not trigger.lint(config, source, strict=True)["ok"]


def test_banded_distance_matches_independent_full_matrix():
    def distance(a, b):
        row = list(range(len(b) + 1))
        for i, ca in enumerate(a, 1):
            new = [i]
            for j, cb in enumerate(b, 1):
                new.append(min(row[j] + 1, new[-1] + 1, row[j - 1] + (ca != cb)))
            row = new
        return row[-1]

    words = [
        "".join(chars) for length in range(5) for chars in itertools.product("ab", repeat=length)
    ]
    for a, b, threshold in itertools.product(words, words, range(3)):
        assert trigger.near(a, b, threshold) == (distance(a, b) <= threshold)


@pytest.mark.parametrize(
    "prompt,term,expected",
    [
        ("a red teapot", "RED TEAPOT", True),
        ("handmade", "hand", False),
        ("red_teapot", "teapot", False),
        ("cafe\u0301", "CAFÉ", True),
        ("x\u0301", "x", False),
        ("x (a+b) y", "(a+b)", True),
        ("a\n  red\t teapot", "red teapot", True),
        ("x ab y", "a.*b", False),
    ],
)
def test_literal_phrase_boundaries(prompt, term, expected):
    assert linting.contains(prompt, term) is expected


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", True),
        ("near_distance", -1),
        ("near_distance", 3),
        ("near_distance", 1.5),
        ("origin", {}),
        ("vocabularies", "guess"),
    ],
)
def test_rules_invalid_contract(planning_case, field, value):
    config, _, _, _ = planning_case
    path = rules_file(config.root)
    data = json.loads(path.read_bytes())
    data[field] = value
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        trigger.lint(config, path)
    assert not (config.root / "state/lint").exists()


@pytest.mark.parametrize(
    "mode",
    [
        "missing",
        "changed",
        "traversal",
        "duplicate_ref",
        "duplicate_terms",
        "duplicate_key",
        "control",
        "long",
    ],
)
def test_vocabulary_inputs_fail_closed(planning_case, mode):
    config, _, _, _ = planning_case
    path = rules_file(config.root)
    rules = json.loads(path.read_bytes())
    vocab = config.root / "vocab.json"
    if mode == "missing":
        vocab.unlink()
    elif mode == "changed":
        vocab.write_bytes(vocab.read_bytes() + b" ")
    elif mode == "traversal":
        rules["vocabularies"][0]["path"] = "../outside.json"
    elif mode == "duplicate_ref":
        rules["vocabularies"].append(copy.deepcopy(rules["vocabularies"][0]))
    else:
        data = json.loads(vocab.read_bytes())
        data["terms"] = {
            "duplicate_terms": ["A", "a"],
            "control": ["a\x00b"],
            "long": ["x" * 129],
        }.get(mode, [])
        raw = canonical_bytes(data)
        if mode == "duplicate_key":
            raw = b'{"version":1,' + raw[1:]
        vocab.write_bytes(raw)
        rules["vocabularies"][0]["sha256"] = sha256(raw)
    write(path, rules)
    with pytest.raises((ValueError, OSError)):
        trigger.lint(config, path)


def test_plan_scope_replay_asset_freshness_and_no_runtime(planning_case, monkeypatch):
    config, catalog, request, _ = planning_case
    for lora in catalog["loras"]:
        lora["trigger_words"] = ["same"]
    reimport(config, catalog, request)
    plan = create_plan(config.root, request)
    path = save_plan(config.root, plan)
    rules = rules_file(config.root)

    def no_http(*args, **kwargs):
        pytest.fail("offline lint attempted HTTP")

    monkeypatch.setattr("itov.comfyui.ComfyUIClient.__init__", no_http)
    result = trigger.lint(config, rules, plan_path=path)
    assert len(result["findings"]) == len(plan["jobs"])
    for finding in result["findings"]:
        assert {h["lora"] for h in finding["holders"]} == {
            lora["id"] for lora in plan["jobs"][finding["job_index"]]["loras"]
        }
    assert not (config.root / "state/jobs").exists()
    assert not (config.root / "state/lint").exists()
    forged = copy.deepcopy(plan)
    forged["jobs"][0]["seed"] += 1
    forged["plan_id"] = sha256(canonical_bytes({k: v for k, v in forged.items() if k != "plan_id"}))
    with pytest.raises(ValueError, match="replay"):
        trigger.lint(config, rules, plan_path=write(config.root / "forged.json", forged))
    asset_path = config.root / catalog["loras"][0]["asset"]["path"]
    original_asset = asset_path.read_bytes()
    asset_path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="SHA-256"):
        trigger.lint(config, rules, plan_path=path)
    asset_path.write_bytes(original_asset)
    catalog["loras"][0]["trigger_words"] = ["changed"]
    reimport(config, catalog, request)
    with pytest.raises(ValueError, match="Stale"):
        trigger.lint(config, rules, plan_path=path)


def test_deterministic_publication_preserves_existing_and_rechecks_head(planning_case, monkeypatch):
    config, catalog, request, _ = planning_case
    rules = rules_file(config.root)
    report = trigger.lint(config, rules)
    assert report == trigger.lint(config, rules)
    saved = trigger.lint(config, rules, save=True)
    assert saved["report_id"] == report["report_id"]
    assert saved == trigger.lint(config, rules, save=True)
    path = Path(saved["saved_path"])
    raw = path.read_bytes()
    assert json.loads(raw) == {k: v for k, v in saved.items() if k != "saved_path"}
    path.write_bytes(b"preserve corrupt evidence")
    with pytest.raises(ValueError, match="differs"):
        trigger.lint(config, rules, save=True)
    assert path.read_bytes() == b"preserve corrupt evidence"
    original = trigger.findings_for

    def change_catalog(*args, **kwargs):
        catalog["loras"][0]["trigger_words"] = ["new"]
        reimport(config, catalog, request)
        return original(*args, **kwargs)

    monkeypatch.setattr(trigger, "findings_for", change_catalog)
    with pytest.raises(ValueError, match="changed during"):
        trigger.lint(config, rules, save=True)


def test_cli_warning_strict_collision_and_invalid_input(planning_case, capsys):
    config, _, _, _ = planning_case
    path = rules_file(config.root, words=["style-a"], distance=0)
    command = ["trigger", "lint", str(path), "--config", str(config.file), "--json"]
    assert main(command) == 0
    assert json.loads(capsys.readouterr().out)["counts"] == {"error": 0, "warning": 1}
    assert main([*command, "--strict"]) == 1
    assert not json.loads(capsys.readouterr().out)["ok"]
    rules_file(config.root, words=["style-a"], kind="reserved", distance=0)
    assert main(command) == 1
    assert "C4_RESERVED" in codes(json.loads(capsys.readouterr().out))
    path.write_bytes(b"{}")
    assert main(command) == 2
    assert "error" in json.loads(capsys.readouterr().out)


@pytest.mark.parametrize(
    "case", ["loras", "declarations", "long_trigger", "vocab_terms", "vocab_files"]
)
def test_resource_bounds_fail_explicitly(planning_case, case):
    config, catalog, _, _ = planning_case
    if case in {"loras", "declarations", "long_trigger"}:
        if case == "loras":
            catalog["loras"] *= 65
        elif case == "declarations":
            catalog["loras"][0]["trigger_words"] = [str(i) for i in range(513)]
        else:
            catalog["loras"][0]["trigger_words"] = ["x" * 129]
        with pytest.raises(ValueError):
            trigger.index(catalog)
    else:
        path = rules_file(
            config.root, words=[str(i) for i in range(5001)] if case == "vocab_terms" else []
        )
        if case == "vocab_files":
            rules = json.loads(path.read_bytes())
            rules["vocabularies"] *= 17
            write(path, rules)
        with pytest.raises(ValueError):
            trigger.load_rules(path)


def test_unrelated_vocabulary_never_matches_and_dirty_catalog_refused(planning_case):
    config, _, _, _ = planning_case
    path = rules_file(config.root, words=["style-a"], models=["other-model"], distance=0)
    result = trigger.lint(config, path)
    assert set(codes(result)) == {"VOCABULARY_UNCOVERED"}
    store = CatalogStore(config.root)
    (store.root / "pending.json").write_bytes(b"preserve unfinished transaction")
    with pytest.raises(ValueError):
        trigger.lint(config, path, save=True)
    assert not (config.root / "state/lint").exists()
