"""Same-user, cross-workspace device leases with durable, explicit crash recovery."""

from __future__ import annotations

import os
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

from itov.catalog import canonical_bytes, require, sha256
from itov.catalog_store import _atomic_write
from itov.comfyui import parse_json_object
from itov.jobs import _now
from itov.locking import file_lock
from itov.qualification import safe_path
from itov.windows_process import job_active, process_identity, process_state


def registry_root() -> Path:
    require(os.name == "nt", "Managed device leases currently require Windows")
    return Path.home() / "AppData/Local/ITOV/device-leases"


def directory(gpu_uuid: str, root: Path | None = None) -> Path:
    device = str(uuid.UUID(gpu_uuid.lower().removeprefix("gpu-")))
    return safe_path(root or registry_root(), device)


def _write(path: Path, body: dict) -> dict:
    value = {**body, "record_id": sha256(canonical_bytes(body))}
    _atomic_write(path, canonical_bytes(value) + b"\n")
    return value


def _read(path: Path) -> dict:
    require(path.is_file(), "Device registry is incomplete; preserve and inspect")
    raw = path.read_bytes()
    value = parse_json_object(raw, message="Invalid device registry")
    body = {k: v for k, v in value.items() if k != "record_id"}
    require(
        value.get("version") == 1
        and value.get("status") in {"idle", "held"}
        and value.get("kind") in {None, "external_server_requests"}
        and value.get("record_id") == sha256(canonical_bytes(body))
        and raw == canonical_bytes(value) + b"\n",
        "Device registry integrity differs; preserve and inspect",
    )
    return value


@contextmanager
def _locked(gpu_uuid: str, root=None):
    folder = directory(gpu_uuid, root)
    folder.mkdir(parents=True, exist_ok=True)
    with file_lock(safe_path(folder, "ownership.lock")):
        marker, state = safe_path(folder, "initialized"), safe_path(folder, "current.json")
        if not marker.exists() and not state.exists():
            _atomic_write(marker, b"itov-device-v1\n", exclusive=True)
            _write(state, {"version": 1, "status": "idle", "previous": None})
        require(marker.read_bytes() == b"itov-device-v1\n", "Invalid device registry marker")
        yield folder, state, _read(state)


def status(gpu_uuid: str, *, root=None) -> dict:
    folder = directory(gpu_uuid, root)
    if not folder.exists():
        return {"status": "uninitialized", "directory": str(folder)}
    # Publication is atomic. A status snapshot must remain readable while its lock is held.
    marker = safe_path(folder, "initialized")
    require(
        marker.is_file() and marker.read_bytes() == b"itov-device-v1\n",
        "Incomplete device registry",
    )
    return {**_read(safe_path(folder, "current.json")), "directory": str(folder)}


def _retire(folder, path, value, reason):
    archive = safe_path(folder, f"{value['lease_id']}.json")
    if archive.exists():
        require(archive.read_bytes() == canonical_bytes(value) + b"\n", "Lease archive differs")
    else:
        _atomic_write(archive, canonical_bytes(value) + b"\n", exclusive=True)
    return _write(
        path,
        {
            "version": 1,
            "status": "idle",
            "previous": value["lease_id"],
            "reason": reason,
            "released_at": _now(),
        },
    )


def recover(gpu_uuid: str, expected_id: str, *, root=None) -> dict:
    with _locked(gpu_uuid, root) as (folder, path, value):
        require(
            value["status"] == "held" and value.get("lease_id") == expected_id,
            "Device lease changed",
        )
        require(process_state(value["owner"]) == "dead", "Device owner is still alive")
        if value.get("kind") == "external_server_requests":
            from itov.client_ownership import recover_requests

            recover_requests(value)
            return _retire(folder, path, value, "explicit_recovery_of_terminal_external_requests")
        require(job_active(value["job_name"]) == 0, "Owned job still has active processes")
        require(
            all(process_state(p) == "dead" for p in value["workers"]),
            "Owned workers are still alive",
        )
        return _retire(folder, path, value, "explicit_recovery_of_confirmed_dead_owner_and_job")


class Lease:
    def __init__(self, gpu_uuid: str, workspace: Path, plan_id: str, *, root=None):
        self.gpu_uuid, self.workspace, self.plan_id, self.root = gpu_uuid, workspace, plan_id, root
        self.context = None
        self.value: dict | None = None

    def __enter__(self):
        self.context = _locked(self.gpu_uuid, self.root)
        entered = False
        try:
            self.folder, self.path, previous = self.context.__enter__()
            entered = True
            require(
                previous["status"] == "idle",
                "Unreleased device lease; inspect and explicitly recover",
            )
            token = str(uuid.uuid4())
            self.value = _write(
                self.path,
                {
                    "version": 1,
                    "status": "held",
                    "lease_id": token,
                    "gpu_uuid": self.gpu_uuid,
                    "workspace": str(self.workspace),
                    "plan_id": self.plan_id,
                    "owner": process_identity(os.getpid()),
                    "workers": [],
                    "job_name": "Global\\ITOV-owned-" + token,
                    "started_at": _now(),
                },
            )
            return self
        except BaseException:
            if entered:
                self.context.__exit__(*sys.exc_info())
            raise

    def register(self, identity: dict):
        if self.value is None:
            raise ValueError("Device lease has not been acquired")
        body = {k: v for k, v in self.value.items() if k != "record_id"}
        body["workers"] = [*body["workers"], identity]
        self.value = _write(self.path, body)

    def release(self):
        if self.value is None:
            raise ValueError("Device lease has not been acquired")
        require(job_active(self.value["job_name"]) == 0, "Owned job has not stopped")
        require(
            all(process_state(p) == "dead" for p in self.value["workers"]),
            "Owned worker exit is unconfirmed",
        )
        _retire(self.folder, self.path, self.value, "owned_job_and_all_workers_stopped")

    def __exit__(self, *args):
        # An exception/abrupt controller exit leaves its journal held. Never clear by age.
        if self.context is not None:
            self.context.__exit__(*args)
