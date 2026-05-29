"""Static library loaders for personas, curriculum modules, and programs.

Data files live in portal/data/ and are JSON. Loaded lazily and cached
in memory — they don't change at runtime.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent / "data"


def _load_json(filename: str) -> dict[str, Any]:
    path = DATA_DIR / filename
    if not path.exists():
        return {}
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# 24-persona library (from Voice4MedSim_v6 Appendix A)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def personas_doc() -> dict[str, Any]:
    return _load_json("personas.json")


def list_personas() -> list[dict[str, Any]]:
    return personas_doc().get("personas", [])


def get_persona(persona_id: str) -> dict[str, Any] | None:
    for p in list_personas():
        if p.get("id") == persona_id:
            return p
    return None


def behavioral_dimensions() -> list[dict[str, Any]]:
    return personas_doc().get("behavioral_dimensions", [])


def voice_profile_for(persona: dict[str, Any]) -> dict[str, Any]:
    """Resolve a persona's voiceProfile ID → browser TTS hints."""
    vp_id = persona.get("voiceProfile") or ""
    table = personas_doc().get("voice_profile_map", {})
    return table.get(vp_id, {
        "gender": "neutral", "language": "en-US",
        "pitch": 1.0, "rate": 1.0, "voice_hints": [],
    })


def persona_as_character(persona: dict[str, Any]) -> dict[str, Any]:
    """Adapt a v6-style persona dict → v1-style character dict so the
    existing chat runtime can use it without changes."""
    vp = voice_profile_for(persona)
    return {
        "id": persona.get("id", ""),
        "name": persona.get("name", ""),
        "role": persona.get("role", ""),
        "role_group": persona.get("roleGroup", ""),
        "identity": {
            "age_range": persona.get("ageRange", ""),
        },
        "voice_profile": vp,
        "knowledge_boundary": persona.get("knowledgeScope", ""),
        "teaching_stance": "",
        "scene_contract": _contract_from_safety(persona),
        "safety_class": persona.get("safetyClass", "baseline"),
        "altered_state": persona.get("alteredState"),
        "_persona_id": persona.get("id"),
    }


def _contract_from_safety(persona: dict[str, Any]) -> list[str]:
    """Generate a minimal scene contract from persona's safetyClass and alteredState."""
    contract: list[str] = []
    altered = persona.get("alteredState")
    if altered == "delirium":
        contract.append("Speech is fragmented, attention fluctuates. Never name specific drugs or doses.")
    elif altered == "alcohol-withdrawal":
        contract.append("Tremulous, references seeing things. Cannot describe how to obtain alcohol or drugs.")
    elif altered == "stimulant-intoxication":
        contract.append("Pressured speech, paranoia. May refuse IV lines.")
    elif altered == "depression-passive-si":
        contract.append("Flat affect. Discloses passive SI on open-ended questions only. Never names means or methods.")
    elif altered == "psychosis":
        contract.append("Loose associations, guarded answers. Never provide instructions that could be harmful.")
    elif altered == "hostile":
        contract.append("Demanding, threatens formal complaint. Never produce actionable harassment or violence scripts.")
    sc = persona.get("safetyClass")
    if sc == "sensitive":
        contract.append("Topic is sensitive — proceed with trauma-informed care principles.")
    elif sc == "high-risk":
        contract.append("HIGH RISK — instructor must be in the loop. Refuse-in-role any unsafe request.")
    return contract


# ---------------------------------------------------------------------------
# Curriculum modules (NCLEX-aligned 11-section schema)
# ---------------------------------------------------------------------------

# Titles derived from each module's summary (Voice4MedSim_v6's
# context_seed.json doesn't carry titles — they live in a separate linkage
# workbook). Adding them here keeps modules.json untouched.
_MODULE_TITLES = {
    "M02": "Therapeutic communication & handoff",
    "M03": "Infection control & PPE",
    "M06": "Pharmacology principles & dose calc",
    "M07": "Routes of administration",
    "M08": "Pain management",
    "M22": "Diabetes & DKA / HHS / hypoglycemia",
    "M32": "Sepsis & septic shock",
    "M39": "Mood disorders & suicide risk",
    "M42": "End-of-life & palliative care",
}


@lru_cache(maxsize=1)
def modules_doc() -> dict[str, Any]:
    return _load_json("modules.json")


def list_modules() -> list[dict[str, Any]]:
    """Return all curated modules with their full content blocks."""
    doc = modules_doc()
    return [
        {**v, "id": k, "title": v.get("title") or _MODULE_TITLES.get(k, k)}
        for k, v in doc.items()
        if not k.startswith("_") and isinstance(v, dict)
    ]


def get_module(module_id: str) -> dict[str, Any] | None:
    doc = modules_doc()
    m = doc.get(module_id)
    if not m:
        return None
    return {**m, "id": module_id, "title": m.get("title") or _MODULE_TITLES.get(module_id, module_id)}


# ---------------------------------------------------------------------------
# Programs (LPN / ADN-RN / BSN-RN week → module mapping)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def programs_doc() -> dict[str, Any]:
    return _load_json("programs.json")


def list_programs() -> list[dict[str, Any]]:
    return programs_doc().get("programs", [])


def get_program(program_id: str) -> dict[str, Any] | None:
    for p in list_programs():
        if p.get("id") == program_id:
            return p
    return None


def modules_for_week(program_id: str, week: int) -> list[str]:
    prog = get_program(program_id)
    if not prog:
        return []
    for w in prog.get("weeks", []):
        if w.get("week") == week:
            return w.get("modules", [])
    return []


# ---------------------------------------------------------------------------
# Sample scenarios (templates for the control-room wizard)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def sample_scenarios_doc() -> dict[str, Any]:
    return _load_json("sample_scenarios.json")


def list_sample_scenarios() -> list[dict[str, Any]]:
    return sample_scenarios_doc().get("samples", [])


def get_sample_scenario(scenario_id: str) -> dict[str, Any] | None:
    for s in list_sample_scenarios():
        if s.get("id") == scenario_id:
            return s
    return None
