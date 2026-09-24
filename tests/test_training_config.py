"""Configuration, order and evidence contracts; synthetic fixtures are not model acceptance."""

import copy
import subprocess
import sys

import pytest
from quality_fixtures import curated_inputs as curated_inputs
from test_evaluation import complete, save_result
from test_training import document, png, save_plan, write
from test_training import training_inputs as training_inputs

from itov import (
    evaluation,
    evaluation_runtime,
    quality,
    training,
    training_config,
    training_results,
)
from itov.catalog import canonical_bytes, sha256


def configured(spec, **settings):
    value = copy.deepcopy(spec)
    value.update(
        version=3,
        profile=training_config.PROFILE,
        optimization={
            "micro_batch_size": 1,
            "accumulation_steps": 2,
            "sampling": "shuffle_epoch",
            "schedule": "linear_warmup_decay",
            "warmup_steps": 2,
            "validation_every_steps": 3,
            "precision": training_config.PRECISION,
            **settings,
        },
    )
    return value


def metrics():
    return {
        "cuda_allocated_bytes": 100,
        "cuda_reserved_bytes": 200,
        "cuda_peak_allocated_bytes": 100,
        "cuda_peak_reserved_bytes": 200,
        "host_available_physical_bytes": 400,
        "host_available_commit_bytes": 500,
    }


def trace_for(plan):
    effective = plan["optimization"]
    return {
        "version": 1,
        "plan_id": plan["plan_id"],
        "config": effective["config"],
        "precision": {
            "frozen_unet_dtype": "torch.bfloat16",
            "adapter_dtype": "torch.float32",
            "gradient_dtype": "torch.float32",
            "vae_dtype": "torch.float32",
            "autocast_dtype": "torch.bfloat16",
            "loss_dtype": "torch.float32",
            "tf32": False,
            "adapter_tensors": 2,
        },
        "steps": [
            {
                **row,
                "micro_loss_billionths": [100] * len(row["micro_batches"]),
                "loss_billionths": 100,
                "gradient_norm_billionths": 50,
                "gradient_tensors": 2,
                "optimizer_state_step": row["step"],
                "optimizer_state_fp32_finite": True,
                "adapter_fp32_finite": True,
                "elapsed_ns": 1,
                "resources": metrics(),
            }
            for row in effective["steps"]
        ],
        "validation": [
            {
                "step": step,
                "losses": [
                    {**row, "loss_billionths": 100} for row in effective["validation_samples"]
                ],
                "elapsed_ns": 1,
                "resources": metrics(),
            }
            for step in effective["validation_steps"]
        ],
    }


def save_trace(item, trace):
    path = document(item.folder / "optimization.json", trace)
    item.result["optimization"] = {"path": "optimization.json", "sha256": sha256(path.read_bytes())}
    document(item.folder / "optimization/effective.json", item.plan["optimization"])
    document(item.folder / "optimization/precision.json", trace["precision"])
    for kind, rows in (("step", trace["steps"]), ("validation", trace["validation"])):
        for row in rows:
            document(item.folder / f"optimization/{kind}-{row['step']:06d}.json", row)
    save_result(item)


@pytest.fixture
def completed_config(curated_inputs):
    item = curated_inputs
    item.spec = configured(item.spec)
    complete(item, "training")
    item.result["quality_matrix"] = [
        {**row, "image": write(item.folder, f"quality-{index}.png", png(index))}
        for index, row in enumerate(quality.expected(item.suite))
    ]
    item.trace = trace_for(item.plan)
    save_trace(item, item.trace)
    return item


@pytest.mark.parametrize("batch,accumulation", [(1, 1), (1, 2), (2, 1)])
@pytest.mark.parametrize("sampling", ["sequential", "shuffle_epoch"])
@pytest.mark.parametrize("schedule,warmup", [("constant", 0), ("linear_warmup_decay", 2)])
def test_supported_configs_plan_exact_full_order(
    curated_inputs, batch, accumulation, sampling, schedule, warmup
):
    item = curated_inputs
    item.spec = configured(
        item.spec,
        micro_batch_size=batch,
        accumulation_steps=accumulation,
        sampling=sampling,
        schedule=schedule,
        warmup_steps=warmup,
    )
    plan, path = save_plan(item)
    assert training.load_plan(path) == plan
    training.revalidate(item.config, plan)
    effective = plan["optimization"]
    rows = [r for s in effective["steps"] for b in s["micro_batches"] for r in b]
    assert len(rows) == 8 * batch * accumulation
    assert [r["position"] for r in rows] == list(range(len(rows)))
    assert [r["noise_seed"] for r in rows] == list(range(11, 11 + len(rows)))
    assert {r["sample"] for r in rows} == {"sample-0", "sample-1"}
    for i in range(0, len(rows), 2):
        assert {r["sample"] for r in rows[i : i + 2]} == {"sample-0", "sample-1"}
    assert effective["validation_steps"] == [0, 3, 6, 8]
    assert effective["config"]["effective_batch_size"] == batch * accumulation
    assert {"training_config.py", "training_optimization.py"} <= plan["worker_sources"].keys()


def test_epoch_wrap_sampling_is_stable_and_independent_of_input_order(curated_inputs):
    spec = configured(curated_inputs.spec)
    spec["parameters"]["seed"] = 2**32 - 1
    samples = [{"id": key, "split": "train"} for key in ("c", "a", "b")]
    samples.append({"id": "heldout", "split": "validation"})
    first = training_config.resolve(spec, samples)
    assert first == training_config.resolve(spec, list(reversed(samples)))
    rows = [r for s in first["steps"] for batch in s["micro_batches"] for r in batch]
    assert [r["noise_seed"] for r in rows[:3]] == [2**32 - 1, 0, 1]
    for index in range(0, 15, 3):
        assert {r["sample"] for r in rows[index : index + 3]} == {"a", "b", "c"}
    # Fixed digest ordering, not interpreter random state or dictionary insertion order.
    assert [r["sample"] for r in rows[:3]] == sorted(
        ("a", "b", "c"),
        key=lambda k: (sha256(canonical_bytes({"seed": 2**32 - 1, "epoch": 0, "sample": k})), k),
    )


@pytest.mark.parametrize(
    "key,value",
    [
        ("micro_batch_size", True),
        ("micro_batch_size", 0),
        ("micro_batch_size", 3),
        ("accumulation_steps", 0),
        ("accumulation_steps", 3),
        ("sampling", "random"),
        ("schedule", "cosine"),
        ("warmup_steps", 0),
        ("warmup_steps", 8),
        ("validation_every_steps", 0),
        ("validation_every_steps", 9),
        ("precision", "fp16"),
        ("extra", 1),
    ],
)
def test_unsupported_or_ambiguous_configuration_refused(curated_inputs, key, value):
    item = curated_inputs
    item.spec = configured(item.spec, **{key: value})
    with pytest.raises(ValueError):
        save_plan(item)


def test_batch_accumulation_product_and_constant_warmup_refused(curated_inputs):
    item = curated_inputs
    for settings in ({"micro_batch_size": 2}, {"schedule": "constant"}):
        item.spec = configured(curated_inputs.spec, **settings)
        with pytest.raises(ValueError):
            save_plan(item)


def test_batch_requires_enough_training_samples(curated_inputs):
    spec = configured(curated_inputs.spec, micro_batch_size=2, accumulation_steps=1)
    with pytest.raises(ValueError, match="sample count"):
        training_config.resolve(
            spec, [{"id": "a", "split": "train"}, {"id": "b", "split": "validation"}]
        )


def test_schedule_rates_have_defined_first_and_last_update(curated_inputs):
    spec = configured(curated_inputs.spec)
    result = training_config.resolve(spec, curated_inputs.dataset["samples"])
    assert [r["learning_rate_trillionths"] for r in result["steps"]] == [
        50000000,
        100000000,
        100000000,
        83333333,
        66666666,
        50000000,
        33333333,
        16666666,
    ]


def test_configured_result_integrates_status_assessment_packet_and_export(completed_config):
    item = completed_config
    status = training.status(item.config, item.plan_path)
    assert status["status"] == "artifacts_validated" and "optimization" in status["artifacts"]
    assert evaluation.assess(item.config, item.plan_path)["technical_pass"]
    assert evaluation.candidate(item.config, item.plan_path)["entry"]
    assert quality.packet(item.config, item.plan_path)["scope"] == "quality_review_pending"


def test_deployed_evaluation_accepts_configured_curated_lineage(completed_config):
    item = completed_config
    specification = {
        "version": 1,
        "id": "configured-deployment",
        "training_plan": {
            "path": item.plan_path.relative_to(item.config.root).as_posix(),
            "sha256": sha256(item.plan_path.read_bytes()),
        },
        "sampler": {
            "steps": 20,
            "cfg_milli": 7000,
            "sampler_name": "dpmpp_2m",
            "scheduler": "karras",
        },
        "width": 512,
        "height": 512,
        "strength_milli": 1000,
    }
    plan, suite, candidate = evaluation_runtime._context(item.config, specification)
    assert plan["plan_id"] == item.plan["plan_id"] and suite == item.suite
    assert candidate["plan_id"] == item.plan["plan_id"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda t: t["steps"].pop(),
        lambda t: t["steps"][0]["micro_batches"][0][0].update(sample="sample-2"),
        lambda t: t["steps"][0]["micro_batches"][0][0].update(position=False),
        lambda t: t["steps"][0].update(learning_rate_trillionths=1),
        lambda t: t["steps"][0].update(gradient_tensors=0),
        lambda t: t["steps"][0].update(gradient_norm_billionths=-1),
        lambda t: t["steps"][0].update(optimizer_state_step=0),
        lambda t: t["steps"][0].update(optimizer_state_fp32_finite=False),
        lambda t: t["steps"][0].update(adapter_fp32_finite=False),
        lambda t: t["steps"][0]["micro_loss_billionths"].pop(),
        lambda t: t["steps"][0]["micro_loss_billionths"].__setitem__(0, 500),
        lambda t: t["steps"][0]["resources"].update(cuda_reserved_bytes=0),
        lambda t: t["steps"][0]["resources"].update(cuda_peak_allocated_bytes=201),
        lambda t: t["validation"][-1]["resources"].update(cuda_peak_reserved_bytes=300),
        lambda t: t["validation"].pop(1),
        lambda t: t["validation"][1].update(step=2),
        lambda t: t["validation"][1]["losses"][0].update(noise_seed=0),
        lambda t: t["validation"][1]["losses"][0].update(loss_billionths=True),
        lambda t: t["validation"][-1]["losses"][0].update(loss_billionths=50),
        lambda t: t["precision"].update(gradient_dtype="torch.bfloat16"),
        lambda t: t["precision"].update(tf32=0),
        lambda t: t["config"].update(effective_batch_size=4),
    ],
)
def test_resealed_optimization_trace_cannot_hide_wrong_behavior(completed_config, mutation):
    item = completed_config
    trace = copy.deepcopy(item.trace)
    mutation(trace)
    save_trace(item, trace)
    observed = training.status(item.config, item.plan_path)
    assert (
        observed["status"] == "failed" and observed["failure_boundary"] == "optimization_evidence"
    )


def test_partial_or_stale_optimization_events_refused(completed_config):
    item = completed_config
    path = item.folder / "optimization/step-000002.json"
    raw = path.read_bytes()
    path.write_bytes(b"partial")
    with pytest.raises(training_results.ResultValidationError, match="event differs"):
        evaluation.assess(item.config, item.plan_path)
    path.write_bytes(raw)
    path.unlink()
    assert (
        training.status(item.config, item.plan_path)["failure_boundary"] == "optimization_evidence"
    )


def test_resealed_plan_cannot_change_sample_order(completed_config):
    item = completed_config
    item.plan["optimization"]["steps"][0]["micro_batches"][0][0]["sample"] = "sample-3"
    with pytest.raises(training_results.ResultValidationError, match="Planned optimization"):
        training_results.validate(item.config, item.plan, item.folder)


def test_config_modules_keep_core_free_of_optional_torch():
    code = (
        "import sys; from itov import training_config,training_optimization; "
        "assert not {'torch','numpy','PIL','diffusers'} & set(sys.modules)"
    )
    run = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
