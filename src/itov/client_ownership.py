"""Cooperative device ownership for requests on an externally controlled server.

The server is never terminated or interrupted. An uncertain POST retains a lease
until its exact request/graph has a positive terminal outcome, even after a crash.
"""

from __future__ import annotations

import os
import sys
import uuid
from urllib.parse import urlsplit

from itov import device
from itov.catalog import object_fields, require
from itov.comfyui import ComfyUIClient, parse_json_object, submission_matches
from itov.config import validate_url
from itov.jobs import _now
from itov.qualification import json_text, safe_path
from itov.windows_process import process_identity

KIND = "external_server_requests"


def local_server(url):
    parsed = urlsplit(validate_url(url))
    require(
        parsed.scheme == "http"
        and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        and not parsed.path,
        "Device-owned submission requires a local loopback HTTP server without a path prefix",
    )


def target_gpu(config):
    from itov.vram import gpu_snapshot

    local_server(config.url)
    gpu = gpu_snapshot()  # The supported ownership profile has exactly one NVIDIA GPU.
    devices = ComfyUIClient(config.url).system_stats()["devices"]
    require(
        len(devices) == 1
        and devices[0].get("type") == "cuda"
        and devices[0].get("index") == 0
        and gpu["name"] in devices[0].get("name", ""),
        "Server CUDA device does not match the single local NVIDIA GPU ownership profile",
    )
    return gpu["uuid"]


def terminal_history(request, history):
    require(isinstance(history, dict), "Terminal server evidence is missing")
    prompt = history.get("prompt")
    require(
        isinstance(prompt, list)
        and len(prompt) >= 4
        and prompt[1] == request["prompt_id"]
        and isinstance(prompt[3], dict)
        and prompt[3].get("itov_request_id") == request["request_id"]
        and submission_matches(parse_json_object(request["workflow_json"]), prompt[2]),
        "Terminal history does not belong to the exact owned request and graph",
    )
    status = history.get("status", {})
    require(
        status.get("status_str") == "error"
        or (status.get("completed") is True and status.get("status_str") == "success"),
        "Owned request is still active or its terminal outcome is uncertain",
    )


def recover_requests(value):
    """Fresh positive proof for outstanding external work; absence never proves completion."""
    local_server(value["server"])
    client = ComfyUIClient(value["server"])
    for request in value["requests"].values():
        if request["terminal"]:
            continue
        prompt = client.find_submission(
            request["request_id"],
            parse_json_object(request["workflow_json"]),
            prompt_id=request.get("prompt_id"),
        )
        if prompt is None:
            raise ValueError("External request outcome is unknown; preserve the device lease")
        terminal_history({**request, "prompt_id": prompt}, client.history(prompt))


class ClientLease:
    """Lazy lease: completed offline observation does not acquire or probe a GPU."""

    def __init__(self, config, operation_id, *, root=None):
        self.config, self.operation_id, self.root = config, operation_id, root
        self.context = None
        self.value: dict | None = None

    def __enter__(self):
        return self

    def _open(self, gpu_uuid, *, expected_id=None) -> dict:
        if self.context is not None:
            if self.value is None:
                raise ValueError("Device lease has not been acquired")
            require(self.value["gpu_uuid"] == gpu_uuid, "Device binding changed")
            return self.value
        context = device._locked(gpu_uuid, self.root)
        entered = False
        try:
            folder, path, current = context.__enter__()
            entered = True
            if current["status"] == "held":
                require(
                    current.get("kind") == KIND
                    and current.get("workspace") == str(self.config.root)
                    and current.get("operation_id") == self.operation_id
                    and current.get("server") == self.config.url
                    and (expected_id is None or current.get("lease_id") == expected_id),
                    "Unreleased device lease belongs to another operation; inspect its owner",
                )
                # Holding the same OS lock proves the prior controller is no longer dispatching.
                body = {k: v for k, v in current.items() if k != "record_id"}
                body.update(owner=process_identity(os.getpid()), resumed_at=_now())
            else:
                require(expected_id is None, "Pending request device lease is missing or retired")
                token = str(uuid.uuid4())
                body = {
                    "version": 1,
                    "status": "held",
                    "kind": KIND,
                    "lease_id": token,
                    "gpu_uuid": gpu_uuid,
                    "workspace": str(self.config.root),
                    "plan_id": self.operation_id,
                    "operation_id": self.operation_id,
                    "server": self.config.url,
                    "owner": process_identity(os.getpid()),
                    "workers": [],
                    "job_name": "Global\\ITOV-owned-" + token,
                    "requests": {},
                    "started_at": _now(),
                    "limits": (
                        "Cooperative single-GPU ownership; "
                        "external server/clients are not controlled."
                    ),
                }
            self.folder, self.path = folder, path
            self.value = device._write(path, body)
            self.context = context
            return self.value
        except BaseException:
            if entered:
                context.__exit__(*sys.exc_info())
            raise

    def _write(self):
        if self.value is None:
            raise ValueError("Device lease has not been acquired")
        self.value = device._write(
            self.path, {k: v for k, v in self.value.items() if k != "record_id"}
        )

    def begin(self, record):
        """Journal intent before POST. False means prior intent, never permission to retry."""
        gpu_uuid = target_gpu(self.config)
        value = self.value if self.value is not None else self._open(gpu_uuid)
        require(value["gpu_uuid"] == gpu_uuid, "Submission device identity changed")
        key = record["request_id"]
        record["device_lease"] = {
            "gpu_uuid": value["gpu_uuid"],
            "lease_id": value["lease_id"],
            "operation_id": self.operation_id,
            "server_control": "external",
        }
        if key in value["requests"]:
            require(
                submission_matches(
                    record["workflow"], parse_json_object(value["requests"][key]["workflow_json"])
                ),
                "Previously journaled request graph differs",
            )
            return False
        require(
            all(item["terminal"] for item in value["requests"].values()),
            "An unresolved request retains device ownership; observe it before submitting",
        )
        queue = ComfyUIClient(self.config.url).queue()
        require(
            not queue["queue_running"] and not queue["queue_pending"],
            "Server queue is busy; no new submission",
        )
        value["requests"][key] = {
            "request_id": key,
            "workflow_json": json_text(record["workflow"]),
            "prompt_id": None,
            "terminal": False,
            "status": "submitting",
        }
        self._write()
        return True

    def attach(self, record):
        binding = record.get("device_lease")
        if binding is None:
            return  # Legacy records remain observable; no new POST is authorized here.
        object_fields(
            binding,
            {"gpu_uuid", "lease_id", "operation_id", "server_control"},
            "request device lease",
        )
        require(
            str(uuid.UUID(binding["lease_id"])) == binding["lease_id"], "Invalid device lease id"
        )
        require(binding["server_control"] == "external", "Unsupported server ownership mode")
        require(binding["operation_id"] == self.operation_id, "Request operation binding differs")
        current = device.status(binding["gpu_uuid"], root=self.root)
        if current.get("lease_id") != binding["lease_id"] or current["status"] != "held":
            # A prior release/recovery is legal; observation still never POSTs.
            archive = safe_path(
                device.directory(binding["gpu_uuid"], self.root), binding["lease_id"] + ".json"
            )
            saved = device._read(archive)
            require(
                saved.get("kind") == KIND
                and saved.get("operation_id") == self.operation_id
                and saved.get("workspace") == str(self.config.root)
                and saved.get("server") == self.config.url
                and saved.get("lease_id") == binding["lease_id"]
                and record["request_id"] in saved["requests"],
                "Retired request lease does not match ownership",
            )
            self._match_request(saved, record)
            return
        value = self._open(binding["gpu_uuid"], expected_id=binding["lease_id"])
        self._match_request(value, record)

    @staticmethod
    def _match_request(value, record):
        request = value["requests"].get(record["request_id"])
        require(isinstance(request, dict), "Request is missing from its device lease")
        require(
            submission_matches(parse_json_object(request["workflow_json"]), record["workflow"])
            and (
                request["prompt_id"] is None
                or record.get("prompt_id") in {None, request["prompt_id"]}
            ),
            "Job graph or prompt differs from its device lease",
        )

    def update(self, record):
        if self.value is None or record["request_id"] not in self.value["requests"]:
            return
        request = self.value["requests"][record["request_id"]]
        require(
            submission_matches(parse_json_object(request["workflow_json"]), record["workflow"]),
            "Request graph changed",
        )
        request.update(prompt_id=record.get("prompt_id"), status=record["status"])
        if record["status"] in {"succeeded", "failed", "collection_failed"}:
            terminal_history(request, record.get("execution"))
            request["terminal"] = True
        elif record["status"] == "rejected":
            require(
                isinstance(record.get("server_error"), dict) and "error" in record["server_error"],
                "Rejection proof is missing",
            )
            request["terminal"] = True
        self._write()

    def __exit__(self, *args):
        if self.context is None:
            return
        try:
            if self.value is None:
                raise ValueError("Device lease has not been acquired")
            if all(item["terminal"] for item in self.value["requests"].values()):
                device._retire(
                    self.folder, self.path, self.value, "external_requests_confirmed_terminal"
                )
        finally:
            self.context.__exit__(*args)
