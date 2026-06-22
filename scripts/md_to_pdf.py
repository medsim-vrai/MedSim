#!/usr/bin/env python3
"""Lightweight Markdown -> PDF for the field-test scripts (and similar docs).

Handles the constructs these docs actually use: # / ## / ### headings, GitHub
pipe tables (header + rows; the `|---|` separator is dropped), paragraphs with
**bold** / *italic* / `code` / [text](link), blockquotes, `- ` bullets, and `---`
rules. Pipe-table cells wrap (each cell is a Paragraph); a trailing "Pass" column
renders as an empty boxed cell to tick on paper.

Glyphs the built-in Helvetica can't draw (emoji, arrows, ballot boxes) are mapped
to ASCII or dropped, so nothing prints as a tofu box.

Usage:  python3 scripts/md_to_pdf.py <input.md> [output.pdf]
"""
import html
import re
import sys

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

NAVY = colors.HexColor("#1f3a5f")
GREY = colors.HexColor("#6b7280")
LINE = colors.HexColor("#9aa4b2")
ZEBRA = colors.HexColor("#f2f5f9")

# --- glyph sanitising (built-in fonts are WinAnsi-ish) -----------------------
_ARROWS = {"→": "->", "←": "<-", "↔": "<->", "↗": "^",
           "↩": "<-", "⧉": "", "☐": "", "☑": "[x]"}
_KEEP = {0x2013, 0x2014, 0x2018, 0x2019, 0x201C, 0x201D, 0x2026, 0x2022}


def sanitize(s: str) -> str:
    for k, v in _ARROWS.items():
        s = s.replace(k, v)
    out = []
    for ch in s:
        o = ord(ch)
        if 0x20 <= o <= 0x7E or 0xA0 <= o <= 0xFF or o in _KEEP:
            out.append(ch)
        # else: emoji / unsupported symbol -> drop
    return "".join(out)


def inline(s: str) -> str:
    """Markdown inline -> reportlab mini-HTML."""
    s = sanitize(s)
    s = html.escape(s, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"`(.+?)`", r'<font face="Courier">\1</font>', s)
    s = re.sub(r"\[(.+?)\]\((.+?)\)", r"\1", s)
    s = re.sub(r"\*(.+?)\*", r"<i>\1</i>", s)
    return s


# --- styles ------------------------------------------------------------------
TITLE = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=16,
                       leading=19, textColor=NAVY, spaceAfter=6)
H2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=12.5, leading=15,
                    textColor=NAVY, spaceBefore=12, spaceAfter=4)
H3 = ParagraphStyle("h3", fontName="Helvetica-Bold", fontSize=10.5, leading=13,
                    textColor=colors.HexColor("#33405a"), spaceBefore=6,
                    spaceAfter=3)
BODY = ParagraphStyle("body", fontName="Helvetica", fontSize=9.5, leading=13,
                      spaceAfter=4)
QUOTE = ParagraphStyle("quote", parent=BODY, leftIndent=12, textColor=GREY,
                       fontName="Helvetica-Oblique")
BULLET = ParagraphStyle("bullet", parent=BODY, leftIndent=14, spaceAfter=2)
CELL = ParagraphStyle("cell", fontName="Helvetica", fontSize=8.5, leading=11)
CELL_H = ParagraphStyle("cellh", fontName="Helvetica-Bold", fontSize=8.5,
                        leading=11, textColor=colors.white)


def col_widths(header, avail):
    w = [None] * len(header)
    fixed = 0.0
    for i, h in enumerate(header):
        hl = sanitize(h).strip().lower()
        if hl == "#":
            w[i] = 0.42 * inch
        elif hl in ("pass", "pass?", "ok"):
            w[i] = 0.62 * inch
        if w[i]:
            fixed += w[i]
    flex = [i for i in range(len(header)) if w[i] is None]
    if flex:
        each = (avail - fixed) / len(flex)
        for i in flex:
            w[i] = each
    return w


def make_table(rows):
    grid = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    grid = [r for r in grid
            if not all(c and set(c) <= set("-: ") for c in r)]   # drop |---|
    header = grid[0]
    widths = col_widths(header, 6.6 * inch)
    data = [[Paragraph(inline(c) or "&nbsp;", CELL_H if ri == 0 else CELL)
             for c in r] for ri, r in enumerate(grid)]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, LINE),
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def parse(md):
    flow, para, lines, i = [], [], md.splitlines(), 0

    def flush():
        if para:
            txt = " ".join(para).strip()
            if txt:
                flow.append(Paragraph(inline(txt), BODY))
            para.clear()

    while i < len(lines):
        ln = lines[i]
        if ln.lstrip().startswith("|"):
            flush()
            block = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                block.append(lines[i])
                i += 1
            flow.append(make_table(block))
            continue
        s = ln.strip()
        if not s:
            flush(); i += 1; continue
        if s.startswith("### "):
            flush(); flow.append(Paragraph(inline(s[4:]), H3))
        elif s.startswith("## "):
            flush(); flow.append(Paragraph(inline(s[3:]), H2))
        elif s.startswith("# "):
            flush(); flow.append(Paragraph(inline(s[2:]), TITLE))
        elif s == "---":
            flush(); flow.append(Spacer(1, 3))
            flow.append(HRFlowable(width="100%", thickness=0.6, color=LINE))
            flow.append(Spacer(1, 3))
        elif s.startswith("> "):
            flush(); flow.append(Paragraph(inline(s[2:]), QUOTE))
        elif s.startswith(("- ", "* ")):
            flush(); flow.append(Paragraph("• " + inline(s[2:]), BULLET))
        else:
            para.append(s)
        i += 1
    flush()
    return flow


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(GREY)
    canvas.drawString(0.75 * inch, 0.5 * inch,
                      "FR-011 Mission Control GUI — Field-Test Script")
    canvas.drawRightString(7.75 * inch, 0.5 * inch, "Page %d" % doc.page)
    canvas.restoreState()


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: md_to_pdf.py <input.md> [output.pdf]")
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else src.rsplit(".", 1)[0] + ".pdf"
    with open(src, encoding="utf-8") as fh:
        flow = parse(fh.read())
    doc = SimpleDocTemplate(
        out, pagesize=letter, leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        topMargin=0.7 * inch, bottomMargin=0.85 * inch,
        title="FR-011 Mission Control GUI - Field-Test Script",
        author="Training Bridge VRAI-MedSim",
    )
    doc.build(flow, onFirstPage=footer, onLaterPages=footer)
    print("wrote", out)


if __name__ == "__main__":
    main()
