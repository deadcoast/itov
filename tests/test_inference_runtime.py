"""Protocol fixtures prove bindings/recovery; real model evidence is retained separately."""

import copy
import json
import sqlite3
from pathlib import Path

import pytest
from quality_fixtures import curated_inputs as curated_inputs  # noqa: F401
from test_evaluation_runtime import runtime_case as runtime_case  # noqa: F401
from test_training import document
from test_training import training_inputs as training_inputs  # noqa: F401

from itov import evaluation
from itov import inference_capabilities as caps
from itov import inference_runtime as runtime
from itov.catalog import sha256
from itov.catalog_store import CatalogStore
from itov.cli import main
from itov.comfyui import ComfyUIClient, ComfyUIError
from itov.owned_jobs import job_path
from itov.training_data import seal


@pytest.fixture
def inference_v2(runtime_case, monkeypatch):
    item = runtime_case
    candidate = evaluation.candidate(item.config, item.plan_path)
    checkpoint = item.spec["checkpoint"]
    monkeypatch.setattr(caps, "CHECKPOINT", checkpoint["sha256"])
    monkeypatch.setattr(caps, "LCM", sha256(b"LCM protocol fixture"))
    lcm = item.config.comfyui_root / "models/loras/lcm.safetensors"
    lcm.parent.mkdir(parents=True, exist_ok=True)
    lcm.write_bytes(b"LCM protocol fixture")
    registry = item.routes["/object_info"][1]
    registry["LoraLoaderModelOnly"]["input"]["required"]["lora_name"][0].extend(
        ["lcm.safetensors", f"itov_candidate_{candidate['export']['sha256']}.safetensors"]
    )
    registry["KSampler"]["input"]["required"]["sampler_name"][0].append("lcm")
    registry["KSampler"]["input"]["required"]["scheduler"][0].append("sgm_uniform")
    item.inference = {
        "version": 2,
        "capability": caps.CAPABILITY,
        "checkpoint": checkpoint,
        "adapters": [
            {
                "kind": "trained_candidate",
                "training_plan": item.eval_spec["training_plan"],
                "candidate_id": candidate["candidate_id"],
                "sha256": candidate["export"]["sha256"],
                "strength_milli": 750,
            }
        ],
        "sampler": item.eval_spec["sampler"],
        "width": 512,
        "height": 512,
        "prompt": "A ceramic vase and two pears",
        "negative_prompt": "",
        "seed": 712345,
        "count": 2,
    }
    return item


def stack(item):
    item.inference["adapters"].insert(
        0,
        {
            "kind": "lcm",
            "loader_name": "lcm.safetensors",
            "sha256": caps.LCM,
            "strength_milli": 1000,
        },
    )
    item.inference["sampler"] = {
        "steps": 4,
        "cfg_milli": 1000,
        "sampler_name": "lcm",
        "scheduler": "sgm_uniform",
    }


def planned(item):
    runtime.prepare(item.config, item.inference)
    value = runtime.plan(item.config, item.inference, save=True)
    return value, item.config.root / f"state/inference/plans/{value['plan_id']}.json"


def execute(item, path, **kwargs):
    return runtime.run(item.config, path, wait_timeout=0.05, poll_interval=0.005, **kwargs)


@pytest.mark.parametrize("layers", ["candidate", "stack", "lcm", "base"])
def test_public_pipeline_exact_bindings_and_offline_replay(
    inference_v2, layers, capsys, monkeypatch
):
    item = inference_v2
    if layers in ("stack", "lcm"):
        stack(item)
    if layers in ("base", "lcm"):
        item.inference["adapters"].pop()
    original = CatalogStore(item.config.root).snapshot().raw
    training_record = (item.folder / "run.json").read_bytes()
    spec_path = document(item.config.root / "inference.json", item.inference)
    args = [str(spec_path), "--config", str(item.config.file), "--json"]
    before = list(item.requests)
    assert main(["inference", "prepare", *args]) == 0
    prepared = json.loads(capsys.readouterr().out)
    assert item.requests == before
    assert prepared["deployment"]["catalog_activation"] is False
    assert main(["inference", "plan", *args, "--save"]) == 0
    result = json.loads(capsys.readouterr().out)
    path, value = Path(result["saved_path"]), result["plan"]
    assert runtime.plan(item.config, item.inference) == value
    assert not item.routes.get("_posted")
    assert (
        main(["inference", "status", str(path), "--config", str(item.config.file), "--json"]) == 1
    )
    assert json.loads(capsys.readouterr().out)["status"] == "not_started"
    assert main(["inference", "run", str(path), "--config", str(item.config.file), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["succeeded"] == 2
    for job, posted in zip(value["jobs"], item.routes["_posted"], strict=True):
        graph = posted["prompt"]
        assert graph == json.loads(job["workflow_json"])
        assert graph["3"]["inputs"]["clip"] == ["1", 1]
        previous = ["1", 0]
        for i, declared in enumerate(item.inference["adapters"]):
            node = graph[str(10 + i)]
            assert node["inputs"]["model"] == previous
            assert node["inputs"]["strength_model"] == declared["strength_milli"] / 1000
            assert node["_meta"]["itov_asset_sha256"] == declared["sha256"]
            previous = [str(10 + i), 0]
        assert graph["6"]["inputs"]["model"] == previous
    before = list(item.requests)

    def offline(*args, **kwargs):
        raise AssertionError("Completed replay attempted HTTP")

    monkeypatch.setattr("socket.socket.connect", offline)
    assert execute(item, path, resume=True)["ok"]
    for action in ("status", "replay"):
        assert main(["inference", action, str(path), "--config", str(item.config.file)]) == 0
        assert "Inference:" in capsys.readouterr().out
    report = runtime.replay(item.config, path, save=True)
    assert report == runtime.replay(item.config, path, save=True)
    assert report["technical_pass"] and report["quality_acceptance"] == "not_established"
    assert item.requests == before and len(item.routes["_posted"]) == 2
    assert CatalogStore(item.config.root).snapshot().raw == original
    assert (item.folder / "run.json").read_bytes() == training_record
    with sqlite3.connect(item.config.root / "state/batches/execution.sqlite3") as db:
        assert {row[0] for row in db.execute("SELECT seed FROM seeds")} == {"712345", "712346"}


@pytest.mark.parametrize(
    "change",
    [
        "checkpoint",
        "candidate",
        "hash",
        "plan",
        "clip",
        "duplicate",
        "order",
        "lcm_hash",
        "lcm_strength",
        "sampler",
        "cfg",
        "strength",
        "version",
        "capability",
        "count",
        "seed",
        "dimensions",
    ],
)
def test_incompatible_stack_fails_before_staging_or_network(inference_v2, change):
    item = inference_v2
    stack(item)
    spec = item.inference
    adapter = spec["adapters"][-1]
    if change == "checkpoint":
        spec["checkpoint"] = {**spec["checkpoint"], "sha256": "a" * 64}
    elif change == "candidate":
        adapter["candidate_id"] = "a" * 64
    elif change == "hash":
        adapter["sha256"] = "a" * 64
    elif change == "plan":
        adapter["training_plan"] = {**adapter["training_plan"], "sha256": "a" * 64}
    elif change == "clip":
        adapter["strength_clip_milli"] = 500
    elif change == "duplicate":
        spec["adapters"] = [adapter, adapter]
    elif change == "order":
        spec["adapters"].reverse()
    elif change == "lcm_hash":
        spec["adapters"][0]["sha256"] = "a" * 64
    elif change == "lcm_strength":
        spec["adapters"][0]["strength_milli"] = 750
    elif change == "sampler":
        spec["sampler"]["sampler_name"] = "dpmpp_2m"
    elif change == "cfg":
        spec["sampler"]["cfg_milli"] = 7000
    elif change == "strength":
        adapter["strength_milli"] = True
    else:
        spec[{"dimensions": "width"}.get(change, change)] = {
            "version": True,
            "capability": "sd15",
            "count": 17,
            "seed": 2**64 - 1,
            "dimensions": 513,
        }[change]
    before = list(item.requests)
    with pytest.raises(ValueError):
        runtime.prepare(item.config, spec)
    assert item.requests == before
    assert not (item.config.root / "state/inference").exists()
    assert not list((item.config.comfyui_root / "models/loras").glob("itov_candidate_*"))


@pytest.mark.parametrize(
    "change",
    ["checkpoint", "deployment", "workspace_asset", "training", "runtime", "schema", "argv"],
)
def test_stale_binding_prevents_post(inference_v2, change):
    item = inference_v2
    value, path = planned(item)
    adapter = value["deployment"]["adapters"][0]
    if change == "checkpoint":
        target = (
            item.config.comfyui_root / "models/checkpoints" / item.spec["checkpoint"]["loader_name"]
        )
    elif change == "deployment":
        target = item.config.comfyui_root / "models/loras" / adapter["loader_name"]
    elif change == "workspace_asset":
        target = item.config.root / adapter["asset"]["path"]
    elif change == "training":
        target = item.plan_path
    else:
        target = item.config.comfyui_root / "comfy/lora.py"
    if change == "schema":
        item.routes["/object_info"][1]["KSampler"]["description"] = "changed"
    elif change == "argv":
        item.routes["/system_stats"][1]["system"]["argv"].append("--changed")
    else:
        target.write_bytes(b"preserve stale input")
    with pytest.raises(ValueError):
        execute(item, path)
    assert not item.routes.get("_posted")


@pytest.mark.parametrize(
    "change", ["graph_strength", "graph_chain", "missing_job", "declared_strength"]
)
def test_resealed_tampering_is_rejected(inference_v2, change):
    item = inference_v2
    value, path = planned(item)
    body = {k: copy.deepcopy(v) for k, v in value.items() if k != "plan_id"}
    if change.startswith("graph"):
        graph = json.loads(body["jobs"][0]["workflow_json"])
        if change == "graph_strength":
            graph["10"]["inputs"]["strength_model"] = 1
        else:
            graph["6"]["inputs"]["model"] = ["1", 0]
        body["jobs"][0]["workflow_json"] = json.dumps(graph)
        body["jobs"][0]["workflow_sha256"] = sha256(json.dumps(graph).encode())
    elif change == "missing_job":
        body["jobs"].pop()
    else:
        body["specification"]["adapters"][0]["strength_milli"] = 500
    document(path, seal(body, "plan_id"))
    with pytest.raises(ValueError):
        execute(item, path)
    assert not item.routes.get("_posted")


@pytest.mark.parametrize("proof", ["present", "missing", "wrong_graph"])
def test_lost_ack_never_duplicates_stack(inference_v2, monkeypatch, proof):
    item = inference_v2
    stack(item)
    _, path = planned(item)
    original = ComfyUIClient.submit

    def lose(client, *args):
        original(client, *args)
        raise ComfyUIError("Lost acknowledgement fixture")

    monkeypatch.setattr(ComfyUIClient, "submit", lose)
    assert execute(item, path)["status"] == "paused"
    monkeypatch.setattr(ComfyUIClient, "submit", original)
    history = item.routes["/history?max_items=200"][1]
    if proof == "missing":
        history.clear()
    elif proof == "wrong_graph":
        history["evaluation-0"]["prompt"][2]["10"]["inputs"]["strength_model"] = 0.1
    observed = execute(item, path, resume=True)
    assert len(item.routes["_posted"]) == (2 if proof == "present" else 1)
    assert observed["ok"] == (proof == "present")


def test_resume_collects_owned_image_before_stale_next_submission(inference_v2):
    item = inference_v2
    _, path = planned(item)
    submit = item.routes["POST /prompt"][1]

    def pause(payload):
        ack = submit(payload)
        item.routes["/history/evaluation-0"] = (200, {})
        return ack

    item.routes["POST /prompt"] = (200, pause)
    assert execute(item, path)["images"][0]["status"] == "timed_out"
    history = item.routes["/history?max_items=200"][1]["evaluation-0"]
    item.routes["/history/evaluation-0"] = (200, {"evaluation-0": history})
    (item.config.comfyui_root / "comfy/lora.py").write_bytes(b"changed")
    observed = execute(item, path, resume=True)
    assert observed["succeeded"] == 1 and observed["status"] == "paused"
    assert len(item.routes["_posted"]) == 1
    assert runtime.abandon(item.config, path)["status"] == "abandoned"


def test_corrupt_artifact_offline_replay_refused_without_rewrite(inference_v2):
    item = inference_v2
    value, path = planned(item)
    assert execute(item, path)["ok"]
    record_path = job_path(item.config, value["plan_id"], 0)
    original = record_path.read_bytes()
    output = Path(json.loads(original)["artifacts"][0]["path"])
    output.write_bytes(b"preserve damaged artifact")
    before = list(item.requests)
    assert runtime.status(item.config, path)["status"] == "artifact_invalid"
    with pytest.raises(ValueError, match="incomplete or invalid"):
        runtime.replay(item.config, path)
    assert item.requests == before and record_path.read_bytes() == original


def test_seed_reservations_survive_changed_strength(inference_v2):
    item = inference_v2
    _, path = planned(item)
    assert execute(item, path)["ok"]
    item.inference["adapters"][0]["strength_milli"] = 500
    _, second = planned(item)
    with pytest.raises(ValueError, match="already reserved"):
        execute(item, second)
    assert len(item.routes["_posted"]) == 2


def test_capabilities_without_config(capsys):
    assert main(["inference", "capabilities", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["capability"] == caps.CAPABILITY
