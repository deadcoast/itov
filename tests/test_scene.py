import copy
import json
from pathlib import Path

import pytest
from test_inference import inference_case as inference_case
from test_trigger import ORIGIN, codes, write

from itov import scene
from itov.batch import create_plan, load_plan, save_plan
from itov.catalog import load_catalog, sha256
from itov.catalog_store import CatalogStore
from itov.cli import main
from itov.inference import plan_inference, prepare_inference


@pytest.fixture
def scene_case(inference_case):
    config, spec = inference_case
    spec.update(
        profile="sdxl-lcm-v1",
        lora={"loader_name": "lcm.safetensors", "sha256": sha256(b"lora fixture")},
        prompt="A ceramic teapot with grain",
        negative_prompt="blur",
    )
    prepared = prepare_inference(config, spec)
    catalog = load_catalog(Path(prepared["catalog"]))
    CatalogStore(config.root).import_catalog(catalog, expected_head=prepared["expected_head"])
    plan = plan_inference(config, spec)
    catalog["loras"][0]["trigger_words"] = ["grain"]
    snapshot = CatalogStore(config.root).import_catalog(catalog, expected_head=plan["catalog_head"])
    request = plan["request"]
    request["catalog_head"] = snapshot.head
    plan = create_plan(config.root, request)
    path = save_plan(config.root, plan)
    value = {
        "version": 1,
        "id": "neutral-scene",
        "origin": ORIGIN,
        "presets": [
            {
                "preset": plan["jobs"][0]["preset"],
                "sampler": "6",
                "required_positive": ["ceramic teapot"],
                "forbidden_positive": ["hand"],
                "required_negative": ["blur"],
                "forbidden_negative": ["teapot"],
                "required_loras": [catalog["loras"][0]["id"]],
                "forbidden_loras": [],
                "max_loras": 1,
                "max_words": {"positive": 10, "negative": 5},
                "triggers": "all_declared",
            }
        ],
    }
    return config, catalog, path, write(config.root / "scene.json", value), value


def changed_graph(case, change):
    config, catalog, path, _, _ = case
    graph_path = config.root / catalog["presets"][0]["workflow"]["path"]
    graph = json.loads(graph_path.read_bytes())
    change(graph)
    raw = json.dumps(graph).encode()
    graph_path.write_bytes(raw)
    catalog["presets"][0]["workflow"]["sha256"] = sha256(raw)
    plan = load_plan(path)
    snapshot = CatalogStore(config.root).import_catalog(catalog, expected_head=plan["catalog_head"])
    request = plan["request"]
    request["catalog_head"] = snapshot.head
    return save_plan(config.root, create_plan(config.root, request))


def test_scene_replays_plan_without_http_or_mutating_catalog(scene_case, monkeypatch):
    config, _, plan, path, _ = scene_case
    before = CatalogStore(config.root).snapshot().raw

    def no_http(*args, **kwargs):
        pytest.fail("scene lint attempted HTTP")

    monkeypatch.setattr("itov.comfyui.ComfyUIClient.__init__", no_http)
    result = scene.lint(config, path, plan)
    assert result["ok"] and not result["findings"]
    assert result == scene.lint(config, path, plan)
    assert len(result["details"]["jobs"]) == 2
    assert result["details"]["jobs"][0]["prompts"]["positive"]["node"] == "3"
    assert CatalogStore(config.root).snapshot().raw == before
    assert not (config.root / "state/jobs").exists()
    assert not (config.root / "state/lint").exists()
    assert scene.lint(config, path, plan, save=True)["report_id"] == result["report_id"]


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("required_positive", ["blur"], "REQUIRED_PHRASE_MISSING"),
        ("required_negative", ["grain"], "REQUIRED_PHRASE_MISSING"),
        ("forbidden_positive", ["grain"], "FORBIDDEN_PHRASE_PRESENT"),
        ("forbidden_negative", ["grain", "blur"], "FORBIDDEN_PHRASE_PRESENT"),
        ("max_words", {"positive": 2, "negative": 0}, "WORD_LIMIT"),
    ],
)
def test_scene_violations_keep_roles_separate(scene_case, field, value, code):
    config, _, plan, path, constraints = scene_case
    rule = constraints["presets"][0]
    # Clear the corresponding required phrase when testing a forbidden phrase.
    if field.startswith("forbidden_"):
        rule[field.replace("forbidden_", "required_")] = []
    rule[field] = value
    write(path, constraints)
    result = scene.lint(config, path, plan)
    assert not result["ok"] and code in codes(result)
    assert {f["job_index"] for f in result["findings"]} == {0, 1}


@pytest.mark.parametrize(
    "positive,negative,expected",
    [
        ("A teapot", "grain", {"TRIGGER_MISSING_POSITIVE", "TRIGGER_IN_NEGATIVE"}),
        ("A teapot grainy", "", {"TRIGGER_MISSING_POSITIVE"}),
        ("A teapot GRAIN", "", set()),
        ("", "", {"EMPTY_POSITIVE", "TRIGGER_MISSING_POSITIVE"}),
    ],
)
def test_explicit_all_declared_trigger_policy(scene_case, positive, negative, expected):
    config, _, _, path, constraints = scene_case

    def change(graph):
        graph["3"]["inputs"]["text"] = positive
        graph["4"]["inputs"]["text"] = negative

    plan = changed_graph(scene_case, change)
    for field in scene.TERM_FIELDS:
        constraints["presets"][0][field] = []
    write(path, constraints)
    assert set(codes(scene.lint(config, path, plan))) == expected
    constraints["presets"][0]["triggers"] = "none"
    write(path, constraints)
    assert set(codes(scene.lint(config, path, plan))) == (
        {"EMPTY_POSITIVE"} if not positive else set()
    )


def test_selected_lora_restrictions(scene_case):
    config, catalog, plan, path, constraints = scene_case
    rule = constraints["presets"][0]
    rule.update(required_loras=[], forbidden_loras=[catalog["loras"][0]["id"]], max_loras=0)
    write(path, constraints)
    assert set(codes(scene.lint(config, path, plan))) == {"FORBIDDEN_LORA_PRESENT", "LORA_COUNT"}


def test_required_catalog_lora_must_be_selected(scene_case):
    config, catalog, plan_path, path, constraints = scene_case
    other = copy.deepcopy(catalog["loras"][0])
    other["id"] = "unselected-lora"
    other["asset"] = {"path": "models_shared/unselected.bin", "sha256": sha256(b"other fixture")}
    (config.root / other["asset"]["path"]).write_bytes(b"other fixture")
    catalog["loras"].append(other)
    plan = load_plan(plan_path)
    snapshot = CatalogStore(config.root).import_catalog(catalog, expected_head=plan["catalog_head"])
    plan["request"]["catalog_head"] = snapshot.head
    plan_path = save_plan(config.root, create_plan(config.root, plan["request"]))
    constraints["presets"][0]["required_loras"] = [other["id"]]
    write(path, constraints)
    assert set(codes(scene.lint(config, path, plan_path))) == {"REQUIRED_LORA_MISSING"}


@pytest.mark.parametrize(
    "field,value",
    [
        ("triggers", "automatic"),
        ("max_loras", True),
        ("max_loras", 9),
        ("max_words", {"positive": 4097, "negative": 5}),
        ("max_words", {"positive": -1, "negative": 5}),
        ("required_positive", ["A", "a"]),
        ("required_positive", ["a hand"]),
        ("required_loras", ["unknown"]),
        ("preset", "absent-preset"),
        ("sampler", "7"),
    ],
)
def test_scene_refuses_ambiguous_or_unsupported_contract(scene_case, field, value):
    config, _, plan, path, constraints = scene_case
    constraints["presets"][0][field] = value
    write(path, constraints)
    with pytest.raises(ValueError):
        scene.lint(config, path, plan, save=True)
    assert not (config.root / "state/lint").exists()


@pytest.mark.parametrize(
    "mode", ["dynamic", "unknown", "same_node", "two_samplers", "wrong_output", "control"]
)
def test_unsupported_conditioning_is_refused_not_silently_skipped(scene_case, mode):
    config, _, _, path, _ = scene_case

    def change(graph):
        if mode == "dynamic":
            graph["3"]["inputs"]["text"] = ["4", 0]
        elif mode == "unknown":
            graph["3"]["class_type"] = "CustomEncode"
        elif mode == "same_node":
            graph["6"]["inputs"]["negative"] = ["3", 0]
        elif mode == "two_samplers":
            graph["extra"] = copy.deepcopy(graph["6"])
        elif mode == "wrong_output":
            graph["6"]["inputs"]["positive"] = ["3", 1]
        else:
            graph["3"]["inputs"]["text"] = "invalid\x00text"

    plan = changed_graph(scene_case, change)
    with pytest.raises(ValueError):
        scene.lint(config, path, plan)


def test_stock_audio_conditioning_tracks_each_output(scene_case):
    config, _, _, path, _ = scene_case

    def change(graph):
        graph["audio"] = {
            "class_type": "ConditioningStableAudio",
            "inputs": {
                "positive": ["3", 0],
                "negative": ["4", 0],
                "seconds_start": 0,
                "seconds_total": 4,
            },
        }
        graph["6"]["inputs"].update(positive=["audio", 0], negative=["audio", 1])

    plan = changed_graph(scene_case, change)
    report = scene.lint(config, path, plan)
    assert report["ok"]
    for job in report["details"]["jobs"]:
        assert job["prompts"]["positive"]["node"] == "3"
        assert job["prompts"]["negative"]["node"] == "4"
    graph = {
        "audio": {"class_type": "ConditioningStableAudio", "inputs": {"positive": ["audio", 0]}}
    }
    with pytest.raises(ValueError, match="path"):
        scene.prompt(graph, ["audio", 0])


def test_cli_scene_exit_codes_and_publication(scene_case, capsys):
    config, _, plan, path, constraints = scene_case
    command = [
        "scene",
        "lint",
        str(path),
        "--plan",
        str(plan),
        "--config",
        str(config.file),
        "--json",
    ]
    assert main([*command, "--save"]) == 0
    assert Path(json.loads(capsys.readouterr().out)["saved_path"]).is_file()
    constraints["presets"][0]["required_positive"] = ["pear"]
    write(path, constraints)
    assert main(command) == 1
    assert "REQUIRED_PHRASE_MISSING" in codes(json.loads(capsys.readouterr().out))
    constraints["presets"] = []
    write(path, constraints)
    assert main(command) == 2
    assert "error" in json.loads(capsys.readouterr().out)
