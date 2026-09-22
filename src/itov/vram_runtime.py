"""Standalone observer bootstrap, executed ONLY by ComfyUI's configured Python.

No model or sampler changes. Install instrumentation at main.start_comfyui so
ComfyUI's own pre-Torch allocator/environment setup runs in its original order.
"""

import hashlib
import importlib.metadata
import json
import os
import runpy
import sys
import tempfile
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path


def publish(path, value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink()


def install(directory, helpers):
    import execution
    import server
    import torch
    from aiohttp import web

    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise RuntimeError("VRAM observer requires exactly one visible CUDA device")
    device = torch.cuda.current_device()
    properties = torch.cuda.get_device_properties(device)
    session_id = str(uuid.uuid4())
    directory = directory / session_id
    directory.mkdir()
    identity = {
        "version": 1,
        "session_id": session_id,
        "pid": os.getpid(),
        "started_at": datetime.now(UTC).isoformat(),
        "bootstrap_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "identity_sha256": hashlib.sha256(
            Path(__file__).with_name("vram_identity.py").read_bytes()
        ).hexdigest(),
        "device": {
            "index": device,
            "name": properties.name,
            "uuid": str(properties.uuid),
            "total_bytes": properties.total_memory,
        },
        "allocator_backend": torch.cuda.get_allocator_backend(),
        "cuda_version": torch.version.cuda,
        "cudnn_version": torch.backends.cudnn.version(),
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("torch", "comfy-aimdo", "comfy-kitchen")
        },
        "environment": {
            name: os.environ.get(name)
            for name in (
                "CUDA_VISIBLE_DEVICES",
                "PYTORCH_CUDA_ALLOC_CONF",
                "PYTORCH_ALLOC_CONF",
                "CUBLAS_WORKSPACE_CONFIG",
                "CUDA_MODULE_LOADING",
            )
        },
    }
    publish(directory / "identity.json", identity)
    state = {"executions": 0, "active": None, "last_workload": None, "errors": []}

    def memory():
        free, total = torch.cuda.mem_get_info(device)
        return {
            "global_free_bytes": free,
            "global_total_bytes": total,
            "allocated_bytes": torch.cuda.memory_allocated(device),
            "reserved_bytes": torch.cuda.memory_reserved(device),
        }

    original_init = server.PromptServer.__init__

    def initialize(self, *args, **kwargs):
        original_init(self, *args, **kwargs)

        @self.routes.get("/itov/vram")
        async def current(request):
            return web.json_response(
                {"identity": identity, "state": dict(state), "memory": memory()}
            )

    server.PromptServer.__init__ = initialize
    original_execute = execution.PromptExecutor.execute

    def execute(self, prompt, prompt_id, extra_data=None, execute_outputs=None):
        extra_data = extra_data or {}
        sequence = state["executions"]
        state.update(executions=sequence + 1, active=prompt_id)
        record = {
            "version": 1,
            "session_id": session_id,
            "sequence": sequence,
            "prompt_id": prompt_id,
            "request_id": extra_data.get("itov_request_id"),
            "workflow_sha256": hashlib.sha256(helpers["encoded"](prompt)).hexdigest(),
            "workload_key": helpers["workload_key"](prompt),
            "previous_workload": state["last_workload"],
            "started_at": datetime.now(UTC).isoformat(),
            "samples": [],
            "errors": [],
        }
        stop = threading.Event()
        worker = None
        started = time.monotonic_ns()

        def sample():
            try:
                record["samples"].append({"elapsed_ns": time.monotonic_ns() - started, **memory()})
            except Exception as error:
                record["errors"].append(str(error))

        def monitor():
            while not stop.wait(0.05):
                sample()

        try:
            torch.cuda.synchronize(device)
            torch.cuda.reset_peak_memory_stats(device)
            sample()
            worker = threading.Thread(target=monitor, daemon=True)
            worker.start()
            result = original_execute(self, prompt, prompt_id, extra_data, execute_outputs or [])
            record["execution_success"] = bool(self.success)
            return result
        except BaseException as error:
            record["execution_success"] = False
            record["errors"].append(str(error))
            raise
        finally:
            stop.set()
            if worker is not None:
                worker.join(timeout=5)
                if worker.is_alive():
                    record["errors"].append("Sampler failed to stop")
            try:
                torch.cuda.synchronize(device)
                sample()
                record["peak_allocated_bytes"] = torch.cuda.max_memory_allocated(device)
                record["peak_reserved_bytes"] = torch.cuda.max_memory_reserved(device)
            except Exception as error:
                record["errors"].append(str(error))
            record["duration_ns"] = time.monotonic_ns() - started
            record["finished_at"] = datetime.now(UTC).isoformat()
            try:
                publish(directory / (str(uuid.UUID(prompt_id)) + ".json"), record)
            except Exception as error:
                state["errors"].append(str(error))
            state.update(active=None, last_workload=record["workload_key"])

    execution.PromptExecutor.execute = execute


def main():
    directory = Path(sys.argv[1]).absolute()
    if directory.resolve() != directory or directory.is_symlink():
        raise ValueError("VRAM telemetry directory redirects")
    if sys.argv[2] != "--":
        raise ValueError("Expected telemetry directory followed by -- and stock main.py arguments")
    main_path = Path(sys.argv[3]).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("user", "scratch", "scratch/temp"):
        owned = directory.parent / name
        if owned.resolve() != owned or owned.is_symlink():
            raise ValueError("VRAM runtime data directory redirects")
        if name != "scratch/temp":
            owned.mkdir(exist_ok=True)
    helpers = runpy.run_path(str(Path(__file__).with_name("vram_identity.py")))
    sys.argv = sys.argv[3:]
    sys.path.insert(0, str(main_path.parent))

    def ready(frame, event, arg):
        if (
            event == "call"
            and frame.f_code.co_name == "start_comfyui"
            and Path(frame.f_code.co_filename).resolve() == main_path
        ):
            sys.setprofile(None)
            install(directory, helpers)
            sys.argv.append(helpers["MARKER"])

    sys.setprofile(ready)
    try:
        runpy.run_path(str(main_path), run_name="__main__")
    finally:
        sys.setprofile(None)


if __name__ == "__main__":
    main()
