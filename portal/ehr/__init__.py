"""EHR template registry — V3.

Three pluggable EHR look-alikes (Helix Health, Cyrus Care, Meridian EHR).
Each one lives in `portal/ehr/{ehr_id}/` and exposes:

- `index.html`     — single-file bundle with V3 bootstrap injected
- `app.jsx`, `ui.jsx`, `screens.jsx`, `data.jsx` — React+Babel standalone
- `catalog.json`   — order catalog for the CPOE / PowerOrders / Orders tab
- `adapter.py`     — `install(seed, db)` for the pre-population pipeline (Phase 4)

This module is the single source of truth for what EHRs the system offers.
The wizard radio, the bootstrap endpoint, the catalog endpoint, and the
adapter import all walk this registry.
"""
from __future__ import annotations

from pathlib import Path

EHR_DIR = Path(__file__).resolve().parent

# Display order matters — first entry is the wizard default when the
# scenario JSON doesn't pin one.
REGISTRY: list[dict[str, str]] = [
    {
        "id":       "helix",
        "name":     "Helix Health",
        "subtitle": "Epic-style",
        "blurb":    "Cobalt + mustard. Tabs: Chart, Vitals, Notes (SmartPhrase), Ambient Scribe, CPOE, Results, MAR.",
        "accent":   "#143b8a",
    },
    {
        "id":       "cyrus",
        "name":     "Cyrus Care",
        "subtitle": "Cerner-style",
        "blurb":    "Teal/navy. Tabs: Worklist, Patient Summary, iView Flowsheet, PowerNote, Ambient Capture, PowerOrders, Results Review.",
        "accent":   "#0e4c5e",
    },
    {
        "id":       "meridian",
        "name":     "Meridian EHR",
        "subtitle": "Meditech-style",
        "blurb":    "Sage/cream. Tabs: My Day, Chart, Vitals, Document, Voice+Scribe, Orders, Results.",
        "accent":   "#4a7556",
    },
]


def all_ids() -> list[str]:
    return [e["id"] for e in REGISTRY]


def get(ehr_id: str) -> dict[str, str] | None:
    for e in REGISTRY:
        if e["id"] == ehr_id:
            return e
    return None


def default_id() -> str:
    return REGISTRY[0]["id"]


def bundle_path(ehr_id: str) -> Path | None:
    """Return the directory containing the EHR's index.html bundle."""
    if get(ehr_id) is None:
        return None
    return EHR_DIR / ehr_id


def catalog(ehr_id: str) -> list[dict]:
    """Load the EHR's order catalog JSON; empty list on missing."""
    import json
    path = EHR_DIR / ehr_id / "catalog.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return []
