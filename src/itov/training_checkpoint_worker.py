"""Optional Torch checkpoint serialization; no pickle and no ML imports at module import."""

from __future__ import annotations

import os
import random
import uuid

from itov import training_checkpoints as checkpoints
from itov.catalog import canonical_bytes, require, sha256
from itov.training_data import publish, seal


def runtime(gpu=None):
    import torch

    return {
        "device": "cuda" if gpu else "cpu",
        "gpu_uuid": gpu["uuid"] if gpu else None,
        "gpu_name": gpu["name"] if gpu else None,
        "driver": gpu["driver"] if gpu else None,
        "cuda_capability": list(torch.cuda.get_device_capability()) if gpu else None,
        "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
        "cudnn_benchmark": torch.backends.cudnn.benchmark,
        "cudnn_deterministic": torch.backends.cudnn.deterministic,
    }


class Checkpoints:
    def __init__(self, plan, output, model, precision, device, emit, source=None):
        self.plan, self.output, self.precision = plan, output, precision
        self.runtime, self.emit, self.source = device, emit, source
        self.learned = [(name, p) for name, p in model.named_parameters() if p.requires_grad]
        self.parameters = [{"name": name, "shape": list(p.shape)} for name, p in self.learned]
        self.references = []
        self.peak_allocated = self.peak_reserved = 0

    def restore(self, optimizer):
        import numpy as np
        import torch
        from safetensors.torch import load

        if self.source is None:
            return [], []
        path, value = self.source
        require(
            canonical_bytes(value["runtime"]) == canonical_bytes(self.runtime),
            "Checkpoint execution device/backend differs",
        )
        require(
            value["parameters"] == self.parameters, "Checkpoint parameter identity/order differs"
        )
        require(value["trace"]["precision"] == self.precision, "Checkpoint precision differs")
        raw = (path.parent / "state.safetensors").read_bytes()
        require(
            sha256(raw) == value["state"]["sha256"],
            "Checkpoint tensor bytes changed before restore",
        )
        tensors = load(raw)
        del raw
        step = value["position"]["completed_steps"]
        for index, (_, parameter) in enumerate(self.learned):
            prefix = f"p{index:06d}."
            with torch.no_grad():
                parameter.copy_(tensors[prefix + "weight"].to(parameter.device))
            optimizer.state[parameter] = {
                "step": torch.tensor(float(step), dtype=torch.float32),
                "exp_avg": tensors[prefix + "exp_avg"].to(parameter.device),
                "exp_avg_sq": tensors[prefix + "exp_avg_sq"].to(parameter.device),
            }
        for group in optimizer.param_groups:
            group["lr"] = (
                self.plan["optimization"]["steps"][step - 1]["learning_rate_trillionths"] / 10**12
            )
        trace = value["trace"]
        # Copy committed history, never infer progress from uncommitted event files.
        for kind, rows in (("step", trace["steps"]), ("validation", trace["validation"])):
            for row in rows:
                self.emit(kind, row["step"], row)
                self.peak_allocated = max(
                    self.peak_allocated, row["resources"]["cuda_peak_allocated_bytes"]
                )
                self.peak_reserved = max(
                    self.peak_reserved, row["resources"]["cuda_peak_reserved_bytes"]
                )
        rng = value["rng"]
        py, np_rng = rng["python"], rng["numpy"]
        random.setstate(
            (
                py["version"],
                tuple(py["keys"]),
                None if py["gauss_hex"] is None else float.fromhex(py["gauss_hex"]),
            )
        )
        np.random.set_state(
            (
                np_rng["algorithm"],
                np.asarray(np_rng["keys"], dtype=np.uint32),
                np_rng["position"],
                np_rng["has_gauss"],
                float.fromhex(np_rng["gauss_hex"]),
            )
        )
        torch.set_rng_state(tensors["rng.cpu"])
        if self.runtime["device"] == "cuda":
            torch.cuda.set_rng_state(tensors["rng.cuda"])
        return list(trace["steps"]), list(trace["validation"])

    def save(self, optimizer, steps, validation):
        import numpy as np
        import torch
        from safetensors.torch import save_file

        step = len(steps)
        if step not in checkpoints.checkpoint_steps(self.plan):
            return
        require(
            all(p.grad is None for _, p in self.learned),
            "Checkpoint requires an update boundary with cleared gradients",
        )
        directory = self.output / "checkpoints"
        directory.mkdir(exist_ok=True)
        final = directory / f"step-{step:06d}"
        require(not final.exists(), "Checkpoint already exists; preserve the original")
        stage = directory / (".partial-" + str(uuid.uuid4()))
        stage.mkdir()
        tensors = {}
        for index, (_, parameter) in enumerate(self.learned):
            state = optimizer.state[parameter]
            require(int(state["step"].item()) == step, "Checkpoint optimizer step differs")
            for field, tensor in (
                ("weight", parameter),
                ("exp_avg", state["exp_avg"]),
                ("exp_avg_sq", state["exp_avg_sq"]),
            ):
                require(
                    tensor.dtype == torch.float32 and bool(torch.isfinite(tensor).all()),
                    "Invalid checkpoint FP32 state",
                )
                tensors[f"p{index:06d}.{field}"] = tensor.detach().cpu().contiguous().clone()
        tensors["rng.cpu"] = torch.get_rng_state()
        if self.runtime["device"] == "cuda":
            tensors["rng.cuda"] = torch.cuda.get_rng_state()
        py, np_rng = random.getstate(), np.random.get_state()
        rng = {
            "python": {
                "version": py[0],
                "keys": list(py[1]),
                "gauss_hex": None if py[2] is None else py[2].hex(),
            },
            "numpy": {
                "algorithm": np_rng[0],
                "keys": np_rng[1].tolist(),
                "position": np_rng[2],
                "has_gauss": np_rng[3],
                "gauss_hex": np_rng[4].hex(),
            },
        }
        state_path = stage / "state.safetensors"
        save_file(tensors, str(state_path))
        with state_path.open("rb+") as stream:
            os.fsync(stream.fileno())
        value = seal(
            {
                "version": 1,
                "profile": checkpoints.PROFILE,
                "plan_id": self.plan["plan_id"],
                "compatibility_id": checkpoints.compatibility(self.plan),
                "position": checkpoints.position(self.plan, step),
                "runtime": self.runtime,
                "parameters": self.parameters,
                "state": {"path": state_path.name, "sha256": sha256(state_path.read_bytes())},
                "rng": rng,
                "trace": {
                    "version": 1,
                    "plan_id": self.plan["plan_id"],
                    "config": self.plan["optimization"]["config"],
                    "precision": self.precision,
                    "steps": steps,
                    "validation": validation,
                },
            },
            "checkpoint_id",
        )
        manifest = publish(stage / "checkpoint.json", value)
        checkpoints.validate(manifest, self.plan, published=False)
        # A partial directory is retained on any exception/interruption; only complete bundles move.
        require(not final.exists(), "Checkpoint publication destination already exists")
        stage.rename(final)
        reference = {
            "path": (final / "checkpoint.json").relative_to(self.output).as_posix(),
            "sha256": sha256((final / "checkpoint.json").read_bytes()),
        }
        self.references.append(reference)
        print(f"Committed checkpoint after optimizer step {step}: {final.name}", flush=True)
