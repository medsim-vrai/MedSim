#!/usr/bin/env python3
"""Regenerate the operator support docs from source — the ONE command to run after any edit.

Single sources of truth:
  • operator-guide.html   → MedSim-Operator-Guide.pdf   (the printable full guide)
  • faq.json              → faq.html                      (the embeddable in-app support widget)

So an author never hand-edits the PDF or faq.html: edit the .html guide / the .json, bump the version
in faq.json meta + CHANGELOG.md, then run `python3 render.py`. Stdlib only; the PDF step uses the
installed Google Chrome (headless). See MAINTENANCE.md.
"""
from __future__ import annotations

import html
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def render_pdf(src="operator-guide.html", out="MedSim-Operator-Guide.pdf") -> None:
    src_p, out_p = HERE / src, HERE / out
    if not src_p.exists():
        print(f"  skip PDF: {src} not found")
        return
    chrome = os.environ.get("CHROME", CHROME)
    if not Path(chrome).exists():
        print(f"  PDF step needs Chrome at {chrome} (set $CHROME). Skipped.")
        return
    subprocess.run(
        [chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
         f"--print-to-pdf={out_p}", src_p.as_uri()],
        check=True, capture_output=True,
    )
    print(f"  ✓ {out}  ({out_p.stat().st_size // 1024} KB)")


def render_faq(src="faq.json", out="faq.html") -> None:
    data = json.loads((HERE / src).read_text())
    meta = data.get("meta", {})
    entries = data.get("entries", [])
    cats: dict[str, list] = {}
    for e in entries:
        cats.setdefault(e.get("category", "Other"), []).append(e)
    order = data.get("categories") or list(cats)

    def esc(s):  # noqa: E306
        return html.escape(str(s or ""))

    blocks = []
    for cat in order:
        items = cats.get(cat, [])
        if not items:
            continue
        rows = "".join(
            f'<details class="qa" data-tags="{esc(" ".join(e.get("tags", [])))}">'
            f'<summary>{esc(e["question"])}'
            f'<span class="upd">updated {esc(e.get("last_updated", meta.get("generated", "")))}</span></summary>'
            f'<div class="a">{esc(e["answer"]).replace(chr(10), "<br>")}</div></details>'
            for e in items
        )
        blocks.append(f'<section class="cat" data-cat="{esc(cat)}"><h2>{esc(cat)}</h2>{rows}</section>')

    doc = FAQ_TEMPLATE.format(
        title=esc(meta.get("system", "MedSim") + " — Support & FAQ"),
        version=esc(meta.get("doc_version", "")),
        generated=esc(meta.get("generated", "")),
        system=esc(meta.get("system", "")),
        count=len(entries),
        blocks="".join(blocks),
    )
    (HERE / out).write_text(doc)
    print(f"  ✓ {out}  ({len(entries)} entries, {(HERE / out).stat().st_size // 1024} KB)")


FAQ_TEMPLATE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>
 :root{{--ink:#13212c;--muted:#55697a;--line:#dde5ea;--accent:#0f766e;--soft:#e6f1ef;--bg:#f6f8fa}}
 *{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
 .wrap{{max-width:820px;margin:0 auto;padding:22px 18px 60px}}
 header h1{{font-size:22px;margin:0 0 3px}} header .sub{{color:var(--muted);font-size:13px}}
 .search{{position:sticky;top:0;background:var(--bg);padding:14px 0 10px;z-index:2}}
 .search input{{width:100%;padding:11px 13px;border:1px solid var(--line);border-radius:10px;font-size:15px}}
 .cat h2{{font-size:13px;text-transform:uppercase;letter-spacing:.05em;color:var(--accent);
  margin:22px 0 8px;padding-bottom:6px;border-bottom:1px solid var(--line)}}
 details.qa{{background:#fff;border:1px solid var(--line);border-radius:10px;margin:8px 0;overflow:hidden}}
 details.qa summary{{cursor:pointer;padding:12px 14px;font-weight:560;list-style:none;
  display:flex;justify-content:space-between;gap:12px;align-items:baseline}}
 details.qa summary::-webkit-details-marker{{display:none}}
 details.qa[open] summary{{background:var(--soft)}}
 .upd{{font-size:11px;color:var(--muted);font-weight:400;white-space:nowrap}}
 .a{{padding:4px 14px 14px;color:#28323b;font-size:14px}}
 .empty{{color:var(--muted);padding:24px 4px;display:none}}
 footer{{margin-top:30px;color:var(--muted);font-size:12px;border-top:1px solid var(--line);padding-top:12px}}
</style></head><body><div class="wrap">
<header><h1>{title}</h1><div class="sub">{count} answers · {system} · doc v{version} · {generated}</div></header>
<div class="search"><input id="q" type="search" placeholder="Search support topics — e.g. microphone, QR, tablet, image…" aria-label="Search"></div>
<div id="list">{blocks}</div>
<p class="empty" id="empty">No matches. Try a different word, or contact your site administrator.</p>
<footer>Generated from <code>faq.json</code> — do not edit this file directly; edit the JSON and re-run <code>render.py</code>.</footer>
</div><script>
 const q=document.getElementById('q'),list=document.getElementById('list'),empty=document.getElementById('empty');
 q.addEventListener('input',()=>{{const t=q.value.trim().toLowerCase();let n=0;
  list.querySelectorAll('details.qa').forEach(d=>{{const hay=(d.textContent+' '+(d.dataset.tags||'')).toLowerCase();
   const show=!t||hay.includes(t);d.style.display=show?'':'none';if(show)n++;}});
  list.querySelectorAll('section.cat').forEach(s=>{{const any=[...s.querySelectorAll('details.qa')].some(d=>d.style.display!=='none');s.style.display=any?'':'none';}});
  empty.style.display=n?'none':'block';}});
</script></body></html>"""


FAQ_PRINT_TMPL = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{title}</title>
<style>
 @page{{size:letter;margin:16mm}}
 :root{{--ink:#16232e;--muted:#54697a;--line:#d7e0e6;--accent:#0f766e}}
 *{{box-sizing:border-box}} body{{margin:0;color:var(--ink);
  font:11.5pt/1.5 -apple-system,system-ui,"Segoe UI",Roboto,sans-serif;
  -webkit-print-color-adjust:exact;print-color-adjust:exact}}
 .cover{{border-bottom:2px solid var(--ink);padding-bottom:12pt;margin-bottom:6pt}}
 .cover .k{{font-size:11pt;letter-spacing:.14em;text-transform:uppercase;color:var(--accent);font-weight:700}}
 .cover h1{{font-size:26pt;margin:6pt 0 4pt}} .cover .m{{color:var(--muted);font-size:10.5pt}}
 h2{{font-size:13pt;color:var(--accent);text-transform:uppercase;letter-spacing:.05em;margin:16pt 0 6pt;
  border-bottom:1px solid var(--line);padding-bottom:4pt;page-break-after:avoid}}
 .qa{{page-break-inside:avoid;margin:8pt 0}} .q{{font-weight:650}} .a{{margin:2pt 0 0;color:#28323b}}
 footer{{margin-top:20pt;border-top:1px solid var(--line);padding-top:8pt;color:var(--muted);font-size:9pt}}
</style></head><body>
<div class="cover"><div class="k">Support &amp; FAQ</div><h1>{system}</h1>
<div class="m">{count} answers · doc v{version} · {generated}</div></div>
{blocks}
<footer>Generated from faq.json — see MAINTENANCE.md. Also available as the searchable in-app Help &amp; Support tool (faq.html).</footer>
</body></html>"""


def render_faq_pdf(src="faq.json", flat="faq-print.html", out="MedSim-Support-FAQ.pdf") -> None:
    """A print-flat FAQ (all answers visible, grouped) → PDF, for binders / handouts."""
    data = json.loads((HERE / src).read_text())
    meta = data.get("meta", {}); entries = data.get("entries", [])
    cats: dict[str, list] = {}
    for e in entries:
        cats.setdefault(e.get("category", "Other"), []).append(e)
    order = data.get("categories") or list(cats)
    blocks = []
    for c in order:
        items = cats.get(c, [])
        if not items:
            continue
        qas = "".join(
            f'<div class="qa"><div class="q">{html.escape(e["question"])}</div>'
            f'<div class="a">{html.escape(e["answer"]).replace(chr(10), "<br>")}</div></div>'
            for e in items)
        blocks.append(f'<h2>{html.escape(c)}</h2>{qas}')
    doc = FAQ_PRINT_TMPL.format(
        title=html.escape(meta.get("system", "MedSim") + " — Support FAQ"),
        system=html.escape(meta.get("system", "")), count=len(entries),
        version=html.escape(meta.get("doc_version", "")), generated=html.escape(meta.get("generated", "")),
        blocks="".join(blocks))
    (HERE / flat).write_text(doc)
    chrome = os.environ.get("CHROME", CHROME)
    if not Path(chrome).exists():
        print("  FAQ-PDF needs Chrome; skipped"); return
    subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={HERE / out}", (HERE / flat).as_uri()], check=True, capture_output=True)
    print(f"  ✓ {out}  ({(HERE / out).stat().st_size // 1024} KB)")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    print("Rendering operator support docs…")
    if what in ("all", "faq"):
        render_faq()
    if what in ("all", "pdf"):
        render_pdf()
    if what in ("all", "faqpdf"):
        render_faq_pdf()
    print("Done.")
