"""Dataset/planning contracts and native process protocol; these are not ML qualification."""

import json
import os
import struct
import sys
import time
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from itov import device, training, training_data
from itov.catalog import canonical_bytes, sha256
from itov.cli import main
from itov.config import initialize
from itov.windows_process import Job, process_identity, process_state

GPU = "GPU-19396af4-e5de-4d99-a258-803d73f4af12"


def png(index, size=512):
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\0" + bytes([index, 20, 30]) * size) * size))
        + chunk(b"IEND", b"")
    )


def write(root, name, raw):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {"path": name, "sha256": sha256(raw)}


def document(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value) + b"\n")
    return path


@pytest.fixture
def training_inputs(tmp_path, monkeypatch):
    config = initialize(tmp_path / "workspace", tmp_path / "comfy")
    samples = []
    for index in range(4):
        image = write(config.root, f"data/{index}.png", png(index))
        caption = write(config.root, f"data/{index}.txt", b"testtrigger geometry\n")
        samples.append(
            {
                "id": f"sample-{index}",
                "split": "train" if index < 2 else "validation",
                "group": f"group-{index}",
                "source": image,
                "image": image,
                "caption": caption,
            }
        )
    dataset = {
        "version": 1,
        "id": "fixture",
        "purpose": "smoke",
        "origin": {"title": "Test fixture", "reference": "test_training.py"},
        "rights": {
            "basis": "Test fixture",
            "reference": "test_training.py",
            "training_permitted": True,
        },
        "preprocessing": "prepared-square-rgb-png-v1",
        "samples": samples,
    }
    path = document(config.root / "data/dataset.json", dataset)
    prepared = training_data.prepare(config.root, path)
    prepared_path = Path(prepared["saved_path"])
    checkpoint = write(config.comfyui_root, "models/checkpoints/fixture.safetensors", b"fixture")
    refs = [
        write(config.root / "model-config", name, b"{}") for name in sorted(training.CONFIG_FILES)
    ]
    environment = write(config.root, "environment/python.exe", b"fixture executable")
    spec = {
        "version": 1,
        "id": "smoke",
        "profile": training.PROFILE,
        "dataset": {
            "path": prepared_path.relative_to(config.root).as_posix(),
            "sha256": sha256(prepared_path.read_bytes()),
        },
        "checkpoint": {"loader_name": "fixture.safetensors", "sha256": checkpoint["sha256"]},
        "model_config": {
            "directory": "model-config",
            "repository": "stabilityai/stable-diffusion-xl-base-1.0",
            "revision": "462165984030d82259a11f4367a4eed129e94a7b",
            "files": refs,
        },
        "environment": environment,
        "trigger": "testtrigger",
        "parameters": {
            "seed": 11,
            "steps": 8,
            "rank": 4,
            "learning_rate_millionths": 100,
            "resolution": 512,
            "timeout_seconds": 60,
        },
    }
    monkeypatch.setattr(
        training, "probe", lambda _: {"python": "fixture", "packages": training.PINNED}
    )
    return SimpleNamespace(
        config=config, dataset=dataset, dataset_path=path, prepared_path=prepared_path, spec=spec
    )


def save_plan(inputs):
    spec_path = document(inputs.config.root / "training.json", inputs.spec)
    value = training.plan(inputs.config, spec_path)
    return value, training.save_plan(inputs.config, value)


def test_prepare_is_replayable_and_revalidates_bytes(training_inputs):
    item = training_inputs
    first = training_data.prepare(item.config.root, item.dataset_path)
    assert training_data.prepare(item.config.root, item.dataset_path) == first
    assert first["counts"] == {"train": 2, "validation": 2}
    assert (
        training_data.load_dataset(item.config.root, item.prepared_path)["dataset_id"]
        == first["dataset_id"]
    )
    (item.config.root / "data/0.txt").write_text("changed")
    with pytest.raises(ValueError, match="SHA-256"):
        training_data.load_dataset(item.config.root, item.prepared_path)


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda d: d.update(version=True), "version"),
        (lambda d: d.update(purpose="production"), "purpose"),
        (lambda d: d["rights"].update(training_permitted=False), "permission"),
        (lambda d: d["samples"][2].update(group="group-0"), "group leakage"),
        (lambda d: d["samples"][2].update(source=d["samples"][0]["source"]), "source leakage"),
        (lambda d: d["samples"][1].update(id="sample-0"), "Duplicate sample"),
        (lambda d: d["samples"][1].update(image=d["samples"][0]["image"]), "reuses"),
        (lambda d: d["samples"][0].update(source={"path": "data/0.png", "sha256": []}), "SHA-256"),
        (lambda d: d.update(samples=d["samples"][:2]), "Both train"),
        (lambda d: d.update(unknown=1), "exactly"),
    ],
)
def test_dataset_rejects_invalid_authority_and_split(training_inputs, mutation, match):
    item = training_inputs
    mutation(item.dataset)
    document(item.dataset_path, item.dataset)
    with pytest.raises(ValueError, match=match):
        training_data.validate(item.config.root, item.dataset_path)


def test_dataset_duplicate_image_and_malformed_snapshot(training_inputs):
    item = training_inputs
    item.dataset["samples"][1]["image"] = write(item.config.root, "data/copy.png", png(0))
    document(item.dataset_path, item.dataset)
    with pytest.raises(ValueError, match="Duplicate prepared image"):
        training_data.validate(item.config.root, item.dataset_path)
    document(item.prepared_path, training_data.seal({"version": 1}, "dataset_id"))
    with pytest.raises(ValueError, match="exactly"):
        training_data.load_dataset(item.config.root, item.prepared_path)


def test_immutable_evidence_refuses_changed_bytes(tmp_path):
    path = tmp_path / "evidence.json"
    training_data.publish(path, {"v": 1})
    with pytest.raises(ValueError, match="preserve"):
        training_data.publish(path, {"v": 2})
    assert json.loads(path.read_bytes()) == {"v": 1}


def test_plan_replays_and_binds_environment_and_source(training_inputs, monkeypatch):
    item = training_inputs
    value, path = save_plan(item)
    assert training.load_plan(path) == value
    training.revalidate(item.config, value)
    assert save_plan(item) == (value, path)
    monkeypatch.setattr(
        training, "probe", lambda _: {"python": "changed", "packages": training.PINNED}
    )
    with pytest.raises(ValueError, match="changed"):
        training.revalidate(item.config, value)


@pytest.mark.parametrize(
    "part", ["checkpoint", "config", "python", "caption", "extra-config", "worker"]
)
def test_plan_rejects_changed_inputs(training_inputs, monkeypatch, part):
    item = training_inputs
    value, _ = save_plan(item)
    paths = {
        "checkpoint": item.config.comfyui_root / "models/checkpoints/fixture.safetensors",
        "config": item.config.root / "model-config/unet/config.json",
        "python": item.config.root / "environment/python.exe",
        "caption": item.config.root / "data/0.txt",
        "extra-config": item.config.root / "model-config/unet/extra.json",
    }
    if part == "worker":
        monkeypatch.setattr(training, "worker_sources", lambda: {"source": "changed"})
    else:
        paths[part].write_bytes(b"changed")
    with pytest.raises(ValueError, match="mismatch|undeclared|changed"):
        training.revalidate(item.config, value)


@pytest.mark.parametrize(
    "key,value",
    [
        ("steps", 0),
        ("steps", 257),
        ("steps", True),
        ("seed", 2**32),
        ("rank", 3),
        ("resolution", 1024),
        ("timeout_seconds", 3601),
        ("learning_rate_millionths", 0),
    ],
)
def test_parameter_bounds(training_inputs, key, value):
    item = training_inputs
    item.spec["parameters"][key] = value
    with pytest.raises(ValueError):
        save_plan(item)


def test_plan_requires_caption_trigger_and_declared_config(training_inputs):
    item = training_inputs
    item.spec["trigger"] = "missing"
    with pytest.raises(ValueError, match="caption"):
        save_plan(item)
    item.spec["trigger"] = "testtrigger"
    item.spec["model_config"]["files"][0]["path"] = []
    with pytest.raises(ValueError, match="text"):
        save_plan(item)


def test_cli_validation_and_malformed_snapshot(training_inputs, capsys):
    item = training_inputs
    assert (
        main(
            [
                "dataset",
                "validate",
                str(item.dataset_path),
                "--config",
                str(item.config.file),
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["counts"]["train"] == 2
    path = document(
        item.config.root / "bad-plan.json", training_data.seal({"version": 1}, "plan_id")
    )
    assert main(["training", "status", str(path), "--config", str(item.config.file), "--json"]) == 2
    assert "exactly" in json.loads(capsys.readouterr().out)["error"]


@pytest.fixture
def protocol(training_inputs, monkeypatch):
    item = training_inputs
    value, path = save_plan(item)
    monkeypatch.setattr(
        training,
        "ComfyUIClient",
        lambda _: SimpleNamespace(queue=lambda: {"queue_running": [], "queue_pending": []}),
    )
    monkeypatch.setattr(training, "gpu_snapshot", lambda: {"uuid": GPU, "free_bytes": 32 * 1024**3})
    monkeypatch.setattr(
        training,
        "host_memory",
        lambda: {"available_physical": 32 * 1024**3, "available_commit": 32 * 1024**3},
    )
    item.plan, item.plan_path = value, path
    item.registry = item.config.root / "leases"
    return item


def fake_job(monkeypatch, behavior):
    code = """
import json,sys,time
from pathlib import Path
sys.path.insert(0, sys.argv[3])
sys.path[:0]=json.loads(sys.argv[4])
from test_evaluation import weights as fixture_weights
from test_training import png
from itov.training_data import publish,seal
from itov.catalog import sha256
request=json.loads(Path(sys.argv[1]).read_bytes())
output=Path(request['output'])
behavior=sys.argv[2]
if behavior=='hang': time.sleep(60)
if behavior=='missing_result': sys.exit(0)
if behavior=='partial_result':
    (output/'result.json').write_bytes(b'{"version":')
    sys.exit(0)
weights=output/'fixture.safetensors'
raw = fixture_weights()
if behavior=='png_weights': raw=png(0)
if behavior=='truncated_weights': raw=raw[:-4]
weights.write_bytes(raw)
result={'version':1,'plan_id':request['plan']['plan_id'],
        'status':'failed' if behavior=='failure' else 'succeeded',
        'weights':{'path':weights.name,'sha256':sha256(weights.read_bytes())},
        'optimizer_steps':8,'training_loss_billionths':[100]*8,
        'changed_adapter_tensors':2,'trainable_parameters':64,
        'adapter_only':True,'export_reloaded':True,'max_memory_allocated':100,
        'max_memory_reserved':200,'quality_acceptance':'not_established',
        'purpose':'smoke','limits':'Protocol fixture, not trained weights','elapsed_ns':123}
rows,previews=[],[]
for index in range(2):
    rows.append({'sample':f'sample-{index+2}','noise_seed':100011+index,'loss_billionths':100})
    pair={'sample':f'sample-{index+2}','seed':200011+index,'prompt':'testtrigger geometry'}
    for role in ('baseline','candidate'):
        name=f'{role}-{index}.png'
        raw=png(index)
        (output/name).write_bytes(raw)
        pair[role]={'path':name,'sha256':sha256(raw)}
    previews.append(pair)
result.update(heldout_before=rows,heldout_after=rows,previews=previews)
if behavior=='incomplete_heldout': result['heldout_after']=[]
if behavior=='wrong_plan': result['plan_id']='0'*64
publish(output/'result.json',seal(result,'result_id'))
"""

    class FixtureJob(Job):
        def spawn(self, command, cwd):
            return super().spawn(
                [
                    sys.executable,
                    "-c",
                    code,
                    command[-1],
                    behavior,
                    str(Path(__file__).parent),
                    json.dumps([str(Path(entry).absolute()) for entry in sys.path]),
                ],
                cwd,
            )

    monkeypatch.setattr(training, "Job", FixtureJob)


@pytest.mark.skipif(os.name != "nt", reason="Native Windows training ownership")
@pytest.mark.parametrize(
    "behavior,boundary",
    [
        ("success", None),
        ("failure", "worker_execution"),
        ("hang", "worker_execution"),
        ("png_weights", "weights"),
        ("truncated_weights", "weights"),
        ("incomplete_heldout", "heldout_matrix"),
        ("missing_result", "result_publication"),
        ("partial_result", "result_publication"),
        ("wrong_plan", "result_binding"),
    ],
)
def test_owned_protocol_stops_worker_retains_attempt_and_never_retries(
    protocol, monkeypatch, behavior, boundary
):
    item = protocol
    fake_job(monkeypatch, behavior)
    if behavior == "hang":
        ticks = iter([0, 1000])
        monkeypatch.setattr(
            training, "time", SimpleNamespace(monotonic=lambda: next(ticks), sleep=time.sleep)
        )
    result = training.run(item.config, item.plan_path, GPU, registry=item.registry)
    assert result["status"] == ("artifacts_validated" if behavior == "success" else "failed")
    assert result["failure_boundary"] == boundary
    assert result["candidate_assessment"] == "not_performed_by_training"
    if behavior != "hang":
        assert result["worker_completion"] == "completed"
    assert process_state(result["worker"]) == "dead"
    assert device.status(GPU, root=item.registry)["status"] == "idle"
    assert training.status(item.config, item.plan_path) == result
    with pytest.raises(ValueError, match="already exists"):
        training.run(item.config, item.plan_path, GPU, registry=item.registry)
    if behavior == "hang":
        assert "time bound" in result["error"]


@pytest.mark.skipif(os.name != "nt", reason="Native Windows training ownership")
@pytest.mark.parametrize("reason", ["queue", "gpu", "host", "uuid", "batch"])
def test_startup_refusal_does_not_claim_run_or_device(protocol, monkeypatch, reason):
    item = protocol
    if reason == "queue":
        monkeypatch.setattr(
            training,
            "ComfyUIClient",
            lambda _: SimpleNamespace(queue=lambda: {"queue_running": [1], "queue_pending": []}),
        )
    elif reason == "gpu":
        monkeypatch.setattr(training, "gpu_snapshot", lambda: {"uuid": GPU, "free_bytes": 0})
    elif reason == "host":
        monkeypatch.setattr(
            training, "host_memory", lambda: {"available_physical": 0, "available_commit": 0}
        )
    elif reason == "batch":
        import sqlite3

        folder = item.config.root / "state/batches"
        folder.mkdir()
        with sqlite3.connect(folder / "execution.sqlite3") as db:
            db.execute("CREATE TABLE runs(plan_id TEXT,status TEXT)")
            db.execute("INSERT INTO runs VALUES('held','paused')")
    with pytest.raises(ValueError):
        training.run(
            item.config,
            item.plan_path,
            GPU + "wrong" if reason == "uuid" else GPU,
            registry=item.registry,
        )
    assert not training.run_folder(item.config, item.plan).exists()
    assert not item.registry.exists()


@pytest.mark.skipif(os.name != "nt", reason="Native Windows training ownership")
def test_run_directory_race_preserves_original_error_and_existing_record(protocol, monkeypatch):
    item = protocol
    folder = training.run_folder(item.config, item.plan)
    prior = b'{"existing":"preserve this attempt"}\n'
    failure = FileExistsError("run directory appeared during startup")
    mkdir = Path.mkdir
    stopped = []

    def raced_directory(path, *args, **kwargs):
        if path == folder:
            mkdir(path, parents=True)
            (path / "run.json").write_bytes(prior)
            raise failure
        return mkdir(path, *args, **kwargs)

    class ObservedJob(Job):
        def stop(self):
            super().stop()
            stopped.append(True)

    monkeypatch.setattr(Path, "mkdir", raced_directory)
    monkeypatch.setattr(training, "Job", ObservedJob)
    with pytest.raises(FileExistsError) as raised:
        training.run(item.config, item.plan_path, GPU, registry=item.registry)
    assert raised.value is failure
    assert stopped == [True]
    assert (folder / "run.json").read_bytes() == prior
    assert not (folder / "request.json").exists()
    assert device.status(GPU, root=item.registry)["status"] == "idle"


@pytest.mark.skipif(os.name != "nt", reason="Native Windows training ownership")
def test_recover_requires_dead_controller_and_does_not_restart(protocol, monkeypatch):
    item = protocol
    fake_job(monkeypatch, "success")
    result = training.run(item.config, item.plan_path, GPU, registry=item.registry)
    body = {
        k: v
        for k, v in training.read_record(item.config, item.plan_path).items()
        if k != "record_id"
    }
    body.update(status="running", owner=process_identity(os.getpid()))
    folder = training.run_folder(item.config, item.plan)
    training._record(folder, body)
    with pytest.raises(ValueError, match="still alive"):
        training.recover(item.config, item.plan_path, registry=item.registry)
    body["owner"]["created"] -= 1
    training._record(folder, body)
    recovered = training.recover(item.config, item.plan_path, registry=item.registry)
    assert recovered["status"] == "failed" and "no retraining" in recovered["error"]
    assert recovered["worker"] == result["worker"]


@pytest.mark.skipif(os.name != "nt", reason="Native Windows training ownership")
@pytest.mark.parametrize("case", ["valid", "truncated", "stale", "uncertain_owner"])
def test_interrupted_final_publication_recovers_without_worker_relaunch(
    protocol, monkeypatch, case
):
    item = protocol
    fake_job(monkeypatch, "success")
    atomic_write = training._atomic_write

    def interrupt_final(path, raw):
        if path.name == "run.json" and json.loads(raw)["status"] == "artifacts_validated":
            raise OSError("Injected interruption before terminal record replacement")
        return atomic_write(path, raw)

    monkeypatch.setattr(training, "_atomic_write", interrupt_final)
    with pytest.raises(ValueError, match="Injected interruption"):
        training.run(item.config, item.plan_path, GPU, registry=item.registry)
    monkeypatch.setattr(training, "_atomic_write", atomic_write)
    folder = training.run_folder(item.config, item.plan)
    interrupted = training.read_record(item.config, item.plan_path)
    assert interrupted["status"] == "validating"
    assert process_state(interrupted["worker"]) == "dead"
    assert device.status(GPU, root=item.registry)["status"] == "idle"
    original_result = (folder / "result.json").read_bytes()
    # A mismatched native creation time proves this recorded controller has exited.
    interrupted.pop("record_id")
    interrupted["owner"]["created"] -= 1
    original_record = training._record(folder, interrupted)
    if case == "truncated":
        (folder / "result.json").write_bytes(b'{"version":')
    elif case == "stale":
        (item.config.root / "environment/python.exe").write_bytes(b"changed")
    elif case == "uncertain_owner":
        monkeypatch.setattr(training, "process_state", lambda _: "unknown")
        with pytest.raises(ValueError, match="still alive"):
            training.recover(item.config, item.plan_path, registry=item.registry)
        assert training.read_record(item.config, item.plan_path) == original_record
        return

    def no_spawn(*args, **kwargs):
        pytest.fail("Recovery must never construct a worker")

    monkeypatch.setattr(training, "Job", no_spawn)
    recovered = training.recover(item.config, item.plan_path, registry=item.registry)
    assert recovered["worker"] == original_record["worker"]
    assert recovered["status"] == ("artifacts_validated" if case == "valid" else "failed")
    assert (
        recovered["failure_boundary"]
        == {"valid": None, "truncated": "result_publication", "stale": "input_freshness"}[case]
    )
    assert (
        json.loads((folder / "records" / f"{original_record['record_id']}.json").read_bytes())
        == original_record
    )
    if case != "truncated":
        assert (folder / "result.json").read_bytes() == original_result
    assert training.status(item.config, item.plan_path) == recovered
    with pytest.raises(ValueError, match="already exists"):
        # Bypass a stale environment so the attempt's no-retraining guard is exercised.
        monkeypatch.setattr(training, "revalidate", lambda *args: None)
        training.run(item.config, item.plan_path, GPU, registry=item.registry)


def test_ml_dependencies_are_not_imported_by_core():
    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from itov import training,evaluation; "
            "assert not any(x in sys.modules for x in ('torch','diffusers','peft','PIL'))",
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(os.name != "nt", reason="Native Windows training ownership")
def test_killed_controller_recovers_published_result_and_releases_lease(protocol):
    import subprocess

    item = protocol
    signal = item.config.root / "validation-published"
    script = """
import json,sys,time
sys.path[:0]=json.loads(sys.argv[6])
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,sys.argv[1])
import pytest
from test_training import fake_job,GPU
from itov import training
from itov.config import load_config
patch=pytest.MonkeyPatch()
fake_job(patch,'success')
training.probe=lambda _: {'python':'fixture','packages':training.PINNED}
training.ComfyUIClient=lambda _: SimpleNamespace(
    queue=lambda: {'queue_running':[],'queue_pending':[]})
training.gpu_snapshot=lambda: {'uuid':GPU,'free_bytes':32*1024**3}
training.host_memory=lambda: {'available_physical':32*1024**3,'available_commit':32*1024**3}
original=training._record
def pause_after_publication(folder,body):
    value=original(folder,body)
    if body['status']=='validating' and body['artifact_validation']=='validating':
        Path(sys.argv[5]).write_text('ready')
        time.sleep(60)
    return value
training._record=pause_after_publication
training.run(load_config(Path(sys.argv[2])),Path(sys.argv[3]),GPU,registry=Path(sys.argv[4]))
"""
    child = subprocess.Popen(
        [
            sys._base_executable,
            "-c",
            script,
            str(Path(__file__).parent),
            str(item.config.file),
            str(item.plan_path),
            str(item.registry),
            str(signal),
            json.dumps([str(Path(entry).absolute()) for entry in sys.path]),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 20
        while not signal.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        if not signal.exists() and child.poll() is not None:
            stdout, stderr = child.communicate(timeout=5)
            pytest.fail(f"Child did not reach validation: {stdout}\n{stderr}")
        assert signal.exists(), "Child did not reach the durable validation boundary"
        pending = training.read_record(item.config, item.plan_path)
        assert pending["owner"]["pid"] == child.pid
        assert process_state(pending["worker"]) == "dead"
        assert device.status(GPU, root=item.registry)["status"] == "held"
    finally:
        if child.poll() is None:
            child.kill()
        stdout, stderr = child.communicate(timeout=20)
    assert not stdout and not stderr
    assert process_state(pending["owner"]) == "dead"
    recovered = training.recover(item.config, item.plan_path, registry=item.registry)
    assert recovered["status"] == "artifacts_validated"
    assert recovered["worker"] == pending["worker"]
    assert device.status(GPU, root=item.registry)["status"] == "idle"
    assert training.status(item.config, item.plan_path) == recovered


@pytest.mark.skipif(os.name != "nt", reason="Native Windows training ownership")
def test_interrupt_during_weight_validation_reports_its_boundary(protocol, monkeypatch):
    from itov import training_results

    item = protocol
    fake_job(monkeypatch, "success")

    def interrupt(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(training_results, "inspect_weights", interrupt)
    observed = training.run(item.config, item.plan_path, GPU, registry=item.registry)
    assert observed["status"] == "failed"
    assert observed["failure_boundary"] == "weights"
    assert observed["worker_completion"] == "completed"
    assert observed["artifact_validation"] == "failed"
    assert observed["error"] == "Interrupted"
    assert process_state(observed["worker"]) == "dead"
    assert device.status(GPU, root=item.registry)["status"] == "idle"
