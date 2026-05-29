"""Cyrus Care EHR adapter (Cerner-style).

Cyrus uses BOTH `fin` (financial number, encounter-scoped) and `mrn`
(patient-scoped). Care team is a list of role-prefixed strings.
"""
from __future__ import annotations

from typing import Any


def install(seed: dict[str, Any], db: Any | None = None) -> dict[str, Any]:
    return {
        "ehr_id":    "cyrus",
        "patients":  [_patient_row(seed)],
        "metadata":  {"format": "cyrus-1", "mrn_prefix": "CY-", "fin_prefix": "FIN-2026-"},
    }


def _patient_row(seed: dict[str, Any]) -> dict[str, Any]:
    care_team = seed.get("care_team") or []
    attending = next((c.get("name") for c in care_team if c.get("role", "").lower() == "attending"), "—")
    team_strs = []
    for c in care_team:
        role = (c.get("role") or "RN").upper()[:8]
        team_strs.append(f"{role}: {c.get('name', '—')}")
    altered = seed.get("altered_state")
    status_extras = []
    if altered == "delirium":
        status_extras.append("CAM positive")
    elif altered == "alcohol-withdrawal":
        status_extras.append("CIWA q4h")
    encounter = seed.get("encounter") or {}
    return {
        "fin":       seed.get("fin") or _synth_fin(seed),
        "mrn":       seed.get("mrn", "CY-XXXXX"),
        "name":      seed.get("name", "—"),
        "chief_complaint": seed.get("chief_complaint", ""),
        "persona_label":   seed.get("persona_label", ""),
        "dob":       seed.get("dob", ""),
        "age":       _age_from_dob(seed.get("dob")),
        "sex":       seed.get("sex", "U"),
        "pronouns":  seed.get("pronouns", "they/them"),
        "location":  encounter.get("location", "—"),
        "los":       encounter.get("los", "—"),
        "status":    " · ".join(filter(None, [encounter.get("type", "Inpatient"), *status_extras])),
        "allergies": [_fmt_allergy(a) for a in (seed.get("allergies") or [])] or ["NKDA"],
        "code":      seed.get("code_status", "Full Code"),
        "isolation": encounter.get("isolation", "Standard"),
        "weight":    seed.get("weight", ""),
        "height":    seed.get("height", ""),
        "bsa":       seed.get("bsa", ""),
        "problems":  [_fmt_problem(p) for p in (seed.get("problem_list") or [])],
        "meds":      [_fmt_med(m) for m in (seed.get("medications") or [])],
        "attending": attending,
        "care_team": team_strs,
    }


def _synth_fin(seed: dict[str, Any]) -> str:
    mrn = seed.get("mrn", "0000000")
    return "FIN-2026-" + "".join(c for c in mrn if c.isdigit())[-7:].rjust(7, "0")


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
    return name


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
