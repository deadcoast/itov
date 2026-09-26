import copy
import json
import subprocess
import uuid
import wave
from pathlib import Path

import pytest
from test_audio import audio_case as audio_case
from test_audio import encoded_audio as encoded_audio
from test_audio import mux_case as mux_case
from test_audio import prepare_plan as audio_plan
from test_batch_execution import execution_case as execution_case
from test_video import encoded_video as encoded_video
from test_video import prepare_plan as video_plan
from test_video import video_case as video_case

from itov import audio, audiovisual, video
from itov.audio_media import verify_audio
from itov.catalog import canonical_bytes, sha256
from itov.cli import main
from itov.media import verify_video, video_tools
from itov.media_configuration import extended_graph
from itov.media_sources import bind_video
from itov.qualification import qualify


def extend_video(spec):
    spec.update(
        version=2,
        profile="wan22-ti2v-5b-v2",
        source=None,
        frames=121,
        sampler={"steps": 20, "cfg_milli": 5000, "shift_milli": 8000},
    )
    return spec


def extend_audio(spec):
    spec.update(
        version=2,
        profile="stable-audio-open-v2",
        seconds=47,
        sampler={"steps": 50, "cfg_milli": 4980},
    )
    return spec


@pytest.mark.parametrize("kind", ["video", "audio"])
def test_extended_graphs_qualify_and_change_plan_identity(request, kind):
    case = request.getfixturevalue(kind + "_case")
    extend = extend_video if kind == "video" else extend_audio
    plan = video_plan if kind == "video" else audio_plan
    legacy = plan(case)
    extend(case[1])
    current = plan(case)
    assert current["plan_id"] != legacy["plan_id"]
    assert qualify(case[0], current)["jobs"] == 2
    graph = json.loads(current["jobs"][0]["workflow_json"])
    assert any(
        n.get("_meta", {}).get("itov_video", {}).get("version") == 2
        or n.get("_meta", {}).get("itov_audio", {}).get("version") == 2
        for n in graph.values()
    )


@pytest.mark.parametrize(
    "kind,key,value",
    [
        ("video", "frames", 125),
        ("video", "frames", 120),
        ("video", "frames", True),
        ("audio", "seconds", 48),
        ("audio", "seconds", 0),
        ("audio", "seconds", 47.0),
        ("video", "sampler", {"steps": 31, "cfg_milli": 5000, "shift_milli": 8000}),
        ("video", "sampler", {"steps": 20, "cfg_milli": True, "shift_milli": 8000}),
        ("video", "sampler", {"steps": 20, "cfg_milli": 5000, "shift_milli": 0}),
        ("audio", "sampler", {"steps": 101, "cfg_milli": 4980}),
        ("audio", "sampler", {"steps": 50, "cfg_milli": 10001}),
        ("audio", "sampler", {"steps": 50, "cfg_milli": 4980, "unknown": 1}),
    ],
)
def test_extended_bounds(kind, key, value):
    module = video if kind == "video" else audio
    path = "examples/wan22.video.json" if kind == "video" else "examples/stable-audio.audio.json"
    spec = (extend_video if kind == "video" else extend_audio)(module.load_spec(Path(path)))
    spec[key] = value
    with pytest.raises(ValueError):
        module.validate_spec(spec)


@pytest.mark.parametrize(
    "node,field,value",
    [
        ("7", "length", 117),
        ("7", "width", 512),
        ("11", "fps", 25),
        ("9", "steps", 31),
        ("8", "shift", 8.0001),
        ("9", "latent_image", ["3", 0]),
        ("9", "sampler_name", "euler"),
    ],
)
def test_extended_video_contract_matches_generation(node, field, value):
    graph = json.loads(
        video.describe(extend_video(video.load_spec(Path("examples/wan22.video.json"))))["workflow"]
    )
    graph[node]["inputs"][field] = value
    with pytest.raises(ValueError):
        extended_graph(graph)


@pytest.mark.parametrize(
    "node,field,value", [("6", "seconds", 46), ("5", "seconds_total", 46), ("7", "cfg", 4.9801)]
)
def test_extended_audio_contract_matches_generation(node, field, value):
    graph = json.loads(
        audio.describe(extend_audio(audio.load_spec(Path("examples/stable-audio.audio.json"))))[
            "workflow"
        ]
    )
    graph[node]["inputs"][field] = value
    with pytest.raises(ValueError):
        extended_graph(graph)


def image_record(config):
    request = str(uuid.uuid4())
    output = config.root / "output/jobs" / request / "source.png"
    output.parent.mkdir(parents=True)
    subprocess.run(
        [
            video_tools()["ffmpeg"],
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=640x640",
            "-frames:v",
            "1",
            str(output),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    record = {
        "version": 1,
        "request_id": request,
        "server": config.url,
        "status": "succeeded",
        "prompt_id": "source-image",
        "workflow": {"2": {"class_type": "SaveImage"}},
        "artifacts": [{"node_id": "2", "path": str(output), "sha256": sha256(output.read_bytes())}],
    }
    path = config.root / "state/jobs" / (request + ".json")
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(canonical_bytes(record) + b"\n")
    return path, output


def test_bound_video_source_staging_cli_and_freshness(video_case, capsys):
    config, spec, _, routes, requests = video_case
    spec = extend_video(spec)
    record, output = image_record(config)
    original = copy.deepcopy(spec)
    result = bind_video(config, spec, record, "2", save=True)
    assert spec == original
    bound = result["specification"]
    assert video.load_spec(Path(result["saved_path"])) == bound
    assert (
        main(
            [
                "video",
                "bind-source",
                result["saved_path"],
                str(record),
                "--node",
                "2",
                "--config",
                str(config.root / "itov.toml"),
                "--save",
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["saved_path"] == result["saved_path"]
    case = (config, bound, None, routes, requests)
    # Server's LoadImage choices are dynamic; qualify the staged immutable name.
    routes["/object_info"][1]["LoadImage"]["input"]["required"]["image"][0].append(
        bound["input_image"]["name"]
    )
    plan = video_plan(case)
    receipt = qualify(config, plan)
    assert record.read_bytes() and str(record) in {f["path"] for f in receipt["files"]}
    assert (
        config.root / "input" / bound["input_image"]["name"]
    ).read_bytes() == output.read_bytes()
    record.write_bytes(record.read_bytes() + b" ")
    with pytest.raises(ValueError, match="record differs"):
        qualify(config, plan)
    with pytest.raises(ValueError, match="record differs"):
        video.plan_video(config, bound)


@pytest.mark.parametrize("damage", ["artifact", "incomplete", "node", "outside", "invalid_png"])
def test_source_lineage_rejects_damage(video_case, damage):
    config, spec, _, _, _ = video_case
    record, output = image_record(config)
    value = json.loads(record.read_bytes())
    if damage == "artifact":
        output.write_bytes(b"changed")
    elif damage == "invalid_png":
        output.write_bytes(b"not a png")
        value["artifacts"][0]["sha256"] = sha256(output.read_bytes())
    elif damage == "incomplete":
        value["status"] = "collecting"
    elif damage == "node":
        value["workflow"]["2"]["class_type"] = "Other"
    else:
        value["artifacts"][0]["path"] = str(config.root / "elsewhere.png")
    record.write_bytes(canonical_bytes(value))
    with pytest.raises(ValueError):
        bind_video(config, extend_video(spec), record, "2", save=True)
    assert not (config.root / "state/media/specifications").exists()


def test_full_extended_audio_and_video_decode(tmp_path):
    tool = video_tools()["ffmpeg"]
    clip, sound = tmp_path / "extended.mp4", tmp_path / "extended.flac"
    subprocess.run(
        [
            tool,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=512x512:rate=24",
            "-frames:v",
            "121",
            "-c:v",
            "libx264",
            str(clip),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    samples = round(47 * 44100 / 4096) * 4096
    subprocess.run(
        [
            tool,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100",
            "-af",
            f"atrim=end_sample={samples}",
            "-ac",
            "2",
            str(sound),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    vc = {"version": 2, "width": 512, "height": 512, "frames": 121, "fps": 24}
    ac = {"version": 2, "sample_rate": 44100, "channels": 2, "samples": samples}
    assert verify_video(clip, vc)["ok"]
    assert verify_audio(sound, ac)["samples"] == samples
    for verify, path, contract in ((verify_video, clip, vc), (verify_audio, sound, ac)):
        contract.pop("version")
        with pytest.raises(ValueError):
            verify(path, contract)


def test_av_saved_offset_spec_cli_and_readonly_missing_replay(mux_case, capsys):
    config, old = mux_case
    paths = {
        k: config.root / "state/jobs" / (v["request_id"] + ".json")
        for k, v in old.items()
        if k in {"video", "audio"}
    }
    result = audiovisual.build_spec(
        config,
        paths["video"],
        paths["audio"],
        video_node="1",
        audio_node="1",
        audio_offset_ms=500,
        save=True,
    )
    spec = audiovisual.load_spec(Path(result["saved_path"]))
    with pytest.raises(ValueError, match="missing"):
        audiovisual.replay(config, spec)
    assert not (config.root / "output/av").exists()
    created = audiovisual.mux(config, spec)
    assert created["receipt"]["alignment"]["offset_samples"] == 24000
    assert (
        main(
            [
                "av",
                "replay",
                result["saved_path"],
                "--config",
                str(config.root / "itov.toml"),
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "verified_existing"
    # The selected source segment matches an independently decoded FFmpeg sample slice.
    expected = Path(created["directory"]) / "expected.wav"
    subprocess.run(
        [
            video_tools()["ffmpeg"],
            "-v",
            "error",
            "-i",
            created["receipt"]["sources"]["audio"]["path"],
            "-af",
            "aresample=48000,atrim=start_sample=24000:end_sample=42000,asetpts=N/SR/TB",
            "-c:a",
            "pcm_s16le",
            str(expected),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    with (
        wave.open(str(expected)) as a,
        wave.open(str(Path(created["directory"]) / "aligned.wav")) as b,
    ):
        assert a.readframes(18000) == b.readframes(18000)


def test_source_record_change_during_mux_keeps_failed_attempt(mux_case, monkeypatch):
    config, spec = mux_case
    original = audiovisual._verify
    path = config.root / "state/jobs" / (spec["audio"]["request_id"] + ".json")

    def changed(*args):
        result = original(*args)
        path.write_bytes(path.read_bytes() + b" ")
        return result

    monkeypatch.setattr(audiovisual, "_verify", changed)
    with pytest.raises(ValueError, match="record changed"):
        audiovisual.mux(config, spec)
    assert len(list((config.root / "output/av").glob(".attempt-*/failure.json"))) == 1
    assert not (config.root / "output/av" / sha256(canonical_bytes(spec))).exists()


def test_interrupt_mux_preserves_attempt_and_recovers(mux_case, monkeypatch):
    config, spec = mux_case
    original = audiovisual._verify
    monkeypatch.setattr(
        audiovisual, "_verify", lambda *a: (_ for _ in ()).throw(KeyboardInterrupt())
    )
    with pytest.raises(KeyboardInterrupt):
        audiovisual.mux(config, spec)
    attempts = list((config.root / "output/av").glob(".attempt-*/output.mp4"))
    assert len(attempts) == 1
    before = attempts[0].read_bytes()
    monkeypatch.setattr(audiovisual, "_verify", original)
    assert audiovisual.mux(config, spec)["status"] == "created"
    assert attempts[0].read_bytes() == before
