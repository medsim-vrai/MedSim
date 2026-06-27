# FR-015 — Clinical report generator (labs · diagnostics · referrals)

**Status:** R1 (labs), R3 (diagnostics), R4 (referrals), R5 (email hardening +
attach-to-chart) **DONE**; R2 (course linkage) planned. **Logged:** 2026-06-25.
**Surfaces:** instructor (Mission Control / control room); print + PDF + email.

## Objective

Let the instructor **generate real-looking clinical reports** — lab results,
diagnostic results, and referral/consult letters — for a scenario's patient, and
**print / download / email** them to students as they'd receive in the real
clinical workflow. The instructor can **control specific values** (to teach a
finding tied to course material), and run the generator either:

- **Pre-run** — from the patient character's history (persona → seed), before the
  scenario starts; or
- **Live** — from the running scenario's state (the frozen session seed +
  instructor chart edits).

## Reuse (already in the repo — do NOT rebuild)

- **`portal/data/clinical_ranges.json`** — 30+ conditions → vitals + lab panels
  (BMP, CBC, Lactate, ABG, Troponin, BNP, Coag, LFT, UDS…); each analyte
  `[low, high, flag]` with `L/H/C`.
- **`portal/ehr_seed.py`** — `seed_from_persona(persona, modules, scenario_text, ehr_id)`
  → `ChartSeed`; `_baseline_labs()` produces `labs_recent = [{panel, time,
  values:[{name, v, ref, flag}]}]`. `ehr_db.seed(session_id)` returns the frozen
  live seed; `seeds_for_patient_only(enc)` / `_encounter_for_persona` resolve a bed.
- **`scripts/md_to_pdf.py`** — reportlab MD→PDF (tables/branding) — the PDF engine.
- **`portal/templates/qr_print.html`** — print-friendly, branded, page-break layout pattern.
- **NCLEX curriculum linkage** (`../NCLEX curriculum linkage/NCLEX_Curriculum_Linkage_Workbook.xlsx`)
  — week/module → labs+diagnostics taught (drives R2 course-linkage).
- **PhysioBridge** (`../Physoligic engine control and integration/PhysioBridge_Workbook.xlsx`)
  — ECG rhythm catalog + Pulse outputs (drives R3 ECG/diagnostics).
- **`portal/data/med_orders.json`** — condition→treatment (informs R4 referrals).

## Report data model (R1)

```
report = {
  kind: "lab",                       # later: "diagnostic" | "referral"
  patient: {name, mrn, dob, sex, age, location},
  meta:    {collected, generated_by, generated_at, scenario_name, report_id, draft: bool},
  panels:  [{panel, time, values:[{name, v, ref, flag, overridden}]}],
  footer:  "Training simulation — not a real clinical result",
}
```

- **Override** = `{panel, analyte, value, flag?}`. Applied over the seed: set `v`,
  recompute `flag` from `ref` (`<lo`→L, `>hi`→H; explicit flag wins), mark
  `overridden` (shown to the instructor only, never on the student copy).
- Always stamp the **training disclaimer** + a synthetic patient banner.

## Delivery (R1)

- **Print** — branded HTML report (`@media print`), opens print dialog.
- **PDF** — reportlab download (`GET …/pdf`).
- **Email** — `smtplib` (stdlib), SMTP creds from the vault
  (`SMTP_HOST/PORT/USER/PASS/FROM`); **config-gated** — if unset, the email action
  returns "configure email at /portal/credentials" and print/PDF still work.

## Phases

| Phase | Scope |
|------|-------|
| **R1 — Labs (MVP)** ✅ | `portal/report_gen.py` (build model from seed + overrides; render HTML/PDF; email), instructor page (pick patient + panels + override values → preview → print/PDF/email), routes, tests. **DONE.** |
| **R2 — Course linkage** | Map NCLEX module/week → suggested panels + teachable analytes, so overrides tie to course material (`portal/data/curriculum_labs.json` authored from the NCLEX workbook). *Still planned.* |
| **R3 — Diagnostics** ✅ | `DIAGNOSTIC_CATALOG` in `report_gen.py` (ECG: rate/rhythm[15-option catalog]/intervals/axis/ST-T/interpretation; CXR / CT head / FAST: technique/findings/impression — all default to normal findings, instructor-editable). `build_diagnostic_report` + `diagnostic_html/pdf`; `POST /api/reports/diagnostic/{preview,pdf,email,attach}`; studio "🫀 Diagnostic" type. **DONE.** |
| **R4 — Referrals** ✅ | `REFERRAL_SPECIALTIES` (17 services) + consult-letter template (specialty, urgency, reason, history, findings, question). History/reason pre-fill from the chart seed (chief complaint + problem list + allergies). `build_referral_report` + `referral_html/pdf`; `POST /api/reports/referral/{preview,pdf,email,attach}`; studio "✉ Referral" type. **DONE.** |
| **R5 — Email hardening + attach-to-chart** ✅ | `parse_recipients` (comma/semicolon multi-recipient + validation + dedupe); port-465 implicit-SSL vs STARTTLS; `from_name` (SMTP_FROM_NAME); pre-flight address validation. Attach: `POST /api/reports/{kind}/attach` files the PDF into the patient chart via FR-014 `scanned_docs` (tagged `source="report"`, `kind=<label>`). Studio "📎 Attach to chart". **DONE.** *Deferred: SMTP setup UI at /portal/credentials + send-audit log.* |

## Gaps / additional support needed

- **Master analyte reference table** — `clinical_ranges.json` is condition-keyed,
  not a clean per-analyte catalog (units, critical thresholds, **age/sex/peds**
  ranges). R1 uses the existing per-condition refs; a vetted analyte catalog is a
  follow-on (R2/R3).
- **Diagnostic + referral clinical content** (R3/R4) must be authored.
- **⚠️ Clinical SME review REQUIRED before student-facing use** — units (e.g.
  troponin assay), age/sex/pregnancy ranges, and physiologically-consistent value
  combinations. R1 reports are stamped "training simulation — sim-tuned values,
  pending clinical review."
- **`reportlab`** must be declared in `pyproject.toml` (used by md_to_pdf, not yet a dep).

## Safety

Reports are **synthetic training artifacts**; every page carries a "training
simulation — not a real clinical result" banner. Instructor-only `overridden`
markers are stripped from the student/print/PDF/email copy.
