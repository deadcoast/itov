"""Batch-owned job records. Once submitting is durable, this module never retries POST."""

from __future__ import annotations

import uuid
from pathlib import Path

from itov.catalog import require, sha256
from itov.comfyui import ComfyUIClient, ComfyUIError, parse_json
from itov.config import Config
from itov.jobs import _guard, _now, _save
from itov.jobs import _wait_job as wait_job
from itov.qualification import json_text, safe_path


def identity(plan_id: str, index: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"itov:batch:v1:{plan_id}:{index}"))


def job_path(config: Config, plan_id: str, index: int) -> Path:
    return safe_path(config.root, f"state/jobs/{identity(plan_id, index)}.json")


def read_owned(config: Config, plan: dict, job: dict) -> dict:
    path = job_path(config, plan["plan_id"], job["index"])
    record = parse_json(path.read_bytes())
    require(
        isinstance(record, dict)
        and record.get("version") == 1
        and record.get("request_id") == path.stem
        and record.get("server") == config.url
        and record.get("owner") == {"plan_id": plan["plan_id"], "index": job["index"]}
        and record.get("workflow_sha256") == job["workflow_sha256"]
        and sha256(job["workflow_json"].encode()) == job["workflow_sha256"]
        and json_text(record.get("workflow")) == json_text(parse_json(job["workflow_json"])),
        "Job ownership/workflow differs from the reserved plan; preserve and inspect",
    )
    require(
        record.get("status") != "prepared" or record.get("prompt_id") is None,
        "Prepared job cannot already have a prompt ID",
    )
    return record


def prepare_owned(config: Config, plan: dict, job: dict) -> dict:
    path = job_path(config, plan["plan_id"], job["index"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with _guard(path):
        if path.exists():
            return read_owned(config, plan, job)
        record = {
            "version": 1,
            "request_id": path.stem,
            "server": config.url,
            "owner": {"plan_id": plan["plan_id"], "index": job["index"]},
            "workflow_path": None,
            "workflow_sha256": job["workflow_sha256"],
            "workflow": parse_json(job["workflow_json"]),
            "created_at": _now(),
            "status": "prepared",
            "prompt_id": None,
            "artifacts": [],
        }
        return _save(path, record)


def submit_owned(
    config: Config, plan: dict, job: dict, client: ComfyUIClient, *, device_owner=None
) -> dict:
    path = job_path(config, plan["plan_id"], job["index"])
    with _guard(path):
        record = read_owned(config, plan, job)
        require(record["status"] == "prepared", "Only a prepared job may be submitted")
        if device_owner is not None and not device_owner.begin(record):
            record.update(
                status="submission_unknown",
                error="Prior device intent exists; observe it without resubmitting",
            )
            return _save(path, record)
        record["status"] = "submitting"
        _save(path, record)
        try:
            acknowledgement = client.submit(record["workflow"], record["request_id"])
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
        else:
            record.update(
                status="queued",
                prompt_id=acknowledgement["prompt_id"],
                acknowledgement=acknowledgement,
            )
        return _save(path, record)


def observe_owned(
    config: Config,
    plan: dict,
    job: dict,
    *,
    timeout: float,
    wait_timeout: float,
    poll_interval: float,
    prompt_id: str | None = None,
) -> dict:
    path = job_path(config, plan["plan_id"], job["index"])
    with _guard(path):
        record = read_owned(config, plan, job)
        require(record["status"] != "prepared", "Prepared job has not been submitted")
        if record["status"] in {"submitting", "submission_unknown"}:
            try:
                match = ComfyUIClient(config.url, timeout=timeout).find_submission(
                    record["request_id"], record["workflow"], prompt_id=prompt_id
                )
                if match:
                    record.update(
                        status="queued",
                        prompt_id=match,
                        reconciled_from="server_request_id_and_exact_workflow",
                    )
                    record.pop("error", None)
                else:
                    record.update(
                        status="submission_unknown",
                        error="No acceptance evidence found; automatic resubmission is forbidden",
                    )
            except ComfyUIError as error:
                record.update(status="submission_unknown", error=str(error))
            _save(path, record)
            if record["status"] == "submission_unknown":
                return record
        elif prompt_id is not None:
            require(record.get("prompt_id") == prompt_id, "Prompt ID differs from acknowledged job")
    return wait_job(
        config, path, timeout=timeout, wait_timeout=wait_timeout, poll_interval=poll_interval
    )
