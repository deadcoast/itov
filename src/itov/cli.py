"""The initial operator interface for workspace and workflow preflight."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from itov import __version__
from itov.comfyui import ComfyUIClient, ComfyUIError
from itov.config import DEFAULT_URL, initialize, load_config, validate_timeout
from itov.doctor import diagnose
from itov.jobs import run_job, wait_job
from itov.runtime import launch_command
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
    return root


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
    except (OSError, ValueError, ComfyUIError) as error:
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": str(error)}))
        else:
            print(f"itov: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
