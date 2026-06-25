"""FR-013b — persistence for instructor-authored scenarios + the personas they
mint.

A generated scenario must be FIRST-CLASS in the launch wizard: appear in the
Scenario step, pre-fill its cast, and seed the EHR. The wizard builds itself
from `library.list_sample_scenarios()` (sample-record shape: `personas[]` of IDs
+ `scenario_text`) and `library.list_personas()` (the catalog `_patient_of`
scans for `roleGroup=="Patient"`). So we save:

  • authored scenarios → a sample-record list (merged into list_sample_scenarios)
  • the personas they reference → a persona list (merged into list_personas)

stored as small JSON files under portal/data/authored/ (writable, gitignored,
PHI-free, survives reset.sh — program-authored content, not session state).
`library` reads these at call time and APPENDS them to the static catalog, so a
newly saved scenario shows up without a restart (the static `*_doc()` loaders
are lru-cached; these are deliberately NOT).

Patient identity + the EHR chart are generated downstream by ehr_seed from the
patient persona (name, ageRange, sex, condition) + scenario_text — so a new
patient just needs a persona with those fields.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

# Writable, gitignored. Read at call time so tests can monkeypatch the dir.
AUTHORED_DIR = Path(__file__).resolve().parent / "data" / "authored"
SCENARIOS_PATH = AUTHORED_DIR / "scenarios.json"
PERSONAS_PATH = AUTHORED_DIR / "personas.json"


def _load(path: Path) -> list[dict[str, Any]]:
    try:
        if path.exists():
            data = json.loads(path.read_text("utf-8"))
            if isinstance(data, list):
                return data
    except (OSError, ValueError):
        pass
    return []


def _save(path: Path, items: list[dict[str, Any]]) -> None:
    AUTHORED_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / (path.name + ".tmp")
    tmp.write_text(json.dumps(items, indent=2), "utf-8")
    tmp.replace(path)   # atomic — never leave a half-written catalog


# ── read ────────────────────────────────────────────────────────────────

def list_scenarios() -> list[dict[str, Any]]:
    return _load(SCENARIOS_PATH)


def list_personas() -> list[dict[str, Any]]:
    return _load(PERSONAS_PATH)


def get_scenario(scenario_id: str) -> dict[str, Any] | None:
    return next((s for s in list_scenarios() if s.get("id") == scenario_id), None)


# ── write (upsert by id) ──────────────────────────────────────────────────

def _upsert(path: Path, record: dict[str, Any]) -> dict[str, Any]:
    items = _load(path)
    items = [it for it in items if it.get("id") != record["id"]]
    items.append(record)
    _save(path, items)
    return record


def save_persona(record: dict[str, Any]) -> dict[str, Any]:
    return _upsert(PERSONAS_PATH, record)


def save_scenario(record: dict[str, Any]) -> dict[str, Any]:
    return _upsert(SCENARIOS_PATH, record)


def remove_scenario(scenario_id: str) -> bool:
    items = list_scenarios()
    kept = [s for s in items if s.get("id") != scenario_id]
    if len(kept) == len(items):
        return False
    _save(SCENARIOS_PATH, kept)
    return True


# ── synthesis (draft → personas + scenario record) ─────────────────────────

def _slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (s or "").lower())).strip("-") or "scenario"


_FAMILY_KW = ("wife", "husband", "son", "daughter", "mother", "father", "family",
              "spouse", "parent", "partner", "caregiver", "sister", "brother")
_ALLIED_KW = ("respiratory", "rt", "pharmacist", "therap", "tech", "dietit",
              "social work", "chaplain", "phlebot", "nutrition")


def _role_group(role: str) -> str:
    r = (role or "").lower()
    if any(k in r for k in _FAMILY_KW):
        return "Family"
    if any(k in r for k in _ALLIED_KW):
        return "Allied Health"
    return "Clinician"


def _new_persona_id() -> str:
    return "AUTH-" + uuid.uuid4().hex[:8].upper()


def _synth_patient_persona(patient: dict[str, Any]) -> dict[str, Any]:
    """A minimal persona the EHR seeder can chart from (name, ageRange, sex,
    condition). roleGroup MUST be 'Patient' so the wizard's _patient_of picks it."""
    age = patient.get("age")
    return {
        "id": _new_persona_id(),
        "name": patient.get("name") or "Authored Patient",
        "roleGroup": "Patient",
        "role": "Patient",
        "ageRange": str(age) if age not in (None, "") else "",
        "sex": patient.get("sex") or "",
        "condition": patient.get("condition") or "",
        "voiceProfile": "",                 # neutral default until a voice/skin is assigned
        "knowledgeScope": "",
        "safetyClass": "baseline",
        "source": "authored",
    }


def _synth_cast_persona(cast: dict[str, Any]) -> dict[str, Any]:
    role = cast.get("role") or "Clinician"
    return {
        "id": _new_persona_id(),
        "name": cast.get("name") or role,
        "roleGroup": _role_group(role),
        "role": role,
        "ageRange": "35-55",
        "voiceProfile": "",
        "knowledgeScope": cast.get("why") or "",
        "safetyClass": "baseline",
        "source": "authored",
    }


def create_from_draft(draft: dict[str, Any]) -> dict[str, Any]:
    """Turn a reviewed Scenario Studio draft into persisted personas + a
    first-class sample-record scenario. Returns the saved scenario record.

    - New-patient mode → synthesize a patient persona; library mode → reference
      the chosen library persona id (no synthesis).
    - Each suggested-cast entry → a synthesized supporting persona.
    - personas[] = [patient, ...cast] (patient first, roleGroup 'Patient').
    """
    if not isinstance(draft, dict):
        raise ValueError("draft is not an object")
    name = (draft.get("name") or "").strip()
    patient = draft.get("patient") or {}
    history = (patient.get("history") or "").strip()
    if not name or not history:
        raise ValueError("draft missing scenario name or patient history")

    inputs = draft.get("_inputs") or {}
    pin = inputs.get("patient") or {}
    persona_ids: list[str] = []

    # patient persona
    if inputs.get("patient_mode") == "library" and (pin.get("persona_id") or "").strip():
        persona_ids.append(pin["persona_id"].strip())
    else:
        pp = _synth_patient_persona(patient)
        save_persona(pp)
        persona_ids.append(pp["id"])

    # supporting cast
    for c in (draft.get("suggested_cast") or []):
        if not isinstance(c, dict) or not (c.get("role") or "").strip():
            continue
        cp = _synth_cast_persona(c)
        save_persona(cp)
        persona_ids.append(cp["id"])

    record = {
        "id": _slug(name) + "-" + uuid.uuid4().hex[:6],
        "name": name,
        "notes": (draft.get("notes") or "").strip(),
        "program_id": "",
        "week": None,
        "modules": list(draft.get("modules") or []),
        "personas": persona_ids,
        "scenario_text": (draft.get("scenario_text") or history).strip(),
        "source": "authored",
        "created_at": time.time(),
        # richer authored detail (harmless extras the current wizard ignores;
        # available for future launch use — vitals timeline, debrief, etc.)
        "setting": (draft.get("setting") or "").strip(),
        "baseline_vitals": patient.get("baseline_vitals") or {},
        "vitals_timeline": draft.get("vitals_timeline") or [],
        "curriculum": draft.get("curriculum") or {"touchpoints": []},
        "treatment_path": draft.get("treatment_path") or [],
    }
    return save_scenario(record)
