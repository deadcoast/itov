"""Check maintained docs and retained originals without running application workflows."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/history/docs-reorganization-20261005/manifest.json"
LINK = re.compile(r"!?\[[^\]\n]*\]\((<[^>]+>|[^\s)]+)(?:\s+\"[^\"]*\")?\)")
REFERENCE = re.compile(r"^\s*\[[^\]]+\]:\s*(\S+)", re.MULTILINE)
FENCE = re.compile(r"^\s{0,3}(\x60{3,}|~{3,})(.*)$")
ARCHIVES = ("docs/history/", "docs/design_spec/", "docs/legacy/", "docs/methods/")


def prose(text: str) -> tuple[str, bool]:
    """Exclude fenced examples; keep line numbers for diagnostics."""
    result = []
    marker = ""
    for line in text.splitlines():
        match = FENCE.match(line)
        if marker:
            if (
                match
                and match[1][0] == marker[0]
                and len(match[1]) >= len(marker)
                and not match[2].strip()
            ):
                marker = ""
            result.append("")
        elif match:
            marker = match[1]
            result.append("")
        else:
            result.append(line)
    return "\n".join(result), not marker


def anchors(text: str) -> set[str]:
    """GitHub-style ATX heading IDs for this repository's Markdown subset."""
    content, _ = prose(text)
    counts: Counter[str] = Counter()
    result = set(re.findall(r'<a\s+(?:id|name)=["\']([^"\']+)', content))
    for line in content.splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)(?:\s+#+)?$", line)
        if not match:
            continue
        heading = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", match[1])
        heading = re.sub(r"<[^>]*>", "", heading).lower()
        slug = "".join(c for c in heading if c.isalnum() or c in "_- ").replace(" ", "-")
        count = counts[slug]
        result.add(f"{slug}-{count}" if count else slug)
        counts[slug] += 1
    return result


def destinations(text: str) -> list[str]:
    content, _ = prose(text)
    return [
        unquote(m[1].strip("<>"))
        for pattern in (LINK, REFERENCE)
        for m in pattern.finditer(content)
    ]


def check_links(path: Path, root: Path = ROOT) -> tuple[list[str], int]:
    text = path.read_text(encoding="utf-8-sig")
    errors = []
    _, balanced = prose(text)
    if not balanced:
        errors.append(f"{path.relative_to(root)}: unclosed code fence")
    checked = 0
    for url in destinations(text):
        parsed = urlsplit(url)
        if parsed.scheme or parsed.netloc:
            continue
        target = (path.parent / parsed.path).resolve() if parsed.path else path
        checked += 1
        if not target.is_relative_to(root):
            errors.append(f"{path.relative_to(root)}: link escapes repository: {url}")
        elif not target.exists():
            errors.append(f"{path.relative_to(root)}: missing local link: {url}")
        elif parsed.fragment and target.suffix.lower() == ".md":
            if parsed.fragment not in anchors(target.read_text(encoding="utf-8-sig")):
                errors.append(f"{path.relative_to(root)}: missing heading: {url}")
    return errors, checked


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    from itov.cli import parser

    errors: list[str] = []
    maintained = [
        ROOT / name
        for name in (
            "README.md",
            "TODO.md",
            "CHANGELOG.md",
            "AGENTS.md",
            "tools/markdown_pdf/README.md",
        )
    ]
    excluded = 0
    for path in sorted((ROOT / "docs").rglob("*.md")):
        name = path.relative_to(ROOT).as_posix()
        is_index = path.name in {"README.md", "INDEX.md"}
        archived = name.startswith(ARCHIVES)
        if name.startswith("docs/history/") and name != "docs/history/README.md":
            excluded += 1
        elif name.startswith("docs/evidence/") and path.parent != ROOT / "docs/evidence":
            excluded += 1
        elif archived and not is_index:
            excluded += 1
        else:
            maintained.append(path)
    checked = 0
    for path in maintained:
        issues, count = check_links(path)
        errors.extend(issues)
        checked += count
    for folder in (
        "guides",
        "contracts",
        "training",
        "evaluation",
        "development",
        "requirements",
        "decisions",
        "reports",
    ):
        for path in (ROOT / "docs" / folder).rglob("*.md"):
            if path.name == "README.md":
                continue
            index = path.parent / "README.md"
            if not index.is_file() or path.name not in destinations(index.read_text("utf-8")):
                errors.append(f"Missing index entry: {path.relative_to(ROOT)}")

    modules = {p.name for p in (ROOT / "src/itov").glob("*.py")}
    module_links = destinations((ROOT / "docs/development/source-map.md").read_text("utf-8"))
    documented = [
        Path(url).name
        for url in module_links
        if url.startswith("../../src/itov/") and url.endswith(".py")
    ]
    if set(documented) != modules or len(documented) != len(modules):
        errors.append("Source map must link every top-level ITOV Python module exactly once")

    inventory = (ROOT / "docs/development/cli-reference.md").read_text("utf-8")
    documented_cli = {}
    for row in inventory.splitlines():
        if row.startswith("| " + chr(96)):
            cells = row.split("|")
            family = cells[1].strip().strip(chr(96))
            if family in documented_cli:
                errors.append(f"Duplicate CLI family: {family}")
            documented_cli[family] = re.findall(r"\x60([^\x60]+)\x60", cells[2])
    expected_cli = {}
    for action in parser()._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                children = [a for a in sub._actions if isinstance(a, argparse._SubParsersAction)]
                expected_cli[name] = list(children[0].choices) if children else []
    if expected_cli != documented_cli:
        errors.append("CLI inventory differs from the current parser's families/actions")

    manifest = json.loads(MANIFEST.read_text("utf-8"))
    preserved = 0
    for item in manifest["files"]:
        original = ROOT / item["preserved_path"]
        if not original.is_file() or sha256(original) != item["original_sha256"]:
            errors.append(f"Changed/missing preserved original: {item['preserved_path']}")
        else:
            preserved += 1
        if not (ROOT / item["current_path"]).is_file():
            errors.append(f"Missing relocated/current document: {item['current_path']}")
    unchanged = 0
    for item in manifest["untouched_documents"]:
        path = ROOT / item["path"]
        if not path.is_file() or sha256(path) != item["sha256"]:
            errors.append(f"Changed/missing retained document: {item['path']}")
        else:
            unchanged += 1
    result = {
        "status": "failed" if errors else "passed",
        "maintained_markdown_files": len(maintained),
        "local_links_checked": checked,
        "historical_markdown_excluded_from_live_links": excluded,
        "source_modules_mapped": len(modules),
        "cli_families": len(expected_cli),
        "cli_actions": sum(len(actions) for actions in expected_cli.values()),
        "preserved_originals_verified": preserved,
        "untouched_documents_verified": unchanged,
        "errors": errors,
        "limits": [
            "Local Markdown links/ATX fragments and fenced-code subset; no external URL checks.",
            "Historical/design/research bodies retain old paths; bytes checked separately.",
            "Parser inventory covers families/actions, not every flag or example command.",
            "No inference, training, runtime submission, model loading or downloads.",
        ],
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
