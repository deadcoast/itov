"""Bounded local validation of the silent H.264 baseline's collected artifacts."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

from itov.catalog import integer, object_fields, require
from itov.comfyui import parse_json


def video_contract(value: dict) -> dict:
    object_fields(value, {"width", "height", "frames", "fps"}, "video contract")
    for key in value:
        integer(value[key], key, minimum=1)
    require(
        512 <= value["width"] <= 832
        and 512 <= value["height"] <= 832
        and value["width"] % 32 == value["height"] % 32 == 0
        and value["width"] * value["height"] <= 832 * 640,
        "Video dimensions must be multiples of 32 in 512..832, at most 832x640 pixels",
    )
    require(
        9 <= value["frames"] <= 49 and value["frames"] % 4 == 1,
        "Video frames must be 4n+1 in 9..49",
    )
    require(8 <= value["fps"] <= 30, "Video fps must be within 8..30")
    return dict(value)


def video_tools() -> dict:
    paths = {name: shutil.which(name) for name in ("ffmpeg", "ffprobe")}
    require(all(paths.values()), "Video validation requires ffmpeg and ffprobe on PATH")
    return paths


def _run(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=120, encoding="utf-8"
        )
    except subprocess.TimeoutExpired as error:
        raise ValueError("Video validation exceeded 120 seconds") from error
    require(result.returncode == 0, f"Video validation failed: {result.stderr[-2000:]}")
    return result.stdout


def verify_video(path: Path, expected: dict) -> dict:
    return _verify_video(path, expected, with_audio=False)


def _verify_video(path: Path, expected: dict, *, with_audio: bool) -> dict:
    expected = video_contract(expected)
    path = path.absolute()
    require(path.is_file() and not path.is_symlink(), "Video must be a local regular file")
    require(0 < path.stat().st_size <= 512 * 1024**2, "Video size must be within 1..512 MiB")
    with path.open("rb") as source:
        before = hashlib.file_digest(source, "sha256").hexdigest()
    tools = video_tools()
    probe = parse_json(
        _run(
            [
                tools["ffprobe"],
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-count_frames",
                "-show_entries",
                "stream=codec_type,codec_name,width,height,avg_frame_rate,nb_read_frames,duration:format=duration,format_name",
                "-of",
                "json",
                str(path),
            ]
        )
    )
    require(
        isinstance(probe, dict) and isinstance(probe.get("streams"), list), "Invalid video probe"
    )
    if with_audio:
        require(
            sorted(item.get("codec_type", "") for item in probe["streams"]) == ["audio", "video"],
            "Mux requires exactly one video and one audio stream",
        )
    else:
        require(len(probe["streams"]) == 1, "Baseline requires one video stream and no audio")
    stream = (
        next(item for item in probe["streams"] if item.get("codec_type") == "video")
        if with_audio
        else probe["streams"][0]
    )
    require(
        stream.get("codec_type") == "video" and stream.get("codec_name") == "h264",
        "Expected H.264 video",
    )
    require(
        "mp4" in probe.get("format", {}).get("format_name", "").split(","), "Expected MP4 container"
    )
    require(
        (stream.get("width"), stream.get("height")) == (expected["width"], expected["height"]),
        "Video dimensions differ from the plan",
    )
    try:
        fps = Fraction(stream["avg_frame_rate"])
        frames = int(stream["nb_read_frames"])
        duration = Fraction(probe["format"]["duration"])
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as error:
        raise ValueError("Video is missing valid timing/frame metadata") from error
    require(
        fps == expected["fps"] and frames == expected["frames"],
        "Video frame rate/count differs from the plan",
    )
    target_duration = Fraction(expected["frames"], expected["fps"])
    require(
        abs(duration - target_duration) <= Fraction(1, 1000), "Video duration differs from the plan"
    )
    decoded = _run(
        [
            tools["ffmpeg"],
            "-v",
            "error",
            "-xerror",
            "-nostdin",
            "-protocol_whitelist",
            "file,pipe",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-an",
            "-sn",
            "-dn",
            "-frames:v",
            str(frames + 1),
            "-pix_fmt",
            "rgb24",
            "-fps_mode",
            "passthrough",
            "-f",
            "framemd5",
            "-",
        ]
    )
    lines = [line.split(",") for line in decoded.splitlines() if line and not line.startswith("#")]
    require(
        len(lines) == frames and all(len(row) == 6 for row in lines),
        "Full video decode frame count differs",
    )
    hashes = [row[-1].strip() for row in lines]
    try:
        time_base = Fraction(
            next(
                line.split(":", 1)[1].strip()
                for line in decoded.splitlines()
                if line.startswith("#tb 0:")
            )
        )
        timing_matches = all(
            int(row[2]) * time_base == Fraction(index, expected["fps"])
            and int(row[3]) * time_base == Fraction(1, expected["fps"])
            for index, row in enumerate(lines)
        )
    except (StopIteration, ValueError, ZeroDivisionError) as error:
        raise ValueError("Missing valid decoded frame timestamps") from error
    require(timing_matches, "Decoded frame timestamps differ from the planned constant frame rate")
    require(len(set(hashes)) > 1, "Video has no observable decoded frame variation")
    with path.open("rb") as source:
        require(
            hashlib.file_digest(source, "sha256").hexdigest() == before,
            "Video changed during validation",
        )
    return {
        "ok": True,
        "scope": "mux_h264_full_decode_and_timing"
        if with_audio
        else "silent_h264_full_decode_and_timing",
        "sha256": before,
        **expected,
        "duration_seconds": float(duration),
        "decoded_frame_md5": hashes,
        "distinct_frames": len(set(hashes)),
        "constant_frame_timestamps": True,
        "tools": tools,
        "limits": "Frame variation does not establish quality, fidelity, or human acceptance.",
    }
