"""Markdown-to-ReportLab rendering without executing HTML or loading resources."""

from __future__ import annotations

import hashlib
import math
import os
import re
import tempfile
from dataclasses import dataclass
from html import escape
from pathlib import Path
from urllib.parse import unquote, urlsplit

import reportlab
from bs4 import BeautifulSoup, Comment, NavigableString, Tag
from markdown_it import MarkdownIt
from mdit_py_plugins.deflist import deflist_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.tasklists import tasklists_plugin
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    HRFlowable,
    LayoutError,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

from .discovery import ConversionError, Discovery, linked

INK = colors.HexColor("#17202d")
BLUE = colors.HexColor("#255577")
MUTED = colors.HexColor("#54616e")
PALE = colors.HexColor("#f1f4f7")


@dataclass
class Source:
    path: Path
    relative: str
    anchor: str
    text: str
    digest: str
    soup: BeautifulSoup


@dataclass
class RenderResult:
    pages: int
    documents: int
    warnings: list[str]


def register_fonts() -> tuple[str, str, str | None]:
    """Use installed Unicode fonts, with bundled Bitstream Vera as a fallback."""
    windows = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    dejavu = Path("/usr/share/fonts/truetype/dejavu")
    bundled = Path(reportlab.__file__).parent / "fonts"
    families = [
        (windows, ["segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf", "segoeuiz.ttf"]),
        (
            dejavu,
            [
                "DejaVuSans.ttf",
                "DejaVuSans-Bold.ttf",
                "DejaVuSans-Oblique.ttf",
                "DejaVuSans-BoldOblique.ttf",
            ],
        ),
        (bundled, ["Vera.ttf", "VeraBd.ttf", "VeraIt.ttf", "VeraBI.ttf"]),
    ]
    names = ["MD-Sans", "MD-Sans-Bold", "MD-Sans-Italic", "MD-Sans-BoldItalic"]
    for folder, files in families:
        if all((folder / filename).is_file() for filename in files):
            for name, filename in zip(names, files, strict=True):
                pdfmetrics.registerFont(TTFont(name, str(folder / filename)))
            break
    pdfmetrics.registerFontFamily(
        names[0], normal=names[0], bold=names[1], italic=names[2], boldItalic=names[3]
    )
    mono = "Courier"
    for candidate in [windows / "consola.ttf", dejavu / "DejaVuSansMono.ttf"]:
        if candidate.is_file():
            mono = "MD-Mono"
            pdfmetrics.registerFont(TTFont(mono, str(candidate)))
            break
    fallback = None
    for candidate in [windows / "seguisym.ttf", dejavu / "DejaVuSans.ttf"]:
        if candidate.is_file():
            fallback = "MD-Symbol"
            pdfmetrics.registerFont(TTFont(fallback, str(candidate)))
            break
    return names[0], mono, fallback


def slug(text: str) -> str:
    return re.sub(r"[^\w\- ]", "", text.casefold()).replace(" ", "-")


def load_sources(discovery: Discovery, encoding: str) -> list[Source]:
    markdown = (
        MarkdownIt("commonmark", {"html": True})
        .enable(["table", "strikethrough"])
        .use(footnote_plugin)
        .use(deflist_plugin)
        .use(tasklists_plugin)
    )
    sources = []
    for number, path in enumerate(discovery.files, 1):
        relative = path.relative_to(discovery.root).as_posix()
        try:
            if linked(path) or any(linked(parent) for parent in path.parents):
                raise ConversionError(f"Source became a link or junction: {relative}")
            raw = path.read_bytes()
            text = raw.decode(encoding)
        except (OSError, UnicodeError, LookupError) as exc:
            raise ConversionError(
                f"Cannot read {relative} with encoding {encoding}: {exc}. "
                "Use --encoding for non-UTF-8 files."
            ) from exc
        # Render front matter as data rather than losing it as metadata.
        match = re.match(r"\A---\r?\n(.*?)\r?\n(?:---|\.\.\.)(?:\r?\n|$)", text, re.S)
        prefix = ""
        body = text
        if match:
            prefix = '<pre data-language="yaml front matter">' + escape(match[0]) + "</pre>"
            body = text[match.end() :]
        soup = BeautifulSoup(prefix + markdown.render(body), "html.parser")
        for backlink in soup.select("a.footnote-backref"):
            backlink.string = "back"
        for link in soup.find_all("a", attrs={"name": True}):
            if not link.has_attr("id"):
                link["id"] = link["name"]
        seen: dict[str, int] = {}
        for heading in soup.find_all(re.compile(r"^h[1-6]$")):
            base = heading.get("id") or slug(heading.get_text()) or "section"
            count = seen.get(base, 0)
            seen[base] = count + 1
            heading["id"] = base if count == 0 else f"{base}-{count}"
        sources.append(
            Source(
                path, relative, f"document-{number}", text, hashlib.sha256(raw).hexdigest(), soup
            )
        )
    return sources


class CodeBlock(Flowable):
    """Page-splittable, width-wrapped code. Never shrink or clip long lines."""

    def __init__(
        self, lines: list[str], font: str, *, fallback: str | None = None, wrapped: bool = False
    ):
        super().__init__()
        self.lines = lines
        self.font = font
        self.fallback = fallback
        self.wrapped = wrapped
        self.font_size = 8
        self.leading = 11
        self.padding = 9
        self.spaceBefore = 5
        self.spaceAfter = 9

    def runs(self, text: str):
        """Keep code monospace except glyphs that need the Unicode fallback font."""
        mapping = getattr(pdfmetrics.getFont(self.font).face, "charToGlyph", None)
        last_font = self.font
        run = []
        for char in text:
            present = ord(char) in mapping if mapping is not None else ord(char) < 127
            font = self.font if present or not self.fallback else self.fallback
            if font != last_font and run:
                yield last_font, "".join(run)
                run = []
            last_font = font
            run.append(char)
        if run:
            yield last_font, "".join(run)

    def text_width(self, text: str) -> float:
        return sum(
            pdfmetrics.stringWidth(run, font, self.font_size) for font, run in self.runs(text)
        )

    def wrap(self, availWidth, availHeight):  # noqa: N803 - ReportLab API
        self.width = availWidth
        if not self.wrapped:
            limit = max(1, availWidth - self.padding * 2)
            wrapped = []
            for original in self.lines:
                line = original.expandtabs(4)
                if not line:
                    wrapped.append("")
                while line:
                    # Binary search also handles long unbroken URLs and identifiers.
                    low, high = 1, len(line)
                    while low < high:
                        middle = (low + high + 1) // 2
                        if self.text_width(line[:middle]) <= limit:
                            low = middle
                        else:
                            high = middle - 1
                    wrapped.append(line[:low])
                    line = line[low:]
            self.lines = wrapped
            self.wrapped = True
        self.height = len(self.lines) * self.leading + self.padding * 2
        return self.width, self.height

    def split(self, availWidth, availHeight):  # noqa: N803
        count = math.floor((availHeight - self.padding * 2) / self.leading)
        if count < 1:
            return []
        if count >= len(self.lines):
            return [self]
        return [
            CodeBlock(self.lines[:count], self.font, fallback=self.fallback, wrapped=True),
            CodeBlock(self.lines[count:], self.font, fallback=self.fallback, wrapped=True),
        ]

    def draw(self):
        canvas = self.canv
        canvas.setFillColor(PALE)
        canvas.rect(0, 0, self.width, self.height, fill=1, stroke=0)
        canvas.setFillColor(INK)
        canvas.setFont(self.font, self.font_size)
        y = self.height - self.padding - self.font_size
        for line in self.lines:
            x = self.padding
            for font, run in self.runs(line):
                canvas.setFont(font, self.font_size)
                canvas.drawString(x, y, run)
                x += pdfmetrics.stringWidth(run, font, self.font_size)
            y -= self.leading


class Anchor(Flowable):
    """A destination that takes no layout space and stays with the next block."""

    def __init__(self, name: str):
        super().__init__()
        self.name = name
        self.keepWithNext = True

    def draw(self):
        self.canv.bookmarkHorizontal(self.name, 0, 0)


class MonolithDoc(BaseDocTemplate):
    def __init__(self, filename, title, page_size, font):
        super().__init__(
            filename,
            pagesize=page_size,
            leftMargin=44,
            rightMargin=44,
            topMargin=48,
            bottomMargin=44,
            title=title,
            author="Markdown directory export",
            pageCompression=1,
        )
        self.font = font
        self.current_source = "Document index"
        self.page_count = 0
        frame = Frame(
            self.leftMargin,
            self.bottomMargin,
            self.width,
            self.height,
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
        )
        self.addPageTemplates(PageTemplate(id="main", frames=frame, onPageEnd=self.footer))

    def beforeDocument(self):
        self.current_source = "Document index"

    def afterFlowable(self, flowable):
        if hasattr(flowable, "running_title"):
            self.current_source = flowable.running_title
        if hasattr(flowable, "source_path"):
            self.current_source = flowable.source_path
            self.canv.bookmarkPage(flowable.anchor)
            self.canv.addOutlineEntry(flowable.source_path, flowable.anchor, level=0)
            self.notify("TOCEntry", (0, escape(flowable.source_path), self.page, flowable.anchor))

    def footer(self, canvas, doc):
        canvas.saveState()
        canvas.setFont(self.font, 8)
        canvas.setFillColor(MUTED)
        label = self.current_source
        while pdfmetrics.stringWidth(label, self.font, 8) > self.width:
            label = "..." + label[4:]
        canvas.drawString(self.leftMargin, self.pagesize[1] - 30, label)
        canvas.setStrokeColor(colors.HexColor("#d9e0e6"))
        canvas.line(self.leftMargin, 32, self.pagesize[0] - self.rightMargin, 32)
        canvas.drawString(self.leftMargin, 20, "Markdown collection")
        canvas.drawRightString(self.pagesize[0] - self.rightMargin, 20, str(doc.page))
        self.page_count = doc.page
        canvas.restoreState()


class Renderer:
    def __init__(self, sources: list[Source], width: float):
        self.sources = sources
        self.width = width
        self.font, self.mono, self.fallback = register_fonts()
        self.warnings: set[str] = set()
        self.source = sources[0]
        self.emitted: set[str] = set()
        self.by_path = {source.path: source for source in sources}
        self.ids = {
            source.anchor: {str(tag["id"]) for tag in source.soup.find_all(id=True)}
            for source in sources
        }
        self.styles = getSampleStyleSheet()
        self.styles["Normal"].fontName = self.font
        self.styles["Normal"].fontSize = 10
        self.styles["Normal"].leading = 14
        self.styles["Normal"].textColor = INK
        self.styles["Normal"].spaceAfter = 7
        self.styles["Normal"].splitLongWords = True
        self.styles["Normal"].allowWidows = 0
        self.styles["Normal"].allowOrphans = 0
        for number in range(1, 7):
            style = self.styles[f"Heading{number}"]
            style.fontName = "MD-Sans-Bold"
            style.fontSize = [18, 15, 12, 11, 10, 10][number - 1]
            style.leading = style.fontSize * 1.25
            style.textColor = INK
            style.spaceBefore = 12
            style.spaceAfter = 7
            style.keepWithNext = True
        self.styles.add(
            ParagraphStyle(
                "Source",
                parent=self.styles["Normal"],
                fontSize=9,
                leading=12,
                textColor=BLUE,
                spaceAfter=12,
            )
        )
        self.styles.add(
            ParagraphStyle(
                "Small", parent=self.styles["Normal"], fontSize=8, leading=11, textColor=MUTED
            )
        )
        self.styles.add(
            ParagraphStyle(
                "Cell", parent=self.styles["Normal"], fontSize=8, leading=11, spaceAfter=2
            )
        )

    def supported(self, char: str, font: str) -> bool:
        face = pdfmetrics.getFont(font).face
        mapping = getattr(face, "charToGlyph", None)
        return ord(char) in mapping if mapping is not None else ord(char) < 127

    def plain(self, text: str, font: str | None = None, *, fallback: bool = False) -> str:
        font = font or self.font
        output = []
        for char in text:
            if (
                char in "\n\r\t"
                or self.supported(char, font)
                or (fallback and self.fallback and self.supported(char, self.fallback))
            ):
                output.append(char)
            else:
                marker = f"[U+{ord(char):04X}]"
                output.append(marker)
                self.warnings.add(
                    f"{self.source.relative}: unsupported glyph {marker}; "
                    "a Unicode code-point marker was printed."
                )
        return "".join(output)

    def text(self, text: str) -> str:
        parts = []
        for char in text:
            if char.isspace() or self.supported(char, self.font):
                parts.append(escape(char))
            elif self.fallback and self.supported(char, self.fallback):
                parts.append(f'<font name="{self.fallback}">{escape(char)}</font>')
            else:
                parts.append(escape(self.plain(char)))
        return "".join(parts)

    def anchor(self, identifier: str) -> str:
        # PDF anchors are opaque and never used as markup directly.
        digest = hashlib.sha256(identifier.encode()).hexdigest()[:20]
        return f"{self.source.anchor}-{digest}"

    def mark_anchor(self, identifier: str) -> str:
        name = self.anchor(identifier)
        self.emitted.add(name)
        return name

    def link(self, target: str) -> str | None:
        try:
            parsed = urlsplit(target)
        except ValueError:
            self.warnings.add(
                f"{self.source.relative}: a malformed link was printed as plain text."
            )
            return None
        if parsed.scheme.casefold() in {"https", "http", "mailto"}:
            return target
        if parsed.scheme or parsed.netloc:
            return None
        path = Path(os.path.abspath(self.source.path.parent / unquote(parsed.path)))
        destination = self.by_path.get(path) if parsed.path else self.source
        if not destination:
            return None
        if not parsed.fragment:
            return "#" + destination.anchor
        identifier = unquote(parsed.fragment)
        if identifier not in self.ids[destination.anchor]:
            return None
        digest = hashlib.sha256(identifier.encode()).hexdigest()[:20]
        return f"#{destination.anchor}-{digest}"

    def inline(self, node) -> str:
        if isinstance(node, Comment):
            return self.text(f"<!--{node}-->")
        if isinstance(node, NavigableString):
            return self.text(str(node))
        if not isinstance(node, Tag):
            return ""
        content = "".join(self.inline(child) for child in node.children)
        prefix = f'<a name="{self.mark_anchor(str(node["id"]))}"/>' if node.has_attr("id") else ""
        name = node.name.lower()
        if name in {"strong", "b"}:
            content = f"<b>{content}</b>"
        elif name in {"em", "i"}:
            content = f"<i>{content}</i>"
        elif name in {"s", "del", "strike"}:
            content = f"<strike>{content}</strike>"
        elif name in {"sup", "sub", "u"}:
            content = f"<{name}>{content}</{name}>"
        elif name in {"code", "kbd", "samp"}:
            code = self.plain(node.get_text(), self.mono, fallback=True)
            runs = CodeBlock([], self.mono, fallback=self.fallback).runs(code)
            content = "".join(
                f'<font name="{font}" size="9">{escape(run)}</font>' for font, run in runs
            )
        elif name == "br":
            content = "<br/>"
        elif name == "a":
            href = str(node.get("href", ""))
            destination = self.link(href) if href else None
            if destination:
                content = (
                    f'<a href="{escape(destination, quote=True)}" color="#255577">'
                    + (content or self.text(href))
                    + "</a>"
                )
            footnote_link = {"footnote-backref", "footnote-ref"}.intersection(node.get("class", []))
            if href and href != node.get_text() and not footnote_link:
                content += " (" + self.text(href) + ")"
        elif name == "input":
            content = "[x] " if node.has_attr("checked") else "[ ] "
        elif name == "img":
            content = self.text(
                f"[Image: {node.get('alt', 'no alt text')}; "
                f"source: {node.get('src', 'unspecified')}]"
            )
            self.warnings.add(
                f"{self.source.relative}: images are represented by alt text and path."
            )
        elif name in {"script", "style", "iframe", "object", "embed", "svg", "math"}:
            content = self.text(str(node))
            self.warnings.add(f"{self.source.relative}: <{name}> was preserved as literal HTML.")
        return prefix + content

    def paragraph(self, markup: str, style: str = "Normal", depth: int = 0) -> Paragraph:
        base = self.styles[style]
        if depth:
            base = ParagraphStyle(f"{style}-{depth}", parent=base, leftIndent=min(depth, 8) * 14)
        return Paragraph(markup or "&#160;", base)

    def code(self, text: str, language: str = "") -> CodeBlock:
        # Keep fence labels in extractable text, including unrecognized languages.
        fence = "`" * max(3, max((len(run) + 1 for run in re.findall(r"`+", text)), default=3))
        text = self.plain(text.replace("\r\n", "\n").replace("\r", "\n"), self.mono, fallback=True)
        lines = (
            fence + self.plain(language, self.mono) + "\n" + text.rstrip("\n") + "\n" + fence
        ).split("\n")
        return CodeBlock(lines, self.mono, fallback=self.fallback)

    def table(self, node: Tag, depth: int) -> list[Flowable]:
        rows = []
        for row in node.find_all("tr"):
            if row.find_parent("table") is node:
                cells = row.find_all(["th", "td"], recursive=False)
                if cells:
                    rows.append(cells)
        if not rows:
            return [self.paragraph(self.inline(node), depth=depth)]
        columns = max(len(row) for row in rows)
        if columns > 6 or any(
            cell.has_attr("colspan") or cell.has_attr("rowspan") for row in rows for cell in row
        ):
            # Wide or merged tables become readable row records, preserving every cell.
            self.warnings.add(
                f"{self.source.relative}: a wide/merged table was rendered as row records."
            )
            output = []
            headers = rows[0] if all(cell.name == "th" for cell in rows[0]) else []
            body = rows[1:] if headers else rows
            for number, row in enumerate(body, 1):
                output.append(self.paragraph(f"<b>Table row {number}</b>", depth=depth))
                for index, cell in enumerate(row):
                    label = (
                        self.inline(headers[index])
                        if index < len(headers)
                        else f"Column {index + 1}"
                    )
                    output.append(
                        self.paragraph(f"<b>{label}:</b> {self.inline(cell)}", depth=depth)
                    )
            return output
        data = [
            [self.paragraph(self.inline(cell), "Cell") for cell in row]
            + [""] * (columns - len(row))
            for row in rows
        ]
        has_header = all(cell.name == "th" for cell in rows[0])
        table = Table(
            data,
            colWidths=[self.width / columns] * columns,
            repeatRows=1 if has_header else 0,
            splitByRow=1,
            splitInRow=1,
            hAlign="LEFT",
            spaceBefore=4,
            spaceAfter=10,
        )
        commands = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d5dee6")),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]
        if has_header:
            commands.append(("BACKGROUND", (0, 0), (-1, 0), PALE))
        table.setStyle(TableStyle(commands))
        return [table]

    def blocks(self, parent, depth: int = 0) -> list[Flowable]:
        output = []
        inline_nodes = []

        def flush():
            if inline_nodes:
                content = "".join(self.inline(node) for node in inline_nodes).strip()
                if content:
                    output.append(self.paragraph(content, depth=depth))
                inline_nodes.clear()

        block_names = {
            "p",
            "pre",
            "ul",
            "ol",
            "li",
            "blockquote",
            "table",
            "hr",
            "div",
            "section",
            "article",
            "details",
            "summary",
            "dl",
            "dt",
            "dd",
            "center",
            "script",
            "style",
            "iframe",
            "object",
            "svg",
            "math",
        }
        for node in parent.children:
            if not isinstance(node, Tag) or (
                node.name not in block_names and not re.fullmatch(r"h[1-6]", node.name)
            ):
                inline_nodes.append(node)
                continue
            flush()
            if node.has_attr("id") and node.name not in {"p", "summary", "dt"}:
                output.append(Anchor(self.mark_anchor(str(node["id"]))))
            if re.fullmatch(r"h[1-6]", node.name):
                content = "".join(self.inline(child) for child in node.children)
                output.append(self.paragraph(content, f"Heading{node.name[1]}", depth))
            elif node.name in {"p", "summary", "dt"}:
                content = self.inline(node)
                if node.name in {"summary", "dt"}:
                    content = f"<b>{content}</b>"
                paragraph = self.paragraph(content, depth=depth)
                children = [child for child in node.children if str(child).strip()]
                if node.name in {"summary", "dt"} or (
                    len(children) == 1
                    and isinstance(children[0], Tag)
                    and children[0].name in {"b", "strong"}
                ):
                    paragraph.keepWithNext = True
                output.append(paragraph)
            elif node.name == "pre":
                code = node.find("code")
                language = str(node.get("data-language", ""))
                if code:
                    classes = code.get("class", [])
                    language = next(
                        (item[9:] for item in classes if item.startswith("language-")), ""
                    )
                output.append(self.code(node.get_text(), language))
            elif node.name in {"ul", "ol"}:
                try:
                    start = int(node.get("start", 1))
                except ValueError:
                    start = 1
                for index, item in enumerate(node.find_all("li", recursive=False), start):
                    if item.has_attr("id"):
                        output.append(Anchor(self.mark_anchor(str(item["id"]))))
                    children = self.blocks(item, depth + 1)
                    marker = f"{index}." if node.name == "ol" else "-"
                    if children and isinstance(children[0], Paragraph):
                        children[0].bulletText = marker
                        children[0].style = ParagraphStyle(
                            "ListItem",
                            parent=children[0].style,
                            bulletFontName=self.font,
                            bulletFontSize=10,
                            bulletIndent=min(depth, 8) * 14,
                        )
                    else:
                        children.insert(0, self.paragraph(marker, depth=depth))
                    output.extend(children)
            elif node.name == "table":
                output.extend(self.table(node, depth))
            elif node.name == "hr":
                output.append(
                    HRFlowable(
                        width="100%", color=colors.HexColor("#d5dee6"), spaceBefore=8, spaceAfter=10
                    )
                )
            elif node.name in {"script", "style", "iframe", "object", "svg", "math"}:
                output.append(self.code(str(node), "html"))
                self.warnings.add(
                    f"{self.source.relative}: <{node.name}> was preserved as literal HTML."
                )
            else:
                output.extend(self.blocks(node, depth + (node.name in {"blockquote", "dd"})))
        flush()
        return output

    def story(self, title: str, discovery: Discovery) -> list[Flowable]:
        toc = TableOfContents()
        toc.levelStyles = [
            ParagraphStyle(
                "Index",
                parent=self.styles["Normal"],
                fontSize=9,
                leading=13,
                spaceBefore=5,
                alignment=TA_LEFT,
            )
        ]
        output = [
            self.paragraph(self.text(title), "Heading1"),
            self.paragraph(f"{len(self.sources)} Markdown documents", "Source"),
            self.paragraph(
                "Documents are ordered by relative path, with README first in each "
                "folder and numbers sorted naturally. Each document starts on a new "
                "page. Source paths and SHA-256 hashes identify the original files."
            ),
            self.paragraph(
                "Code fences and language labels are retained. Long code lines wrap; "
                "tabs display as four spaces. Images appear as alt text and source "
                "paths. HTML is interpreted as document structure or shown literally; "
                "scripts and external resources are never executed or loaded."
            ),
            self.paragraph(
                f"Excluded entries: {len(discovery.skipped)}. Hidden, private, "
                "dependency, generated, and linked entries are omitted.",
                "Small",
            ),
            Spacer(1, 10),
            self.paragraph("Document index", "Heading2"),
            toc,
        ]
        for number, source in enumerate(self.sources, 1):
            self.source = source
            heading = self.paragraph(f"Document {number} / {len(self.sources)}", "Heading2")
            heading.source_path = self.plain(source.relative)
            heading.anchor = source.anchor
            output.extend(
                [
                    PageBreak(),
                    heading,
                    self.paragraph("Source: " + self.text(source.relative), "Source"),
                    self.paragraph("SHA-256: " + source.digest, "Small"),
                    Spacer(1, 6),
                ]
            )
            content = self.blocks(source.soup)
            # IDs inside literal HTML or table containers still get usable destinations.
            for identifier in sorted(self.ids[source.anchor]):
                if self.anchor(identifier) not in self.emitted:
                    output.append(Anchor(self.mark_anchor(identifier)))
            output.extend(content or [self.paragraph("[Empty Markdown document]")])
        if self.warnings:
            heading = self.paragraph("Conversion notes", "Heading1")
            heading.running_title = "Conversion notes"
            output.extend([PageBreak(), heading])
            output.extend(
                self.paragraph(self.text(warning), "Small") for warning in sorted(self.warnings)
            )
        return output


def render_pdf(
    discovery: Discovery,
    output: Path,
    *,
    title: str | None = None,
    encoding: str = "utf-8-sig",
    page_size: str = "a4",
    force: bool = False,
) -> RenderResult:
    if output.suffix.casefold() != ".pdf":
        raise ConversionError("The output filename must end in .pdf.")
    if output.exists() and not force:
        raise ConversionError(f"Output already exists: {output}. Use --force to replace it.")
    if output.is_symlink() or (output.exists() and linked(output)):
        raise ConversionError("The output must not be a link or junction.")
    sources = load_sources(discovery, encoding)
    size = A4 if page_size == "a4" else LETTER
    renderer = Renderer(sources, size[0] - 88)
    title = title or discovery.root.name + " - Markdown collection"
    title = renderer.plain(title)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(prefix=".markdown-pdf-", suffix=".pdf", dir=output.parent)
    temporary = Path(filename)
    try:
        # Own the stream so ReportLab cannot leave it open after a rendering failure.
        with os.fdopen(fd, "wb") as stream:
            doc = MonolithDoc(stream, title, size, renderer.font)
            try:
                doc.multiBuild(renderer.story(title, discovery))
            except LayoutError as exc:
                raise ConversionError(f"Cannot lay out {doc.current_source}: {exc}") from exc
        if force:
            os.replace(temporary, output)
        else:
            # Atomic, no-clobber publication, including files created during rendering.
            try:
                os.link(temporary, output)
            except FileExistsError as exc:
                raise ConversionError(f"Output appeared during conversion: {output}") from exc
        return RenderResult(doc.page_count, len(sources), sorted(renderer.warnings))
    finally:
        temporary.unlink(missing_ok=True)
