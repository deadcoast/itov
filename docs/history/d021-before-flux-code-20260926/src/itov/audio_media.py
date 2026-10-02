"""Full-decode checks for bounded, lossless stereo audio artifacts."""

import array
import hashlib
import math
import subprocess
import sys
from pathlib import Path

from itov.catalog import integer, object_fields, require
from itov.comfyui import parse_json
from itov.media import _run, video_tools


def audio_contract(value: dict) -> dict:
    extended = isinstance(value, dict) and "version" in value
    object_fields(
        value,
        {"sample_rate", "channels", "samples"} | ({"version"} if extended else set()),
        "audio contract",
    )
    require(
        not extended or type(value["version"]) is int and value["version"] == 2,
        "Unsupported audio contract version",
    )
    for key in value:
        integer(value[key], key, minimum=1)
    require(
        value["sample_rate"] == 44100 and value["channels"] == 2,
        "Audio baseline requires 44100 Hz stereo",
    )
    require(
        4096 <= value["samples"] <= (round(47 * 44100 / 4096) * 4096 if extended else 44100 * 11)
        and value["samples"] % 4096 == 0,
        "Audio samples must be bounded multiples of 4096",
    )
    return dict(value)


def probe_audio(path: Path) -> dict:
    return parse_json(
        _run(
            [
                video_tools()["ffprobe"],
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-show_entries",
                "stream=codec_type,codec_name,sample_rate,channels,duration,start_time,duration_ts,time_base:format=format_name,duration",
                "-of",
                "json",
                str(path),
            ]
        )
    )


def decode_audio(path: Path, *, max_samples: int = 44100 * 11) -> dict:
    # Limit decoded bytes even if container metadata lies. One extra sample detects overflow.
    command = [
        video_tools()["ffmpeg"],
        "-v",
        "error",
        "-xerror",
        "-nostdin",
        "-protocol_whitelist",
        "file,pipe",
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-vn",
        "-sn",
        "-dn",
        "-af",
        f"atrim=end_sample={max_samples + 1}",
        "-ac",
        "2",
        "-c:a",
        "pcm_f32le",
        "-f",
        "f32le",
        "-",
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=120)
    except subprocess.TimeoutExpired as error:
        raise ValueError("Audio decoding exceeded 120 seconds") from error
    require(
        result.returncode == 0,
        "Audio decode failed: " + result.stderr.decode(errors="replace")[-2000:],
    )
    require(
        len(result.stdout) % 8 == 0 and 0 < len(result.stdout) <= max_samples * 8,
        "Decoded audio exceeds the sample bound or is empty",
    )
    samples = array.array("f", result.stdout)
    if sys.byteorder != "little":
        samples.byteswap()
    require(all(math.isfinite(value) for value in samples), "Audio contains nonfinite samples")
    peak = max(abs(value) for value in samples)
    rms = math.sqrt(sum(value * value for value in samples) / len(samples))
    require(peak > 0 and rms > 0, "Audio is entirely silent")
    return {
        "samples": len(samples) // 2,
        "peak": peak,
        "rms": rms,
        "decoded_f32le_sha256": hashlib.sha256(result.stdout).hexdigest(),
    }


def verify_audio(path: Path, expected: dict) -> dict:
    expected = audio_contract(expected)
    path = path.absolute()
    require(
        path.is_file() and path.resolve() == path and not path.is_symlink(),
        "Audio must be a local regular file without redirection",
    )
    require(0 < path.stat().st_size <= 16 * 1024**2, "Audio exceeds 16 MiB or is empty")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    probe = probe_audio(path)
    require(len(probe.get("streams", [])) == 1, "Audio must contain exactly one stream")
    stream = probe["streams"][0]
    require(
        probe.get("format", {}).get("format_name") == "flac"
        and stream.get("codec_name") == "flac"
        and stream.get("codec_type") == "audio",
        "Audio baseline requires lossless FLAC",
    )
    require(
        stream.get("sample_rate") == str(expected["sample_rate"])
        and stream.get("channels") == expected["channels"],
        "Audio sample rate/channels differ",
    )
    decoded = decode_audio(path, max_samples=expected["samples"])
    require(decoded["samples"] == expected["samples"], "Decoded audio sample count differs")
    require(
        hashlib.sha256(path.read_bytes()).hexdigest() == before, "Audio changed during validation"
    )
    return {
        "ok": True,
        "scope": "lossless_audio_full_decode",
        "sha256": before,
        **expected,
        **decoded,
        "duration_seconds": expected["samples"] / expected["sample_rate"],
        "limits": "Finite nonzero samples do not establish quality or prompt compliance.",
    }
