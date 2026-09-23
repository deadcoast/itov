"""Durable observations of one ComfyUI job, with explicit uncertain outcomes."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from itov.audio_media import audio_contract, verify_audio
from itov.comfyui import ComfyUIClient, ComfyUIError, parse_json, submission_matches
from itov.config import Config, validate_timeout
from itov.image_media import image_contract, verify_image
from itov.locking import file_lock
from itov.media import verify_video, video_contract
from itov.workflow import validate_workflow


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _contained_directory(config: Config, relative: str) -> Path:
    directory = config.root / relative
    if not directory.resolve().is_relative_to(config.root):
        raise ValueError(f"Job directory escapes the workspace: {directory}")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _save(path: Path, record: dict) -> dict:
    record["updated_at"] = _now()
    record["record_path"] = str(path)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=".job-", delete=False
    ) as target:
        temporary = Path(target.name)
        json.dump(record, target, indent=2, allow_nan=False)
        target.write("\n")
        target.flush()
        os.fsync(target.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return record


def _guard(path: Path):
    return file_lock(path.with_suffix(".lock"))


def _timing(wait_timeout: float, poll_interval: float):
    if not math.isfinite(wait_timeout) or not 0 < wait_timeout <= 86400:
        raise ValueError("Wait timeout must be greater than 0 and at most 86400 seconds")
    if not math.isfinite(poll_interval) or not 0 < poll_interval <= 60:
        raise ValueError("Poll interval must be greater than 0 and at most 60 seconds")


def _descriptors(history: dict) -> list[dict]:
    outputs = history.get("outputs")
    if not isinstance(outputs, dict):
        raise ComfyUIError("Successful history record has no outputs object")
    descriptors = []
    for node_id, output in outputs.items():
        if not isinstance(output, dict):
            raise ComfyUIError("Invalid output metadata")
        for category, values in output.items():
            if not isinstance(values, list):
                continue
            for value in values:
                if not isinstance(value, dict) or "filename" not in value:
                    continue
                filename = value["filename"]
                folder = value.get("subfolder", "")
                # ComfyUI uses the host's path separator in nested subfolders.
                # Validate both spellings, but retain the exact server descriptor.
                portable_folder = folder.replace("\\", "/") if isinstance(folder, str) else ""
                kind = value.get("type")
                if isinstance(kind, str) and kind in {"input", "temp"}:
                    continue
                if (
                    not isinstance(filename, str)
                    or not filename
                    or any(c in filename for c in "/\\:\0")
                    or filename in {".", ".."}
                    or not isinstance(folder, str)
                    or any(c in folder for c in ":\0")
                    or PurePosixPath(portable_folder).is_absolute()
                    or ".." in PurePosixPath(portable_folder).parts
                    or kind != "output"
                ):
                    raise ComfyUIError(
                        "History artifact has an unsupported or unsafe output descriptor"
                    )
                descriptors.append(
                    {
                        "node_id": str(node_id),
                        "category": str(category),
                        "filename": filename,
                        "subfolder": folder,
                        "type": kind,
                    }
                )
    if not descriptors:
        raise ComfyUIError("Execution succeeded but produced no persistent file artifacts")
    return descriptors


def _collect(config: Config, client: ComfyUIClient, record: dict, history: dict):
    directory = _contained_directory(config, f"output/jobs/{record['request_id']}")
    artifacts = []
    for index, descriptor in enumerate(_descriptors(history)):
        # Server filenames are metadata only; local names do not incorporate untrusted paths.
        extension = Path(descriptor["filename"]).suffix
        if not re.fullmatch(r"\.[A-Za-z0-9]{1,10}", extension):
            extension = ".bin"
        destination = directory / f"artifact-{index:04d}{extension}"
        download = client.download_output(descriptor, destination)
        artifacts.append({**descriptor, **download})
    record["artifacts"] = artifacts
    _verify_media(record)


def _verify_media(record: dict):
    for node_id, node in record.get("workflow", {}).items():
        if node["class_type"] == "SaveImage" and "itov_image" in node.get("_meta", {}):
            expected = image_contract(node["_meta"]["itov_image"])
            outputs = [item for item in record["artifacts"] if item["node_id"] == node_id]
            require_count = len(outputs) == 1 and len(record["artifacts"]) == 1
            if not require_count:
                raise ValueError("Expected exactly one collected evaluation image")
            outputs[0]["image_validation"] = verify_image(Path(outputs[0]["path"]), expected)
        if node["class_type"] == "SaveAudioAdvanced":
            metadata = node.get("_meta", {})
            if not isinstance(metadata, dict):
                raise ValueError("Audio metadata must be an object")
            if "itov_audio" in metadata:
                expected = audio_contract(metadata["itov_audio"])
                outputs = [item for item in record["artifacts"] if item["node_id"] == node_id]
                if len(outputs) != 1:
                    raise ValueError(
                        "Expected exactly one collected artifact for each audio output"
                    )
                outputs[0]["audio_validation"] = verify_audio(Path(outputs[0]["path"]), expected)
        if node["class_type"] != "SaveVideo":
            continue
        metadata = node.get("_meta", {})
        if not isinstance(metadata, dict):
            raise ValueError("Video metadata must be an object")
        if "itov_video" not in metadata:
            continue
        expected = video_contract(metadata["itov_video"])
        outputs = [item for item in record["artifacts"] if item["node_id"] == node_id]
        if len(outputs) != 1:
            raise ValueError("Expected exactly one collected artifact for each video output")
        outputs[0]["video_validation"] = verify_video(Path(outputs[0]["path"]), expected)


def _wait(
    config: Config,
    client: ComfyUIClient,
    path: Path,
    record: dict,
    wait_timeout: float,
    poll_interval: float,
) -> dict:
    deadline = time.monotonic() + wait_timeout
    original_timeout = client.timeout
    record["status"] = "observing"
    record.pop("error", None)
    _save(path, record)
    try:
        while time.monotonic() < deadline:
            client.timeout = min(original_timeout, max(0.001, deadline - time.monotonic()))
            history = client.history(record["prompt_id"])
            if history is not None:
                if "owner" in record:
                    prompt = history.get("prompt")
                    if (
                        not isinstance(prompt, list)
                        or len(prompt) < 4
                        or prompt[1] != record["prompt_id"]
                        or not isinstance(prompt[3], dict)
                        or prompt[3].get("itov_request_id") != record["request_id"]
                        or not submission_matches(record["workflow"], prompt[2])
                    ):
                        raise ComfyUIError("History does not belong to this batch job and workflow")
                status = history["status"]
                messages = status.get("messages", [])
                if not isinstance(messages, list):
                    raise ComfyUIError("/history: status messages must be an array")
                failed = status.get("status_str") == "error" or any(
                    isinstance(event, list)
                    and event
                    and isinstance(event[0], str)
                    and event[0] in {"execution_error", "execution_interrupted"}
                    for event in messages
                )
                if failed:
                    record.update(status="failed", execution=history)
                    return _save(path, record)
                if status.get("completed") is True and status.get("status_str") == "success":
                    record.update(status="collecting", execution=history)
                    _save(path, record)
                    client.timeout = original_timeout
                    _collect(config, client, record, history)
                    record["status"] = "succeeded"
                    record.pop("error", None)
                    return _save(path, record)
            time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
        record.update(
            status="timed_out",
            error="Stopped waiting; the server job may still run. Resume with job wait.",
        )
    except KeyboardInterrupt:
        record.update(
            status="detached",
            error="Stopped waiting; the server job was not cancelled. Resume with job wait.",
        )
    except (ComfyUIError, OSError, ValueError) as error:
        if record["status"] == "collecting":
            state = "collection_failed"
        else:
            state = "timed_out" if time.monotonic() >= deadline else "observation_failed"
        record.update(status=state, error=str(error))
    finally:
        client.timeout = original_timeout
    return _save(path, record)


def run_job(
    config: Config,
    workflow: Path,
    *,
    timeout: float = 3,
    wait_timeout: float = 120,
    poll_interval: float = 1,
) -> dict:
    _timing(wait_timeout, poll_interval)
    client = ComfyUIClient(config.url, timeout=timeout)
    raw = workflow.read_bytes()
    graph = parse_json(raw)
    validation = validate_workflow(graph, client.object_info()).to_dict()
    request_id = str(uuid.uuid4())
    path = _contained_directory(config, "state/jobs") / f"{request_id}.json"
    record = {
        "version": 1,
        "request_id": request_id,
        "server": config.url,
        "workflow_path": str(workflow.resolve()),
        "workflow_sha256": hashlib.sha256(raw).hexdigest(),
        "workflow": graph,
        "validation": validation,
        "created_at": _now(),
        "status": "validating",
        "prompt_id": None,
        "artifacts": [],
    }
    with _guard(path):
        if not validation["valid"]:
            record["status"] = "validation_failed"
            return _save(path, record)
        record["status"] = "submitting"
        _save(path, record)
        try:
            acknowledgement = client.submit(graph, request_id)
        except (ComfyUIError, KeyboardInterrupt) as error:
            rejected = (
                isinstance(error, ComfyUIError)
                and error.status_code == 400
                and isinstance(error.details, dict)
                and "error" in error.details
            )
            record.update(status="rejected" if rejected else "submission_unknown", error=str(error))
            if isinstance(error, ComfyUIError):
                record["server_error"] = error.details
            return _save(path, record)
        record.update(
            status="queued", prompt_id=acknowledgement["prompt_id"], acknowledgement=acknowledgement
        )
        _save(path, record)
        return _wait(config, client, path, record, wait_timeout, poll_interval)


def wait_job(
    config: Config,
    path: Path,
    *,
    timeout: float = 3,
    wait_timeout: float = 120,
    poll_interval: float = 1,
) -> dict:
    _timing(wait_timeout, poll_interval)
    validate_timeout(timeout)
    path = path.resolve()
    directory = _contained_directory(config, "state/jobs")
    if path.parent != directory.resolve():
        raise ValueError("Job record must be in this workspace's state/jobs directory")
    request_id = str(uuid.UUID(path.stem))
    if path.name != request_id + ".json":
        raise ValueError("Invalid job record filename")
    with _guard(path):
        record = parse_json(path.read_bytes())
        if (
            not isinstance(record, dict)
            or type(record.get("version")) is not int
            or record["version"] != 1
            or record.get("request_id") != request_id
            or record.get("server") != config.url
            or not isinstance(record.get("status"), str)
            or record.get("status")
            not in {
                "prepared",
                "validating",
                "validation_failed",
                "submitting",
                "queued",
                "observing",
                "collecting",
                "succeeded",
                "failed",
                "rejected",
                "submission_unknown",
                "timed_out",
                "detached",
                "observation_failed",
                "collection_failed",
            }
            or not isinstance(record.get("artifacts"), list)
            or any(
                not isinstance(item, dict)
                or not isinstance(item.get("path"), str)
                or not isinstance(item.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
                for item in record.get("artifacts", [])
            )
        ):
            raise ValueError("Job record does not match the configured workspace/server")
        if record.get("status") == "succeeded":
            expected_directory = _contained_directory(config, f"output/jobs/{request_id}")
            artifacts = record.get("artifacts")
            intact = isinstance(artifacts, list) and bool(artifacts)
            if intact:
                for artifact in artifacts:
                    output = Path(artifact["path"])
                    if output.resolve().parent != expected_directory.resolve():
                        raise ValueError("Saved artifact path does not belong to this job")
                    if not output.is_file():
                        intact = False
                        break
                    with output.open("rb") as source:
                        if hashlib.file_digest(source, "sha256").hexdigest() != artifact["sha256"]:
                            intact = False
                            break
            if intact:
                _verify_media(record)
                return record
        if record.get("status") in {"failed", "rejected", "validation_failed"}:
            return record
        if not isinstance(record.get("prompt_id"), str) or not record["prompt_id"]:
            raise ValueError(
                "Submission acceptance is unknown; no prompt ID to resume. "
                "Do not automatically resubmit."
            )
        return _wait(
            config,
            ComfyUIClient(config.url, timeout=timeout),
            path,
            record,
            wait_timeout,
            poll_interval,
        )
