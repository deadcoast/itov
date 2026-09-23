"""HTTP protocol/PNG fixtures, separate from actual model evaluation evidence."""

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from quality_fixtures import curated_inputs as curated_inputs
from test_evaluation import complete
from test_training import document, png
from test_training import training_inputs as training_inputs

from itov import evaluation
from itov import evaluation_runtime as runtime
from itov.catalog import sha256
from itov.catalog_store import CatalogStore
from itov.cli import main
from itov.comfyui import ComfyUIClient, ComfyUIError
from itov.owned_jobs import job_path
from itov.runtime import launch_command
from itov.training_data import seal


@pytest.fixture
def runtime_case(curated_inputs, http_server):
    item = complete(curated_inputs, "training")
    url, routes, requests = http_server
    root = item.config.comfyui_root
    for name in (*runtime.RUNTIME_SOURCES, "main.py", "nodes.py", "folder_paths.py", "python.exe"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"stock runtime protocol fixture")
    item.config = replace(item.config, url=url, comfyui_python=root / "python.exe")
    item.config.file.write_text(
        f"version = 1\n[comfyui]\nroot = {json.dumps(str(root))}\n"
        f"python = {json.dumps(str(root / 'python.exe'))}\nurl = {json.dumps(url)}\n"
    )
    candidate = evaluation.candidate(item.config, item.plan_path)
    loader = f"itov_evaluation_{candidate['export']['sha256']}.safetensors"
    schemas = {
        "CheckpointLoaderSimple": (
            {"ckpt_name": [["fixture.safetensors"]]},
            ["MODEL", "CLIP", "VAE"],
        ),
        "LoraLoaderModelOnly": (
            {"model": ["MODEL"], "lora_name": [[loader]], "strength_model": ["FLOAT"]},
            ["MODEL"],
        ),
        "CLIPTextEncode": ({"clip": ["CLIP"], "text": ["STRING"]}, ["CONDITIONING"]),
        "EmptyLatentImage": (
            {"width": ["INT"], "height": ["INT"], "batch_size": ["INT"]},
            ["LATENT"],
        ),
        "KSampler": (
            {
                "model": ["MODEL"],
                "seed": ["INT"],
                "steps": ["INT"],
                "cfg": ["FLOAT"],
                "sampler_name": [["dpmpp_2m"]],
                "scheduler": [["karras"]],
                "denoise": ["FLOAT"],
                "positive": ["CONDITIONING"],
                "negative": ["CONDITIONING"],
                "latent_image": ["LATENT"],
            },
            ["LATENT"],
        ),
        "VAEDecode": ({"samples": ["LATENT"], "vae": ["VAE"]}, ["IMAGE"]),
        "SaveImage": ({"images": ["IMAGE"], "filename_prefix": ["STRING"]}, []),
    }
    routes["/object_info"] = (
        200,
        {
            kind: {
                "input": {"required": fields},
                "output": outputs,
                "python_module": "nodes",
                "output_node": kind == "SaveImage",
            }
            for kind, (fields, outputs) in schemas.items()
        },
    )
    routes["/system_stats"][1]["system"].update(
        argv=launch_command(item.config)[2:], comfyui_version="fixture"
    )
    routes["/queue"] = (200, {"queue_running": [], "queue_pending": []})
    history = {}
    routes["/history?max_items=200"] = (200, history)

    def submit(payload):
        index = len(routes["_posted"]) - 1
        prompt = f"evaluation-{index}"
        graph = payload["prompt"]
        record = {
            "prompt": [index, prompt, graph, payload["extra_data"], ["8"]],
            "outputs": {
                "8": {
                    "images": [
                        {"filename": f"evaluation-{index}.png", "subfolder": "", "type": "output"}
                    ]
                }
            },
            "status": {"completed": True, "status_str": "success", "messages": []},
        }
        history[prompt] = record
        routes[f"/history/{prompt}"] = (200, {prompt: record})
        routes[f"/view?filename=evaluation-{index}.png&subfolder=&type=output"] = (200, png(index))
        return {"prompt_id": prompt}

    routes["POST /prompt"] = (200, submit)
    item.eval_spec = {
        "version": 1,
        "id": "runtime-fixture",
        "training_plan": {
            "path": item.plan_path.relative_to(item.config.root).as_posix(),
            "sha256": sha256(item.plan_path.read_bytes()),
        },
        "sampler": {
            "steps": 20,
            "cfg_milli": 7000,
            "sampler_name": "dpmpp_2m",
            "scheduler": "karras",
        },
        "width": 512,
        "height": 512,
        "strength_milli": 1000,
    }
    item.eval_spec_path = document(item.config.root / "evaluation.json", item.eval_spec)
    item.routes, item.requests = routes, requests
    return item


def planned(item):
    value = runtime.plan(item.config, item.eval_spec_path, save=True)
    path = item.config.root / f"state/evaluation/plans/{value['plan_id']}.json"
    return value, path


def execute(item, path, **kwargs):
    return runtime.run(item.config, path, wait_timeout=0.1, poll_interval=0.005, **kwargs)


def test_complete_matrix_deployment_public_commands_and_offline_replay(runtime_case, capsys):
    item = runtime_case
    head = CatalogStore(item.config.root).snapshot().head
    old_run = (item.folder / "run.json").read_bytes()
    args = [str(item.eval_spec_path), "--config", str(item.config.file), "--save", "--json"]
    assert main(["evaluation", "plan", *args]) == 0
    preview = json.loads(capsys.readouterr().out)
    path = Path(preview["saved_path"])
    value = runtime.load_plan(path)
    assert runtime.plan(item.config, item.eval_spec_path) == value
    assert len(value["jobs"]) == 16
    assert len({(job["case_id"], job["seed"]) for job in value["jobs"]}) == 4
    assert runtime.status(item.config, path)["status"] == "not_started"
    assert not item.routes.get("_posted")
    assert execute(item, path)["succeeded"] == 16
    assert len(item.routes["_posted"]) == 16
    for job, payload in zip(value["jobs"], item.routes["_posted"], strict=True):
        assert payload["prompt"] == json.loads(job["workflow_json"])
        assert payload["prompt"]["6"]["inputs"]["seed"] == job["seed"]
        assert ("2" in payload["prompt"]) == job["role"].startswith("adapter_")
    before = list(item.requests)
    first = runtime.replay(item.config, path, save=True)
    assert runtime.replay(item.config, path, save=True) == first
    assert first["technical_pass"] and first["quality_acceptance"] == "not_established"
    assert execute(item, path, resume=True)["succeeded"] == 16
    for action in ("status", "replay"):
        assert main(["evaluation", action, str(path), "--config", str(item.config.file)]) == 0
        assert "Progress: 16/16 completed" in capsys.readouterr().out
    assert item.requests == before
    assert CatalogStore(item.config.root).snapshot().head == head
    assert (item.folder / "run.json").read_bytes() == old_run
    with sqlite3.connect(item.config.root / "state/batches/execution.sqlite3") as db:
        keys = db.execute("SELECT seed FROM seeds").fetchall()
    assert len(keys) == 4 and all(row[0].startswith("evaluation:") for row in keys)


@pytest.mark.parametrize("change", ["deployment", "runtime", "schema", "argv", "suite"])
def test_changed_binding_refuses_new_submission(runtime_case, change):
    item = runtime_case
    value, path = planned(item)
    if change == "deployment":
        (
            item.config.comfyui_root / "models/loras" / value["deployment"]["loader_name"]
        ).write_bytes(b"changed")
    elif change == "runtime":
        (item.config.comfyui_root / "comfy/lora.py").write_bytes(b"changed")
    elif change == "schema":
        item.routes["/object_info"][1]["KSampler"]["description"] = "changed"
    elif change == "argv":
        item.routes["/system_stats"][1]["system"]["argv"].append("--changed")
    else:
        (item.config.root / item.spec["qualification"]["suite"]["path"]).write_bytes(b"changed")
    with pytest.raises(ValueError):
        execute(item, path)
    assert not item.routes.get("_posted")


@pytest.mark.parametrize("mutation", ["graph", "case", "missing"])
def test_resealed_plan_cannot_change_matrix_or_graph(runtime_case, mutation):
    item = runtime_case
    value, path = planned(item)
    value.pop("plan_id")
    if mutation == "graph":
        graph = json.loads(value["jobs"][0]["workflow_json"])
        graph["6"]["inputs"]["steps"] = 1
        value["jobs"][0]["workflow_json"] = json.dumps(graph)
    elif mutation == "case":
        value["jobs"][0]["role"] = "adapter_plain"
    else:
        value["jobs"].pop()
    document(path, seal(value, "plan_id"))
    with pytest.raises(ValueError, match="bindings differ"):
        runtime.load_plan(path)


@pytest.mark.parametrize("proof", ["present", "missing", "wrong_graph"])
def test_lost_ack_is_observed_never_reposted(runtime_case, monkeypatch, proof):
    item = runtime_case
    value, path = planned(item)
    original = ComfyUIClient.submit

    def lost_ack(client, *args):
        original(client, *args)
        raise ComfyUIError("Lost acknowledgement fixture")

    monkeypatch.setattr(ComfyUIClient, "submit", lost_ack)
    first = execute(item, path)
    assert first["status"] == "paused" and len(item.routes["_posted"]) == 1
    monkeypatch.setattr(ComfyUIClient, "submit", original)
    if proof == "missing":
        item.routes["/history?max_items=200"][1].clear()
    elif proof == "wrong_graph":
        item.routes["/history?max_items=200"][1]["evaluation-0"]["prompt"][2] = {}
    second = execute(item, path, resume=True)
    assert len(item.routes["_posted"]) == (16 if proof == "present" else 1)
    assert second["status"] == ("succeeded" if proof == "present" else "paused")
    assert job_path(item.config, value["plan_id"], 0).is_file()


def test_corrupt_output_stops_matrix_and_preserves_evidence(runtime_case):
    item = runtime_case
    _, path = planned(item)
    submit = item.routes["POST /prompt"][1]

    def corrupt(payload):
        result = submit(payload)
        item.routes["/view?filename=evaluation-0.png&subfolder=&type=output"] = (200, png(0)[:40])
        return result

    item.routes["POST /prompt"] = (200, corrupt)
    observed = execute(item, path)
    assert observed["status"] == "paused"
    assert observed["matrix"][0]["status"] == "collection_failed"
    assert len(item.routes["_posted"]) == 1
    with pytest.raises(ValueError, match="incomplete"):
        runtime.replay(item.config, path)
    assert execute(item, path, resume=True)["status"] == "paused"
    assert len(item.routes["_posted"]) == 1
    assert runtime.abandon(item.config, path)["status"] == "abandoned"
    assert execute(item, path, resume=True)["status"] == "abandoned"
    assert len(item.routes["_posted"]) == 1


def test_accepted_job_is_collected_before_stale_runtime_blocks_next_job(runtime_case):
    item = runtime_case
    _, path = planned(item)
    submit = item.routes["POST /prompt"][1]

    def pause(payload):
        result = submit(payload)
        item.routes["/history/evaluation-0"] = (200, {})
        return result

    item.routes["POST /prompt"] = (200, pause)
    assert execute(item, path)["matrix"][0]["status"] == "timed_out"
    assert len(item.routes["_posted"]) == 1
    retained = item.routes["/history?max_items=200"][1]["evaluation-0"]
    item.routes["/history/evaluation-0"] = (200, {"evaluation-0": retained})
    (item.config.comfyui_root / "nodes.py").write_bytes(b"changed")
    observed = execute(item, path, resume=True)
    assert observed["succeeded"] == 1 and observed["status"] == "paused"
    assert len(item.routes["_posted"]) == 1


def test_existing_deployment_is_not_overwritten(runtime_case):
    item = runtime_case
    value, _ = planned(item)
    target = item.config.comfyui_root / "models/loras" / value["deployment"]["loader_name"]
    target.write_bytes(b"preserve")
    with pytest.raises(ValueError, match="differs"):
        planned(item)
    assert target.read_bytes() == b"preserve"


@pytest.mark.parametrize("change", ["steps", "strength", "boolean", "training_ref", "sampler"])
def test_invalid_specification_refuses_before_deployment(runtime_case, change):
    item = runtime_case
    if change == "steps":
        item.eval_spec["sampler"]["steps"] = 500
    elif change == "strength":
        item.eval_spec["strength_milli"] = 0
    elif change == "boolean":
        item.eval_spec["sampler"]["cfg_milli"] = True
    elif change == "training_ref":
        item.eval_spec["training_plan"]["sha256"] = "0" * 64
    else:
        item.eval_spec["sampler"]["sampler_name"] = "unqualified"
    document(item.eval_spec_path, item.eval_spec)
    with pytest.raises(ValueError):
        planned(item)
    assert not (item.config.comfyui_root / "models/loras").exists()
    assert not item.routes.get("_posted")


def test_changed_completed_artifact_is_reported_without_network_or_rewriting(runtime_case):
    item = runtime_case
    value, path = planned(item)
    assert execute(item, path)["ok"]
    record_path = job_path(item.config, value["plan_id"], 0)
    original_record = record_path.read_bytes()
    artifact = Path(json.loads(original_record)["artifacts"][0]["path"])
    artifact.write_bytes(b"preserve damaged evidence")
    before = list(item.requests)
    observed = runtime.status(item.config, path)
    assert observed["status"] == "artifact_invalid"
    assert observed["matrix"][0]["status"] == "artifact_invalid"
    with pytest.raises(ValueError, match="invalid"):
        runtime.replay(item.config, path)
    assert record_path.read_bytes() == original_record
    assert artifact.read_bytes() == b"preserve damaged evidence"
    assert item.requests == before


def test_abandonment_allows_distinct_plan_with_same_paired_seeds(runtime_case):
    item = runtime_case
    first, path = planned(item)
    item.routes["/queue"][1]["queue_pending"] = [[0, "unrelated", {}, {}]]
    assert execute(item, path)["status"] == "paused"
    assert runtime.abandon(item.config, path)["status"] == "abandoned"
    item.eval_spec["id"] = "second-comparison"
    document(item.eval_spec_path, item.eval_spec)
    second, other = planned(item)
    assert first["plan_id"] != second["plan_id"]
    assert execute(item, other)["status"] == "paused"
    with sqlite3.connect(item.config.root / "state/batches/execution.sqlite3") as db:
        keys = db.execute("SELECT seed FROM seeds").fetchall()
    assert len(keys) == 8
    assert not item.routes.get("_posted")
    assert runtime.abandon(item.config, other)["status"] == "abandoned"
