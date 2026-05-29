"""Data layer for scenarios, characters, and debriefs.

YAML files in scenarios/ and characters/ are the persistent form. The portal
reads them via list_*() / get_*() and writes them via save_*() / delete_*() /
duplicate_*(). Schema validation happens at load-time in B1/B2; this layer
just round-trips the YAML and provides convenience helpers.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCENARIOS_DIR = PROJECT_ROOT / "scenarios"
CHARACTERS_DIR = PROJECT_ROOT / "characters"
DEBRIEFS_DIR = PROJECT_ROOT / "data" / "debriefs"

_SLUG_RE = re.compile(r"[^a-z0-9_]+")


def slugify(text: str) -> str:
    s = _SLUG_RE.sub("_", (text or "").lower().strip()).strip("_")
    return s or "untitled"


def _dump(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, sort_keys=False, default_flow_style=False, allow_unicode=True)


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

def list_scenarios() -> list[dict[str, Any]]:
    if not SCENARIOS_DIR.exists():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(SCENARIOS_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text()) or {}
            error = None
        except yaml.YAMLError as exc:
            data = {}
            error = str(exc)
        out.append({
            "id": data.get("id", path.stem),
            "name": data.get("name", path.stem),
            "characters": data.get("characters", []) or [],
            "patient_summary": _patient_summary(data.get("patient", {}) or {}),
            "error": error,
            "path": str(path),
        })
    return out


def get_scenario(scenario_id: str) -> dict[str, Any] | None:
    path = SCENARIOS_DIR / f"{scenario_id}.yaml"
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError:
        return None


def save_scenario(data: dict[str, Any], old_id: str | None = None) -> str:
    SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)
    new_id = (data.get("id") or "").strip() or slugify(data.get("name", ""))
    data["id"] = new_id
    (SCENARIOS_DIR / f"{new_id}.yaml").write_text(_dump(data))
    if old_id and old_id != new_id:
        old_path = SCENARIOS_DIR / f"{old_id}.yaml"
        if old_path.exists():
            old_path.unlink()
    return new_id


def delete_scenario(scenario_id: str) -> bool:
    path = SCENARIOS_DIR / f"{scenario_id}.yaml"
    if path.exists():
        path.unlink()
        return True
    return False


def duplicate_scenario(scenario_id: str) -> str | None:
    src = SCENARIOS_DIR / f"{scenario_id}.yaml"
    if not src.exists():
        return None
    try:
        data = yaml.safe_load(src.read_text()) or {}
    except yaml.YAMLError:
        return None
    new_id = _unique_id(SCENARIOS_DIR, f"{scenario_id}_copy")
    data["id"] = new_id
    data["name"] = (data.get("name") or scenario_id) + " (copy)"
    (SCENARIOS_DIR / f"{new_id}.yaml").write_text(_dump(data))
    return new_id


def _patient_summary(patient: dict[str, Any]) -> str:
    parts = []
    if patient.get("age") not in (None, ""):
        parts.append(f"{patient['age']}y")
    if patient.get("sex"):
        parts.append(str(patient["sex"]).lower())
    if patient.get("history"):
        h = str(patient["history"])
        parts.append(h[:60] + ("…" if len(h) > 60 else ""))
    return " · ".join(parts)


# ---------------------------------------------------------------------------
# Characters
# ---------------------------------------------------------------------------

def list_characters() -> list[dict[str, Any]]:
    if not CHARACTERS_DIR.exists():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(CHARACTERS_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text()) or {}
            error = None
        except yaml.YAMLError as exc:
            data = {}
            error = str(exc)
        out.append({
            "id": data.get("id", path.stem),
            "name": data.get("name", path.stem),
            "role": data.get("role", "") or "",
            "teaching_stance": data.get("teaching_stance", "") or "",
            "error": error,
            "path": str(path),
        })
    return out


def get_character(character_id: str) -> dict[str, Any] | None:
    path = CHARACTERS_DIR / f"{character_id}.yaml"
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError:
        return None


def save_character(data: dict[str, Any], old_id: str | None = None) -> str:
    CHARACTERS_DIR.mkdir(parents=True, exist_ok=True)
    new_id = (data.get("id") or "").strip() or slugify(data.get("name", ""))
    data["id"] = new_id
    (CHARACTERS_DIR / f"{new_id}.yaml").write_text(_dump(data))
    if old_id and old_id != new_id:
        old_path = CHARACTERS_DIR / f"{old_id}.yaml"
        if old_path.exists():
            old_path.unlink()
    return new_id


def delete_character(character_id: str) -> bool:
    path = CHARACTERS_DIR / f"{character_id}.yaml"
    if path.exists():
        path.unlink()
        return True
    return False


def duplicate_character(character_id: str) -> str | None:
    src = CHARACTERS_DIR / f"{character_id}.yaml"
    if not src.exists():
        return None
    try:
        data = yaml.safe_load(src.read_text()) or {}
    except yaml.YAMLError:
        return None
    new_id = _unique_id(CHARACTERS_DIR, f"{character_id}_copy")
    data["id"] = new_id
    data["name"] = (data.get("name") or character_id) + " (copy)"
    (CHARACTERS_DIR / f"{new_id}.yaml").write_text(_dump(data))
    return new_id


# ---------------------------------------------------------------------------
# Debriefs
# ---------------------------------------------------------------------------

def list_debriefs() -> list[dict[str, Any]]:
    if not DEBRIEFS_DIR.exists():
        return []
    out = []
    for path in sorted(DEBRIEFS_DIR.glob("*.md"), reverse=True):
        stat = path.stat()
        out.append({
            "name": path.stem,
            "size_kb": round(stat.st_size / 1024, 1),
            "path": str(path),
        })
    return out


# ---------------------------------------------------------------------------
# Example loader (called from the Home page)
# ---------------------------------------------------------------------------

def load_examples() -> dict[str, list[str]]:
    """Load the sepsis worked example from the PDF — 4 characters + 1 scenario.

    Skips any file that already exists, so a second click is safe.
    """
    from . import example
    created_chars: list[str] = []
    created_scens: list[str] = []
    CHARACTERS_DIR.mkdir(parents=True, exist_ok=True)
    SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)
    for c in example.CHARACTERS:
        path = CHARACTERS_DIR / f"{c['id']}.yaml"
        if not path.exists():
            path.write_text(_dump(c))
            created_chars.append(c["id"])
    for s in example.SCENARIOS:
        path = SCENARIOS_DIR / f"{s['id']}.yaml"
        if not path.exists():
            path.write_text(_dump(s))
            created_scens.append(s["id"])
    return {"characters": created_chars, "scenarios": created_scens}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unique_id(directory: Path, base: str) -> str:
    candidate = base
    n = 1
    while (directory / f"{candidate}.yaml").exists():
        n += 1
        candidate = f"{base}{n}"
    return candidate
