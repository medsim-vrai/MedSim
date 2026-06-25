"""FR-013b — Scenario Studio: guided, AI-assisted scenario generation.

The instructor describes a case (premise, objectives, acuity, setting), chooses a
patient (new-from-scratch or from the library), and supplies LOCAL factors —
standing orders, issues facing the local patient population, and key patient
features. Claude drafts a complete, runnable scenario from those inputs; the
instructor reviews/edits every field before saving (FR-008 "nothing live until
confirmed" posture).

LOCAL GROUNDING (the point of FR-013): the instructor's local factors AND the
active local-context library items (FR-013a) are woven into the generation
prompt, so the generated patient presentation, expected treatment path, and
supporting cast reflect LOCAL practice — not just generic best practice. The
same overlay still applies live at turn time (FR-013a runtime injection).

This module is split so the pieces that don't need the network — `build_prompt`,
`extract_json`, `normalize_draft` — are pure and unit-testable; only `generate`
makes the Anthropic call (mirroring runtime.py's client usage).
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from . import local_context as _lc

# Authoring is a one-shot, quality-sensitive task (unlike the latency-sensitive
# character turn, which uses haiku) — default to a stronger current model, but
# allow an env override per deployment / cost posture.
GEN_MODEL = os.environ.get("MEDSIM_SCENARIO_MODEL", "claude-sonnet-4-6")
MAX_TOKENS = 4096

# Vitals we always want the draft to carry (the EHR seeder + monitors read these).
_VITAL_KEYS = ("BP", "HR", "RR", "SpO2", "T")


# ── Input normalization ───────────────────────────────────────────────────

def _clean(s: Any) -> str:
    return str(s or "").strip()


def _as_lines(v: Any) -> list[str]:
    """Accept a list, or newline/bullet text, → a clean list of non-empty lines."""
    if isinstance(v, list):
        items = [_clean(x) for x in v]
    else:
        items = [re.sub(r"^[\-\*•\d.)\s]+", "", ln).strip()
                 for ln in _clean(v).splitlines()]
    return [x for x in items if x]


def coerce_inputs(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Coerce the request body into the canonical ScenarioInputs the prompt uses.
    Defensive: every field is optional except `premise` (validated in generate)."""
    raw = raw or {}
    lf = raw.get("local_factors") or {}
    if not isinstance(lf, dict):
        lf = {}
    patient = raw.get("patient") or {}
    if not isinstance(patient, dict):
        patient = {}
    return {
        "premise": _clean(raw.get("premise")),
        "objectives": _as_lines(raw.get("objectives")),
        "acuity": _clean(raw.get("acuity")) or "deteriorating",
        "setting": _clean(raw.get("setting")),
        "duration_min": int(raw.get("duration_min") or 30),
        "patient_mode": "library" if _clean(raw.get("patient_mode")) == "library" else "new",
        "patient": {
            "persona_id": _clean(patient.get("persona_id")),
            "name": _clean(patient.get("name")),
            "age": patient.get("age"),
            "sex": _clean(patient.get("sex")),
            "condition": _clean(patient.get("condition")),
        },
        "local_factors": {
            "standing_orders": _clean(lf.get("standing_orders")),
            "population_issues": _clean(lf.get("population_issues")),
            "patient_features": _clean(lf.get("patient_features")),
        },
        "use_local_overlay": bool(raw.get("use_local_overlay", True)),
        "cast_hint": _clean(raw.get("cast_hint")),
        "n_supporting": int(raw.get("n_supporting") or 0),
    }


# ── Prompt assembly (pure) ──────────────────────────────────────────────────

_SCHEMA_HINT = """Return STRICT JSON only (no prose, no code fence) matching:
{
  "name": "short scenario title",
  "notes": "instructor pre-brief: 1-2 sentences of setup + the learning objectives",
  "setting": "care setting, e.g. 'Med-surg floor'",
  "patient": {
    "name": "full name", "age": 68, "sex": "male|female|other",
    "condition": "primary diagnosis label",
    "history": "the clinical narrative that drives the chart: PMH, current presentation, recent vitals/labs, current state — concrete numbers (e.g. 'BP 84/52, lactate 4.2')",
    "baseline_vitals": {"BP": "112/68", "HR": "84", "RR": "18", "SpO2": "96%", "T": "37.1 C"}
  },
  "vitals_timeline": [
    {"t_minutes": 0, "vitals": {"BP": "...", "HR": "...", "RR": "...", "SpO2": "...", "T": "..."}}
  ],
  "scenario_text": "the bedside narrative the sim seeds from (may mirror patient.history)",
  "suggested_cast": [
    {"role": "Attending physician", "name": "Dr. ...", "why": "why they're in the scene", "shared": false}
  ],
  "curriculum": {"touchpoints": ["learning objective / key recognition point", "..."]},
  "treatment_path": ["expected key clinical actions, in order"],
  "modules": ["short curriculum tags, e.g. 'sepsis', 'delirium'"]
}"""


def _local_grounding_block(inputs: dict[str, Any]) -> str:
    """The LOCAL practice context that MUST shape the draft: the instructor's
    inline local factors + (optionally) the active local-context library items."""
    lf = inputs["local_factors"]
    parts: list[str] = []
    if lf["standing_orders"]:
        parts.append(f"Local standing orders:\n{lf['standing_orders']}")
    if lf["population_issues"]:
        parts.append(f"Issues facing this local patient population:\n{lf['population_issues']}")
    if lf["patient_features"]:
        parts.append(f"Key features of the patient(s) being modeled here:\n{lf['patient_features']}")
    if inputs["use_local_overlay"]:
        active = _lc.active_items()
        if active:
            lines = [f"  - [{it.get('type')}] {it.get('title')}: {it.get('content')}"
                     for it in active]
            parts.append("Active local-context library (this site's protocols/formulary/"
                         "priorities):\n" + "\n".join(lines))
    if not parts:
        return ""
    return ("LOCAL PRACTICE CONTEXT — the generated patient presentation, expected "
            "treatment path, and supporting cast MUST reflect these. Where a local "
            "item differs from generic best practice, follow the LOCAL item.\n\n"
            + "\n\n".join(parts))


def _patient_spec_block(inputs: dict[str, Any]) -> str:
    p = inputs["patient"]
    if inputs["patient_mode"] == "library" and p["persona_id"]:
        return (f"PATIENT: use the existing library patient '{p['persona_id']}'"
                + (f" ({p['name']})" if p["name"] else "")
                + ". Build the clinical narrative around that patient.")
    bits = [b for b in (
        f"name {p['name']}" if p["name"] else "",
        f"age {p['age']}" if p["age"] not in (None, "") else "",
        f"sex {p['sex']}" if p["sex"] else "",
        f"condition: {p['condition']}" if p["condition"] else "",
    ) if b]
    spec = "; ".join(bits) if bits else "invent a realistic patient that fits the premise"
    return f"PATIENT: create a NEW patient from scratch — {spec}."


def build_prompt(inputs: dict[str, Any]) -> tuple[str, str]:
    """Return (system_prompt, user_prompt). Pure — no network, no globals beyond
    the active local-context library (read for grounding)."""
    system = (
        "You are a clinical-simulation scenario author for healthcare training "
        "(nursing / allied health). Produce realistic, pedagogically sound, "
        "SAFE training scenarios. Ground every clinical detail in standard best "
        "practice, THEN layer the provided LOCAL practice context on top — local "
        "standing orders, population issues, and patient features must shape the "
        "presentation, the expected treatment path, and the supporting cast. "
        "Never invent medications or protocols beyond best practice + the local "
        "context. Use concrete numbers (vitals, labs) so the patient chart can be "
        "seeded from the narrative. " + _SCHEMA_HINT
    )
    grounding = _local_grounding_block(inputs)
    user_parts = [
        f"CASE PREMISE: {inputs['premise']}",
        f"SETTING: {inputs['setting']}" if inputs["setting"] else "",
        f"ACUITY / ARC: {inputs['acuity']} over ~{inputs['duration_min']} minutes "
        "(provide a vitals_timeline that reflects this arc).",
        ("LEARNING OBJECTIVES:\n" + "\n".join(f"  - {o}" for o in inputs["objectives"]))
        if inputs["objectives"] else "",
        _patient_spec_block(inputs),
        (f"SUPPORTING CAST: {inputs['cast_hint']}" if inputs["cast_hint"] else "")
        + (f" (about {inputs['n_supporting']} supporting characters)"
           if inputs["n_supporting"] else ""),
        grounding,
        "Now output the scenario as STRICT JSON per the schema. JSON only.",
    ]
    user = "\n\n".join(p for p in user_parts if p)
    return system, user


# ── Response parsing + draft normalization (pure) ───────────────────────────

def extract_json(text: str) -> dict[str, Any]:
    """Pull the JSON object out of a model reply that may be fenced or prose-
    wrapped. Raises ValueError if no parseable object is found."""
    t = _clean(text)
    # strip a leading ```json / ``` fence if present
    fence = re.search(r"```(?:json)?\s*(.+?)```", t, re.DOTALL | re.IGNORECASE)
    if fence:
        t = fence.group(1).strip()
    try:
        obj = json.loads(t)
    except ValueError:
        start, end = t.find("{"), t.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("no JSON object in model reply")
        obj = json.loads(t[start:end + 1])
    if not isinstance(obj, dict):
        raise ValueError("model reply was not a JSON object")
    return obj


def _norm_vitals(v: Any) -> dict[str, str]:
    if not isinstance(v, dict):
        return {}
    out = {k: _clean(v.get(k)) for k in _VITAL_KEYS if _clean(v.get(k))}
    # keep any extra vitals the model added, too
    for k, val in v.items():
        if k not in out and _clean(val):
            out[str(k)] = _clean(val)
    return out


def normalize_draft(raw: dict[str, Any]) -> dict[str, Any]:
    """Coerce a model draft into the canonical Scenario Studio draft shape, with
    safe defaults. Raises ValueError if the essential bones (name + patient) are
    missing — the instructor should regenerate rather than save junk."""
    if not isinstance(raw, dict):
        raise ValueError("draft is not an object")
    p = raw.get("patient") or {}
    if not isinstance(p, dict):
        p = {}
    name = _clean(raw.get("name"))
    history = _clean(p.get("history"))
    if not name or not history:
        raise ValueError("draft missing scenario name or patient history")

    age = p.get("age")
    try:
        age = int(age) if age not in (None, "") else None
    except (TypeError, ValueError):
        age = None

    timeline = []
    for row in (raw.get("vitals_timeline") or []):
        if not isinstance(row, dict):
            continue
        try:
            t = int(row.get("t_minutes"))
        except (TypeError, ValueError):
            continue
        vit = _norm_vitals(row.get("vitals"))
        if vit:
            timeline.append({"t_minutes": t, "vitals": vit})

    cast = []
    for c in (raw.get("suggested_cast") or []):
        if not isinstance(c, dict):
            continue
        role = _clean(c.get("role"))
        if not role:
            continue
        cast.append({
            "role": role,
            "name": _clean(c.get("name")),
            "why": _clean(c.get("why")),
            "shared": bool(c.get("shared")),
        })

    curriculum = raw.get("curriculum") or {}
    touchpoints = _as_lines(curriculum.get("touchpoints")
                            if isinstance(curriculum, dict) else None)

    return {
        "name": name,
        "notes": _clean(raw.get("notes")),
        "setting": _clean(raw.get("setting")),
        "patient": {
            "name": _clean(p.get("name")),
            "age": age,
            "sex": _clean(p.get("sex")),
            "condition": _clean(p.get("condition")),
            "history": history,
            "baseline_vitals": _norm_vitals(p.get("baseline_vitals")),
        },
        "vitals_timeline": timeline,
        "scenario_text": _clean(raw.get("scenario_text")) or history,
        "suggested_cast": cast,
        "curriculum": {"touchpoints": touchpoints},
        "treatment_path": _as_lines(raw.get("treatment_path")),
        "modules": _as_lines(raw.get("modules")),
    }


# ── Generation (the one networked entry point) ──────────────────────────────

def generate(raw_inputs: dict[str, Any] | None, *, api_key: str) -> dict[str, Any]:
    """Draft a scenario from the instructor inputs. Returns a normalized draft
    dict for review. Raises ValueError on bad input / unparseable reply;
    RuntimeError on an API failure."""
    if not _clean(api_key):
        raise ValueError("no Anthropic API key")
    inputs = coerce_inputs(raw_inputs)
    if not inputs["premise"]:
        raise ValueError("a case premise is required")
    system, user = build_prompt(inputs)
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=GEN_MODEL, max_tokens=MAX_TOKENS, system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(getattr(b, "text", "") for b in (resp.content or []))
    except Exception as exc:  # noqa: BLE001 — surface a clean message to the API layer
        raise RuntimeError(str(exc)) from exc
    draft = normalize_draft(extract_json(text))
    draft["_inputs"] = inputs            # echo back so the review UI / save can reuse
    draft["_model"] = GEN_MODEL
    return draft
