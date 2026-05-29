"""Render module-guide Markdown files in this directory to PDF.

Usage:
    ../../../medsim_v6/.venv/bin/python render_pdfs.py        # render all M*.md
    ../../../medsim_v6/.venv/bin/python render_pdfs.py M03_*  # specific guides

The PDFs land next to the .md sources. Re-run on every material
change — the .md is the source of truth, the PDF is the rendered
artifact.

Layout: Letter-size, 0.75" margins, header on every page with module
title, footer with date and page number. Headings, paragraphs, tables,
and code blocks rendered with reportlab's Platypus flowables.
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path
from xml.sax.saxutils import escape

import markdown as md_lib
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph,
    Spacer, Table, TableStyle, PageBreak, Preformatted,
)

HERE = Path(__file__).parent
DATE = time.strftime("%Y-%m-%d")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    body = ParagraphStyle(
        "Body", parent=base["BodyText"],
        fontName="Helvetica", fontSize=10, leading=13.5,
        spaceAfter=6, alignment=TA_LEFT,
    )
    h1 = ParagraphStyle(
        "H1", parent=base["Heading1"],
        fontName="Helvetica-Bold", fontSize=18, leading=22,
        spaceBefore=14, spaceAfter=10, textColor=colors.HexColor("#1a2a4a"),
    )
    h2 = ParagraphStyle(
        "H2", parent=base["Heading2"],
        fontName="Helvetica-Bold", fontSize=13, leading=17,
        spaceBefore=12, spaceAfter=6, textColor=colors.HexColor("#1a2a4a"),
    )
    h3 = ParagraphStyle(
        "H3", parent=base["Heading3"],
        fontName="Helvetica-Bold", fontSize=11, leading=14,
        spaceBefore=8, spaceAfter=4, textColor=colors.HexColor("#1a2a4a"),
    )
    code = ParagraphStyle(
        "Code", parent=base["Code"],
        fontName="Courier", fontSize=8.5, leading=11,
        leftIndent=12, spaceAfter=6,
    )
    quote = ParagraphStyle(
        "Quote", parent=base["BodyText"],
        fontName="Helvetica-Oblique", fontSize=10, leading=13.5,
        leftIndent=12, rightIndent=12,
        textColor=colors.HexColor("#444"), spaceAfter=6,
    )
    return {"body": body, "h1": h1, "h2": h2, "h3": h3,
            "code": code, "quote": quote}


def _on_page(title: str):
    def _draw(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8.5)
        canvas.setFillColor(colors.HexColor("#555"))
        # Header
        canvas.drawString(0.75 * inch, LETTER[1] - 0.5 * inch, title)
        canvas.drawRightString(LETTER[0] - 0.75 * inch,
                                LETTER[1] - 0.5 * inch,
                                "MEDSIM V7 · Module Guide")
        canvas.setStrokeColor(colors.HexColor("#bbb"))
        canvas.line(0.75 * inch, LETTER[1] - 0.55 * inch,
                    LETTER[0] - 0.75 * inch, LETTER[1] - 0.55 * inch)
        # Footer
        canvas.drawString(0.75 * inch, 0.5 * inch, f"Rendered {DATE}")
        canvas.drawRightString(LETTER[0] - 0.75 * inch, 0.5 * inch,
                                f"Page {doc.page}")
        canvas.restoreState()
    return _draw


# ── Minimal markdown → reportlab flowable translator ─────────────────
# We avoid a heavy HTML-to-flowable library. Tokenize the markdown line
# by line, build Paragraph / Table / Preformatted / Spacer flowables.

_INLINE_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_INLINE_CODE = re.compile(r"`([^`]+)`")
_CODE_PLACEHOLDER = "\x00CODE{}\x00"


def _inline(text: str) -> str:
    """Convert inline markdown (bold + code) to reportlab markup.

    Strategy: code spans first, swapped out for placeholders so their
    contents are NOT touched by escape() or bold substitution. Then
    escape, then bold, then restore code spans with their content also
    escaped. Italic (single `*`) is intentionally not supported — it
    collides with `*` inside code spans (e.g. `blocks*` glob patterns)
    and the module guides do not need it.
    """
    # 1. Extract code spans into placeholders.
    spans: list[str] = []
    def _stash(m: re.Match) -> str:
        spans.append(m.group(1))
        return _CODE_PLACEHOLDER.format(len(spans) - 1)
    work = _INLINE_CODE.sub(_stash, text)
    # 2. Escape XML in the surrounding text.
    work = escape(work)
    # 3. Bold.
    work = _INLINE_BOLD.sub(r"<b>\1</b>", work)
    # 4. Restore code spans with their content escaped.
    def _restore(m: re.Match) -> str:
        idx = int(m.group(1))
        return f'<font face="Courier" color="#3a3a3a">{escape(spans[idx])}</font>'
    work = re.sub(r"\x00CODE(\d+)\x00", _restore, work)
    return work


def _parse_table(rows: list[str]) -> Table | None:
    """rows is the list of pipe-table lines including the header and
    separator. Returns a reportlab Table flowable or None on parse error."""
    if len(rows) < 2:
        return None
    def _split(row: str) -> list[str]:
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        return cells
    header = _split(rows[0])
    # rows[1] is the separator (---|---|---) — skip
    body = [_split(r) for r in rows[2:] if r.strip()]
    data = [header] + body
    # Wrap every cell in a Paragraph so long content wraps.
    body_style = ParagraphStyle("TblBody", fontName="Helvetica",
                                 fontSize=8.5, leading=11)
    head_style = ParagraphStyle("TblHead", fontName="Helvetica-Bold",
                                 fontSize=9, leading=11,
                                 textColor=colors.white)
    wrapped: list[list[Paragraph]] = []
    for i, row in enumerate(data):
        style = head_style if i == 0 else body_style
        wrapped.append([Paragraph(_inline(cell), style) for cell in row])
    tbl = Table(wrapped, repeatRows=1, hAlign="LEFT")
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a2a4a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#bbb")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f5f6fa")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return tbl


def md_to_flowables(md: str, styles: dict[str, ParagraphStyle]) -> list:
    """Translate markdown source to reportlab flowables."""
    flowables: list = []
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        # Code fence
        if line.startswith("```"):
            buf = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1  # skip closing fence
            flowables.append(Preformatted("\n".join(buf), styles["code"]))
            continue
        # Table (pipe table)
        if line.lstrip().startswith("|"):
            buf = [line]
            i += 1
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                buf.append(lines[i])
                i += 1
            tbl = _parse_table(buf)
            if tbl is not None:
                flowables.append(tbl)
                flowables.append(Spacer(1, 4))
            continue
        # Headings
        if line.startswith("# "):
            flowables.append(Paragraph(_inline(line[2:]), styles["h1"]))
            i += 1
            continue
        if line.startswith("## "):
            flowables.append(Paragraph(_inline(line[3:]), styles["h2"]))
            i += 1
            continue
        if line.startswith("### "):
            flowables.append(Paragraph(_inline(line[4:]), styles["h3"]))
            i += 1
            continue
        # Horizontal rule
        if line.strip() in ("---", "***", "___"):
            flowables.append(Spacer(1, 4))
            i += 1
            continue
        # Block quote
        if line.startswith("> "):
            buf = [line[2:]]
            i += 1
            while i < len(lines) and lines[i].startswith("> "):
                buf.append(lines[i][2:])
                i += 1
            flowables.append(Paragraph(_inline(" ".join(buf)), styles["quote"]))
            continue
        # Unordered list (simple — flatten to a single paragraph with bullets)
        if line.lstrip().startswith(("- ", "* ")):
            buf = []
            while i < len(lines) and lines[i].lstrip().startswith(("- ", "* ")):
                buf.append(lines[i].lstrip()[2:])
                i += 1
            for item in buf:
                flowables.append(Paragraph("• " + _inline(item),
                                            styles["body"]))
            continue
        # Blank line — paragraph break
        if not line.strip():
            i += 1
            continue
        # Body paragraph — gather contiguous non-empty lines
        buf = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not lines[i].startswith(
            ("#", "|", "```", "> ", "- ", "* ")
        ) and lines[i].strip() not in ("---", "***", "___"):
            buf.append(lines[i])
            i += 1
        flowables.append(Paragraph(_inline(" ".join(buf)), styles["body"]))
    return flowables


def render_one(md_path: Path) -> Path:
    text = md_path.read_text()
    # First-line "# {title}" becomes the running header.
    first_line = next((ln for ln in text.splitlines() if ln.strip()), "")
    title = first_line.lstrip("# ").strip() or md_path.stem
    pdf_path = md_path.with_suffix(".pdf")
    doc = BaseDocTemplate(
        str(pdf_path), pagesize=LETTER,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        topMargin=0.85 * inch, bottomMargin=0.75 * inch,
        title=title,
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin,
                  doc.width, doc.height, id="body")
    doc.addPageTemplates([
        PageTemplate(id="default", frames=[frame],
                     onPage=_on_page(title))
    ])
    styles = _styles()
    flowables = md_to_flowables(text, styles)
    doc.build(flowables)
    return pdf_path


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        patterns = argv[1:]
    else:
        patterns = ["M*.md"]
    targets: list[Path] = []
    for pat in patterns:
        targets.extend(sorted(HERE.glob(pat)))
    # Don't accidentally render the template.
    targets = [t for t in targets if t.name != "MODULE_GUIDE_TEMPLATE.md"]
    if not targets:
        print("No module guides matched.", file=sys.stderr)
        return 1
    for md_path in targets:
        out = render_one(md_path)
        print(f"rendered {md_path.name} → {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
