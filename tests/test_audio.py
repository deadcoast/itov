import json
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from test_batch_execution import execution_case as execution_case
from test_video import encoded_video as encoded_video

from itov.audio import (
    describe,
    load_spec,
    output_contract,
    plan_audio,
    prepare_audio,
    validate_spec,
)
from itov.audio_media import verify_audio
from itov.audiovisual import mux
from itov.audiovisual import validate_spec as validate_av_spec
from itov.batch import create_plan, save_plan
from itov.batch_execution import run_batch
from itov.catalog import MAX_INTEGER, load_catalog, sha256
from itov.catalog_store import CatalogStore
from itov.cli import main
from itov.media import verify_video, video_tools
from itov.owned_jobs import job_path
from itov.qualification import qualify, save_qualification
from itov.workflow import validate_workflow


@pytest.fixture
def audio_case(execution_case):
    config, _, _, _, routes, requests = execution_case
    spec = load_spec(Path("examples/stable-audio.audio.json"))
    registry = json.loads(Path("tests/fixtures/stable-audio-stock-node-schema.json").read_bytes())
    routes["/object_info"] = (200, registry)
    for key, folder in (("checkpoint", "checkpoints"), ("text_encoder", "text_encoders")):
        raw = ("synthetic " + key).encode()
        spec[key]["sha256"] = sha256(raw)
        path = config.comfyui_root / "models" / folder / spec[key]["loader_name"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    path = config.comfyui_root / "comfy_extras/nodes_audio.py"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(b"stock source fixture")
    return config, spec, routes, requests


def prepare_plan(case):
    config, spec, _, _ = case
    prepared = prepare_audio(config, spec)
    CatalogStore(config.root).import_catalog(
        load_catalog(Path(prepared["catalog"])), expected_head=prepared["expected_head"]
    )
    return plan_audio(config, spec)


def test_repeatable_audio_plan_is_explicit_and_preparation_has_no_side_effects(audio_case):
    config, spec, routes, requests = audio_case
    before = CatalogStore(config.root).snapshot()
    requests.clear()
    prepared = prepare_audio(config, spec)
    assert prepared == prepare_audio(config, spec)
    assert CatalogStore(config.root).snapshot().raw == before.raw
    assert not requests
    with pytest.raises(ValueError, match="Import"):
        plan_audio(config, spec)
    plan = prepare_plan(audio_case)
    assert plan == plan_audio(config, spec)
    assert [job["seed"] for job in plan["jobs"]] == [spec["seed"], spec["seed"] + 1]
    graph = json.loads(describe(spec)["workflow"])
    assert validate_workflow(graph, routes["/object_info"][1]).valid
    assert output_contract(spec) == {"sample_rate": 44100, "channels": 2, "samples": 176128}
    receipt = qualify(config, plan)
    assert receipt["profile"] == "stock-stable-audio-v1"
    assert len(receipt["files"]) == 6
    assert not any(method == "POST" for method, _ in requests)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("version", True),
        ("seconds", True),
        ("seconds", 0),
        ("seconds", 11),
        ("seconds", 1.5),
        ("seed", MAX_INTEGER),
        ("count", 5),
        ("prompt", "embedding:foo"),
        ("negative_prompt", "x" * 4097),
        ("profile", "unknown"),
    ],
)
def test_audio_spec_bounds_before_writes(audio_case, key, value):
    config, spec, _, _ = audio_case
    spec[key] = value
    with pytest.raises(ValueError):
        prepare_audio(config, spec)
    assert not (config.root / "workflows/audio").exists()


@pytest.mark.parametrize("key", ["checkpoint", "text_encoder"])
def test_pinned_audio_models_reject_changes(audio_case, key):
    config, spec, _, _ = audio_case
    plan = prepare_plan(audio_case)
    folder = "checkpoints" if key == "checkpoint" else "text_encoders"
    (config.comfyui_root / "models" / folder / spec[key]["loader_name"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="SHA-256"):
        qualify(config, plan)
    with pytest.raises(ValueError, match="SHA-256"):
        plan_audio(config, spec)


@pytest.mark.parametrize("change", ["missing_pin", "encoder_type", "format", "module", "duration"])
def test_audio_profile_refuses_unsafe_graph_changes(audio_case, change):
    config, spec, routes, _ = audio_case
    plan = prepare_plan(audio_case)
    store = CatalogStore(config.root)
    catalog = store.snapshot().to_dict()["catalog"]
    preset = next(p for p in catalog["presets"] if p["id"].startswith("audio-"))
    path = config.root / preset["workflow"]["path"]
    graph = json.loads(path.read_bytes())
    if change == "missing_pin":
        del graph["1"]["_meta"]
    elif change == "encoder_type":
        graph["2"]["inputs"]["type"] = "wan"
    elif change == "format":
        graph["9"]["inputs"]["format"] = "mp3"
        graph["9"]["inputs"]["format.quality"] = "128k"
    elif change == "duration":
        graph["6"]["inputs"]["seconds"] = 100
    else:
        routes["/object_info"][1]["SaveAudioAdvanced"]["python_module"] = "custom_nodes.audio"
    raw = json.dumps(graph).encode()
    path.write_bytes(raw)
    preset["workflow"]["sha256"] = sha256(raw)
    snapshot = store.import_catalog(catalog, expected_head=plan["catalog_head"])
    plan["request"]["catalog_head"] = snapshot.head
    with pytest.raises(ValueError):
        qualify(config, create_plan(config.root, plan["request"]))


@pytest.fixture
def encoded_audio(tmp_path):
    path = tmp_path / "sample.flac"
    subprocess.run(
        [
            video_tools()["ffmpeg"],
            "-v",
            "error",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100",
            "-af",
            "atrim=end_sample=176128",
            "-ac",
            "2",
            "-c:a",
            "flac",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    return path, {"sample_rate": 44100, "channels": 2, "samples": 176128}


def test_audio_full_decode_and_count(encoded_audio):
    path, contract = encoded_audio
    result = verify_audio(path, contract)
    assert result["ok"] and result["rms"] > 0 and result["samples"] == 176128
    contract["samples"] += 4096
    with pytest.raises(ValueError, match="sample count"):
        verify_audio(path, contract)


@pytest.mark.parametrize("damage", ["truncated", "silence", "mono", "rate"])
def test_audio_decode_rejects_damage_or_wrong_format(encoded_audio, damage):
    path, contract = encoded_audio
    if damage == "truncated":
        path.write_bytes(path.read_bytes()[:100])
    else:
        source = (
            "anullsrc=sample_rate=44100:channel_layout=stereo"
            if damage == "silence"
            else "sine=frequency=440:sample_rate=44100"
        )
        subprocess.run(
            [
                video_tools()["ffmpeg"],
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                source,
                "-af",
                "atrim=end_sample=176128",
                "-ac",
                "1" if damage == "mono" else "2",
                "-ar",
                "48000" if damage == "rate" else "44100",
                str(path),
            ],
            check=True,
            capture_output=True,
        )
    with pytest.raises(ValueError):
        verify_audio(path, contract)


def test_audio_collection_failure_resume_does_not_duplicate(audio_case, encoded_audio, monkeypatch):
    config, _, routes, requests = audio_case
    plan = prepare_plan(audio_case)
    path = save_plan(config.root, plan)
    receipt = save_qualification(config, qualify(config, plan))
    failed = True

    def validate(path, expected):
        if failed:
            raise ValueError("injected decode failure")
        return verify_audio(path, expected)

    def submit(payload):
        index = len(routes["_posted"]) - 1
        if index:
            previous = json.loads(job_path(config, plan["plan_id"], index - 1).read_bytes())
            assert previous["artifacts"][0]["audio_validation"]["ok"]
        prompt = f"audio-{index}"
        entry = {
            "prompt": [index, prompt, payload["prompt"], payload["extra_data"], ["9"]],
            "outputs": {
                "9": {"audio": [{"filename": prompt + ".flac", "subfolder": "", "type": "output"}]}
            },
            "status": {"completed": True, "status_str": "success", "messages": []},
        }
        routes[f"/history/{prompt}"] = (200, {prompt: entry})
        routes[f"/view?filename={prompt}.flac&subfolder=&type=output"] = (
            200,
            encoded_audio[0].read_bytes(),
        )
        return {"prompt_id": prompt}

    routes["POST /prompt"] = (200, submit)
    monkeypatch.setattr("itov.jobs.verify_audio", validate)
    assert run_batch(config, path, qualification=receipt, poll_interval=0.01)["status"] == "paused"
    assert len(routes["_posted"]) == 1
    first = json.loads(job_path(config, plan["plan_id"], 0).read_bytes())
    assert first["status"] == "collection_failed" and Path(first["artifacts"][0]["path"]).exists()
    failed = False
    assert run_batch(config, path, resume=True, poll_interval=0.01)["status"] == "succeeded"
    assert len(routes["_posted"]) == 2
    requests.clear()
    assert run_batch(config, path, resume=True)["status"] == "succeeded"
    assert not requests


@pytest.fixture
def mux_case(audio_case, encoded_video, encoded_audio):
    config, _, _, _ = audio_case
    spec = {"version": 1, "policy": "start-zero-trim-or-pad-v1"}
    for kind, (source, contract), class_type in (
        ("video", encoded_video, "SaveVideo"),
        ("audio", encoded_audio, "SaveAudioAdvanced"),
    ):
        request_id = str(uuid.uuid4())
        directory = config.root / "output/jobs" / request_id
        directory.mkdir(parents=True)
        output = directory / source.name
        shutil.copyfile(source, output)
        record = {
            "version": 1,
            "status": "succeeded",
            "request_id": request_id,
            "server": config.url,
            "prompt_id": "synthetic-prompt",
            "workflow": {"1": {"class_type": class_type, "_meta": {"itov_" + kind: contract}}},
            "artifacts": [
                {"node_id": "1", "path": str(output), "sha256": sha256(output.read_bytes())}
            ],
        }
        raw = json.dumps(record).encode()
        jobs = config.root / "state/jobs"
        jobs.mkdir(exist_ok=True)
        (jobs / (request_id + ".json")).write_bytes(raw)
        spec[kind] = {
            "request_id": request_id,
            "node_id": "1",
            "sha256": sha256(output.read_bytes()),
            "record_sha256": sha256(raw),
        }
    return config, spec


def test_real_mux_is_immutable_replayable_and_does_not_weaken_silent_contract(mux_case):
    config, spec = mux_case
    result = mux(config, spec)
    assert result["status"] == "created"
    receipt = result["receipt"]
    assert receipt["alignment"]["target_samples"] == 18000
    assert receipt["alignment"]["trim_samples_estimate"] > 0
    assert receipt["validation"]["contiguous_audio_timestamps"]
    with pytest.raises(ValueError, match="no audio"):
        verify_video(
            Path(result["directory"]) / "output.mp4", receipt["sources"]["video"]["contract"]
        )
    resumed = mux(config, spec)
    assert resumed["status"] == "verified_existing" and resumed["receipt"] == receipt
    output = Path(result["directory"]) / "output.mp4"
    output.write_bytes(b"preserve changed artifact")
    with pytest.raises(ValueError, match="differs"):
        mux(config, spec)
    assert output.read_bytes() == b"preserve changed artifact"


@pytest.mark.parametrize("damage", ["record", "source", "outside", "incomplete", "receipt"])
def test_mux_refuses_changed_or_unowned_inputs(mux_case, damage):
    config, spec = mux_case
    path = config.root / "state/jobs" / (spec["audio"]["request_id"] + ".json")
    record = json.loads(path.read_bytes())
    if damage == "record":
        path.write_bytes(path.read_bytes() + b" ")
    elif damage == "source":
        Path(record["artifacts"][0]["path"]).write_bytes(b"changed")
    elif damage == "receipt":
        result = mux(config, spec)
        receipt = Path(result["directory"]) / "receipt.json"
        value = json.loads(receipt.read_bytes())
        value["alignment"]["offset_samples"] = 10
        receipt.write_text(json.dumps(value))
    else:
        if damage == "outside":
            record["artifacts"][0]["path"] = str(config.root / "elsewhere.flac")
        else:
            record["status"] = "collection_failed"
        raw = json.dumps(record).encode()
        path.write_bytes(raw)
        spec["audio"]["record_sha256"] = sha256(raw)
    with pytest.raises(ValueError):
        mux(config, spec)


def test_failed_mux_retains_attempt_and_recovers_without_overwrite(mux_case, monkeypatch):
    import itov.audiovisual as av

    config, spec = mux_case
    original = av._verify
    monkeypatch.setattr(av, "_verify", lambda *args: (_ for _ in ()).throw(ValueError("injected")))
    with pytest.raises(ValueError, match="injected"):
        mux(config, spec)
    failed = list((config.root / "output/av").glob(".attempt-*/failure.json"))
    assert len(failed) == 1 and failed[0].with_name("output.mp4").exists()
    before = failed[0].read_bytes()
    monkeypatch.setattr(av, "_verify", original)
    assert mux(config, spec)["status"] == "created"
    assert failed[0].read_bytes() == before


def test_audio_cli(audio_case, encoded_audio, capsys):
    config, spec, _, _ = audio_case
    file = config.root / "audio.json"
    file.write_text(json.dumps(spec))
    assert main(["audio", "prepare", str(file), "--config", str(config.root / "itov.toml")]) == 0
    assert "Scope: prepared_audio_candidates" in capsys.readouterr().out
    assert main(["audio", "verify", str(file), str(encoded_audio[0])]) == 0
    assert "Samples: 176128" in capsys.readouterr().out
    assert main(["audio", "verify", str(file), str(encoded_audio[0]), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["samples"] == 176128


def test_seed_upper_bound_single_job():
    spec = load_spec(Path("examples/stable-audio.audio.json"))
    spec.update(seed=MAX_INTEGER, count=1)
    assert validate_spec(spec)["seed"] == MAX_INTEGER


def test_mux_pads_short_audio_with_silence(mux_case):
    import wave

    config, spec = mux_case
    record_path = config.root / "state/jobs" / (spec["video"]["request_id"] + ".json")
    record = json.loads(record_path.read_bytes())
    output = Path(record["artifacts"][0]["path"])
    subprocess.run(
        [
            video_tools()["ffmpeg"],
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=512x512:rate=8",
            "-frames:v",
            "49",
            "-c:v",
            "libx264",
            str(output),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    record["workflow"]["1"]["_meta"]["itov_video"].update(frames=49, fps=8)
    record["artifacts"][0]["sha256"] = sha256(output.read_bytes())
    raw = json.dumps(record).encode()
    record_path.write_bytes(raw)
    spec["video"].update(sha256=sha256(output.read_bytes()), record_sha256=sha256(raw))
    result = mux(config, spec)
    alignment = result["receipt"]["alignment"]
    assert alignment["target_samples"] == 294000 and alignment["pad_samples_estimate"] > 0
    with wave.open(str(Path(result["directory"]) / "aligned.wav"), "rb") as source:
        source.setpos(290000)
        assert source.readframes(4000) == bytes(16000)


def test_mux_verifier_rejects_shifted_audio(mux_case):
    from itov.audiovisual import _verify

    config, spec = mux_case
    result = mux(config, spec)
    receipt = result["receipt"]
    directory = Path(result["directory"])
    subprocess.run(
        [
            video_tools()["ffmpeg"],
            "-v",
            "error",
            "-y",
            "-i",
            receipt["sources"]["video"]["path"],
            "-itsoffset",
            "0.1",
            "-i",
            str(directory / "aligned.wav"),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            str(directory / "output.mp4"),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    with pytest.raises(ValueError, match="duration|start|timestamps"):
        _verify(directory, receipt["sources"]["video"], receipt["alignment"])


@pytest.mark.parametrize("request_id", [None, True, 1, [], {}, "../escape", "not-a-uuid"])
def test_av_refuses_invalid_ownership_ids(request_id):
    spec = {
        "version": 1,
        "policy": "start-zero-trim-or-pad-v1",
        "audio": {},
        "video": {
            "request_id": request_id,
            "node_id": "1",
            "sha256": "a" * 64,
            "record_sha256": "b" * 64,
        },
    }
    with pytest.raises(ValueError, match="request ID|UUID"):
        validate_av_spec(spec)
