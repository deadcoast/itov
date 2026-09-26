"""Explicit completed-job bindings for media inputs and downstream composition."""

import struct
import uuid
from pathlib import Path

from itov.catalog import digest, object_fields, require, sha256, text
from itov.comfyui import parse_json
from itov.evidence_reads import read_document
from itov.qualification import _file, safe_path
from itov.training_data import publish


def binding(value):
    object_fields(value, {"request_id", "node_id", "sha256", "record_sha256"}, "source binding")
    require(
        isinstance(value["request_id"], str)
        and str(uuid.UUID(value["request_id"])) == value["request_id"],
        "Invalid source request",
    )
    text(value["node_id"], "output node")
    digest(value["sha256"], "artifact hash")
    digest(value["record_sha256"], "source record hash")
    return value


def completed(config, value, kind):
    binding(value)
    path = safe_path(config.root, f"state/jobs/{value['request_id']}.json")
    raw = read_document(path)
    require(sha256(raw) == value["record_sha256"], "Pinned source job record differs")
    record = parse_json(raw)
    require(
        isinstance(record, dict)
        and type(record.get("version")) is int
        and record["version"] == 1
        and record.get("status") == "succeeded"
        and record.get("request_id") == value["request_id"]
        and record.get("server") == config.url
        and isinstance(record.get("prompt_id"), str),
        "Source must be a completed job in this workspace/server",
    )
    graph = record.get("workflow")
    require(isinstance(graph, dict), "Invalid source workflow")
    node = graph.get(value["node_id"])
    require(
        isinstance(node, dict) and node.get("class_type") == kind, "Source output node type differs"
    )
    rows = record.get("artifacts")
    require(
        isinstance(rows, list) and all(isinstance(r, dict) for r in rows),
        "Invalid source artifacts",
    )
    rows = [r for r in rows if r.get("node_id") == value["node_id"]]
    require(
        len(rows) == 1
        and rows[0].get("sha256") == value["sha256"]
        and isinstance(rows[0].get("path"), str),
        "Source requires one exact output artifact",
    )
    output = Path(rows[0]["path"]).absolute()
    require(
        output.parent == safe_path(config.root, f"output/jobs/{value['request_id']}"),
        "Source artifact belongs to another job",
    )
    output = safe_path(config.root, output.relative_to(config.root).as_posix())
    require(_file(output)["sha256"] == value["sha256"], "Source artifact hash differs")
    return output, record


def image_source(config, value, expected):
    output, _ = completed(config, value, "SaveImage")
    require(value["sha256"] == expected, "Source image and input pins differ")
    require(output.stat().st_size <= 16 * 1024**2, "Source PNG exceeds 16 MiB")
    raw = output.read_bytes()
    require(sha256(raw) == expected and len(raw) >= 24, "Source image changed or is invalid")
    require(raw[:16] == b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR", "Source image must be a PNG")
    from itov.image_media import decode_image

    width, height = struct.unpack(">II", raw[16:24])
    decode_image(output, {"width": width, "height": height})
    require(
        sha256(read_document(safe_path(config.root, f"state/jobs/{value['request_id']}.json")))
        == value["record_sha256"],
        "Source record changed during decode",
    )
    return output


def from_record(config, path, node, kind):
    path = Path(path).absolute()
    require(
        path.parent == safe_path(config.root, "state/jobs"), "Select this workspace's job record"
    )
    path = safe_path(config.root, path.relative_to(config.root).as_posix())
    raw = read_document(path)
    record = parse_json(raw)
    require(
        isinstance(record, dict) and isinstance(record.get("artifacts"), list),
        "Invalid source record",
    )
    rows = [r for r in record["artifacts"] if isinstance(r, dict) and r.get("node_id") == node]
    require(len(rows) == 1, "Select exactly one completed output node")
    value = {
        "request_id": path.stem,
        "node_id": node,
        "record_sha256": sha256(raw),
        "sha256": rows[0].get("sha256"),
    }
    completed(config, value, kind)
    return value


def bind_video(config, specification, record, node, *, save=False):
    from itov.video import validate_spec

    spec = validate_spec(specification)
    require(spec["version"] == 2, "Source binding requires a version-two video specification")
    value = from_record(config, record, node, "SaveImage")
    spec["source"] = value
    spec["input_image"] = {
        "name": "itov-source-" + value["sha256"] + ".png",
        "sha256": value["sha256"],
    }
    image_source(config, value, value["sha256"])
    spec = validate_spec(spec)
    result = {"ok": True, "scope": "bound_video_source", "specification": spec}
    if save:
        from itov.catalog import canonical_bytes

        path = safe_path(
            config.root, f"state/media/specifications/{sha256(canonical_bytes(spec))}.video.json"
        )
        publish(path, spec)
        result["saved_path"] = str(path)
    return result
