"""Checkpoint/continuation contracts; byte fixtures do not qualify actual training."""

import copy
import json
import random
import shutil
import struct
import subprocess
import sys

import pytest
from quality_fixtures import curated_inputs as curated_inputs
from test_evaluation import complete, save_result
from test_training import document, png, save_plan, write
from test_training import training_inputs as training_inputs
from test_training_config import configured, save_trace, trace_for

from itov import evaluation, quality, training, training_data, windows_process
from itov import training_checkpoints as checkpoints
from itov.catalog import canonical_bytes, sha256
from itov.cli import main


def durable(spec):
    return {**configured(spec), "version": 4, "checkpoints": {"every_steps": 2}}


def payload(parameters, mutate=None):
    header, raw = {}, bytearray()
    for index, parameter in enumerate(parameters):
        count = 1
        for size in parameter["shape"]:
            count *= size
        for name in ("weight", "exp_avg", "exp_avg_sq"):
            key = f"p{index:06d}.{name}"
            data = struct.pack(f"<{count}f", *([0.1] * count))
            header[key] = {
                "dtype": "F32",
                "shape": parameter["shape"],
                "data_offsets": [len(raw), len(raw) + len(data)],
            }
            raw.extend(data)
    header["rng.cpu"] = {"dtype": "U8", "shape": [16], "data_offsets": [len(raw), len(raw) + 16]}
    raw.extend(bytes(range(16)))
    if mutate:
        mutate(header, raw)
    encoded = canonical_bytes(header)
    encoded += b" " * (-len(encoded) % 8)
    return struct.pack("<Q", len(encoded)) + encoded + raw


def checkpoint(item, step, *, mutate=None, tensor_mutate=None):
    folder = item.folder / "checkpoints" / f"step-{step:06d}"
    parameters = [{"name": "down", "shape": [4, 8]}, {"name": "up", "shape": [8, 4]}]
    trace = copy.deepcopy(item.trace)
    trace.update(
        steps=trace["steps"][:step],
        validation=[r for r in trace["validation"] if r["step"] <= step],
    )
    value = {
        "version": 1,
        "profile": checkpoints.PROFILE,
        "plan_id": item.plan["plan_id"],
        "compatibility_id": checkpoints.compatibility(item.plan),
        "position": checkpoints.position(item.plan, step),
        "runtime": {
            "device": "cpu",
            "gpu_uuid": None,
            "gpu_name": None,
            "driver": None,
            "cuda_capability": None,
            "deterministic_algorithms": False,
            "cudnn_benchmark": False,
            "cudnn_deterministic": False,
        },
        "parameters": parameters,
        "state": write(folder, "state.safetensors", payload(parameters, tensor_mutate)),
        "rng": {
            "python": {
                "version": 3,
                "keys": list(random.Random(1).getstate()[1]),
                "gauss_hex": None,
            },
            "numpy": {
                "algorithm": "MT19937",
                "keys": [1] * 624,
                "position": 1,
                "has_gauss": 0,
                "gauss_hex": "0x0.0p+0",
            },
        },
        "trace": trace,
    }
    if mutate:
        mutate(value)
    path = document(folder / "checkpoint.json", training_data.seal(value, "checkpoint_id"))
    return path, {
        "path": path.relative_to(item.folder).as_posix(),
        "sha256": sha256(path.read_bytes()),
    }


@pytest.fixture
def completed_checkpoint(curated_inputs, monkeypatch):
    item = curated_inputs
    item.spec = durable(item.spec)
    complete(item, "training")
    item.result["quality_matrix"] = [
        {**row, "image": write(item.folder, f"quality-{i}.png", png(i))}
        for i, row in enumerate(quality.expected(item.suite))
    ]
    item.trace = trace_for(item.plan)
    item.result["checkpoints"] = [checkpoint(item, n)[1] for n in (2, 4, 6, 8)]
    save_trace(item, item.trace)
    monkeypatch.setattr(windows_process, "process_state", lambda _: "dead")
    monkeypatch.setattr(windows_process, "job_active", lambda _: 0)
    return item


def terminal(item, status="failed"):
    return training._record(
        item.folder,
        {
            "version": 2,
            "plan_id": item.plan["plan_id"],
            "status": status,
            "owner": {"pid": 1, "created": 1},
            "worker": None,
            "lease": {"job_name": "fixture"},
        },
    )


def test_v4_results_packets_and_read_only_checkpoints(completed_checkpoint, capsys):
    item = completed_checkpoint
    assert training.status(item.config, item.plan_path)["status"] == "artifacts_validated"
    assert evaluation.assess(item.config, item.plan_path)["technical_pass"]
    assert quality.packet(item.config, item.plan_path)["plan_id"] == item.plan["plan_id"]
    observed = checkpoints.status(item.config, item.plan_path)
    assert [r["resumable"] for r in observed["entries"]] == [True, True, True, False]
    before = {p: p.read_bytes() for p in item.folder.rglob("*") if p.is_file()}
    assert (
        main(
            [
                "training",
                "checkpoints",
                str(item.plan_path),
                "--config",
                str(item.config.file),
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["_cli"]["outcome"] == "ok"
    assert all(p.read_bytes() == raw for p, raw in before.items())


@pytest.mark.parametrize("every", [True, 0, -1, 9, "2"])
def test_invalid_checkpoint_cadence(curated_inputs, every):
    item = curated_inputs
    item.spec = durable(item.spec)
    item.spec["checkpoints"]["every_steps"] = every
    with pytest.raises(ValueError):
        save_plan(item)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda v: v.update(version=True),
        lambda v: v.update(compatibility_id="0" * 64),
        lambda v: v["position"].update(completed_steps=3),
        lambda v: v["position"].update(next_position=999),
        lambda v: v["position"].update(next_learning_rate_trillionths=1),
        lambda v: v["runtime"].update(cudnn_benchmark=1),
        lambda v: v["parameters"][0].update(shape=[True, 8]),
        lambda v: v["parameters"][1].update(name="down"),
        lambda v: v["rng"]["python"].update(version=2),
        lambda v: v["rng"]["python"]["keys"].pop(),
        lambda v: v["rng"]["python"].update(gauss_hex="nan"),
        lambda v: v["rng"]["numpy"].update(position=625),
        lambda v: v["rng"]["numpy"].update(algorithm="PCG64"),
        lambda v: v["trace"]["steps"].pop(),
        lambda v: v["trace"]["validation"].clear(),
        lambda v: v["trace"]["steps"][0]["micro_batches"][0][0].update(noise_seed=99),
    ],
)
def test_resealed_invalid_checkpoint_refused(completed_checkpoint, mutate):
    item = completed_checkpoint
    path, _ = checkpoint(item, 2, mutate=mutate)
    with pytest.raises(ValueError):
        checkpoints.validate(path, item.plan)
    observed = checkpoints.status(item.config, item.plan_path)
    assert observed["entries"][0]["status"] == "invalid"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda h, b: h.pop("rng.cpu"),
        lambda h, b: h["p000000.weight"].update(dtype="F16"),
        lambda h, b: h["p000000.weight"].update(shape=[8, 4]),
        lambda h, b: h["p000001.weight"].update(data_offsets=[0, 128]),
        lambda h, b: b.__setitem__(slice(0, 4), struct.pack("<f", float("nan"))),
        lambda h, b: b.__setitem__(slice(256, 260), struct.pack("<f", -1.0)),
        lambda h, b: b.extend(b"undeclared"),
    ],
)
def test_resealed_tensor_corruption_refused(completed_checkpoint, mutate):
    item = completed_checkpoint
    path, _ = checkpoint(item, 2, tensor_mutate=mutate)
    with pytest.raises(ValueError):
        checkpoints.validate(path, item.plan)


def test_partial_missing_extra_and_changed_payloads_remain_visible(completed_checkpoint):
    item = completed_checkpoint
    path, _ = checkpoint(item, 2)
    partial = path.parent.parent / ".partial-interrupted"
    shutil.copytree(path.parent, partial)
    with pytest.raises(ValueError, match="Partial"):
        checkpoints.validate(partial / "checkpoint.json", item.plan)
    (path.parent / "state.safetensors").write_bytes(b"truncated")
    rows = checkpoints.status(item.config, item.plan_path)["entries"]
    assert rows[0]["status"] == "partial" and rows[1]["status"] == "invalid"
    checkpoint(item, 2)
    (path.parent / "extra.txt").write_text("uncommitted")
    with pytest.raises(ValueError, match="undeclared"):
        checkpoints.validate(path, item.plan)
    assert (partial / "state.safetensors").is_file()


def test_continuation_is_new_immutable_plan_with_same_compatibility(completed_checkpoint, capsys):
    item = completed_checkpoint
    terminal(item)
    source, _ = checkpoint(item, 2)
    before = {p: p.read_bytes() for p in item.folder.rglob("*") if p.is_file()}
    plan = checkpoints.resume_plan(item.config, item.plan_path, source)
    path = training.save_plan(item.config, plan)
    assert plan["plan_id"] != item.plan["plan_id"]
    assert checkpoints.compatibility(plan) == checkpoints.compatibility(item.plan)
    training.revalidate(item.config, plan)
    assert not training.run_folder(item.config, plan).exists()
    assert all(p.read_bytes() == raw for p, raw in before.items())
    assert (
        main(
            [
                "training",
                "resume-plan",
                str(item.plan_path),
                "--checkpoint",
                str(source),
                "--config",
                str(item.config.file),
                "--save",
                "--json",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["plan_id"] == plan["plan_id"] and output["saved_path"] == str(path)


@pytest.mark.parametrize("status", ["running", "validating"])
def test_unrecovered_source_refused(completed_checkpoint, status):
    item = completed_checkpoint
    terminal(item, status)
    with pytest.raises(ValueError, match="Recover"):
        checkpoints.resume_plan(item.config, item.plan_path, checkpoint(item, 2)[0])


def test_live_source_and_final_checkpoint_refused(completed_checkpoint, monkeypatch):
    item = completed_checkpoint
    terminal(item)
    with pytest.raises(ValueError, match="remaining"):
        checkpoints.resume_plan(item.config, item.plan_path, checkpoint(item, 8)[0])
    monkeypatch.setattr(windows_process, "process_state", lambda _: "alive")
    with pytest.raises(ValueError, match="controller"):
        checkpoints.resume_plan(item.config, item.plan_path, checkpoint(item, 2)[0])


@pytest.mark.parametrize("change", ["source", "environment", "data", "settings", "checkpoint"])
def test_stale_continuation_refused(completed_checkpoint, monkeypatch, change):
    item = completed_checkpoint
    terminal(item)
    source, _ = checkpoint(item, 2)
    plan = checkpoints.resume_plan(item.config, item.plan_path, source)
    if change == "source":
        monkeypatch.setattr(training, "worker_sources", lambda: {"changed": "0" * 64})
    elif change == "environment":
        monkeypatch.setattr(training, "probe", lambda _: {"changed": True})
    elif change == "data":
        (item.config.root / "data/0.txt").write_text("changed")
    elif change == "settings":
        plan["specification"]["parameters"]["seed"] += 1
    else:
        (source.parent / "state.safetensors").write_bytes(b"changed")
    with pytest.raises(ValueError):
        training.revalidate(item.config, plan)


def test_missing_checkpoint_result_evidence_is_not_success(completed_checkpoint):
    item = completed_checkpoint
    item.result["checkpoints"].pop()
    save_result(item)
    status = training.status(item.config, item.plan_path)
    assert status["status"] == "failed" and status["failure_boundary"] == "checkpoint_evidence"


def continued(item):
    terminal(item)
    source, _ = checkpoint(item, 2)
    new = copy.copy(item)
    new.plan = checkpoints.resume_plan(item.config, item.plan_path, source)
    new.plan_path = training.save_plan(item.config, new.plan)
    new.folder = training.run_folder(item.config, new.plan)
    new.folder.mkdir()
    for path in item.folder.iterdir():
        if path.suffix in {".png", ".safetensors"}:
            shutil.copyfile(path, new.folder / path.name)
    new.result = copy.deepcopy(item.result)
    new.result["plan_id"] = new.plan["plan_id"]
    new.trace = trace_for(new.plan)
    new.result["checkpoints"] = [checkpoint(new, n)[1] for n in (4, 6, 8)]
    save_trace(new, new.trace)
    return new


def test_resumed_result_and_packet_validate_without_current_worker(
    completed_checkpoint, monkeypatch
):
    new = continued(completed_checkpoint)
    monkeypatch.setattr(training, "worker_sources", lambda: {"newer": "0" * 64})
    assert training.status(new.config, new.plan_path)["status"] == "artifacts_validated"
    assert evaluation.assess(new.config, new.plan_path)["technical_pass"]
    assert quality.packet(new.config, new.plan_path)["plan_id"] == new.plan["plan_id"]


def test_resealed_continuation_cannot_rewrite_inherited_history(completed_checkpoint):
    new = continued(completed_checkpoint)
    new.trace["steps"][0]["elapsed_ns"] += 1
    new.result["checkpoints"] = [checkpoint(new, n)[1] for n in (4, 6, 8)]
    save_trace(new, new.trace)
    status = training.status(new.config, new.plan_path)
    assert status["status"] == "failed" and status["failure_boundary"] == "checkpoint_evidence"
    assert "history" in status["error"]


def test_checkpoint_copied_outside_source_attempt_refused(completed_checkpoint):
    item = completed_checkpoint
    terminal(item)
    source, _ = checkpoint(item, 2)
    copied = item.config.root / "copied/step-000002"
    shutil.copytree(source.parent, copied)
    with pytest.raises(ValueError, match="outside"):
        checkpoints.resume_plan(item.config, item.plan_path, copied / "checkpoint.json")


def test_missing_payload_and_stale_inherited_source_fail(completed_checkpoint):
    item = completed_checkpoint
    new = continued(item)
    source = item.folder / "checkpoints/step-000002/state.safetensors"
    source.rename(source.with_suffix(".retained"))
    status = training.status(new.config, new.plan_path)
    assert status["status"] == "failed" and status["failure_boundary"] == "checkpoint_evidence"
    assert source.with_suffix(".retained").is_file()


def test_checkpoint_imports_are_dependency_light():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from itov import "
            "training_checkpoints,training_checkpoint_worker,checkpoint_tensors; "
            "assert not {'torch','numpy','safetensors','PIL','diffusers'} & set(sys.modules)",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
