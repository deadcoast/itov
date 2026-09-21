import json
import subprocess
from pathlib import Path

import pytest
from test_batch_execution import execution_case as execution_case

from itov.batch import create_plan, save_plan
from itov.batch_execution import abandon_batch, run_batch
from itov.catalog import MAX_INTEGER, load_catalog, sha256
from itov.catalog_store import CatalogStore
from itov.cli import main
from itov.comfyui import ComfyUIError
from itov.media import verify_video, video_tools
from itov.owned_jobs import job_path
from itov.qualification import qualify, save_qualification
from itov.video import describe, load_spec, plan_video, prepare_video
from itov.workflow import validate_workflow


@pytest.fixture
def video_case(execution_case, monkeypatch):
    config, _, _, _, routes, requests = execution_case
    spec = load_spec(Path("examples/wan22.video.json"))
    registry = json.loads(Path("tests/fixtures/wan22-stock-node-schema.json").read_bytes())
    routes["/object_info"] = (200, registry)
    for key, folder in (
        ("diffusion", "diffusion_models"),
        ("text_encoder", "text_encoders"),
        ("vae", "vae"),
    ):
        raw = ("synthetic " + key).encode()
        spec[key]["sha256"] = sha256(raw)
        target = config.comfyui_root / "models" / folder / spec[key]["loader_name"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    for name in ("nodes_model_advanced", "nodes_wan", "nodes_video"):
        path = config.comfyui_root / "comfy_extras" / (name + ".py")
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"stock source fixture")
    source = config.root / "source.png"
    source.write_bytes(b"synthetic image fixture")
    spec["input_image"]["sha256"] = sha256(source.read_bytes())
    monkeypatch.setattr(
        "itov.qualification.video_tools", lambda: {"ffmpeg": "fixture", "ffprobe": "fixture"}
    )
    return config, spec, source, routes, requests


def prepare_plan(case):
    config, spec, source, _, _ = case
    prepared = prepare_video(config, spec, image_source=source)
    CatalogStore(config.root).import_catalog(
        load_catalog(Path(prepared["catalog"])), expected_head=prepared["expected_head"]
    )
    return plan_video(config, spec)


def test_video_prepare_and_plan_preserve_catalog_and_are_repeatable(video_case, monkeypatch):
    config, spec, source, routes, requests = video_case
    before = CatalogStore(config.root).snapshot()
    requests.clear()
    prepared = prepare_video(config, spec, image_source=source)
    assert prepared == prepare_video(config, spec)
    assert CatalogStore(config.root).snapshot().raw == before.raw
    assert not requests and not (config.root / "state/jobs").exists()
    with pytest.raises(ValueError, match="Import"):
        plan_video(config, spec)
    plan = prepare_plan(video_case)
    assert plan == plan_video(config, spec)
    assert [job["seed"] for job in plan["jobs"]] == [spec["seed"], spec["seed"] + 1]
    assert len(CatalogStore(config.root).snapshot().to_dict()["catalog"]["presets"]) == 2
    graph = json.loads(plan["jobs"][0]["workflow_json"])
    assert validate_workflow(graph, routes["/object_info"][1]).valid
    assert graph["7"]["inputs"]["start_image"] == ["4", 0]
    assert graph["12"]["inputs"]["format.codec"] == "h264"
    receipt = qualify(config, plan)
    assert receipt["profile"] == "stock-wan22-v1"
    assert len(receipt["files"]) == 10  # 3 core files, 3 node modules, 3 weights, input.
    assert not any(method == "POST" for method, _ in requests)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("version", True),
        ("profile", "unknown"),
        ("frames", 32),
        ("frames", 53),
        ("fps", True),
        ("fps", 31),
        ("width", 513),
        ("height", 864),
        ("count", 5),
        ("seed", MAX_INTEGER),
        ("prompt", "embedding:external"),
        ("negative_prompt", "x" * 4097),
    ],
)
def test_invalid_video_spec_refuses_writes(video_case, key, value):
    config, spec, source, _, _ = video_case
    spec[key] = value
    with pytest.raises(ValueError):
        prepare_video(config, spec, image_source=source)
    assert not (config.root / "workflows/video").exists()


@pytest.mark.parametrize("key", ["diffusion", "text_encoder", "vae", "input_image"])
def test_video_pins_are_enforced_by_qualification(video_case, key):
    config, spec, _, _, _ = video_case
    plan = prepare_plan(video_case)
    if key == "input_image":
        path = config.root / "input" / spec[key]["name"]
    else:
        folder = {"diffusion": "diffusion_models", "text_encoder": "text_encoders", "vae": "vae"}[
            key
        ]
        path = config.comfyui_root / "models" / folder / spec[key]["loader_name"]
    path.write_bytes(b"changed asset")
    with pytest.raises(ValueError, match="SHA-256"):
        qualify(config, plan)
    with pytest.raises(ValueError, match="SHA-256"):
        plan_video(config, spec)


@pytest.mark.parametrize(("key", "alias"), [("diffusion", "unet"), ("text_encoder", "clip")])
def test_ambiguous_model_aliases_are_refused(video_case, key, alias):
    config, spec, source, _, _ = video_case
    path = config.comfyui_root / "models" / alias / spec[key]["loader_name"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(("synthetic " + key).encode())
    with pytest.raises(ValueError, match="unambiguous"):
        prepare_video(config, spec, image_source=source)


def test_input_and_workflow_conflicts_are_preserved(video_case):
    config, spec, source, _, _ = video_case
    prepared = prepare_video(config, spec, image_source=source)
    target = config.root / "input" / spec["input_image"]["name"]
    target.write_bytes(b"preserve")
    with pytest.raises(ValueError, match="differs"):
        prepare_video(config, spec, image_source=source)
    assert target.read_bytes() == b"preserve"
    target.write_bytes(source.read_bytes())
    Path(prepared["workflow"]).write_bytes(b"preserve workflow")
    with pytest.raises(ValueError, match="differs"):
        prepare_video(config, spec)
    assert Path(prepared["workflow"]).read_bytes() == b"preserve workflow"


def test_video_node_module_and_source_are_bound(video_case):
    config, _, _, routes, _ = video_case
    plan = prepare_plan(video_case)
    original = qualify(config, plan)
    (config.comfyui_root / "comfy_extras/nodes_wan.py").write_bytes(b"changed stock code")
    assert qualify(config, plan)["qualification_id"] != original["qualification_id"]
    routes["/object_info"][1]["SaveVideo"]["python_module"] = "custom_nodes.fake"
    with pytest.raises(ValueError, match="stock implementation"):
        qualify(config, plan)


def test_missing_video_input_pin_refused(video_case):
    config, spec, _, _, _ = video_case
    plan = prepare_plan(video_case)
    store = CatalogStore(config.root)
    catalog = store.snapshot().to_dict()["catalog"]
    preset = next(item for item in catalog["presets"] if item["id"].startswith("video-"))
    path = config.root / preset["workflow"]["path"]
    graph = json.loads(path.read_bytes())
    graph["4"].pop("_meta")
    raw = json.dumps(graph).encode()
    path.write_bytes(raw)
    preset["workflow"]["sha256"] = sha256(raw)
    snapshot = store.import_catalog(catalog, expected_head=plan["catalog_head"])
    plan["request"]["catalog_head"] = snapshot.head
    with pytest.raises(ValueError, match="SHA-256"):
        qualify(config, create_plan(config.root, plan["request"]))


def test_video_cli_preparation_and_plan(video_case, capsys):
    config, spec, source, _, _ = video_case
    file = config.root / "video.json"
    file.write_text(json.dumps(spec))
    args = [str(file), "--config", str(config.file), "--json"]
    assert main(["video", "prepare", *args, "--image-source", str(source)]) == 0
    prepared = json.loads(capsys.readouterr().out)
    CatalogStore(config.root).import_catalog(
        load_catalog(Path(prepared["catalog"])), expected_head=prepared["expected_head"]
    )
    assert main(["video", "plan", *args, "--save"]) == 0
    assert Path(json.loads(capsys.readouterr().out)["path"]).is_file()


@pytest.mark.parametrize("finish", ["resume", "abandon", "missing_history"])
def test_video_decode_failure_stops_next_job_and_resume_never_reposts(
    video_case, monkeypatch, finish
):
    config, _, _, routes, requests = video_case
    plan = prepare_plan(video_case)
    path = save_plan(config.root, plan)
    receipt = save_qualification(config, qualify(config, plan))
    failed = True

    def validate(path, expected):
        assert path.read_bytes() == b"video fixture"
        if failed:
            raise ValueError("Injected video decode failure")
        return {"ok": True, **expected}

    def submit(payload):
        index = len(routes["_posted"]) - 1
        if index:
            previous = json.loads(job_path(config, plan["plan_id"], index - 1).read_bytes())
            assert previous["artifacts"][0]["video_validation"]["ok"]
        prompt = f"video-{index}"
        entry = {
            "prompt": [index, prompt, payload["prompt"], payload["extra_data"], ["12"]],
            "outputs": {
                "12": {"images": [{"filename": prompt + ".mp4", "subfolder": "", "type": "output"}]}
            },
            "status": {"completed": True, "status_str": "success", "messages": []},
        }
        routes[f"/history/{prompt}"] = (200, {prompt: entry})
        routes[f"/view?filename={prompt}.mp4&subfolder=&type=output"] = (200, b"video fixture")
        return {"prompt_id": prompt, "node_errors": {}}

    routes["POST /prompt"] = (200, submit)
    monkeypatch.setattr("itov.jobs.verify_video", validate)
    result = run_batch(config, path, qualification=receipt, poll_interval=0.01)
    assert result["status"] == "paused"
    assert len(routes["_posted"]) == 1
    first = json.loads(job_path(config, plan["plan_id"], 0).read_bytes())
    assert first["status"] == "collection_failed" and first["prompt_id"] == "video-0"
    if finish != "resume":
        if finish == "missing_history":
            routes["/history/video-0"] = (200, {})
            with pytest.raises(ComfyUIError, match="ownership evidence"):
                abandon_batch(config, path)
        else:
            assert abandon_batch(config, path)["status"] == "abandoned"
            assert first["artifacts"]
            assert run_batch(config, path, resume=True)["status"] == "abandoned"
        assert len(routes["_posted"]) == 1
        return
    failed = False
    assert run_batch(config, path, resume=True, poll_interval=0.01)["status"] == "succeeded"
    assert len(routes["_posted"]) == 2
    requests.clear()
    assert run_batch(config, path, resume=True)["status"] == "succeeded"
    assert not requests


@pytest.fixture
def encoded_video(tmp_path):
    tools = video_tools()
    path = tmp_path / "sample.mp4"
    command = [
        tools["ffmpeg"],
        "-v",
        "error",
        "-nostdin",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=512x512:rate=24",
        "-frames:v",
        "9",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(path),
    ]
    subprocess.run(command, check=True, capture_output=True, timeout=30)
    return path, {"width": 512, "height": 512, "frames": 9, "fps": 24}


def test_full_real_video_decode(encoded_video):
    path, expected = encoded_video
    result = verify_video(path, expected)
    assert result["distinct_frames"] == 9 and result["constant_frame_timestamps"]
    assert result["duration_seconds"] == 0.375


@pytest.mark.parametrize(("key", "value"), [("width", 544), ("fps", 25), ("frames", 13)])
def test_video_metadata_must_match_contract(encoded_video, key, value):
    path, expected = encoded_video
    expected[key] = value
    with pytest.raises(ValueError, match="differ"):
        verify_video(path, expected)


def test_truncated_video_is_rejected(encoded_video):
    path, expected = encoded_video
    path.write_bytes(path.read_bytes()[:200])
    with pytest.raises(ValueError, match="validation failed"):
        verify_video(path, expected)


def test_static_video_is_rejected(tmp_path):
    tools = video_tools()
    path = tmp_path / "static.mp4"
    subprocess.run(
        [
            tools["ffmpeg"],
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=red:size=512x512:rate=24",
            "-frames:v",
            "9",
            "-c:v",
            "libx264",
            str(path),
        ],
        capture_output=True,
        check=True,
        timeout=30,
    )
    with pytest.raises(ValueError, match="no observable"):
        verify_video(path, {"width": 512, "height": 512, "frames": 9, "fps": 24})


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("format", "avi", "invalid_choice"),
        ("format.codec", "hevc", "invalid_choice"),
        ("format.codec", None, "invalid_choice"),
    ],
)
def test_dynamic_video_encoding_inputs_are_validated(field, value, code):
    graph = json.loads(describe(load_spec(Path("examples/wan22.video.json")))["workflow"])
    graph["12"]["inputs"][field] = value
    registry = json.loads(Path("tests/fixtures/wan22-stock-node-schema.json").read_bytes())
    assert code in {issue.code for issue in validate_workflow(graph, registry).issues}


def test_required_dynamic_child_is_checked():
    graph = json.loads(describe(load_spec(Path("examples/wan22.video.json")))["workflow"])
    del graph["12"]["inputs"]["format.codec"]
    registry = json.loads(Path("tests/fixtures/wan22-stock-node-schema.json").read_bytes())
    assert any(
        issue.code == "missing_input" and issue.input_name == "format.codec"
        for issue in validate_workflow(graph, registry).issues
    )


def test_nested_video_input_is_rejected_before_preparation(video_case):
    config, spec, source, _, _ = video_case
    spec["input_image"]["name"] = "nested/still-life.png"
    with pytest.raises(ValueError, match="top-level PNG"):
        prepare_video(config, spec, image_source=source)
    assert not (config.root / "workflows/video").exists()
