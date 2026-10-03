"""Owned local A/V composition with immutable publication and offline replay."""

import os
import tempfile
import uuid
import wave
from fractions import Fraction
from pathlib import Path

from itov.audio_media import decode_audio, probe_audio, verify_audio
from itov.catalog import (
    canonical_bytes,
    digest,
    object_fields,
    read_document,
    require,
    sha256,
    text,
)
from itov.catalog_store import _atomic_write
from itov.comfyui import parse_json_object
from itov.config import Config
from itov.locking import file_lock
from itov.media import _run, _verify_video, verify_video, video_tools
from itov.qualification import _file, json_text, safe_path


def _receipt_bytes(value: dict) -> bytes:
    # Measurement receipts contain finite floats; catalog/spec JSON remains integer-only.
    return json_text(value).encode("utf-8")


def load_spec(path: Path) -> dict:
    return validate_spec(
        parse_json_object(
            read_document(path), message="audiovisual specification: expected an object"
        )
    )


def validate_spec(value: dict) -> dict:
    extended = isinstance(value, dict) and value.get("version") == 2
    object_fields(
        value,
        {"version", "video", "audio", "policy"} | ({"audio_offset_ms"} if extended else set()),
        "audiovisual specification",
    )
    require(
        type(value["version"]) is int and value["version"] in (1, 2), "Invalid audiovisual version"
    )
    require(
        value["policy"]
        == ("source-offset-trim-or-pad-v2" if extended else "start-zero-trim-or-pad-v1"),
        "Unsupported audio alignment policy",
    )
    if extended:
        require(
            type(value["audio_offset_ms"]) is int and 0 <= value["audio_offset_ms"] < 47000,
            "Audio source offset must be 0..46999 milliseconds",
        )
    for kind in ("video", "audio"):
        binding = value[kind]
        object_fields(binding, {"request_id", "node_id", "sha256", "record_sha256"}, kind)
        require(isinstance(binding["request_id"], str), "Invalid request ID")
        require(
            str(uuid.UUID(binding["request_id"])) == binding["request_id"], "Invalid request ID"
        )
        text(binding["node_id"], "node_id")
        digest(binding["sha256"], "artifact hash")
        digest(binding["record_sha256"], "job record hash")
    return parse_json_object(canonical_bytes(value))


def _source(config: Config, binding: dict, kind: str) -> dict:
    path = safe_path(config.root, f"state/jobs/{binding['request_id']}.json")
    raw = read_document(path)
    require(sha256(raw) == binding["record_sha256"], "Pinned job record differs")
    record = parse_json_object(raw, message="Job record must be an object")
    require(
        type(record.get("version")) is int
        and record.get("version") == 1
        and record.get("status") == "succeeded"
        and record.get("request_id") == binding["request_id"]
        and record.get("server") == config.url
        and isinstance(record.get("prompt_id"), str),
        "Mux requires a completed owned job",
    )
    require(isinstance(record.get("workflow"), dict), "Job workflow must be an object")
    node = record["workflow"].get(binding["node_id"], {})
    require(
        isinstance(node, dict) and isinstance(node.get("_meta"), dict),
        "Media output requires contract metadata",
    )
    require(
        node.get("class_type") == ("SaveVideo" if kind == "video" else "SaveAudioAdvanced"),
        "Bound node is not the expected media output",
    )
    contract = node.get("_meta", {}).get("itov_" + kind)
    require(
        isinstance(record.get("artifacts"), list)
        and all(isinstance(item, dict) for item in record["artifacts"]),
        "Invalid job artifacts",
    )
    artifacts = [
        item for item in record.get("artifacts", []) if item.get("node_id") == binding["node_id"]
    ]
    require(len(artifacts) == 1, "Mux requires exactly one artifact for each bound output")
    artifact = artifacts[0]
    require(isinstance(artifact.get("path"), str), "Artifact requires a local path")
    output = Path(artifact["path"]).absolute()
    directory = safe_path(config.root, f"output/jobs/{binding['request_id']}")
    require(
        output.parent == directory and output.resolve() == output and not output.is_symlink(),
        "Artifact path does not belong to the bound job",
    )
    require(
        artifact["sha256"] == binding["sha256"] and _file(output)["sha256"] == binding["sha256"],
        "Pinned source artifact differs",
    )
    validation = (verify_video if kind == "video" else verify_audio)(output, contract)
    return {
        **binding,
        "path": str(output),
        "prompt_id": record["prompt_id"],
        "contract": contract,
        "validation": validation,
    }


def _alignment(video: dict, audio: dict, offset_ms=0) -> dict:
    contract = video["contract"]
    target = round(Fraction(contract["frames"] * 48000, contract["fps"]))
    resampled = round(Fraction(audio["contract"]["samples"] * 48000, 44100))
    offset = offset_ms * 48
    require(offset < resampled, "Audio source offset leaves no samples")
    return {
        "sample_rate": 48000,
        "channels": 2,
        "target_samples": target,
        "offset_samples": offset,
        "resampled_source_samples_estimate": resampled,
        "trim_samples_estimate": max(0, resampled - offset - target),
        "pad_samples_estimate": max(0, target - (resampled - offset)),
        "normalization": "none",
        "sample_format": "s16le",
        "codec": "aac",
        "bitrate": "192k",
    }


def _verify(directory: Path, video: dict, alignment: dict) -> dict:
    wav = directory / "aligned.wav"
    with wave.open(str(wav), "rb") as source:
        require(
            (
                source.getframerate(),
                source.getnchannels(),
                source.getsampwidth(),
                source.getnframes(),
            )
            == (48000, 2, 2, alignment["target_samples"]),
            "Aligned WAV contract differs",
        )
    aligned = decode_audio(wav, max_samples=alignment["target_samples"])
    require(aligned["samples"] == alignment["target_samples"], "Aligned WAV decode differs")
    output = directory / "output.mp4"
    visual = _verify_video(output, video["contract"], with_audio=True)
    require(
        visual["decoded_frame_md5"] == video["validation"]["decoded_frame_md5"],
        "Mux changed decoded video frames",
    )
    probe = probe_audio(output)
    audio = next(item for item in probe["streams"] if item["codec_type"] == "audio")
    require(
        audio.get("codec_name") == "aac"
        and audio.get("sample_rate") == "48000"
        and audio.get("channels") == 2,
        "Mux audio format differs",
    )
    target = Fraction(alignment["target_samples"], 48000)
    for stream in probe["streams"]:
        require(
            abs(Fraction(stream.get("start_time", "999"))) <= Fraction(1, 48000),
            "Mux stream does not start at zero",
        )
        require(
            abs(Fraction(stream.get("duration", "999")) - target) <= Fraction(1, 1000),
            "Mux stream duration differs by more than 1 ms",
        )
    # AAC encodes 1024-sample packets. MP4 edit lists specify the audible end;
    # full PCM decode may include less than one terminal packet of padding.
    decoded = decode_audio(output, max_samples=alignment["target_samples"] + 1023)
    require(
        alignment["target_samples"] <= decoded["samples"] < alignment["target_samples"] + 1024,
        "Decoded AAC duration exceeds the terminal packet allowance",
    )
    frames = parse_json_object(
        _run(
            [
                video_tools()["ffprobe"],
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-select_streams",
                "a:0",
                "-show_frames",
                "-show_entries",
                "frame=best_effort_timestamp,nb_samples:stream=time_base",
                "-of",
                "json",
                str(output),
            ]
        )
    )
    time_base = Fraction(frames["streams"][0]["time_base"])
    cursor = 0
    for frame in frames["frames"]:
        require(
            int(frame["best_effort_timestamp"]) * time_base == Fraction(cursor, 48000),
            "Decoded audio timestamps have a gap, overlap, or offset",
        )
        cursor += int(frame["nb_samples"])
    require(cursor == decoded["samples"], "Decoded audio timing/sample count differs")
    return {
        "ok": True,
        "scope": "decoded_av_container_timing",
        "video": visual,
        "aligned_audio": aligned,
        "aac_audio": decoded,
        "aac_terminal_padding_samples": decoded["samples"] - alignment["target_samples"],
        "contiguous_audio_timestamps": True,
        "stream_timing": probe["streams"],
        "limits": (
            "Container alignment does not establish semantic synchronization, "
            "lip sync, loudness targets, or human acceptance."
        ),
    }


def build_spec(
    config, video_record, audio_record, *, video_node, audio_node, audio_offset_ms=0, save=False
):
    from itov.media_sources import from_record
    from itov.training_data import publish

    spec = validate_spec(
        {
            "version": 2,
            "policy": "source-offset-trim-or-pad-v2",
            "audio_offset_ms": audio_offset_ms,
            "video": from_record(config, video_record, video_node, "SaveVideo"),
            "audio": from_record(config, audio_record, audio_node, "SaveAudioAdvanced"),
        }
    )
    video, audio = (_source(config, spec[kind], kind) for kind in ("video", "audio"))
    _alignment(video, audio, audio_offset_ms)
    result = {"ok": True, "scope": "bound_av_sources", "specification": spec}
    if save:
        path = safe_path(
            config.root, f"state/av/specifications/{sha256(canonical_bytes(spec))}.json"
        )
        publish(path, spec)
        result["saved_path"] = str(path)
    return result


def _fresh_sources(config, sources):
    for source in sources:
        require(
            _file(Path(source["path"]))["sha256"] == source["sha256"], "Source changed during mux"
        )
        record = safe_path(config.root, f"state/jobs/{source['request_id']}.json")
        require(
            sha256(read_document(record)) == source["record_sha256"],
            "Source job record changed during mux",
        )


def replay(config, spec):
    return mux(config, spec, require_existing=True)


def mux(config: Config, spec: dict, *, require_existing=False) -> dict:
    spec = validate_spec(spec)
    operation_id = sha256(canonical_bytes(spec))
    root = safe_path(config.root, "output/av")
    destination = safe_path(root, operation_id)
    require(
        not require_existing or destination.is_dir(),
        "Published A/V output is missing; replay cannot create it",
    )
    root.mkdir(parents=True, exist_ok=True)
    locks = safe_path(config.root, "state/av")
    locks.mkdir(parents=True, exist_ok=True)
    with file_lock(locks / (operation_id + ".lock")):
        video, audio = (_source(config, spec[kind], kind) for kind in ("video", "audio"))
        alignment = _alignment(video, audio, spec.get("audio_offset_ms", 0))
        destination = safe_path(root, operation_id)
        if destination.exists():
            receipt = parse_json_object(
                read_document(safe_path(destination, "receipt.json")),
                message="Mux receipt must be an object",
            )
            require(
                receipt.get("specification") == spec
                and receipt.get("operation_id") == operation_id,
                "Existing mux receipt differs; preserve and inspect",
            )
            body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
            require(
                sha256(_receipt_bytes(body)) == receipt.get("receipt_sha256"),
                "Mux receipt hash differs",
            )
            for name in ("aligned.wav", "output.mp4"):
                require(
                    _file(safe_path(destination, name))["sha256"]
                    == receipt["outputs"][name]["sha256"],
                    "Published mux artifact differs; preserve and inspect",
                )
            _verify(destination, video, alignment)
            require(
                receipt.get("alignment") == alignment
                and receipt.get("sources") == {"video": video, "audio": audio},
                "Published A/V source or alignment contract differs",
            )
            _fresh_sources(config, (video, audio))
            return {
                "ok": True,
                "status": "verified_existing",
                "directory": str(destination),
                "receipt": receipt,
            }
        attempt = Path(tempfile.mkdtemp(prefix=f".attempt-{operation_id[:12]}-", dir=root))
        try:
            tools = video_tools()
            common = [tools["ffmpeg"], "-v", "error", "-xerror", "-nostdin", "-n"]
            samples = alignment["target_samples"]
            offset_filter = (
                f"atrim=start_sample={alignment['offset_samples']}," if spec["version"] == 2 else ""
            )
            _run(
                common
                + [
                    "-protocol_whitelist",
                    "file,pipe",
                    "-i",
                    audio["path"],
                    "-map",
                    "0:a:0",
                    "-af",
                    f"aresample=48000,{offset_filter}apad,atrim=end_sample={samples},asetpts=N/SR/TB",
                    "-ac",
                    "2",
                    "-c:a",
                    "pcm_s16le",
                    "-map_metadata",
                    "-1",
                    str(attempt / "aligned.wav"),
                ]
            )
            _run(
                common
                + [
                    "-protocol_whitelist",
                    "file,pipe",
                    "-i",
                    video["path"],
                    "-protocol_whitelist",
                    "file,pipe",
                    "-i",
                    str(attempt / "aligned.wav"),
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0",
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-map_metadata",
                    "-1",
                    "-movflags",
                    "+faststart",
                    str(attempt / "output.mp4"),
                ]
            )
            validation = _verify(attempt, video, alignment)
            _fresh_sources(config, (video, audio))
            receipt = {
                "version": 1,
                "operation_id": operation_id,
                "specification": spec,
                "sources": {"video": video, "audio": audio},
                "alignment": alignment,
                "validation": validation,
                "tools": {
                    name: {
                        "path": path,
                        "sha256": _file(Path(path))["sha256"],
                        "version": _run([path, "-version"]).splitlines()[0],
                    }
                    for name, path in tools.items()
                },
                "outputs": {
                    name: {
                        key: value for key, value in _file(attempt / name).items() if key != "path"
                    }
                    for name in ("aligned.wav", "output.mp4")
                },
            }
            receipt["receipt_sha256"] = sha256(_receipt_bytes(receipt))
            _atomic_write(attempt / "receipt.json", _receipt_bytes(receipt) + b"\n", exclusive=True)
            _fresh_sources(config, (video, audio))
            os.rename(attempt, destination)
        except Exception as error:
            if attempt.exists():
                _atomic_write(
                    attempt / "failure.json",
                    canonical_bytes({"specification": spec, "error": str(error)}) + b"\n",
                    exclusive=True,
                )
            raise
        return {"ok": True, "status": "created", "directory": str(destination), "receipt": receipt}
