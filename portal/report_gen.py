"""FR-015 R1 — clinical LAB report generator (engine).

Pure functions over a ChartSeed-shaped dict (`seed.labs_recent = [{panel, time,
values:[{name, v, ref, flag}]}]`, plus patient identity). The instructor selects
panels and OVERRIDES specific analyte values (to teach a finding); flags recompute
from the reference range. Renders a branded printable HTML report and a reportlab
PDF, and can email it (stdlib smtplib, config-gated).

The route layer (server.py) resolves the seed — PRE-RUN via `seed_from_persona`,
or LIVE via `ehr_db.seed(encounter_id)` — and calls these. Everything here is
network-free except `email_report`. Every report is a SYNTHETIC training artifact
and carries a training-simulation disclaimer.
"""
from __future__ import annotations

import io
import re
import smtplib
import ssl
import time
from email.message import EmailMessage
from typing import Any

DISCLAIMER = ("TRAINING SIMULATION — not a real clinical result. "
              "Values are sim-tuned and pending clinical review.")
_REF_RE = re.compile(r"\s*(-?\d+\.?\d*)\s*[-–]\s*(-?\d+\.?\d*)")


def flag_for(value: Any, ref: str) -> str:
    """Recompute an L/H flag from a numeric value vs a 'lo-hi' reference range.
    Returns '' when not computable (non-numeric value or unparseable range)."""
    try:
        v = float(str(value))
    except (TypeError, ValueError):
        return ""
    m = _REF_RE.match(str(ref or ""))
    if not m:
        return ""
    lo, hi = float(m.group(1)), float(m.group(2))
    if v < lo:
        return "L"
    if v > hi:
        return "H"
    return ""


def available_panels(seed: dict[str, Any]) -> list[str]:
    return [p.get("panel") for p in ((seed or {}).get("labs_recent") or []) if p.get("panel")]


def _normal_value(ref: str) -> str:
    """Midpoint of a 'lo-hi' reference range — the default for a panel synthesized
    from the catalog (the instructor then overrides to teach a finding)."""
    m = _REF_RE.match(str(ref or ""))
    if not m:
        return ""
    lo, hi = float(m.group(1)), float(m.group(2))
    v = (lo + hi) / 2
    return f"{v:.2f}" if (hi - lo) < 2 and v < 10 else f"{v:.0f}"


_PANEL_ORDER = ["BMP", "CBC", "Lactate", "ABG", "Troponin", "BNP", "Coag",
                "LFT", "Lipid", "Ketones", "Urine", "UDS", "Tryptase"]


def panel_catalog() -> list[dict[str, Any]]:
    """FULL catalog of lab panels the instructor can include — every panel/analyte
    defined across CLINICAL_RANGES (not just the patient's seeded ones), each with
    a reference range (stable_baseline where available, else the condition range).
    Lets the instructor ADD panels the patient's condition didn't seed."""
    from . import ehr_seed as _es
    cr = getattr(_es, "CLINICAL_RANGES", {}) or {}
    base = (cr.get("stable_baseline") or {}).get("labs") or {}
    cat: dict[str, dict[str, str]] = {}

    def _add(panel: str, analyte: str, spec: Any) -> None:
        d = cat.setdefault(panel, {})
        if analyte in d:
            return
        ref_spec = (base.get(panel) or {}).get(analyte) or spec
        d[analyte] = (f"{ref_spec[0]}-{ref_spec[1]}"
                      if isinstance(ref_spec, (list, tuple)) and len(ref_spec) >= 2 else "")

    for panel, analytes in base.items():          # BMP, CBC (normal refs) first
        for a, spec in analytes.items():
            _add(panel, a, spec)
    for cond, spec in cr.items():
        if cond == "stable_baseline":
            continue
        for panel, analytes in ((spec or {}).get("labs") or {}).items():
            for a, sp in analytes.items():
                _add(panel, a, sp)
    panels = sorted(cat, key=lambda p: _PANEL_ORDER.index(p) if p in _PANEL_ORDER else 99)
    return [{"panel": p, "analytes": [{"name": a, "ref": r} for a, r in cat[p].items()]}
            for p in panels]


def build_lab_report(seed: dict[str, Any], *, panels: list[str] | None = None,
                     overrides: list[dict[str, Any]] | None = None,
                     generated_by: str = "", scenario_name: str = "",
                     catalog: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Assemble the lab-report model from a seed + panel selection + overrides.
    Requested panels NOT present in the seed are synthesized from `catalog` (normal
    midpoint values) so the instructor can ADD any panel. `overrides` =
    [{panel, analyte, value, flag?}]; an override sets the value, recomputes the
    flag (explicit L/H/C wins), and marks `overridden`."""
    seed = seed or {}
    ov: dict[tuple[str, str], dict[str, Any]] = {}
    for o in (overrides or []):
        p, a = str(o.get("panel") or "").strip(), str(o.get("analyte") or "").strip()
        if p and a:
            ov[(p, a)] = o
    seed_panels = {p.get("panel"): p for p in (seed.get("labs_recent") or []) if p.get("panel")}
    cat_map = {c.get("panel"): c for c in (catalog or [])}
    names = list(panels) if panels else list(seed_panels.keys())
    out_panels: list[dict[str, Any]] = []
    for pname in names:
        src = seed_panels.get(pname)
        if src is None:                      # panel not seeded → synthesize from catalog
            cat = cat_map.get(pname)
            if cat is None:
                continue
            src = {"panel": pname, "time": "T-0h",
                   "values": [{"name": a.get("name"), "v": _normal_value(a.get("ref", "")),
                               "ref": a.get("ref", ""), "flag": ""}
                              for a in (cat.get("analytes") or [])]}
        vals = []
        for val in (src.get("values") or []):
            name = val.get("name")
            ref = val.get("ref", "")
            v = val.get("v")
            flag = val.get("flag", "")
            overridden = False
            o = ov.get((pname, name))
            if o is not None and str(o.get("value", "")).strip() != "":
                v = str(o.get("value")).strip()
                overridden = True
                explicit = str(o.get("flag") or "").upper().strip()
                flag = explicit if explicit in ("L", "H", "C") else flag_for(v, ref)
            vals.append({"name": name, "v": v, "ref": ref, "flag": flag,
                         "overridden": overridden})
        out_panels.append({"panel": pname, "time": src.get("time", ""), "values": vals})
    return {
        "kind": "lab",
        "patient": {
            "name": seed.get("name") or "Patient",
            "mrn": seed.get("mrn") or "—",
            "dob": seed.get("dob") or "",
            "sex": seed.get("sex") or "",
        },
        "meta": {
            "generated_by": generated_by,
            "generated_at": time.time(),
            "scenario_name": scenario_name,
            "collected": (out_panels[0]["time"] if out_panels else ""),
        },
        "panels": out_panels,
        "disclaimer": DISCLAIMER,
    }


# ── rendering ────────────────────────────────────────────────────────────────

_FLAG_LABEL = {"L": "LOW", "H": "HIGH", "C": "CRITICAL"}


def _esc(s: Any) -> str:
    return (str("" if s is None else s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def report_html(report: dict[str, Any], *, for_student: bool = False) -> str:
    """A self-contained, print-friendly branded HTML lab report. When
    `for_student`, the instructor-only `overridden` markers are stripped."""
    p = report.get("patient", {})
    meta = report.get("meta", {})
    rows_html = []
    for pan in report.get("panels", []):
        rows = []
        for v in pan.get("values", []):
            flag = v.get("flag") or ""
            cls = {"C": "crit", "H": "hi", "L": "lo"}.get(flag, "")
            star = "" if for_student or not v.get("overridden") else \
                ' <span class="ov" title="instructor-set">●</span>'
            rows.append(
                f'<tr class="{cls}"><td>{_esc(v.get("name"))}{star}</td>'
                f'<td class="val">{_esc(v.get("v"))}</td>'
                f'<td class="ref">{_esc(v.get("ref"))}</td>'
                f'<td class="flag">{_FLAG_LABEL.get(flag, "")}</td></tr>')
        rows_html.append(
            f'<h3>{_esc(pan.get("panel"))} <span class="t">{_esc(pan.get("time"))}</span></h3>'
            f'<table><thead><tr><th>Analyte</th><th>Result</th>'
            f'<th>Reference</th><th>Flag</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table>")
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Laboratory Report — {_esc(p.get('name'))}</title>
<style>
  body{{font:14px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#16213e;margin:0;background:#fff}}
  .wrap{{max-width:760px;margin:0 auto;padding:26px 28px}}
  .hd{{display:flex;align-items:center;justify-content:space-between;border-bottom:3px solid #1f2d6b;padding-bottom:10px}}
  .brand{{font-weight:800;font-size:20px;color:#1f2d6b}} .brand small{{display:block;font-size:10px;letter-spacing:.16em;color:#0f9aa7;text-transform:uppercase}}
  h1{{font-size:17px;margin:16px 0 4px}}
  .pt{{display:grid;grid-template-columns:1fr 1fr;gap:2px 18px;background:#f4f6fc;border:1px solid #e2e6f0;border-radius:8px;padding:10px 14px;margin:8px 0 4px;font-size:13px}}
  .pt b{{color:#6b7596;font-weight:600}}
  h3{{margin:18px 0 4px;font-size:14px}} h3 .t{{color:#7a85a6;font-weight:500;font-size:12px}}
  table{{width:100%;border-collapse:collapse;font-size:13px}}
  th,td{{text-align:left;padding:6px 9px;border-bottom:1px solid #edf0f6}}
  th{{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:#6b7596}}
  td.val{{font-weight:700}} td.ref{{color:#6b7596}} td.flag{{font-weight:700}}
  tr.hi td.flag,tr.hi td.val{{color:#b4540a}} tr.lo td.flag,tr.lo td.val{{color:#1d4ed8}}
  tr.crit td{{background:#fdeaec}} tr.crit td.flag,tr.crit td.val{{color:#b00020}}
  .ov{{color:#2b6cb0}}
  .disc{{margin-top:20px;padding:9px 12px;background:#fff7ed;border:1px solid #f3d6b5;border-radius:8px;color:#9a5b13;font-size:12px}}
  .ft{{margin-top:14px;color:#9aa4bf;font-size:10.5px}}
  @media print{{.noprint{{display:none}} body{{background:#fff}}}}
</style></head><body><div class="wrap">
  <div class="hd"><span class="brand">Helix Health<small>Laboratory</small></span>
    <span class="brand" style="font-size:15px">Laboratory Report</span></div>
  <div class="pt">
    <div><b>Patient</b> {_esc(p.get('name'))}</div><div><b>MRN</b> {_esc(p.get('mrn'))}</div>
    <div><b>DOB</b> {_esc(p.get('dob'))}</div><div><b>Sex</b> {_esc(p.get('sex'))}</div>
    <div><b>Collected</b> {_esc(meta.get('collected'))}</div>
    <div><b>Ordering</b> {_esc(meta.get('generated_by') or '—')}</div>
  </div>
  {''.join(rows_html) or '<p>No panels selected.</p>'}
  <div class="disc">{_esc(report.get('disclaimer'))}</div>
  <div class="ft">{_esc(meta.get('scenario_name'))} · Training Bridge VRAI- MedSim</div>
</div></body></html>"""


def report_pdf(report: dict[str, Any]) -> bytes:
    """Render the report to a branded PDF (reportlab). Student-facing copy
    (no instructor override markers)."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                    TableStyle)
    p = report.get("patient", {})
    meta = report.get("meta", {})
    styles = getSampleStyleSheet()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, title="Laboratory Report",
                            topMargin=0.7 * inch, bottomMargin=0.7 * inch)
    story: list[Any] = [
        Paragraph("<b>Helix Health</b> — Laboratory Report", styles["Title"]),
        Paragraph(f"Patient: <b>{_esc(p.get('name'))}</b> &nbsp; MRN: {_esc(p.get('mrn'))} "
                  f"&nbsp; DOB: {_esc(p.get('dob'))} &nbsp; Sex: {_esc(p.get('sex'))}",
                  styles["Normal"]),
        Paragraph(f"Collected: {_esc(meta.get('collected'))} &nbsp; "
                  f"Ordering: {_esc(meta.get('generated_by') or '—')}", styles["Normal"]),
        Spacer(1, 10),
    ]
    for pan in report.get("panels", []):
        story.append(Paragraph(f"<b>{_esc(pan.get('panel'))}</b> "
                               f"<font size=8 color='#7a85a6'>{_esc(pan.get('time'))}</font>",
                               styles["Heading4"]))
        data = [["Analyte", "Result", "Reference", "Flag"]]
        styled = []
        for i, v in enumerate(pan.get("values", []), start=1):
            data.append([_esc(v.get("name")), _esc(v.get("v")), _esc(v.get("ref")),
                         _FLAG_LABEL.get(v.get("flag") or "", "")])
            fl = v.get("flag")
            if fl == "C":
                styled.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#fdeaec")))
                styled.append(("TEXTCOLOR", (3, i), (3, i), colors.HexColor("#b00020")))
            elif fl == "H":
                styled.append(("TEXTCOLOR", (3, i), (3, i), colors.HexColor("#b4540a")))
            elif fl == "L":
                styled.append(("TEXTCOLOR", (3, i), (3, i), colors.HexColor("#1d4ed8")))
        t = Table(data, colWidths=[2.1 * inch, 1.4 * inch, 1.7 * inch, 1.0 * inch])
        t.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#6b7596")),
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#1f2d6b")),
            ("LINEBELOW", (0, 1), (-1, -1), 0.3, colors.HexColor("#edf0f6")),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 4),
        ] + styled))
        story.append(t)
        story.append(Spacer(1, 8))
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"<i>{_esc(report.get('disclaimer'))}</i>", styles["Normal"]))
    doc.build(story)
    return buf.getvalue()


def _patient_block(seed: dict[str, Any]) -> dict[str, Any]:
    seed = seed or {}
    return {"name": seed.get("name") or "Patient", "mrn": seed.get("mrn") or "—",
            "dob": seed.get("dob") or "", "sex": seed.get("sex") or ""}


# ── FR-015 R3 — diagnostic reports (ECG / imaging) ──────────────────────────

DIAGNOSTIC_CATALOG: list[dict[str, Any]] = [
    {"id": "ecg", "name": "12-lead ECG", "fields": [
        {"key": "rate", "label": "Rate", "default": "78 bpm"},
        {"key": "rhythm", "label": "Rhythm", "default": "Normal sinus rhythm", "options": [
            "Normal sinus rhythm", "Sinus tachycardia", "Sinus bradycardia",
            "Atrial fibrillation", "Atrial flutter", "SVT", "1st-degree AV block",
            "2nd-degree AV block (Mobitz I)", "2nd-degree AV block (Mobitz II)",
            "3rd-degree AV block", "Ventricular tachycardia", "Ventricular fibrillation",
            "Asystole", "PEA", "Paced rhythm"]},
        {"key": "intervals", "label": "Intervals", "default": "PR 160 ms · QRS 90 ms · QTc 420 ms"},
        {"key": "axis", "label": "Axis", "default": "Normal axis"},
        {"key": "st_t", "label": "ST / T-wave changes", "default": "None"},
        {"key": "interpretation", "label": "Interpretation", "default": "Normal ECG.", "multiline": True}]},
    {"id": "cxr", "name": "Chest X-ray", "fields": [
        {"key": "technique", "label": "Technique", "default": "AP portable; adequate inspiration"},
        {"key": "findings", "label": "Findings", "multiline": True, "default":
            "Lungs clear bilaterally. No effusion, consolidation, or pneumothorax. "
            "Cardiomediastinal silhouette within normal limits. Lines/tubes appropriately positioned."},
        {"key": "impression", "label": "Impression", "default": "No acute cardiopulmonary process.", "multiline": True}]},
    {"id": "ct_head", "name": "CT head — non-contrast", "fields": [
        {"key": "technique", "label": "Technique", "default": "Non-contrast axial CT of the head"},
        {"key": "findings", "label": "Findings", "multiline": True, "default":
            "No acute intracranial hemorrhage, mass effect, or midline shift. "
            "Gray-white differentiation preserved. Ventricles and sulci normal for age."},
        {"key": "impression", "label": "Impression", "default": "No acute intracranial abnormality.", "multiline": True}]},
    {"id": "fast", "name": "FAST ultrasound", "fields": [
        {"key": "views", "label": "Views", "default": "RUQ · LUQ · subxiphoid · suprapubic"},
        {"key": "findings", "label": "Findings", "multiline": True,
         "default": "No free fluid in any window. No pericardial effusion."},
        {"key": "impression", "label": "Impression", "default": "Negative FAST exam.", "multiline": True}]},
]


def diagnostic_catalog() -> list[dict[str, Any]]:
    return DIAGNOSTIC_CATALOG


def build_diagnostic_report(seed: dict[str, Any], *, study_id: str,
                            fields: dict[str, Any] | None = None,
                            generated_by: str = "", scenario_name: str = "") -> dict[str, Any]:
    """Assemble a diagnostic-study report from the catalog template + instructor
    edits. Missing/blank fields fall back to the study's normal-finding default."""
    study = next((s for s in DIAGNOSTIC_CATALOG if s["id"] == study_id), None)
    if study is None:
        raise ValueError(f"unknown diagnostic study {study_id!r}")
    fv = fields or {}
    rows = []
    for f in study["fields"]:
        val = fv.get(f["key"])
        if val is None or str(val).strip() == "":
            val = f.get("default", "")
        rows.append({"key": f["key"], "label": f["label"], "value": str(val).strip(),
                     "multiline": bool(f.get("multiline"))})
    return {
        "kind": "diagnostic", "study": study["name"], "study_id": study["id"],
        "patient": _patient_block(seed),
        "meta": {"generated_by": generated_by, "generated_at": time.time(),
                 "scenario_name": scenario_name},
        "fields": rows, "disclaimer": DISCLAIMER,
    }


# Shared chrome for the non-lab reports (diagnostic + referral) — same brand look.
_DOC_STYLE = """
  body{font:14px/1.55 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#16213e;margin:0;background:#fff}
  .wrap{max-width:760px;margin:0 auto;padding:26px 28px}
  .hd{display:flex;align-items:center;justify-content:space-between;border-bottom:3px solid #1f2d6b;padding-bottom:10px}
  .brand{font-weight:800;font-size:20px;color:#1f2d6b} .brand small{display:block;font-size:10px;letter-spacing:.16em;color:#0f9aa7;text-transform:uppercase}
  .pt{display:grid;grid-template-columns:1fr 1fr;gap:2px 18px;background:#f4f6fc;border:1px solid #e2e6f0;border-radius:8px;padding:10px 14px;margin:10px 0;font-size:13px}
  .pt b{color:#6b7596;font-weight:600}
  .dx-row{display:grid;grid-template-columns:170px 1fr;gap:10px;padding:7px 0;border-bottom:1px solid #edf0f6}
  .dx-k{color:#6b7596;font-weight:600;font-size:12.5px} .dx-v{white-space:pre-wrap}
  .letter p{margin:10px 0;white-space:pre-wrap} .letter .sec{color:#6b7596;font-weight:700;font-size:11px;text-transform:uppercase;letter-spacing:.04em;margin-top:14px}
  .disc{margin-top:20px;padding:9px 12px;background:#fff7ed;border:1px solid #f3d6b5;border-radius:8px;color:#9a5b13;font-size:12px}
  .ft{margin-top:14px;color:#9aa4bf;font-size:10.5px}
  @media print{.noprint{display:none}}
"""


def _doc_shell(title_right: str, sub: str, patient: dict[str, Any], meta: dict[str, Any],
               inner: str, disclaimer: str) -> str:
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{_esc(title_right)} — {_esc(patient.get('name'))}</title>
<style>{_DOC_STYLE}</style></head><body><div class="wrap">
  <div class="hd"><span class="brand">Helix Health<small>{_esc(sub)}</small></span>
    <span class="brand" style="font-size:15px">{_esc(title_right)}</span></div>
  <div class="pt">
    <div><b>Patient</b> {_esc(patient.get('name'))}</div><div><b>MRN</b> {_esc(patient.get('mrn'))}</div>
    <div><b>DOB</b> {_esc(patient.get('dob'))}</div><div><b>Sex</b> {_esc(patient.get('sex'))}</div>
    <div><b>Ordering</b> {_esc(meta.get('generated_by') or '—')}</div></div>
  {inner}
  <div class="disc">{_esc(disclaimer)}</div>
  <div class="ft">{_esc(meta.get('scenario_name'))} · Training Bridge VRAI- MedSim</div>
</div></body></html>"""


def diagnostic_html(report: dict[str, Any]) -> str:
    inner = "".join(
        f'<div class="dx-row"><div class="dx-k">{_esc(f.get("label"))}</div>'
        f'<div class="dx-v">{_esc(f.get("value"))}</div></div>'
        for f in report.get("fields", []))
    return _doc_shell(report.get("study", "Diagnostic report"), "Diagnostics",
                      report.get("patient", {}), report.get("meta", {}),
                      inner, report.get("disclaimer", ""))


def _doc_pdf(title: str, patient: dict[str, Any], meta: dict[str, Any],
             rows: list[tuple[str, str]], disclaimer: str) -> bytes:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    p, styles, buf = patient, getSampleStyleSheet(), io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, title=title,
                            topMargin=0.7 * inch, bottomMargin=0.7 * inch)
    story: list[Any] = [
        Paragraph(f"<b>Helix Health</b> — {_esc(title)}", styles["Title"]),
        Paragraph(f"Patient: <b>{_esc(p.get('name'))}</b> &nbsp; MRN: {_esc(p.get('mrn'))} "
                  f"&nbsp; DOB: {_esc(p.get('dob'))} &nbsp; Sex: {_esc(p.get('sex'))}", styles["Normal"]),
        Paragraph(f"Ordering: {_esc(meta.get('generated_by') or '—')}", styles["Normal"]),
        Spacer(1, 10)]
    for label, value in rows:
        story.append(Paragraph(f"<b>{_esc(label)}</b>", styles["Heading5"]))
        story.append(Paragraph(_esc(value).replace("\n", "<br/>"), styles["Normal"]))
        story.append(Spacer(1, 6))
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"<i>{_esc(disclaimer)}</i>", styles["Normal"]))
    doc.build(story)
    return buf.getvalue()


def diagnostic_pdf(report: dict[str, Any]) -> bytes:
    rows = [(f.get("label", ""), f.get("value", "")) for f in report.get("fields", [])]
    return _doc_pdf(report.get("study", "Diagnostic report"), report.get("patient", {}),
                    report.get("meta", {}), rows, report.get("disclaimer", ""))


# ── FR-015 R4 — referral / consult letters ──────────────────────────────────

REFERRAL_SPECIALTIES: list[str] = [
    "Cardiology", "Pulmonology / Critical Care", "Nephrology", "Neurology",
    "Gastroenterology", "General Surgery", "Orthopedic Surgery", "Urology",
    "Infectious Disease", "Endocrinology", "Hematology / Oncology", "Psychiatry",
    "Palliative Care", "Physical Therapy", "Social Work / Case Management",
    "Nutrition / Dietitian", "Wound Care",
]
_REFERRAL_FIELDS = [
    {"key": "reason", "label": "Reason for consultation", "multiline": True},
    {"key": "history", "label": "Pertinent history", "multiline": True},
    {"key": "findings", "label": "Pertinent findings / current status", "multiline": True},
    {"key": "question", "label": "Specific question for the consultant", "multiline": True},
]


def referral_catalog() -> list[dict[str, Any]]:
    """Shaped like the diagnostic catalog so the studio reuses one field renderer:
    a single 'study' (the consult letter) whose fields carry the specialty +
    urgency selects and the free-text sections."""
    return [{"id": "consult", "name": "Consult / referral letter", "fields": (
        [{"key": "specialty", "label": "Consult service", "options": REFERRAL_SPECIALTIES,
          "default": REFERRAL_SPECIALTIES[0]},
         {"key": "urgency", "label": "Urgency", "options": ["Routine", "Urgent", "Emergent"],
          "default": "Routine"}]
        + [{**f, "default": ""} for f in _REFERRAL_FIELDS])}]


def _referral_defaults(seed: dict[str, Any]) -> dict[str, str]:
    """Pre-fill reason/history from the chart seed so a usable letter exists
    before the instructor types anything; blank fields fall back to these."""
    seed = seed or {}
    reason = str(seed.get("chief_complaint") or "").strip()
    probs = [str(p.get("name") or p.get("dx") or p.get("desc") or "").strip()
             for p in (seed.get("problem_list") or [])]
    probs = [p for p in probs if p]
    alls = [str(a.get("substance") or a.get("name") or a.get("allergen") or "").strip()
            for a in (seed.get("allergies") or [])]
    alls = [a for a in alls if a and a.lower() not in ("nkda", "none", "no known drug allergies")]
    hist = []
    if probs:
        hist.append("PMH: " + ", ".join(probs[:8]) + ".")
    hist.append("Allergies: " + (", ".join(alls) + "." if alls else "NKDA."))
    return {"reason": reason, "history": " ".join(hist), "findings": "", "question": ""}


def build_referral_report(seed: dict[str, Any], *, fields: dict[str, Any] | None = None,
                          generated_by: str = "", scenario_name: str = "") -> dict[str, Any]:
    fv = fields or {}
    defaults = _referral_defaults(seed)
    specialty = str(fv.get("specialty") or "").strip() or "Consult"
    urgency = str(fv.get("urgency") or "Routine").strip() or "Routine"
    rows = []
    for f in _REFERRAL_FIELDS:
        val = str(fv.get(f["key"]) or "").strip() or defaults.get(f["key"], "")
        rows.append({"key": f["key"], "label": f["label"], "value": val, "multiline": True})
    return {
        "kind": "referral", "specialty": specialty, "urgency": urgency,
        "patient": _patient_block(seed),
        "meta": {"generated_by": generated_by, "generated_at": time.time(),
                 "scenario_name": scenario_name},
        "fields": rows, "disclaimer": DISCLAIMER,
    }


def referral_html(report: dict[str, Any]) -> str:
    inner = ('<div class="letter">'
             f'<p><b>To:</b> {_esc(report.get("specialty"))} Consult Service'
             f' &nbsp;·&nbsp; <b>Urgency:</b> {_esc(report.get("urgency"))}</p>')
    for f in report.get("fields", []):
        inner += (f'<div class="sec">{_esc(f.get("label"))}</div>'
                  f'<p>{_esc(f.get("value")) or "—"}</p>')
    inner += '</div>'
    return _doc_shell(f'{report.get("specialty", "Consult")} consult', "Referral",
                      report.get("patient", {}), report.get("meta", {}), inner,
                      report.get("disclaimer", ""))


def referral_pdf(report: dict[str, Any]) -> bytes:
    rows = [("To", f'{report.get("specialty", "Consult")} Consult Service — '
                    f'{report.get("urgency", "Routine")}')]
    rows += [(f.get("label", ""), f.get("value", "") or "—") for f in report.get("fields", [])]
    return _doc_pdf(f'{report.get("specialty", "Consult")} Consult Request',
                    report.get("patient", {}), report.get("meta", {}), rows,
                    report.get("disclaimer", ""))


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def parse_recipients(to: str) -> list[str]:
    """Split a comma/semicolon-separated list into validated addresses
    (deduped, order preserved). Raises ValueError on a malformed address."""
    out: list[str] = []
    seen: set[str] = set()
    for part in re.split(r"[,;]", to or ""):
        addr = part.strip()
        if not addr:
            continue
        if not _EMAIL_RE.match(addr):
            raise ValueError(f"Not a valid email address: {addr!r}")
        if addr.lower() not in seen:
            seen.add(addr.lower())
            out.append(addr)
    return out


def email_report(*, to: str, subject: str, body_text: str, pdf_bytes: bytes | None,
                 filename: str, smtp: dict[str, Any]) -> None:
    """Email the report PDF via SMTP. `smtp` keys: host, port, user, pass, from,
    from_name. `to` may be a comma/semicolon-separated list. Port 465 → implicit
    SSL; otherwise STARTTLS is attempted. Raises ValueError when SMTP isn't
    configured or no valid recipient is given."""
    host = (smtp.get("host") or "").strip()
    if not host:
        raise ValueError("Email is not configured — set SMTP_HOST/PORT/USER/PASS/FROM "
                         "at /portal/credentials.")
    recipients = parse_recipients(to)            # validates before we open a socket
    if not recipients:
        raise ValueError("A recipient email address is required.")
    from_addr = (smtp.get("from") or smtp.get("user") or "noreply@medsim.local").strip()
    from_name = (smtp.get("from_name") or "").strip()
    msg = EmailMessage()
    msg["Subject"] = subject or "Clinical Report (Training Simulation)"
    msg["From"] = f"{from_name} <{from_addr}>" if from_name else from_addr
    msg["To"] = ", ".join(recipients)
    msg.set_content(body_text or "Attached: clinical report (training simulation).")
    if pdf_bytes:
        msg.add_attachment(pdf_bytes, maintype="application", subtype="pdf",
                           filename=filename or "report.pdf")
    port = int(smtp.get("port") or 587)
    ctx = ssl.create_default_context()
    user = (smtp.get("user") or "").strip()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=20, context=ctx) as s:
            if user:
                s.login(user, smtp.get("pass", ""))
            s.send_message(msg, to_addrs=recipients)
    else:
        with smtplib.SMTP(host, port, timeout=20) as s:
            try:
                s.starttls(context=ctx)
            except smtplib.SMTPException:
                pass  # server without STARTTLS (e.g. a local test relay)
            if user:
                s.login(user, smtp.get("pass", ""))
            s.send_message(msg, to_addrs=recipients)
