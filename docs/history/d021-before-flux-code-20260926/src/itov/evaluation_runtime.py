"""Frozen deployed SDXL evaluation plans using the shared owned-job protocol."""

from __future__ import annotations

import sqlite3
from contextlib import closing, nullcontext
from pathlib import Path

from itov import evaluation, quality, training
from itov.batch_execution import _lock, abandon_reserved_plan, run_reserved_plan
from itov.catalog import (
    canonical_bytes,
    identifier,
    integer,
    object_fields,
    read_document,
    require,
    sha256,
)
from itov.comfyui import parse_json
from itov.execution_store import report as execution_report
from itov.image_media import image_contract, image_tools, verify_image
from itov.inference import _copy_lora
from itov.owned_jobs import job_path, read_owned
from itov.qualification import _file, json_text, qualify_graphs, safe_path
from itov.training_data import check_seal, file_ref, publish, seal
from itov.training_results import boundary

SCOPE = "deployed_evaluation_plan"
RUNTIME_SOURCES = (
    "execution.py",
    "comfy/sd.py",
    "comfy/lora.py",
    "comfy/lora_convert.py",
    "comfy/model_patcher.py",
    "comfy/samplers.py",
    "comfy/sample.py",
    "comfy/k_diffusion/sampling.py",
)


def validate_spec(value):
    require(
        isinstance(value, dict)
        and type(value.get("version")) is int
        and value["version"] in (1, 2),
        "Unsupported evaluation version",
    )
    extra = {"strength_milli"} if value["version"] == 1 else {"corpus", "mode"}
    object_fields(
        value,
        {"version", "id", "training_plan", "sampler", "width", "height"} | extra,
        "deployed evaluation specification",
    )
    identifier(value["id"], "evaluation id")
    image_contract({key: value[key] for key in ("width", "height")})
    if value["version"] == 1:
        integer(value["strength_milli"], "adapter strength", minimum=1)
        require(value["strength_milli"] <= 1000, "Evaluation strength must be 1..1000 milli")
    else:
        object_fields(value["corpus"], {"path", "sha256"}, "frozen corpus reference")
        require(value["mode"] in {"baseline", "comparison"}, "Invalid corpus evaluation mode")
    sampler = value["sampler"]
    object_fields(
        sampler, {"steps", "cfg_milli", "sampler_name", "scheduler"}, "evaluation sampler"
    )
    integer(sampler["steps"], "sampler steps", minimum=1)
    integer(sampler["cfg_milli"], "sampler CFG", minimum=1)
    require(
        sampler["steps"] <= 50 and sampler["cfg_milli"] <= 15000,
        "Evaluation sampler budget exceeded",
    )
    require(
        sampler["sampler_name"] == "dpmpp_2m" and sampler["scheduler"] == "karras",
        "Evaluation currently supports explicit dpmpp_2m/karras settings",
    )
    object_fields(value["training_plan"], {"path", "sha256"}, "training plan reference")
    return value


def _context(config, spec, *, save=False):
    validate_spec(spec)
    path, _ = file_ref(config.root, spec["training_plan"])
    trained = training.load_plan(path)
    require(
        trained["specification"]["version"] in (2, 3, 4),
        "Evaluation requires a frozen v2/v3/v4 training suite",
    )
    curated, suite = quality.qualification(config.root, trained["specification"])
    if spec["version"] == 2:
        from itov import evaluation_corpus

        corpus_path, _ = file_ref(config.root, spec["corpus"])
        frozen = evaluation_corpus.inspect(config, corpus_path)
        require(
            curated["dataset_id"] == frozen["dataset_id"]
            and suite["trigger"] == frozen["specification"]["suite"]["trigger"],
            "Corpus dataset or trigger differs",
        )
        suite = frozen["specification"]["suite"]
    candidate = evaluation.candidate(config, path, save=save)
    return trained, suite, candidate


def _definition(spec, trained_id, checkpoint, suite, candidate):
    validate_spec(spec)
    image = {key: spec[key] for key in ("width", "height")}
    deployment = {
        "loader_name": f"itov_evaluation_{candidate['export']['sha256']}.safetensors",
        "asset": candidate["entry"]["asset"],
    }
    definition_id = sha256(canonical_bytes({"spec": spec, "candidate": candidate, "suite": suite}))
    jobs = []
    from itov.evaluation_cases import conditions

    require(suite["version"] == spec["version"], "Evaluation suite version differs")
    expected = [
        condition.to_dict()
        for condition in conditions(suite, baseline=spec.get("mode") == "baseline")
    ]
    for index, condition in enumerate(expected):
        adapter = condition["role"].startswith("adapter_")
        graph = {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": checkpoint["loader_name"]},
                "_meta": {"itov_asset_sha256": checkpoint["sha256"]},
            },
            "3": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["1", 1], "text": condition["prompt"]},
            },
            "4": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["1", 1], "text": condition["negative_prompt"]},
            },
            "5": {"class_type": "EmptyLatentImage", "inputs": {**image, "batch_size": 1}},
            "6": {
                "class_type": "KSampler",
                "inputs": {
                    "model": ["2" if adapter else "1", 0],
                    "seed": condition["seed"],
                    "steps": spec["sampler"]["steps"],
                    "cfg": spec["sampler"]["cfg_milli"] / 1000,
                    "sampler_name": spec["sampler"]["sampler_name"],
                    "scheduler": spec["sampler"]["scheduler"],
                    "positive": ["3", 0],
                    "negative": ["4", 0],
                    "latent_image": ["5", 0],
                    "denoise": 1,
                },
            },
            "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["1", 2]}},
            "8": {
                "class_type": "SaveImage",
                "inputs": {
                    "images": ["7", 0],
                    "filename_prefix": f"itov/evaluation/{definition_id}/{index:03d}",
                },
                "_meta": {"itov_image": image},
            },
        }
        if adapter:
            graph["2"] = {
                "class_type": "LoraLoaderModelOnly",
                "inputs": {
                    "model": ["1", 0],
                    "lora_name": deployment["loader_name"],
                    "strength_model": condition.get("strength_milli", spec.get("strength_milli"))
                    / 1000,
                },
                "_meta": {"itov_asset_sha256": deployment["asset"]["sha256"]},
            }
        encoded = json_text(graph)
        jobs.append(
            {
                "index": index,
                **condition,
                "preset": "evaluation",
                "workflow_json": encoded,
                "workflow_sha256": sha256(encoded.encode()),
                "loras": [{"loader_name": deployment["loader_name"], "asset": deployment["asset"]}]
                if adapter
                else [],
            }
        )
    return {
        "version": 1,
        "scope": SCOPE,
        "specification": spec,
        "training_plan_id": trained_id,
        "checkpoint": checkpoint,
        "candidate": candidate,
        "suite": suite,
        "deployment": deployment,
        "jobs": jobs,
        "request": {
            "bindings": {
                "evaluation": {
                    "seed_inputs": [{"node": "6", "class_type": "KSampler", "input": "seed"}]
                }
            }
        },
    }


def _runtime(config, value, *, timeout):
    receipt = qualify_graphs(config, value, timeout=timeout, extra_sources=RUNTIME_SOURCES)
    receipt.pop("qualification_id")
    receipt.pop("plan_id")
    return {**receipt, "image_decoder": image_tools(), "profile": "stock-sdxl-evaluation-v1"}


def plan(config, spec_path, *, save=False, timeout=3):
    spec = validate_spec(parse_json(read_document(spec_path)))
    trained, suite, candidate = _context(config, spec, save=save)
    body = _definition(
        spec, trained["plan_id"], trained["specification"]["checkpoint"], suite, candidate
    )
    deployment = body["deployment"]
    destination = safe_path(config.comfyui_root / "models/loras", deployment["loader_name"])
    if save:
        source, _ = file_ref(config.root, deployment["asset"])
        _copy_lora(source, destination, deployment["asset"]["sha256"])
    require(
        destination.is_file(), "Candidate is not deployed; use evaluation plan --save to stage it"
    )
    require(
        _file(destination)["sha256"] == deployment["asset"]["sha256"], "Deployed candidate differs"
    )
    draft = seal(body, "plan_id")
    value = seal({**body, "runtime": _runtime(config, draft, timeout=timeout)}, "plan_id")
    if save:
        publish(safe_path(config.root, f"state/evaluation/plans/{value['plan_id']}.json"), value)
    return value


def load_plan(path):
    with boundary("evaluation_plan"):
        value = check_seal(parse_json(read_document(path)), "plan_id")
        object_fields(
            value,
            {
                "version",
                "scope",
                "specification",
                "training_plan_id",
                "checkpoint",
                "candidate",
                "suite",
                "deployment",
                "jobs",
                "request",
                "runtime",
                "plan_id",
            },
            "deployed evaluation plan",
        )
        expected = _definition(
            value["specification"],
            value["training_plan_id"],
            value["checkpoint"],
            value["suite"],
            value["candidate"],
        )
        require(
            {k: v for k, v in value.items() if k not in {"runtime", "plan_id"}} == expected,
            "Evaluation plan graph/coverage bindings differ",
        )
        return value


def _fresh_inputs(config, value):
    trained, suite, candidate = _context(config, value["specification"])
    expected = _definition(
        value["specification"],
        trained["plan_id"],
        trained["specification"]["checkpoint"],
        suite,
        candidate,
    )
    require(
        {k: v for k, v in value.items() if k not in {"runtime", "plan_id"}} == expected,
        "Evaluation candidate, suite or training inputs changed",
    )
    file_ref(config.root, value["deployment"]["asset"])
    path = safe_path(config.comfyui_root / "models/loras", value["deployment"]["loader_name"])
    require(
        _file(path)["sha256"] == value["deployment"]["asset"]["sha256"],
        "Deployed candidate differs",
    )


def _receipt(value):
    return seal({**value["runtime"], "plan_id": value["plan_id"]}, "qualification_id")


def _qualify(config, value, *, timeout):
    _fresh_inputs(config, value)
    require(
        _runtime(config, value, timeout=timeout) == value["runtime"],
        "Evaluation runtime, graph schema or asset identity changed; no new submission",
    )
    return _receipt(value)


def run(
    config, path, *, resume=False, prompt_id=None, timeout=3, wait_timeout=300, poll_interval=1
):
    value = load_plan(path)
    run_reserved_plan(
        config,
        value,
        qualification=None if resume else _receipt(value),
        resume=resume,
        prompt_id=prompt_id,
        timeout=timeout,
        wait_timeout=wait_timeout,
        poll_interval=poll_interval,
        qualify_plan=_qualify,
        submission_guard=lambda config, plan: nullcontext(),
    )
    return status(config, path)


def abandon(config, path):
    value = load_plan(path)
    abandon_reserved_plan(config, value)
    return status(config, path)


def status(config, path):
    value = load_plan(path)
    database = safe_path(config.root, "state/batches/execution.sqlite3")
    with _lock(config):
        if not database.is_file():
            require(not (database.parent / "initialized").exists(), "Execution database is missing")
            observed = {"status": "not_started", "ok": False, "jobs": [], "error": None}
        else:
            with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
                db.row_factory = sqlite3.Row
                started = db.execute(
                    "SELECT 1 FROM runs WHERE plan_id = ?", (value["plan_id"],)
                ).fetchone()
                observed = (
                    execution_report(db, config, value)
                    if started
                    else {"status": "not_started", "ok": False, "jobs": [], "error": None}
                )
        matrix = []
        for index, job in enumerate(value["jobs"]):
            row = {
                key: job[key]
                for key in ("index", "case_id", "seed", "role", "prompt", "negative_prompt")
            }
            if "strength_milli" in job:
                row["strength_milli"] = job["strength_milli"]
            row["status"] = "reserved" if observed["jobs"] else "not_started"
            record_path = job_path(config, value["plan_id"], index)
            row["record_path"] = str(record_path)
            if observed["jobs"]:
                durable = observed["jobs"][index]
                if durable["status"] != "reserved" or record_path.exists():
                    record = read_owned(config, value, job)
                    require(isinstance(record.get("status"), str), "Invalid evaluation job status")
                    require(
                        durable["prompt_id"] is None
                        or durable["prompt_id"] == record.get("prompt_id"),
                        "Evaluation prompt differs from durable ownership",
                    )
                    require(
                        record["status"] != "prepared"
                        or durable["status"] in {"prepared", "reserved"},
                        "Evaluation job moved backwards; preserve and inspect",
                    )
                    row.update(
                        status=record["status"],
                        request_id=record["request_id"],
                        prompt_id=record.get("prompt_id"),
                        error=record.get("error"),
                        record_sha256=sha256(record_path.read_bytes()),
                    )
                    if record["status"] == "succeeded":
                        try:
                            require(
                                isinstance(record.get("artifacts"), list)
                                and len(record["artifacts"]) == 1,
                                "Expected exactly one evaluation artifact",
                            )
                            artifact = record["artifacts"][0]
                            require(
                                isinstance(artifact, dict)
                                and isinstance(artifact.get("path"), str),
                                "Invalid evaluation artifact record",
                            )
                            output = Path(artifact["path"])
                            expected_parent = config.root / f"output/jobs/{record['request_id']}"
                            require(
                                output.parent == expected_parent and artifact.get("node_id") == "8",
                                "Evaluation artifact ownership differs",
                            )
                            relative = output.relative_to(config.root).as_posix()
                            file_ref(
                                config.root, {"path": relative, "sha256": artifact.get("sha256")}
                            )
                            decoded = verify_image(
                                output, {k: value["specification"][k] for k in ("width", "height")}
                            )
                            require(
                                decoded["decoder_sha256"]
                                == value["runtime"]["image_decoder"]["sha256"],
                                "Image decoder changed",
                            )
                            row.update(
                                image={"path": relative, "sha256": artifact["sha256"]},
                                decoded=decoded,
                            )
                        except (OSError, ValueError) as error:
                            row.update(status="artifact_invalid", error=str(error))
            matrix.append(row)
    complete = observed["status"] == "succeeded" and all(
        row["status"] == "succeeded" for row in matrix
    )
    invalid = any(row["status"] == "artifact_invalid" for row in matrix)
    next_action = {
        "not_started": "Run evaluation run with this plan.",
        "succeeded": "Run evaluation replay --save, then inspect quality.",
        "abandoned": "This plan is retired. Preserve its evidence; use a new specification id.",
        "failed": "Inspect failed job records; abandon this plan before a new comparison.",
    }.get(
        observed["status"],
        "Inspect job records; evaluation resume observes accepted work without resubmission.",
    )
    if invalid:
        next_action = (
            "Preserve and inspect the invalid artifact; quality acceptance is unavailable."
        )
    return {
        "scope": "deployed_evaluation_status",
        "plan_id": value["plan_id"],
        "candidate_id": value["candidate"]["candidate_id"],
        "recorded_status": observed["status"],
        "status": "artifact_invalid" if invalid else observed["status"],
        "ok": complete,
        "error": observed["error"],
        "succeeded": sum(row["status"] == "succeeded" for row in matrix),
        "total": len(matrix),
        "matrix": matrix,
        "quality_acceptance": "not_established",
        "next_action": next_action,
    }


def replay(config, path, *, save=False):
    value = load_plan(path)
    observed = status(config, path)
    require(observed["ok"], "Evaluation matrix is incomplete or invalid; inspect evaluation status")
    _fresh_inputs(config, value)
    for item in value["runtime"]["files"]:
        require(_file(Path(item["path"])) == item, "Evaluation runtime or model bytes changed")
    require(image_tools() == value["runtime"]["image_decoder"], "Image decoder changed")
    result = seal(
        {
            "version": 1,
            "scope": "deployed_evaluation_technical_report",
            "plan_id": value["plan_id"],
            "candidate": value["candidate"],
            "deployment": value["deployment"],
            "suite": value["suite"],
            "runtime": value["runtime"],
            "sampler": value["specification"]["sampler"],
            **(
                {"strength_milli": value["specification"]["strength_milli"]}
                if value["specification"]["version"] == 1
                else {
                    "mode": value["specification"]["mode"],
                    "corpus": value["specification"]["corpus"],
                    "strengths_milli": value["suite"]["strengths_milli"],
                }
            ),
            "matrix": observed["matrix"],
            "technical_pass": True,
            "quality_acceptance": "not_established",
            "limits": (
                "Complete owned runtime matrix and decoded PNGs; no quality verdict, promotion, "
                "loader-target mapping certificate or Diffusers sampler parity claim."
            ),
        },
        "report_id",
    )
    if save:
        publish(
            safe_path(config.root, f"state/evaluation/reports/{result['report_id']}.json"), result
        )
    return result
