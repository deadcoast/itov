"""Prompt-or-positional-path command-line entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .discovery import ConversionError, discover


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="markdown-pdf",
        description="Combine a directory's Markdown files into one searchable PDF.",
    )
    result.add_argument("directory", nargs="?", help="input directory; prompts when omitted")
    result.add_argument(
        "-o", "--output", type=Path, help="output PDF (default: DIRECTORY.pdf beside input)"
    )
    result.add_argument("--title", help="title on the index page and in PDF metadata")
    result.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="exclude a name or root-relative path pattern; may be repeated",
    )
    result.add_argument(
        "--list",
        action="store_true",
        dest="list_only",
        help="list included files and exclusions without reading Markdown or writing a PDF",
    )
    result.add_argument(
        "--encoding", default="utf-8-sig", help="source encoding (default: UTF-8 with optional BOM)"
    )
    result.add_argument("--page-size", choices=["a4", "letter"], default="a4")
    result.add_argument("--force", action="store_true", help="replace an existing output PDF")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        value = args.directory
        if value is None:
            value = input("Directory containing Markdown files (blank cancels): ").strip()
            if not value:
                print("Cancelled.")
                return 0
        # Accommodate quoted paths pasted into the interactive prompt.
        value = value.strip().strip('"').strip("'")
        if not value:
            raise ConversionError("The directory path is empty.")
        discovery = discover(Path(value), args.exclude)
        print(f"Found {len(discovery.files)} Markdown files:")
        for path in discovery.files:
            print(f"  {path.relative_to(discovery.root).as_posix()}")
        print(f"Skipped {len(discovery.skipped)} excluded entries.")
        if args.list_only:
            for path, reason in discovery.skipped:
                print(f"  SKIP {path} ({reason})")
            return 0
        from .render import render_pdf

        output = (
            args.output.expanduser().absolute()
            if args.output
            else discovery.root.with_name(discovery.root.name + ".pdf")
        )
        result = render_pdf(
            discovery,
            output,
            title=args.title,
            encoding=args.encoding,
            page_size=args.page_size,
            force=args.force,
        )
        for warning in result.warnings:
            print(f"Warning: {warning}", file=sys.stderr)
        print(
            f"Created {output}\n{result.documents} documents; {result.pages} pages; "
            f"{output.stat().st_size:,} bytes."
        )
        return 0
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.", file=sys.stderr)
        return 130
    except (ConversionError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
