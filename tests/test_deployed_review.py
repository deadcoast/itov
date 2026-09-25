"""Decision and mapping contract fixtures; actual loader/image evidence is separate."""

import copy
import json
import struct
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_training import document

from itov import deployed_loader as loader
from itov import deployed_review as review
from itov import evaluation_runtime
from itov.cli import main
from itov.config import initialize
from itov.deployed_loader_worker import tensor_pair
from itov.evidence_reads import EvidenceReads
from itov.training_data import file_ref, seal


@pytest.fixture
def reviewed(tmp_path, monkeypatch):
    config = initialize(tmp_path / "workspace", tmp_path / "runtime")
    plan_path = document(config.root / "plan.json", {"fixture": "plan"})
    mapping_path = document(config.root / "mapping.json", {"fixture": "mapping"})
    report = {
        "mode": "comparison",
        "plan_id": "a" * 64,
        "candidate": {"candidate_id": "b" * 64},
        "report_id": "c" * 64,
        "suite": {
            "version": 2,
            "cases": [
                {
                    "id": "one",
                    "seeds": [123],
                    "prompt": "One object",
                    "expectation": "Intact object",
                }
            ],
        },
        "strengths_milli": [250, 500, 1000],
        "matrix": [],
    }
    for index, (role, strength) in enumerate(
        [
            ("base_plain", 0),
            ("base_trigger", 0),
            ("adapter_plain", 250),
            ("adapter_trigger", 250),
            ("adapter_plain", 500),
            ("adapter_trigger", 500),
            ("adapter_plain", 1000),
            ("adapter_trigger", 1000),
        ]
    ):
        artifact = document(config.root / f"image-{index}.json", {"fixture": index})
        report["matrix"].append(
            {
                "index": index,
                "role": role,
                "strength_milli": strength,
                "case_id": "one",
                "seed": 123,
                "image": loader.reference(config, artifact),
                "decoded": {"decoded_rgb_sha256": str(index) * 64},
            }
        )

    def replay(*args, **kwargs):
        for row in report["matrix"]:
            file_ref(config.root, row["image"])
        return copy.deepcopy(report)

    monkeypatch.setattr(evaluation_runtime, "replay", replay)
    monkeypatch.setattr(
        loader,
        "inspect",
        lambda *a: {"plan_id": "a" * 64, "candidate_id": "b" * 64, "mapping_id": "d" * 64},
    )
    packet = review.packet(config, plan_path, mapping_path, save=True)
    path = config.root / f"state/evaluation/review-packets/{packet['packet_id']}.json"
    value = review.template(packet)
    value.update(
        reviewer="Fixture",
        method="Constructed contract judgments",
        limitations="No image/model quality evidence",
    )
    for row in value["observations"] + value["comparisons"]:
        for judgment in row["judgments"].values():
            judgment.update(
                verdict="pass", notes="Synthetic fixture", uncertainty="Not a natural image"
            )
    review_path = document(config.root / "review.json", value)
    return config, path, review_path, packet, value, report


def test_complete_decision_replay_cli_and_preserved_template(reviewed, capsys):
    config, path, review_path, packet, value, _ = reviewed
    template_path = path.with_suffix(".review.json")
    template_path.write_text("preserved edit")
    assert (
        review.packet(config, config.root / "plan.json", config.root / "mapping.json", save=True)
        == packet
    )
    assert template_path.read_text() == "preserved edit"
    assert path.with_suffix(".md").read_text().count("![image]") == 8
    decision = review.decide(config, path, review_path, save=True)
    assert decision["disposition"] == "accepted_for_matrix"
    assert decision["required_judgments"] == {
        "pass": 21,
        "fail": 0,
        "uncertain": 0,
        "unavailable": 0,
    }
    assert decision["promotion_eligible"] is False
    saved = config.root / f"state/evaluation/decisions/{decision['decision_id']}.json"
    assert review.replay(config, saved) == decision
    args = ["--config", str(config.file)]
    assert main(["evaluation", "review-inspect", str(path), *args, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["packet_id"] == packet["packet_id"]
    assert main(["evaluation", "decision-replay", str(saved), *args]) == 0
    assert "accepted_for_matrix" in capsys.readouterr().out
    assert main(["evaluation", "decide", str(path), "--review", str(review_path), *args]) == 0
    assert "No candidate activation" in capsys.readouterr().out


@pytest.mark.parametrize(
    "section,index,verdict,expected",
    [
        ("observations", 0, "fail", "accepted_for_matrix"),
        ("observations", 2, "fail", "rejected"),
        ("observations", 7, "uncertain", "inconclusive"),
        ("comparisons", 0, "unavailable", "inconclusive"),
        ("comparisons", 2, "fail", "rejected"),
    ],
)
def test_failed_and_unknown_candidate_judgments_block_acceptance(
    reviewed, section, index, verdict, expected
):
    config, path, review_path, _, value, _ = reviewed
    next(iter(value[section][index]["judgments"].values()))["verdict"] = verdict
    document(review_path, value)
    decision = review.decide(config, path, review_path)
    assert decision["disposition"] == expected
    assert decision["promotion_eligible"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_image",
        "duplicate_image",
        "missing_pair",
        "strength",
        "seed",
        "role",
        "hash",
        "pixel",
        "bool_index",
        "pending",
        "notes",
        "uncertainty",
        "reviewer",
        "method",
        "extra",
        "packet",
        "version",
        "missing_criterion",
    ],
)
def test_incomplete_or_misbound_review_refused(reviewed, mutation):
    config, _, _, packet, value, _ = reviewed
    if mutation == "missing_image":
        value["observations"].pop()
    elif mutation == "duplicate_image":
        value["observations"][1] = copy.deepcopy(value["observations"][0])
    elif mutation == "missing_pair":
        value["comparisons"].pop()
    elif mutation == "strength":
        value["comparisons"][0]["strength_milli"] = 1000
    elif mutation == "seed":
        value["comparisons"][0]["seed"] += 1
    elif mutation == "role":
        value["comparisons"][0]["images"]["base_plain"] = value["comparisons"][0]["images"][
            "adapter_plain"
        ]
    elif mutation == "hash":
        value["observations"][0]["image_sha256"] = "e" * 64
    elif mutation == "pixel":
        value["observations"][0]["rgb_sha256"] = "e" * 64
    elif mutation == "bool_index":
        value["observations"][0]["index"] = False
    elif mutation in {"pending", "notes", "uncertainty"}:
        value["observations"][0]["judgments"]["prompt_adherence"][
            "verdict" if mutation == "pending" else mutation
        ] = None if mutation == "pending" else ""
    elif mutation == "reviewer":
        value["reviewer_kind"] = "fixture"
    elif mutation == "method":
        value["method"] = ""
    elif mutation == "extra":
        value["approved"] = True
    elif mutation == "packet":
        value["packet_id"] = "e" * 64
    elif mutation == "version":
        value["version"] = True
    elif mutation == "missing_criterion":
        value["comparisons"][0]["judgments"].pop("preservation")
    with pytest.raises(ValueError):
        review.validate_review(config, value, packet)


@pytest.mark.parametrize("mutation", ["image", "source", "review", "rubric", "decision"])
def test_stale_or_resealed_evidence_refused(reviewed, mutation, monkeypatch):
    config, path, review_path, packet, value, _ = reviewed
    source = document(config.root / "notes.json", {"notes": "review evidence"})
    value["sources"] = [loader.reference(config, source)]
    document(review_path, value)
    decision = review.decide(config, path, review_path, save=True)
    saved = config.root / f"state/evaluation/decisions/{decision['decision_id']}.json"
    if mutation == "image":
        (config.root / "image-0.json").write_text("changed")
    elif mutation == "source":
        source.write_text("changed")
    elif mutation == "review":
        review_path.write_text("changed")
    elif mutation == "rubric":
        monkeypatch.setitem(review.IMAGE_RUBRICS, "prompt_adherence", "changed")
    else:
        decision.pop("decision_id")
        decision["disposition"] = "rejected"
        document(saved, seal(decision, "decision_id"))
    with pytest.raises(ValueError):
        review.replay(config, saved)


def test_final_boundary_checks_review_inputs(reviewed, monkeypatch):
    config, path, review_path, _, _, _ = reviewed
    original = EvidenceReads.verify

    def changed(reads):
        review_path.write_text("changed while deciding")
        original(reads)

    monkeypatch.setattr(EvidenceReads, "verify", changed)
    with pytest.raises(ValueError, match="Evidence changed"):
        review.decide(config, path, review_path, save=True)
    assert not (config.root / "state/evaluation/decisions").exists()


def probe_result():
    down, up = "lora_unet_one.lora_down.weight", "lora_unet_one.lora_up.weight"
    target = "diffusion_model.one.weight"
    header = {down: {"shape": [8, 16]}, up: {"shape": [32, 8]}}
    value = {
        "version": 1,
        "device": "cpu",
        "cuda_initialized": False,
        "visible_cuda_devices": 0,
        "torch_version": "fixture",
        "model_class": "SDXL",
        "rows": [
            {
                "target": target,
                "tensors": [down, up],
                "base_shape": [32, 16],
                "up_shape": [32, 8],
                "down_shape": [8, 16],
                "patch_type": "lora",
                "alpha_scale_milli": 1000,
            }
        ],
        "accepted": [{"strength_milli": s, "targets": [target]} for s in (250, 500, 1000)],
        "unconsumed": [],
    }
    return value, header


@pytest.mark.parametrize(
    "mutation",
    [
        None,
        "missing",
        "extra",
        "duplicate",
        "target",
        "shape",
        "rank",
        "scale",
        "type",
        "strength",
        "accepted",
        "bool",
        "unconsumed",
        "model",
        "gpu",
    ],
)
def test_loader_tensor_and_patch_coverage(mutation):
    value, header = probe_result()
    if mutation == "missing":
        value["rows"] = []
    elif mutation == "extra":
        header["unused"] = {"shape": [1, 1]}
    elif mutation == "duplicate":
        value["rows"] *= 2
    elif mutation == "target":
        value["rows"][0]["target"] = "text_encoder.one.weight"
    elif mutation == "shape":
        value["rows"][0]["base_shape"][0] = 64
    elif mutation == "rank":
        value["rows"][0]["down_shape"][0] = 4
    elif mutation == "scale":
        value["rows"][0]["alpha_scale_milli"] = 500
    elif mutation == "type":
        value["rows"][0]["patch_type"] = "diff"
    elif mutation == "strength":
        value["accepted"][0]["strength_milli"] = 500
    elif mutation == "accepted":
        value["accepted"][0]["targets"] = []
    elif mutation == "bool":
        value["version"] = True
    elif mutation == "unconsumed":
        value["unconsumed"] = ["tensor"]
    elif mutation == "model":
        value["model_class"] = "Other"
    elif mutation == "gpu":
        value["device"] = "cuda:0"
    if mutation:
        with pytest.raises(ValueError):
            loader.validate_result(value, header, [250, 500, 1000])
    else:
        assert loader.validate_result(value, header, [250, 500, 1000]) == value


def test_incomplete_groups_and_baseline_refused(reviewed):
    config, _, _, _, _, report = reviewed
    report["mode"] = "baseline"
    with pytest.raises(ValueError, match="complete corpus comparison"):
        review.packet(config, config.root / "plan.json", config.root / "mapping.json")
    report["matrix"].pop()
    with pytest.raises(ValueError, match="Incomplete comparison"):
        review.groups(report)


@pytest.fixture
def mapped(tmp_path, monkeypatch):
    config = initialize(
        tmp_path / "workspace", tmp_path / "runtime", python=tmp_path / "runtime/python.exe"
    )
    config.comfyui_root.mkdir()
    for name in (*loader.SOURCES, "python.exe"):
        path = config.comfyui_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Protocol fixture")
    measured, header = probe_result()
    asset = config.comfyui_root / "models/loras/fixture.safetensors"
    asset.parent.mkdir(parents=True)
    encoded = json.dumps(header).encode()
    asset.write_bytes(struct.pack("<Q", len(encoded)) + encoded)
    graph = json.dumps({"1": {"inputs": {"ckpt_name": "fixture.safetensors"}}})
    plan = {
        "plan_id": "a" * 64,
        "candidate": {"candidate_id": "b" * 64},
        "runtime": {
            "files": [loader._file(config.python)],
            "runtime": {"pytorch_version": "fixture"},
        },
        "specification": {},
        "deployment": {"loader_name": asset.name},
        "jobs": [
            {"workflow_json": graph, "strength_milli": s, "role": "adapter_plain"}
            for s in (250, 500, 1000)
        ],
    }
    plan_path = document(config.root / "plan.json", plan)
    monkeypatch.setattr(evaluation_runtime, "load_plan", lambda p: json.loads(p.read_bytes()))
    monkeypatch.setattr(evaluation_runtime, "_fresh_inputs", lambda *a: None)

    def run(command, **kwargs):
        assert command[1] == "-I" and kwargs["timeout"] == 600
        assert kwargs["env"]["CUDA_VISIBLE_DEVICES"] == "-1"
        request = json.loads(Path(command[-2]).read_bytes())
        assert request["adapter"] == str(asset)
        kwargs["stdout"].write("CPU fixture worker; no model executed\n")
        document(Path(command[-1]), measured)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", run)
    return config, plan_path


def test_loader_mapping_replay_and_cli(mapped, capsys):
    config, plan_path = mapped
    value = loader.mapping(config, plan_path, save=True)
    path = config.root / f"state/evaluation/mappings/{value['mapping_id']}.json"
    assert loader.inspect(config, path) == value
    assert main(["evaluation", "mapping-inspect", str(path), "--config", str(config.file)]) == 0
    assert "Mapped targets: 1" in capsys.readouterr().out


@pytest.mark.parametrize(
    "mutation", ["source", "request", "result", "worker", "command", "log", "plan"]
)
def test_loader_stale_bindings_refused(mapped, mutation):
    config, plan_path = mapped
    value = loader.mapping(config, plan_path, save=True)
    path = config.root / f"state/evaluation/mappings/{value['mapping_id']}.json"
    if mutation == "source":
        (config.comfyui_root / loader.SOURCES[0]).write_text("changed")
    elif mutation in {"request", "result", "log"}:
        (config.root / value[mutation]["path"]).write_text("changed")
    elif mutation == "plan":
        plan_path.write_text("changed")
    else:
        value.pop("mapping_id")
        if mutation == "worker":
            value["worker"]["sha256"] = "e" * 64
        else:
            value["command"][1] = "-O"
        document(path, seal(value, "mapping_id"))
    with pytest.raises(ValueError):
        loader.inspect(config, path)


def test_failed_loader_keeps_attempt_and_never_publishes_certificate(mapped, monkeypatch):
    config, plan_path = mapped

    def fail(command, **kwargs):
        kwargs["stdout"].write("retained loader failure")
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(ValueError, match="Loader probe failed; preserve"):
        loader.mapping(config, plan_path, save=True)
    assert not (config.root / "state/evaluation/mappings").exists()
    assert (
        next((config.root / "state/evaluation/loader-attempts").glob("*/worker.log")).read_text()
        == "CPU loader probe; CUDA_VISIBLE_DEVICES=-1; isolated Python\nretained loader failure"
    )


def test_worker_traces_each_patch_tensor_instead_of_cumulative_loaded_keys():
    first_up, first_down, second_up, second_down = (object() for _ in range(4))
    tensors = {
        "a.lora_up.weight": first_up,
        "a.lora_down.weight": first_down,
        "b.lora_up.weight": second_up,
        "b.lora_down.weight": second_down,
    }
    mapping = {"a": "first", "b": "second"}
    assert tensor_pair(tensors, mapping, "first", first_up, first_down) == [
        "a.lora_down.weight",
        "a.lora_up.weight",
    ]
    assert tensor_pair(tensors, mapping, "second", second_up, second_down) == [
        "b.lora_down.weight",
        "b.lora_up.weight",
    ]
    with pytest.raises(AssertionError):
        tensor_pair(tensors, mapping, "first", second_up, second_down)
    tensors["alias"] = first_up
    with pytest.raises(AssertionError):
        tensor_pair(tensors, mapping, "first", first_up, first_down)
