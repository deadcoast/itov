"""The initial operator interface for workspace and workflow preflight."""

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
from itov.comfyui import ComfyUIClient, ComfyUIError
from itov.config import DEFAULT_URL, initialize, load_config, validate_timeout
from itov.doctor import diagnose
from itov.inference import load_spec, plan_inference, prepare_inference
from itov.jobs import run_job, wait_job
from itov.media import verify_video
from itov.qualification import qualify, save_qualification
from itov.rotation import PlanningError
from itov.runtime import launch_command
from itov.video import load_spec as load_video_spec
from itov.video import plan_video, prepare_video
from itov.workflow import load_json, validate_workflow


def _connection_arguments(parser: argparse.ArgumentParser):
    parser.add_argument("--config", type=Path, default=Path("workspace/itov.toml"))
    parser.add_argument(
        "--timeout", type=float, default=3.0, help="Per-request timeout, up to 60 seconds"
    )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Local ComfyUI workspace and workflow preflight")
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
    inference = commands.add_parser("inference", help="Prepare pinned stock SDXL inference batches")
    inference_actions = inference.add_subparsers(dest="action", required=True)
    for action in ("prepare", "plan"):
        item = inference_actions.add_parser(action)
        item.add_argument("file", type=Path, help="Inference specification JSON")
        item.add_argument("--config", type=Path, default=Path("workspace/itov.toml"))
        item.add_argument("--json", action="store_true")
        if action == "plan":
            item.add_argument("--save", action="store_true")
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


def _print_result(result: dict, *, as_json: bool):
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False))
    elif "request_id" in result:
        print(f"{result['status'].upper()} prompt={result.get('prompt_id') or 'unknown'}")
        print(f"Record: {result['record_path']}")
        if result.get("error"):
            print(result["error"])
        for artifact in result["artifacts"]:
            print(f"Output: {artifact['path']} (SHA-256 {artifact['sha256']})")
    elif "checks" in result:
        for check in result["checks"]:
            print(f"{check['status'].upper():4} {check['name']}: {check['detail']}")
        print(result["limits"])
    elif "valid" in result:
        print(
            f"{'PASS' if result['valid'] else 'FAIL'} {result['scope']}: "
            f"{result['node_count']} nodes"
        )
        for issue in result["issues"]:
            location = ":".join(
                str(issue[key]) for key in ("node_id", "input_name") if issue[key] is not None
            )
            print(f"  {issue['code']} {location}: {issue['message']}")
        print(result["limits"])
    else:
        print(f"Created workspace: {result['config']}")


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
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
            )
            _print_result(result, as_json=args.json)
            return 0 if result["status"] == "succeeded" else 1
        elif args.command == "av":
            result = mux(load_config(args.config), load_av_spec(args.file))
            print(json.dumps(result, indent=2))
            return 0
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
            print(json.dumps(result, indent=2))
            return 0
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
            print(json.dumps(result, indent=2))
            return 0
        elif args.command == "inference":
            config = load_config(args.config)
            spec = load_spec(args.file)
            if args.action == "prepare":
                result = prepare_inference(config, spec)
                if not args.json:
                    print(f"Prepared preset: {result['preset_id']}")
                    print(f"Catalog candidate: {result['catalog']}")
                    print(f"Import with --expected-head {result['expected_head']}")
                    print(result["limits"])
            else:
                plan = plan_inference(config, spec)
                path = save_plan(config.root, plan) if args.save else None
                result = {"ok": True, "plan": plan, "path": str(path) if path else None}
                if not args.json:
                    print(f"Planned {len(plan['jobs'])} inference jobs: {plan['plan_id']}")
                    if path:
                        print(f"Plan: {path}")
                    print("Qualify the saved plan before running; no jobs were submitted.")
            if args.json:
                print(json.dumps(result, indent=2))
            return 0
        elif args.command == "catalog":
            result = _catalog_command(args)
            if args.json:
                print(json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False))
            else:
                print(
                    f"{'PASS' if result['ok'] else 'FAIL'} catalog {args.action}: "
                    f"{result['presets']} presets, {result['loras']} LoRAs"
                )
                if "head" in result:
                    print(f"Head: {result['head']} ({result['events']} ledger events)")
                if result.get("recovery_required"):
                    print("Pending transaction: run catalog recover")
                if "recovery" in result:
                    print(f"Recovery: {result['recovery']}")
            return 0 if result["ok"] else 1
        elif args.command == "batch":
            workspace = load_config(args.config).root
            if args.action == "plan":
                plan = create_plan(workspace, load_request(args.file))
                path = save_plan(workspace, plan) if args.save else None
                result = {"ok": True, "plan": plan, "path": str(path) if path else None}
                if args.json:
                    print(json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False))
                else:
                    print(f"Planned {len(plan['jobs'])} jobs: {plan['plan_id']}")
                    for job in plan["jobs"][:10]:
                        stack = ", ".join(
                            f"{item['id']}@{item['strength_milli']}/1000" for item in job["loras"]
                        )
                        print(
                            f"  {job['index'] + 1}: {job['preset']} seed={job['seed']} "
                            f"LoRAs={stack or 'none'}"
                        )
                    if len(plan["jobs"]) > 10:
                        print("  Use --json to inspect all jobs.")
                    if path:
                        print(f"Plan: {path}")
                    print("Planning only; no jobs submitted or render history changed.")
            elif args.action == "verify":
                result = verify_plan(workspace, args.file)
                print(
                    json.dumps(result, indent=2)
                    if args.json
                    else f"PASS {result['jobs']} jobs reproduced: {result['plan_id']}"
                )
            elif args.action == "qualify":
                config = load_config(args.config)
                receipt = qualify(config, load_plan(args.file), timeout=args.timeout)
                path = save_qualification(config, receipt) if args.save else None
                result = {"ok": True, "qualification": receipt, "path": str(path) if path else None}
                if args.json:
                    print(json.dumps(result, indent=2))
                else:
                    print(f"PASS {receipt['scope']}: {receipt['jobs']} jobs")
                    print(f"Qualification: {path or receipt['qualification_id']}")
                    print("Preflight only; model inference and output quality require execution.")
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
                        prompt_id=getattr(args, "prompt_id", None),
                        timeout=args.timeout,
                        wait_timeout=args.wait_timeout,
                        poll_interval=args.poll_interval,
                    )
                if args.json:
                    print(json.dumps(result, indent=2))
                else:
                    print(
                        f"{result['status'].upper()} "
                        f"{result['succeeded']}/{len(result['jobs'])} jobs"
                    )
                    print(f"Plan: {result['plan_id']}")
                    if result.get("error"):
                        print(result["error"])
                    for job in result["jobs"]:
                        print(
                            f"  {job['job_index'] + 1}: {job['status']} "
                            f"request={job['request_id']} "
                            f"prompt={job['prompt_id'] or 'unknown'}"
                        )
                return 0 if result["ok"] or args.action in {"status", "abandon"} else 1
            return 0
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
        _print_result(result, as_json=args.json)
        return 0 if result.get("ok", result.get("valid", False)) else 1
    except PlanningError as error:
        if getattr(args, "json", False):
            print(json.dumps(error.to_dict()))
        else:
            print(
                f"itov: {error.code} at job index {error.index}: {error}; {error.details}",
                file=sys.stderr,
            )
        return 2
    except (OSError, ValueError, ComfyUIError, sqlite3.Error) as error:
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": str(error)}))
        else:
            print(f"itov: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
