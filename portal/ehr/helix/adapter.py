"""Helix Health EHR adapter (Epic-style).

`install(seed, db)` is wired in Phase 4. For Phase 2 it's a stub that
returns the chart-seed unchanged so the bootstrap endpoint can hand
synthetic data to the bundle.
"""
from __future__ import annotations

from typing import Any


def install(seed: dict[str, Any], db: Any | None = None) -> dict[str, Any]:
    """Translate a neutral ChartSeed into Helix-native patient rows.

    Helix uses an MRN as primary key. Allergies render as
    'Substance (reaction)'. Care team becomes attending + PCP.
    """
    out = {
        "ehr_id":    "helix",
        "patients":  [_patient_row(seed)],
        "metadata":  {"format": "helix-1", "mrn_prefix": "HLX-"},
    }
    return out


def _patient_row(seed: dict[str, Any]) -> dict[str, Any]:
    care_team = seed.get("care_team") or []
    attending = next((c.get("name") for c in care_team if c.get("role", "").lower() == "attending"), "—")
    pcp = next((c.get("name") for c in care_team if "pcp" in c.get("role", "").lower()), "Unassigned")
    altered = seed.get("altered_state")
    status_extras = []
    if altered == "delirium":
        status_extras.append("Confused on arrival")
    elif altered == "alcohol-withdrawal":
        status_extras.append("CIWA q4h")
    return {
        "mrn":       seed.get("mrn", "HLX-XXXXX"),
        "name":      seed.get("name", "—"),
        "chief_complaint": seed.get("chief_complaint", ""),
        "persona_label":   seed.get("persona_label", ""),
        "dob":       seed.get("dob", ""),
        "age":       _age_from_dob(seed.get("dob")),
        "sex":       seed.get("sex", "U"),
        "pronouns":  seed.get("pronouns", "they/them"),
        "room":      (seed.get("encounter") or {}).get("location", "—"),
        "status":    " · ".join(filter(None, [(seed.get("encounter") or {}).get("type", "Inpatient"), *status_extras])),
        "allergies": [_fmt_allergy(a) for a in (seed.get("allergies") or [])] or ["NKDA"],
        "code":      seed.get("code_status", "Full Code"),
        "isolation": (seed.get("encounter") or {}).get("isolation", "Standard"),
        "problems":  [_fmt_problem(p) for p in (seed.get("problem_list") or [])],
        "meds":      [_fmt_med(m) for m in (seed.get("medications") or [])],
        "pcp":       pcp,
        "attending": attending,
    }


def _fmt_allergy(a: Any) -> str:
    if isinstance(a, str):
        return a
    sub = a.get("substance") or a.get("name") or "—"
    rxn = a.get("reaction") or a.get("severity") or ""
    return f"{sub} ({rxn})" if rxn else sub


def _fmt_problem(p: Any) -> str:
    if isinstance(p, str):
        return p
    name = p.get("name") or p.get("display") or "—"
    onset = p.get("onset") or ""
    return f"{name} ({onset})" if onset else name


def _fmt_med(m: Any) -> str:
    if isinstance(m, str):
        return m
    name = m.get("name") or "—"
    dose = m.get("dose") or ""
    freq = m.get("frequency") or m.get("freq") or ""
    return " ".join(filter(None, [name, dose, freq]))


def _age_from_dob(dob: str | None) -> int | str:
    if not dob:
        return ""
    try:
        from datetime import date
        y, m, d = (int(x) for x in dob.split("-")[:3])
        today = date.today()
        return today.year - y - ((today.month, today.day) < (m, d))
    except Exception:
        return ""
