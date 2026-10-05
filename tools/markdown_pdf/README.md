# Markdown directory to PDF

A local command-line tool for handing a directory of development specifications to an
LLM as one searchable PDF. It recursively discovers Markdown, includes a linked file
index and PDF bookmarks, and starts each source document on a new page with its relative
path and SHA-256 hash. It does not modify source files.

## Run

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) if needed. From the
repository in PowerShell:

```powershell
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
# Prompt for the directory. Blank input cancels.
uv run --project tools/markdown_pdf --locked --no-dev markdown-pdf
# Explicit input, output and title.
uv run --project tools/markdown_pdf --locked --no-dev markdown-pdf docs/design_spec -o output/pdf/design-specs.pdf --title "Development specifications"
# Preview files and exclusions without reading document contents.
uv run --project tools/markdown_pdf --locked --no-dev markdown-pdf docs/design_spec --list
# Restrict a whole-docs export to maintained material as needed.
uv run --project tools/markdown_pdf --locked --no-dev markdown-pdf docs --exclude history --exclude evidence --exclude legacy --exclude design_spec --exclude methods
```

Run from the repository root, or use an absolute path with `--project`. The earlier
PowerShell launcher is absent in this checkout; the project CLI above is the
supported source entry point. Input is a positional directory argument.

The default output is `DIRECTORY.pdf` **beside** the selected directory. Existing
PDFs are protected; pass `--force` only when deliberately replacing an export.
Prefer a new named output under `output/pdf/` to retain previous exports. Relative
output paths resolve from the working directory and must end in `.pdf`.

Dependency installation may use the network on first run. Conversion itself reads local
Markdown and generates the PDF locally; it does not upload documents, fetch images or
stylesheets, run JavaScript, or execute code blocks. No browser, Pandoc, or LaTeX is needed.
The tool has its own environment and lockfile; ITOV's runtime dependencies are unchanged.

## Discovery and exclusions

- Extensions: `.md`, `.markdown`, `.mdown`, `.mkd`, case insensitive.
- Order: relative paths, natural numeric ordering (`2` before `10`), README first within
  each directory. Number filenames when you need a particular reading order.
- Dot-prefixed files/directories are skipped.
- Names containing the words `sensitive`, `private`, `secret`, `secrets`, `credentials`,
  or `confidential` are skipped, case insensitive. Words are separated by punctuation,
  whitespace, or underscores; for example `sensitive`, `private-notes`, and `api_secrets`.
- Dependency/generated directories are skipped: `node_modules`, `vendor`, `venv`, `env`,
  `__pycache__`, `site-packages`, `build`, `dist`, `target`, `coverage`, `htmlcov`, `output`,
  `tmp`, `temp`, `workspace`, `$recycle.bin`, and `System Volume Information`.
- Symbolic links and Windows junctions/reparse points are skipped. Input paths passing
  through links or private directories are rejected.
- `--exclude` matches a filename/directory name or a root-relative path using glob
  wildcards. Matching a directory prunes its entire subtree before opening it.

These are filename rules, not a content classifier or a guarantee about another LLM's
upload/content policies. The tool does not read excluded directories or redact included
documents. It does not interpret `.gitignore`; use `--exclude` for project-specific rules.
The PDF records an exclusion count; `--list` shows the names and reasons locally.

## Formatting and preservation

- No markdownlint check is required. CommonMark, tables, strikethrough, task lists,
  definition lists, and footnotes are supported.
- Headings, paragraphs, lists, blockquotes, simple HTML structure, `<details>` contents,
  emphasis, line breaks, and links are rendered as document content.
- Fenced code stays selectable text in a monospace font, with visible fences and language
  labels. All fence languages are accepted, including Mermaid, which remains source text.
  Long lines wrap without truncation; tabs display as four spaces. Code can cross pages.
  The PDF is an ingestion copy, not a byte-for-byte source reconstruction.
- Tables wrap and paginate. Tables wider than six columns or containing merged cells are
  presented as labeled row records to keep their content readable.
- YAML front matter is preserved as a code block.
- Included Markdown file links and known heading anchors become internal PDF links.
  External link destinations remain visible and HTTP/HTTPS/mailto links are clickable.
- Images are represented by alt text and source path; image pixels are not embedded.
- Scripts, styles, SVG, MathML, and embedded active HTML are printed literally. Custom CSS
  is not applied. HTML is never passed through as ReportLab markup.
- UTF-8 (with or without BOM) is the default. Use `--encoding cp1252`, for example, for
  older documents. An unreadable source fails the export instead of silently omitting it.
- Installed Segoe UI/Consolas or DejaVu fonts are preferred; bundled Vera and Courier are
  fallbacks. Unsupported characters are printed as `[U+XXXX]` with explicit warnings.
  This is intended primarily for English specs; emoji and multilingual typography are
  not fully covered.
- Conversion notes are included in the PDF when formatting fallbacks occur.

Options also include `--page-size letter` (default A4), `--title`, and `--help`.
Exit codes: `0` success or blank-input cancellation; `2` invalid input/conversion failure;
`130` interrupted prompt or Ctrl+C.

## Verify the tool

```powershell
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
uv run --project tools/markdown_pdf --locked pytest tools/markdown_pdf/tests
```

Tests cover prompt bypass, discovery pruning, path ordering, links, exclusions, overwrite
protection, encoding errors, text extraction, code/table pagination, and page text bounds.
Visual review is also needed when making changes to layout.
