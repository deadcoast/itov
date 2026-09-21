from __future__ import annotations

import builtins
import os
from pathlib import Path

import pymupdf
import pytest
from markdown_pdf.cli import main
from markdown_pdf.discovery import ConversionError, discover
from markdown_pdf.render import MonolithDoc, render_pdf
from pypdf import PdfReader
from reportlab.platypus import LayoutError


def write(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_discovery_prunes_excluded_directories_before_descent(tmp_path, monkeypatch):
    write(tmp_path, "10_final.MD", "ten")
    write(tmp_path, "2_start.markdown", "two")
    write(tmp_path, "README.md", "first")
    write(tmp_path, "nested/4_api.mdown", "four")
    write(tmp_path, "nested/3_api.mkd", "three")
    excluded = [
        "sensitive",
        "Private",
        "secrets",
        "my-sensitive-notes",
        ".git",
        "node_modules",
        "workspace",
        "output",
        "archive",
    ]
    for name in excluded:
        write(tmp_path, f"{name}/must-not-read.md", "excluded")
    write(tmp_path, "credentials.md", "excluded")
    original = os.scandir
    visited = []

    def guarded(path):
        assert Path(path).name not in excluded
        visited.append(Path(path))
        return original(path)

    monkeypatch.setattr(os, "scandir", guarded)
    result = discover(tmp_path, ["archive"])
    assert [path.relative_to(tmp_path).as_posix() for path in result.files] == [
        "README.md",
        "2_start.markdown",
        "10_final.MD",
        "nested/3_api.mkd",
        "nested/4_api.mdown",
    ]
    assert len(result.skipped) == len(excluded) + 1
    assert visited == [tmp_path, tmp_path / "nested"]


def test_private_input_root_is_rejected(tmp_path):
    path = write(tmp_path, "sensitive/child/spec.md", "excluded")
    with pytest.raises(ConversionError, match="excluded private directory"):
        discover(path.parent)


def test_linked_files_and_directories_are_not_followed(tmp_path):
    source = tmp_path / "source"
    write(source, "good.md", "included")
    target = write(tmp_path, "elsewhere/hidden.md", "excluded")
    try:
        (source / "linked.md").symlink_to(target)
        (source / "linked-directory").symlink_to(target.parent, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks is unavailable on this host")
    found = discover(source)
    assert [path.name for path in found.files] == ["good.md"]
    assert len(found.skipped) == 2


def test_prompt_and_positional_path(tmp_path, monkeypatch, capsys):
    write(tmp_path, "one.md", "# One")
    calls = []

    def answer(prompt):
        calls.append(prompt)
        return f'"{tmp_path}"'

    monkeypatch.setattr(builtins, "input", answer)
    assert main(["--list"]) == 0
    assert len(calls) == 1
    assert main([str(tmp_path), "--list"]) == 0
    assert len(calls) == 1
    assert "one.md" in capsys.readouterr().out


def test_cancel_and_bad_inputs(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(builtins, "input", lambda _: "")
    assert main([]) == 0
    assert main([str(tmp_path / "absent")]) == 2
    assert main([str(tmp_path)]) == 2
    assert "No Markdown files" in capsys.readouterr().err


def test_pdf_content_pagination_html_and_links(tmp_path):
    source = tmp_path / "specs"
    code = "\n".join(f"    print('CODE_LINE_{number:03}')" for number in range(180))
    long_code = "long_identifier_" * 70 + "LONG_LINE_END"
    table = "| Name | Behavior |\n| --- | --- |\n" + "\n".join(
        f"| ROW_{number:03} | Expected behavior {number} |" for number in range(100)
    )
    write(
        source,
        "README.md",
        """---
owner: engineering
---
# Overview

Preserve **bold**, *italic*, ~~old~~, `inline_code`, and <u>inline HTML</u>.

See [API](2_api.md#endpoint), [website](https://example.com/spec), and footnote.[^note]

[^note]: Footnote content is retained.

- [x] Completed work
- [ ] Pending work
- Parent
  - Nested item

> Quoted requirement

<details><summary>Implementation detail</summary><p>Expanded detail body.</p></details>

![Architecture](https://example.invalid/diagram.png)

<script>UNEXECUTED_SCRIPT()</script>
""",
    )
    write(source, "2_api.md", f"# Endpoint\n\n```python\n{code}\n{long_code}\n```\n\n{table}\n")
    write(source, "3_empty.md", "")
    write(source, "sensitive/hidden.md", "EXCLUDED_CONTENT_SENTINEL")
    destination = tmp_path / "result.pdf"
    result = render_pdf(discover(source), destination)
    pdf = PdfReader(destination)
    text = "\n".join(page.extract_text() for page in pdf.pages)
    assert result.documents == 3
    assert result.pages == len(pdf.pages) > 7
    for sentinel in [
        "owner: engineering",
        "Overview",
        "inline HTML",
        "Footnote content",
        "Completed work",
        "Pending work",
        "Nested item",
        "Expanded detail body",
        "UNEXECUTED_SCRIPT",
        "```python",
        "LONG_LINE_END",
        "[Empty Markdown document]",
    ]:
        assert sentinel in text
    for number in range(180):
        assert f"CODE_LINE_{number:03}" in text
    for number in range(100):
        assert f"ROW_{number:03}" in text
    assert "EXCLUDED_CONTENT_SENTINEL" not in text
    assert len(pdf.outline) == 3
    annotations = [
        annotation.get_object() for page in pdf.pages for annotation in page.get("/Annots", [])
    ]
    assert any(annotation.get("/Dest") for annotation in annotations)
    assert any(
        annotation.get("/A", {}).get("/URI") == "https://example.com/spec"
        for annotation in annotations
    )
    assert result.warnings
    # Check actual rendered text positions, not only the extraction stream.
    with pymupdf.open(destination) as rendered:
        for page in rendered:
            for x0, y0, x1, y1, *_ in page.get_text("blocks"):
                assert x0 >= 40 and y0 >= 10
                assert x1 <= page.rect.width - 40 and y1 <= page.rect.height - 10


def test_very_tall_table_row_and_wide_table(tmp_path):
    long_cell = "<br>".join(f"CELL_LINE_{number:03}" for number in range(190))
    write(
        tmp_path,
        "tables.md",
        f"""# Tables

| Key | Details |
| --- | --- |
| Large | {long_cell} |

| A | B | C | D | E | F | G |
| - | - | - | - | - | - | - |
| a | b | c | d | e | f | WIDE_LAST_CELL |
""",
    )
    out = tmp_path / "tables.pdf"
    result = render_pdf(discover(tmp_path), out)
    text = "\n".join(page.extract_text() for page in PdfReader(out).pages)
    assert result.pages >= 5
    assert "WIDE_LAST_CELL" in text
    for number in range(190):
        assert f"CELL_LINE_{number:03}" in text


def test_existing_output_and_read_error_do_not_destroy_previous_pdf(tmp_path):
    source = write(tmp_path, "spec.md", "# Source")
    output = tmp_path / "out.pdf"
    render_pdf(discover(tmp_path), output)
    original = output.read_bytes()
    with pytest.raises(ConversionError, match="already exists"):
        render_pdf(discover(tmp_path), output)
    source.write_bytes(b"\xff\xfeinvalid")
    with pytest.raises(ConversionError, match="Cannot read"):
        render_pdf(discover(tmp_path), output, force=True)
    assert output.read_bytes() == original
    assert not list(tmp_path.glob(".markdown-pdf-*"))


def test_explicit_encoding_and_force(tmp_path):
    source = write(tmp_path, "spec.md", "# Before")
    output = tmp_path / "out.pdf"
    assert main([str(tmp_path), "-o", str(output)]) == 0
    source.write_bytes("# Updated café".encode("cp1252"))
    assert main([str(tmp_path), "-o", str(output), "--encoding", "cp1252", "--force"]) == 0
    assert "Updated café" in "\n".join(page.extract_text() for page in PdfReader(output).pages)


def test_default_output_is_beside_input(tmp_path):
    source = tmp_path / "My specs"
    write(source, "spec.md", "# A specification")
    assert main([str(source)]) == 0
    assert (tmp_path / "My specs.pdf").is_file()


@pytest.mark.skipif(os.name != "nt", reason="Windows junction test")
def test_windows_junction_is_pruned(tmp_path):
    import _winapi

    root = tmp_path / "source"
    write(root, "spec.md", "included")
    target = write(tmp_path, "elsewhere/hidden.md", "must not include")
    _winapi.CreateJunction(str(target.parent), str(root / "junction"))
    result = discover(root)
    assert [path.name for path in result.files] == ["spec.md"]
    assert result.skipped == [("junction", "link/junction")]


def test_failed_render_keeps_previous_output_and_cleans_temporary_file(tmp_path, monkeypatch):
    write(tmp_path, "spec.md", "# Source")
    output = tmp_path / "out.pdf"
    output.write_bytes(b"previous export")

    def fail(self, *_args, **_kwargs):
        self.filename.write(b"incomplete PDF")
        raise LayoutError("simulated rendering failure")

    monkeypatch.setattr(MonolithDoc, "multiBuild", fail)
    assert main([str(tmp_path), "-o", str(output), "--force"]) == 2
    assert output.read_bytes() == b"previous export"
    assert not list(tmp_path.glob(".markdown-pdf-*"))


def test_unicode_code_and_custom_html_anchors(tmp_path):
    write(
        tmp_path,
        "spec.md",
        """# Unicode and HTML

<a name="legacy"></a>

[Legacy anchor](#legacy)

<a href="http://[broken">Malformed URL</a>

```text
set_a ∪ set_b; item ∈ set_a; left ∧ right; ✓ ⚠
```

Inline `∪ ∈ ∧` remains selectable.
""",
    )
    output = tmp_path / "out.pdf"
    result = render_pdf(discover(tmp_path), output)
    text = "\n".join(page.extract_text() for page in PdfReader(output).pages)
    # Available Windows/DejaVu symbol fonts cover these. Other hosts warn explicitly.
    if any("unsupported glyph" in warning for warning in result.warnings):
        assert "[U+" in text
    else:
        for char in "∪∈∧✓⚠":
            assert char in text
    assert "Malformed URL" in text and "http://[broken" in text
