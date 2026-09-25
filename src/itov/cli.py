"""Public command dispatch with a shared operator response contract."""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from itov import __version__
from itov.audio import load_spec as load_audio_spec
from itov.audio import output_contract, plan_audio, prepare_audio
from itov.audio_media import verify_audio
from itov.audiovisual import load_spec as load_av_spec
from itov.audiovisual import mux
from itov.batch import create_plan, load_plan, load_request, save_plan, verify_plan
from itov.batch_execution import abandon_batch, batch_status, run_batch
from itov.catalog import load_catalog, verify_assets
from itov.catalog_store import CatalogStore
from itov.cli_output import present
from itov.comfyui import ComfyUIClient, ComfyUIError
from itov.config import DEFAULT_URL, initialize, load_config, validate_timeout
from itov.doctor import diagnose
from itov.inference import load_spec, plan_inference, prepare_inference
from itov.jobs import run_job, wait_job
from itov.media import verify_video
from itov.qualification import qualify, save_qualification
from itov.rotation import PlanningError
from itov.runtime import launch_command, profile_launch_command
from itov.video import load_spec as load_video_spec
from itov.video import plan_video, prepare_video
from itov.workflow import load_json, validate_workflow


def _connection_arguments(parser: argparse.ArgumentParser):
    parser.add_argument("--config", type=Path, default=Path("workspace/itov.toml"))
    parser.add_argument(
        "--timeout", type=float, default=3.0, help="Per-request timeout, up to 60 seconds"
    )


class ArgumentError(ValueError):
    pass


class ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ArgumentError(message)


def parser() -> argparse.ArgumentParser:
    root = ArgumentParser(description="Owned media generation, training and evaluation")
    root.add_argument("--version", action="version", version=f"itov {__version__}")
    commands = root.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Create a workspace without overwriting existing files")
    init.add_argument("directory", nargs="?", type=Path, default=Path("workspace"))
    init.add_argument(
        "--comfyui-root", type=Path, default=Path("AI/ComfyUI/ComfyUI_windows_portable/ComfyUI")
    )
    init.add_argument("--comfyui-python", type=Path)
    init.add_argument("--url", default=DEFAULT_URL)
    init.add_argument("--json", action="store_true")

    doctor = commands.add_parser("doctor", help="Check local tools and a running ComfyUI server")
    _connection_arguments(doctor)
    doctor.add_argument("--offline", action="store_true", help="Skip HTTP requests")
    doctor.add_argument("--json", action="store_true")

    workflow = commands.add_parser("workflow", help="Inspect exported ComfyUI API workflows")
    actions = workflow.add_subparsers(dest="action", required=True)
    validate = actions.add_parser(
        "validate", help="Validate graph structure and optionally node schemas"
    )
    validate.add_argument("file", type=Path)
    source = validate.add_mutually_exclusive_group()
    source.add_argument("--object-info", type=Path, help="Previously saved /object_info JSON")
    source.add_argument(
        "--live", action="store_true", help="Read node metadata from configured ComfyUI"
    )
    _connection_arguments(validate)
    validate.add_argument("--json", action="store_true")

    server = commands.add_parser("server", help="Run the configured local ComfyUI installation")
    server_actions = server.add_subparsers(dest="action", required=True)
    start = server_actions.add_parser(
        "start", help="Run in the foreground; Ctrl+C stops this server"
    )
    _connection_arguments(start)
    start.add_argument("--custom-nodes", action="store_true", help="Enable installed custom nodes")
    start.add_argument(
        "--print-command", action="store_true", help="Print the argument list without launching"
    )

    job = commands.add_parser("job", help="Submit one workflow or resume observing an existing job")
    job_actions = job.add_subparsers(dest="action", required=True)
    for action in ("run", "wait"):
        item = job_actions.add_parser(
            action,
            help="Submit a workflow" if action == "run" else "Resume from a saved job record",
        )
        item.add_argument(
            "file",
            type=Path,
            help="API workflow JSON" if action == "run" else "Saved state/jobs/*.json record",
        )
        _connection_arguments(item)
        item.add_argument(
            "--wait-timeout",
            type=float,
            default=120.0,
            help="Seconds to observe execution; timeout does not cancel the server job",
        )
        item.add_argument("--poll-interval", type=float, default=1.0)
        item.add_argument("--json", action="store_true")
        if action == "wait":
            item.add_argument("--prompt-id", help="Reconcile an uncertain owned submission")
    catalog = commands.add_parser("catalog", help="Validate and record versioned catalog snapshots")
    catalog_actions = catalog.add_subparsers(dest="action", required=True)
    for action in ("validate", "init", "import", "show", "verify", "recover"):
        item = catalog_actions.add_parser(action)
        item.add_argument("--config", type=Path, default=Path("workspace/itov.toml"))
        item.add_argument("--json", action="store_true")
        if action in {"validate", "import"}:
            item.add_argument("file", type=Path)
        if action in {"import", "verify"}:
            item.add_argument("--expected-head", required=action == "import")
        if action in {"validate", "verify"}:
            item.add_argument("--check-files", action="store_true")
    batch = commands.add_parser("batch", help="Plan, qualify, and execute sequential batches")
    batch_actions = batch.add_subparsers(dest="action", required=True)
    for action in ("plan", "verify"):
        item = batch_actions.add_parser(action)
        item.add_argument(
            "file", type=Path, help="Planning request" if action == "plan" else "Saved plan"
        )
        item.add_argument("--config", type=Path, default=Path("workspace/itov.toml"))
        item.add_argument("--json", action="store_true")
        if action == "plan":
            item.add_argument(
                "--save", action="store_true", help="Save under workspace/state/plans"
            )
    for action in ("qualify", "run", "resume", "status", "abandon"):
        item = batch_actions.add_parser(action)
        item.add_argument("file", type=Path, help="Saved immutable batch plan")
        _connection_arguments(item)
        item.add_argument("--json", action="store_true")
        if action == "qualify":
            item.add_argument("--save", action="store_true")
        if action == "run":
            item.add_argument("--qualification", type=Path, required=True)
        if action == "resume":
            item.add_argument("--prompt-id", help="Reconcile only with matching server provenance")
        if action in {"run", "resume"}:
            item.add_argument("--wait-timeout", type=float, default=120.0)
            item.add_argument("--poll-interval", type=float, default=1.0)
            item.add_argument(
                "--vram-profile",
                type=Path,
                action="append",
                help="Bind measured VRAM profiles; retained automatically on resume",
            )
    inference = commands.add_parser(
        "inference", help="Deploy, qualify and execute SDXL adapter stacks"
    )
    inference_actions = inference.add_subparsers(dest="action", required=True)
    for action in (
        "capabilities",
        "prepare",
        "plan",
        "run",
        "status",
        "resume",
        "replay",
        "abandon",
    ):
        item = inference_actions.add_parser(action)
        if action != "capabilities":
            item.add_argument(
                "file", type=Path, help="Inference specification or saved v2 plan JSON"
            )
        item.add_argument("--config", type=Path, default=Path("workspace/itov.toml"))
        item.add_argument("--json", action="store_true")
        if action in {"plan", "replay"}:
            item.add_argument("--save", action="store_true")
        if action in {"plan", "run", "resume"}:
            item.add_argument("--timeout", type=float, default=3)
        if action in {"run", "resume"}:
            item.add_argument("--wait-timeout", type=float, default=300)
            item.add_argument("--poll-interval", type=float, default=1)
        if action == "resume":
            item.add_argument("--prompt-id")
    video = commands.add_parser("video", help="Prepare, plan, and verify pinned Wan video batches")
    video_actions = video.add_subparsers(dest="action", required=True)
    for action in ("prepare", "plan", "verify"):
        item = video_actions.add_parser(action)
        item.add_argument("file", type=Path, help="Video specification JSON")
        item.add_argument("--config", type=Path, default=Path("workspace/itov.toml"))
        item.add_argument("--json", action="store_true")
        if action == "prepare":
            item.add_argument(
                "--image-source", type=Path, help="Copy this exact pinned PNG into workspace input"
            )
        elif action == "plan":
            item.add_argument("--save", action="store_true")
        else:
            item.add_argument("artifact", type=Path, help="Collected MP4 to decode and verify")
    audio = commands.add_parser("audio", help="Prepare, plan, and verify pinned audio batches")
    audio_actions = audio.add_subparsers(dest="action", required=True)
    for action in ("prepare", "plan", "verify"):
        item = audio_actions.add_parser(action)
        item.add_argument("file", type=Path, help="Audio specification JSON")
        item.add_argument("--config", type=Path, default=Path("workspace/itov.toml"))
        item.add_argument("--json", action="store_true")
        if action == "plan":
            item.add_argument("--save", action="store_true")
        if action == "verify":
            item.add_argument("artifact", type=Path)
    av = commands.add_parser("av", help="Compose completed owned audio/video artifacts")
    av_actions = av.add_subparsers(dest="action", required=True)
    item = av_actions.add_parser("mux", help="Create or reverify an immutable audiovisual output")
    item.add_argument("file", type=Path, help="Pinned audiovisual specification JSON")
    item.add_argument("--config", type=Path, default=Path("workspace/itov.toml"))
    item.add_argument("--json", action="store_true")
    vram = commands.add_parser("vram", help="Measure exact workloads and check VRAM admission")
    actions = vram.add_subparsers(dest="action", required=True)
    server = actions.add_parser(
        "server", help="Start a stock runtime with in-process memory observation"
    )
    server.add_argument("--config", type=Path, default=Path("workspace/itov.toml"))
    server.add_argument("--print-command", action="store_true")
    for action in ("capture", "check"):
        item = actions.add_parser(action)
        item.add_argument("file", type=Path, help="Saved batch plan")
        item.add_argument("--config", type=Path, default=Path("workspace/itov.toml"))
        item.add_argument("--json", action="store_true")
        if action == "capture":
            item.add_argument("--qualification", type=Path, required=True)
            item.add_argument("--wait-timeout", type=float, default=900)
        else:
            item.add_argument("--profile", type=Path, action="append", default=[])
            item.add_argument("--workers", type=int, default=1)
            item.add_argument("--save", action="store_true")
    parallel = commands.add_parser("parallel", help="Bounded two-worker audio qualification")
    actions = parallel.add_subparsers(dest="action", required=True)
    for action in ("calibrate", "qualify", "resume", "recover"):
        item = actions.add_parser(action)
        item.add_argument(
            "file", type=Path, help="Saved audio plan: four calibration or two trial jobs"
        )
        item.add_argument("--config", type=Path, default=Path("workspace/itov.toml"))
        item.add_argument("--json", action="store_true")
        if action in {"calibrate", "qualify"}:
            item.add_argument("--ports", nargs=2, type=int, default=[8191, 8192])
            item.add_argument("--wait-timeout", type=float, default=900)
        if action == "qualify":
            item.add_argument("--calibration", action="append", type=Path, required=True)
    device = commands.add_parser("device", help="Inspect or explicitly recover a managed GPU lease")
    actions = device.add_subparsers(dest="action", required=True)
    for action in ("status", "recover"):
        item = actions.add_parser(action)
        item.add_argument("--gpu", required=True, help="Exact NVIDIA GPU UUID")
        item.add_argument("--json", action="store_true")
        if action == "recover":
            item.add_argument("--lease", required=True, help="Exact abandoned lease UUID")
    for name in ("trigger", "scene"):
        lint_group = commands.add_parser(name, help="Offline catalog/plan lint without rewrites")
        lint_actions = lint_group.add_subparsers(dest="action", required=True)
        lint = lint_actions.add_parser("lint")
        lint.add_argument("file", type=Path, help="Trigger rules or scene constraints JSON")
        lint.add_argument("--plan", type=Path, required=name == "scene")
        lint.add_argument("--config", type=Path, default=Path("workspace/itov.toml"))
        lint.add_argument("--save", action="store_true", help="Save an immutable lint report")
        lint.add_argument("--json", action="store_true")
        if name == "trigger":
            lint.add_argument("--strict", action="store_true", help="Treat warnings as failure")
    datasets = commands.add_parser("dataset", help="Explicit training dataset integrity")
    dataset_actions = datasets.add_subparsers(dest="action", required=True)
    for action in ("validate", "prepare", "curate"):
        item = dataset_actions.add_parser(action)
        item.add_argument("file", type=Path)
        item.add_argument("--config", type=Path, default=Path("workspace/itov.toml"))
        item.add_argument("--json", action="store_true")
        if action == "curate":
            item.add_argument("--save", action="store_true")
            item.add_argument(
                "--freeze", type=Path, help="Bind this import to a verified frozen review"
            )
    for action in ("import", "status", "recover", "verify"):
        item = dataset_actions.add_parser(action)
        item.add_argument(
            "file",
            type=Path,
            help="Import declaration, saved operation, or prepared snapshot for verify",
        )
        item.add_argument("--config", type=Path, default=Path("workspace/itov.toml"))
        item.add_argument("--json", action="store_true")
        if action in {"import", "recover"}:
            item.add_argument(
                "--source-root",
                type=Path,
                help="Declared input root; import defaults to declaration directory",
            )
            item.add_argument(
                "--image-python",
                type=Path,
                help="Python with the optional pinned Pillow dependency",
            )
    for action in ("inspect", "freeze", "review-verify"):
        item = dataset_actions.add_parser(action)
        item.add_argument(
            "file", type=Path, help="Inspection specification, review, or frozen selection"
        )
        item.add_argument("--config", type=Path, default=Path("workspace/itov.toml"))
        item.add_argument("--json", action="store_true")
        if action != "review-verify":
            item.add_argument("--save", action="store_true")
        if action == "inspect":
            item.add_argument("--image-python", type=Path, help="Python with Pillow 12.3.0")
    training = commands.add_parser("training", help="Pinned, owned SDXL LoRA training")
    training_actions = training.add_subparsers(dest="action", required=True)
    for action in ("plan", "run", "status", "recover", "candidate", "checkpoints", "resume-plan"):
        item = training_actions.add_parser(action)
        item.add_argument("file", type=Path)
        item.add_argument("--config", type=Path, default=Path("workspace/itov.toml"))
        item.add_argument("--json", action="store_true")
        if action in {"plan", "candidate", "resume-plan"}:
            item.add_argument("--save", action="store_true")
        if action == "resume-plan":
            item.add_argument("--checkpoint", type=Path, required=True)
        if action == "run":
            item.add_argument("--gpu", required=True)
    experiment = commands.add_parser(
        "experiment", help="Preregister bounded checkpoint experiments"
    )
    actions = experiment.add_subparsers(dest="action", required=True)
    for action in ("plan", "run", "status", "packet", "decide", "replay"):
        item = actions.add_parser(action)
        item.add_argument("file", type=Path, help="Experiment specification or saved manifest")
        item.add_argument("--config", type=Path, default=Path("workspace/itov.toml"))
        item.add_argument("--json", action="store_true")
        if action in {"plan", "packet", "decide"}:
            item.add_argument("--save", action="store_true")
        if action == "run":
            item.add_argument("--member", required=True)
            item.add_argument("--gpu", required=True)
        if action == "decide":
            item.add_argument("--review", type=Path, required=True)
        if action == "replay":
            item.add_argument("--decision", type=Path, required=True)
    evaluation = commands.add_parser("evaluation", help="Technical training assessment")
    evaluation_actions = evaluation.add_subparsers(dest="action", required=True)
    for action in (
        "mapping",
        "mapping-inspect",
        "review-packet",
        "review-inspect",
        "decide",
        "decision-replay",
    ):
        item = evaluation_actions.add_parser(action)
        item.add_argument("file", type=Path)
        item.add_argument("--config", type=Path, default=Path("workspace/itov.toml"))
        item.add_argument("--json", action="store_true")
        if action in {"mapping", "review-packet", "decide"}:
            item.add_argument("--save", action="store_true")
        if action == "review-packet":
            item.add_argument("--mapping", type=Path, required=True)
        if action == "decide":
            item.add_argument("--review", type=Path, required=True)
    for action in ("assess", "packet", "plan", "run", "status", "resume", "replay", "abandon"):
        item = evaluation_actions.add_parser(action)
        item.add_argument("file", type=Path)
        item.add_argument("--config", type=Path, default=Path("workspace/itov.toml"))
        item.add_argument("--json", action="store_true")
        if action in {"assess", "packet", "plan", "replay"}:
            item.add_argument("--save", action="store_true")
        if action in {"plan", "run", "resume"}:
            item.add_argument("--timeout", type=float, default=3)
        if action in {"run", "resume"}:
            item.add_argument("--wait-timeout", type=float, default=300)
            item.add_argument("--poll-interval", type=float, default=1)
        if action == "resume":
            item.add_argument("--prompt-id")
    promotion = commands.add_parser("promotion", help="Explicitly reviewed catalog promotion")
    promotion_actions = promotion.add_subparsers(dest="action", required=True)
    for action in ("prepare", "apply"):
        item = promotion_actions.add_parser(action)
        item.add_argument("file", type=Path)
        item.add_argument("--review", type=Path, required=action == "apply")
        item.add_argument("--config", type=Path, default=Path("workspace/itov.toml"))
        item.add_argument("--json", action="store_true")
        if action == "prepare":
            item.add_argument("--save", action="store_true")
        else:
            item.add_argument("--expected-head", required=True)
            item.add_argument("--decision", required=True)
    corpus = commands.add_parser("corpus", help="Freeze evaluation coverage and record baselines")
    actions = corpus.add_subparsers(dest="action", required=True)
    for action in ("freeze", "inspect", "baseline", "replay"):
        item = actions.add_parser(action)
        item.add_argument("file", type=Path)
        item.add_argument("--config", type=Path, default=Path("workspace/itov.toml"))
        item.add_argument("--json", action="store_true")
        if action in {"freeze", "baseline"}:
            item.add_argument("--save", action="store_true")
        if action == "baseline":
            item.add_argument("--evaluation", type=Path, required=True)
            item.add_argument("--review", type=Path)
    checks = commands.add_parser("checks", help="Measure images and calibrate optional evaluators")
    actions = checks.add_subparsers(dest="action", required=True)
    for action in ("packet", "inspect", "calibrate", "replay"):
        item = actions.add_parser(action)
        item.add_argument("file", type=Path)
        item.add_argument("--config", type=Path, default=Path("workspace/itov.toml"))
        item.add_argument("--json", action="store_true")
        if action in {"packet", "calibrate"}:
            item.add_argument("--save", action="store_true")
        if action == "calibrate":
            item.add_argument("--reference", type=Path, required=True)
            item.add_argument("--evaluator", type=Path)
    return root


def _catalog_command(args) -> dict:
    if args.action == "validate":
        catalog = load_catalog(args.file)
        result = {
            "ok": True,
            "scope": "catalog_schema",
            "presets": len(catalog["presets"]),
            "loras": len(catalog["loras"]),
        }
        if args.check_files:
            result["assets"] = verify_assets(catalog, load_config(args.config).root)
            result["scope"] = "catalog_schema_and_asset_bytes"
        return result
    store = CatalogStore(load_config(args.config).root)
    if args.action == "recover":
        return store.recover()
    if args.action == "init":
        snapshot = store.initialize()
    elif args.action == "import":
        snapshot = store.import_catalog(load_catalog(args.file), expected_head=args.expected_head)
    else:
        snapshot = store.snapshot()
    result = {**snapshot.report(), "recovery_required": store.recovery_required}
    if args.action == "show":
        result["snapshot"] = snapshot.to_dict()
    if args.action == "verify":
        if args.expected_head and snapshot.head != args.expected_head:
            raise ValueError("Catalog differs from expected head")
        if args.check_files:
            result["assets"] = verify_assets(snapshot.to_dict()["catalog"], store.workspace)
        result["ok"] = not result["recovery_required"]
    return result


def _execute(args):
    if hasattr(args, "timeout"):
        validate_timeout(args.timeout)
    if args.command == "init":
        config = initialize(
            args.directory, args.comfyui_root, python=args.comfyui_python, url=args.url
        )
        result = {"ok": True, "config": str(config.file)}
    elif args.command == "doctor":
        result = diagnose(load_config(args.config), offline=args.offline, timeout=args.timeout)
    elif args.command == "server":
        config = load_config(args.config)
        command = launch_command(config, custom_nodes=args.custom_nodes)
        if args.print_command:
            print(json.dumps(command))
            return 0
        return subprocess.call(command, cwd=config.comfyui_root)
    elif args.command == "job":
        operation = run_job if args.action == "run" else wait_job
        result = operation(
            load_config(args.config),
            args.file,
            timeout=args.timeout,
            wait_timeout=args.wait_timeout,
            poll_interval=args.poll_interval,
            **{"prompt_id": args.prompt_id} if args.action == "wait" else {},
        )
        return result
    elif args.command == "checks":
        from itov import image_checks

        config = load_config(args.config)
        if args.action in {"inspect", "replay"}:
            return getattr(image_checks, args.action)(config, args.file)
        if args.action == "packet":
            result = image_checks.packet(config, args.file, save=args.save)
            folder, key = "packets", "packet_id"
        else:
            result = image_checks.calibrate(
                config, args.file, args.reference, evaluator_path=args.evaluator, save=args.save
            )
            folder, key = "calibrations", "calibration_id"
        if args.save:
            result = {
                **result,
                "saved_path": str(
                    config.root / f"state/evaluation/checks/{folder}/{result[key]}.json"
                ),
            }
        return result
    elif args.command == "corpus":
        from itov import evaluation_corpus

        config = load_config(args.config)
        if args.action == "baseline":
            result = evaluation_corpus.baseline(
                config, args.file, args.evaluation, review_path=args.review, save=args.save
            )
        elif args.action == "freeze":
            result = evaluation_corpus.freeze(config, args.file, save=args.save)
        else:
            return getattr(evaluation_corpus, args.action)(config, args.file)
        if args.save:
            folder, key = (
                ("corpora", "corpus_id")
                if args.action == "freeze"
                else ("baselines", "baseline_id")
            )
            result = {
                **result,
                "saved_path": str(config.root / f"state/evaluation/{folder}/{result[key]}.json"),
            }
        return result
    elif args.command == "experiment":
        from itov import experiments

        config = load_config(args.config)
        if args.action == "run":
            return experiments.run(config, args.file, args.member, args.gpu)
        if args.action == "decide":
            result = experiments.decide(config, args.file, args.review, save=args.save)
        elif args.action == "replay":
            return experiments.replay(config, args.file, args.decision)
        elif args.action == "status":
            return experiments.status(config, args.file)
        else:
            result = getattr(experiments, args.action)(config, args.file, save=args.save)
        if args.save:
            category, key = {
                "plan": ("plans", "experiment_id"),
                "packet": ("packets", "packet_id"),
                "decide": ("decisions", "decision_id"),
            }[args.action]
            result = {
                **result,
                "saved_path": str(config.root / f"state/experiments/{category}/{result[key]}.json"),
            }
        return result
    elif args.command in {"dataset", "training", "evaluation", "promotion"}:
        from itov import evaluation, training, training_data

        config = load_config(args.config)
        if args.command == "dataset":
            if args.action in {"inspect", "freeze", "review-verify"}:
                from itov import dataset_freeze, dataset_inspection

                if args.action == "inspect":
                    result = dataset_inspection.inspect(
                        config, args.file, image_python=args.image_python, save=args.save
                    )
                elif args.action == "freeze":
                    result = dataset_freeze.freeze(config, args.file, save=args.save)
                else:
                    result = dataset_freeze.verify(config, args.file)
            elif args.action in {"import", "status", "recover", "verify"}:
                from itov import dataset_import

                if args.action == "verify":
                    result = training_data.load_dataset(config.root, args.file)
                elif args.action == "status":
                    result = dataset_import.status(config, args.file)
                else:
                    operation = (
                        dataset_import.begin if args.action == "import" else dataset_import.recover
                    )
                    result = operation(
                        config,
                        args.file,
                        source_root=args.source_root,
                        image_python=args.image_python,
                    )
            elif args.action == "curate":
                from itov import curation

                result = (
                    curation.bind_selection(config.root, args.file, args.freeze, save=args.save)
                    if args.freeze
                    else curation.validate(config.root, args.file, save=args.save)
                )
            else:
                operation = (
                    training_data.prepare if args.action == "prepare" else training_data.validate
                )
                result = operation(config.root, args.file)
        elif args.command == "evaluation":
            if args.action in {
                "mapping",
                "mapping-inspect",
                "review-packet",
                "review-inspect",
                "decide",
                "decision-replay",
            }:
                from itov import deployed_loader, deployed_review

                if args.action == "mapping":
                    result = deployed_loader.mapping(config, args.file, save=args.save)
                elif args.action == "mapping-inspect":
                    result = deployed_loader.inspect(config, args.file)
                elif args.action == "review-packet":
                    result = deployed_review.packet(config, args.file, args.mapping, save=args.save)
                elif args.action == "review-inspect":
                    result = deployed_review.inspect(config, args.file)
                elif args.action == "decide":
                    result = deployed_review.decide(config, args.file, args.review, save=args.save)
                else:
                    result = deployed_review.replay(config, args.file)
                if getattr(args, "save", False):
                    folder, key = {
                        "mapping": ("mappings", "mapping_id"),
                        "review-packet": ("review-packets", "packet_id"),
                        "decide": ("decisions", "decision_id"),
                    }[args.action]
                    result = {
                        **result,
                        "saved_path": str(
                            config.root / f"state/evaluation/{folder}/{result[key]}.json"
                        ),
                    }
            elif args.action in {"plan", "run", "status", "resume", "replay", "abandon"}:
                from itov import evaluation_runtime

                if args.action == "plan":
                    result = evaluation_runtime.plan(
                        config, args.file, save=args.save, timeout=args.timeout
                    )
                    if args.save:
                        result = {
                            **result,
                            "saved_path": str(
                                config.root / f"state/evaluation/plans/{result['plan_id']}.json"
                            ),
                        }
                elif args.action in {"run", "resume"}:
                    result = evaluation_runtime.run(
                        config,
                        args.file,
                        resume=args.action == "resume",
                        prompt_id=getattr(args, "prompt_id", None),
                        timeout=args.timeout,
                        wait_timeout=args.wait_timeout,
                        poll_interval=args.poll_interval,
                    )
                elif args.action == "replay":
                    result = evaluation_runtime.replay(config, args.file, save=args.save)
                else:
                    result = getattr(evaluation_runtime, args.action)(config, args.file)
            elif args.action == "packet":
                from itov import quality

                result = quality.packet(config, args.file, save=args.save)
            else:
                result = evaluation.assess(config, args.file, save=args.save)
        elif args.command == "promotion":
            if args.action == "apply":
                result = evaluation.apply_promotion(
                    config, args.file, args.review, args.expected_head, args.decision
                )
            else:
                result = evaluation.promotion(config, args.file, args.review, save=args.save)
        elif args.action in {"plan", "resume-plan"}:
            if args.action == "resume-plan":
                from itov import training_checkpoints

                result = training_checkpoints.resume_plan(config, args.file, args.checkpoint)
            else:
                result = training.plan(config, args.file)
            if args.save:
                saved = training.save_plan(config, result)
                result = {**result, "saved_path": str(saved)}
        elif args.action == "candidate":
            result = evaluation.candidate(config, args.file, save=args.save)
        elif args.action == "run":
            result = training.run(config, args.file, args.gpu)
        elif args.action == "checkpoints":
            from itov import training_checkpoints

            result = training_checkpoints.status(config, args.file)
        else:
            result = getattr(training, args.action)(config, args.file)
        return result
    elif args.command in {"trigger", "scene"}:
        from itov import scene, trigger

        config = load_config(args.config)
        if args.command == "trigger":
            result = trigger.lint(
                config, args.file, plan_path=args.plan, strict=args.strict, save=args.save
            )
        else:
            result = scene.lint(config, args.file, args.plan, save=args.save)
        return result
    elif args.command == "device":
        from itov import device

        result = (
            device.status(args.gpu)
            if args.action == "status"
            else device.recover(args.gpu, args.lease)
        )
        return result
    elif args.command == "parallel":
        from itov import parallel

        config = load_config(args.config)
        if args.action == "resume":
            result = parallel.resume(config, args.file)
        elif args.action == "recover":
            result = parallel.recover(config, args.file)
        else:
            result = parallel.run(
                config,
                args.file,
                calibrate=args.action == "calibrate",
                calibration_paths=getattr(args, "calibration", None),
                ports=args.ports,
                wait_timeout=args.wait_timeout,
            )
        return result
    elif args.command == "vram":
        from itov import vram

        config = load_config(args.config)
        if args.action == "server":
            command = profile_launch_command(config)
            if args.print_command:
                print(json.dumps(command))
                return 0
            return subprocess.run(command, cwd=config.comfyui_root).returncode
        if args.action == "capture":
            result = vram.capture(
                config, args.file, args.qualification, wait_timeout=args.wait_timeout
            )
        else:
            result = vram.check(
                config,
                load_plan(args.file),
                [vram.load_profile(path) for path in args.profile],
                workers=args.workers,
            )
            if args.save:
                result, path = vram._save(config, "decisions", result, "decision_id")
                result = {**result, "path": str(path)}
        return result
    elif args.command == "av":
        result = mux(load_config(args.config), load_av_spec(args.file))
        return result
    elif args.command == "audio":
        spec = load_audio_spec(args.file)
        if args.action == "verify":
            result = verify_audio(args.artifact, output_contract(spec))
        elif args.action == "prepare":
            result = prepare_audio(load_config(args.config), spec)
        else:
            config = load_config(args.config)
            plan = plan_audio(config, spec)
            path = save_plan(config.root, plan) if args.save else None
            result = {
                "ok": True,
                "plan": plan,
                "path": str(path) if path else None,
                "limits": "No jobs submitted; qualify before execution.",
            }
        return result
    elif args.command == "video":
        spec = load_video_spec(args.file)
        if args.action == "verify":
            result = verify_video(
                args.artifact, {key: spec[key] for key in ("width", "height", "frames", "fps")}
            )
        else:
            config = load_config(args.config)
            if args.action == "prepare":
                result = prepare_video(config, spec, image_source=args.image_source)
            else:
                plan = plan_video(config, spec)
                path = save_plan(config.root, plan) if args.save else None
                result = {
                    "ok": True,
                    "plan": plan,
                    "path": str(path) if path else None,
                    "limits": "No jobs submitted; qualify before execution.",
                }
        return result
    elif args.command == "inference":
        from itov import inference_runtime
        from itov.inference_capabilities import capabilities

        if args.action == "capabilities":
            result = capabilities()
            return result
        config = load_config(args.config)
        spec = load_spec(args.file) if args.action in {"prepare", "plan"} else None
        if spec is None or spec["version"] == 2:
            if args.action == "prepare":
                result = inference_runtime.prepare(config, spec)
            elif args.action == "plan":
                result = inference_runtime.plan(config, spec, save=args.save, timeout=args.timeout)
                result = {
                    "ok": True,
                    "scope": result["scope"],
                    "plan": result,
                    "plan_id": result["plan_id"],
                    "saved_path": str(
                        config.root / f"state/inference/plans/{result['plan_id']}.json"
                    )
                    if args.save
                    else None,
                    "next_action": "Run inference run with the saved plan.",
                }
            elif args.action in {"run", "resume"}:
                result = inference_runtime.run(
                    config,
                    args.file,
                    resume=args.action == "resume",
                    prompt_id=getattr(args, "prompt_id", None),
                    timeout=args.timeout,
                    wait_timeout=args.wait_timeout,
                    poll_interval=args.poll_interval,
                )
            elif args.action == "replay":
                result = inference_runtime.replay(config, args.file, save=args.save)
            else:
                result = getattr(inference_runtime, args.action)(config, args.file)
            return result
        if args.action == "prepare":
            result = prepare_inference(config, spec)
        else:
            plan = plan_inference(config, spec)
            path = save_plan(config.root, plan) if args.save else None
            result = {"ok": True, "plan": plan, "path": str(path) if path else None}
        return result
    elif args.command == "catalog":
        result = _catalog_command(args)
        return result
    elif args.command == "batch":
        workspace = load_config(args.config).root
        if args.action == "plan":
            plan = create_plan(workspace, load_request(args.file))
            path = save_plan(workspace, plan) if args.save else None
            result = {"ok": True, "plan": plan, "path": str(path) if path else None}
        elif args.action == "verify":
            result = verify_plan(workspace, args.file)
        elif args.action == "qualify":
            config = load_config(args.config)
            receipt = qualify(config, load_plan(args.file), timeout=args.timeout)
            path = save_qualification(config, receipt) if args.save else None
            result = {"ok": True, "qualification": receipt, "path": str(path) if path else None}
        else:
            config = load_config(args.config)
            if args.action in {"status", "abandon"}:
                operation = batch_status if args.action == "status" else abandon_batch
                result = operation(config, args.file)
            else:
                result = run_batch(
                    config,
                    args.file,
                    qualification=getattr(args, "qualification", None),
                    resume=args.action == "resume",
                    vram_profiles=args.vram_profile,
                    prompt_id=getattr(args, "prompt_id", None),
                    timeout=args.timeout,
                    wait_timeout=args.wait_timeout,
                    poll_interval=args.poll_interval,
                )
            return result
        return result
    else:
        graph = load_json(args.file)
        registry = None
        if args.object_info:
            registry = load_json(args.object_info)
            if not isinstance(registry, dict) or not registry:
                raise ValueError("Object info must contain a nonempty node registry")
        elif args.live:
            config = load_config(args.config)
            registry = ComfyUIClient(config.url, timeout=args.timeout).object_info()
        result = validate_workflow(graph, registry).to_dict()
    return result


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    args = argparse.Namespace(command="arguments", json="--json" in arguments)
    try:
        args = parser().parse_args(arguments)
        result = _execute(args)
        # Foreground servers retain their child exit status and stream output.
        return result if isinstance(result, int) else present(args, result)
    except PlanningError as error:
        return present(args, error.to_dict(), exception=True)
    except (OSError, ValueError, ComfyUIError, sqlite3.Error) as error:
        boundary = getattr(error, "boundary", None)
        return present(
            args,
            {
                "ok": False,
                "error": str(error),
                "error_type": type(error).__name__,
                **({"failure_boundary": boundary} if boundary else {}),
            },
            exception=True,
        )
    except KeyboardInterrupt:
        return present(
            args,
            {"ok": False, "error": "Observation interrupted; execution may still be active."},
            interrupted=True,
        )


if __name__ == "__main__":
    raise SystemExit(main())
