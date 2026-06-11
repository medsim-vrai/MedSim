# FR-008 — instructor-staged medication errors (S1: catalog + arming engine).
#
# The instructor arms a CLASSIFIED error along four axes: type × vector ×
# encounter point × optional patient impact (S4). This module is the engine
# core: grounded suggestions, arm/disarm/resolve lifecycle, per-session state.
#
# Boundedness (the design's spine):
#   • Suggestions come ONLY from catalog ∩ session (formulary/MAR/allergies) —
#     no free-text clinical content can enter the system through this path.
#   • Errors live in _SESSION_ERRORS (memory) and, from S2 on, as surgical
#     edits to the session's PRIVATE chart record — authored scenario files are
#     never touched (standing constraint).
#   • Every armed record carries a `snapshot` slot so document-vector edits
#     restore byte-for-byte on disarm (S2 wires it; the field exists now).
#
# S1 scope: suggest/arm/disarm/resolve/state. No application of the error yet
# (S2 document vector, S3 verbal vector, S4 impact), no UI (S5), no behavior
# change while nothing is armed.

from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path
from typing import Any

DATA = Path(__file__).resolve().parent / "data" / "med_errors.json"

TYPES = ("transcription", "wrong_dose", "interaction", "allergy", "admin")

# The instructor's taxonomy: which vector(s) can realistically introduce each
# error type (FR-008 spec table — type 1 verbal-only, type 5 document-only).
VECTORS_BY_TYPE: dict[str, tuple[str, ...]] = {
    "transcription": ("verbal",),
    "wrong_dose": ("verbal", "document"),
    "interaction": ("verbal", "document"),
    "allergy": ("verbal", "document"),
    "admin": ("document",),
}

ENCOUNTERS = ("report", "charting", "prep", "med_pass")

_MAX_SUGGESTIONS = 6

_catalog_cache: dict[str, Any] | None = None

# session_id -> {"seq": int, "errors": [armed-record, ...]}
_SESSION_ERRORS: dict[str, dict[str, Any]] = {}


def catalog() -> dict[str, Any]:
    global _catalog_cache
    if _catalog_cache is None:
        _catalog_cache = json.loads(DATA.read_text(encoding="utf-8"))
    return _catalog_cache


# ── session grounding ─────────────────────────────────────────────────────────

def _board_items(session_id: str) -> list[dict[str, Any]]:
    try:
        from . import med_orders
        state = med_orders.get_state(session_id)
        return list((state or {}).get("items") or [])
    except Exception:  # noqa: BLE001 — grounding is best-effort
        return []


def _mar_names(session_id: str) -> list[str]:
    try:
        from . import med_orders
        return med_orders.active_med_names(session_id)
    except Exception:  # noqa: BLE001
        return []


def _documented_allergies(session_id: str) -> list[dict[str, str]]:
    try:
        from . import ehr_db
        chart = ehr_db.seed(session_id) or {}
        return [a for a in (chart.get("allergies") or []) if isinstance(a, dict)]
    except Exception:  # noqa: BLE001
        return []


def _formulary_names() -> set[str]:
    """Every drug orderable anywhere in the authored formulary (all conditions)."""
    try:
        from . import med_orders
        names: set[str] = set()
        for key, entry in med_orders.catalog().items():
            if key.startswith("_"):
                continue
            for tier in ("primary", "alternative"):
                for opt in entry.get(tier) or []:
                    n = str(opt.get("drug") or "").strip()
                    if n:
                        names.add(n)
        return names
    except Exception:  # noqa: BLE001
        return set()


def _name_match(needle: str, hay: str) -> bool:
    """'Heparin' matches 'Heparin gtt' / 'heparin 5000 units' — word-boundary
    containment, case-insensitive. Keeps grounding tolerant of MAR phrasing."""
    return re.search(rf"\b{re.escape(needle.lower())}\b", hay.lower()) is not None


def _on_session(session_id: str, drug: str) -> tuple[bool, dict[str, Any] | None]:
    """Is this drug on the session's board or MAR? Returns (found, board_item)."""
    for it in _board_items(session_id):
        if _name_match(drug, str(it.get("drug") or "")):
            return True, it
    for n in _mar_names(session_id):
        if _name_match(drug, n):
            return True, None
    return False, None


# ── dose transforms ────────────────────────────────────────────────────────────

_NUM_RE = re.compile(r"(\d+(?:\.\d+)?)")


def _fmt_num(x: float) -> str:
    s = f"{x:.4f}".rstrip("0").rstrip(".")
    return s if s else "0"


def transform_dose(dose: str, t: dict[str, Any]) -> str | None:
    """Apply one catalog dose transform to a dose string ('0.5 mg' ×10 → '5 mg';
    '25 mcg' mg-for-mcg → '25 mg'). None when the dose can't support it — the
    candidate is then simply not offered (bounded by construction)."""
    dose = (dose or "").strip()
    if not dose or dose == "—":
        return None
    if t.get("op") == "mul":
        m = _NUM_RE.search(dose)
        if not m:
            return None
        wrong = float(m.group(1)) * float(t["factor"])
        if wrong <= 0 or wrong >= 100000:
            return None
        return dose[:m.start(1)] + _fmt_num(wrong) + dose[m.end(1):]
    if t.get("op") == "unit_swap":
        frm, to = str(t.get("from") or ""), str(t.get("to") or "")
        if not frm or not to:
            return None
        if not re.search(rf"\b{re.escape(frm)}\b", dose):
            return None
        return re.sub(rf"\b{re.escape(frm)}\b", to, dose, count=1)
    return None


# ── suggestions ────────────────────────────────────────────────────────────────

def _rng(session_id: str, *salt: str) -> random.Random:
    return random.Random(f"{session_id}:med-errors:{':'.join(salt)}")


def suggest(session_id: str, err_type: str, vector: str,
            encounter: str) -> list[dict[str, Any]]:
    """Grounded candidates for the chosen axes. Deterministic per (session, axes).
    Raises ValueError on an axis combination outside the instructor's taxonomy."""
    _validate_axes(err_type, vector, encounter)
    cat = catalog()
    out: list[dict[str, Any]] = []

    if err_type == "transcription":
        for pair in cat.get("sound_alike_pairs") or []:
            for intended, wrong in ((pair["a"], pair["b"]), (pair["b"], pair["a"])):
                found, item = _on_session(session_id, intended)
                if not found:
                    continue
                dose = str((item or {}).get("dose") or "")
                out.append({
                    "type": err_type, "vector": vector, "encounter": encounter,
                    "intended_drug": intended, "wrong_drug": wrong,
                    "dose": dose, "note": str(pair.get("note") or ""),
                    "display": f"“{wrong}” heard for {intended}"
                               + (f" ({dose})" if dose else ""),
                })

    elif err_type == "wrong_dose":
        for it in _board_items(session_id):
            drug, dose = str(it.get("drug") or ""), str(it.get("dose") or "")
            for t in cat.get("dose_transforms") or []:
                wrong = transform_dose(dose, t)
                if wrong is None or wrong == dose:
                    continue
                out.append({
                    "type": err_type, "vector": vector, "encounter": encounter,
                    "drug": drug, "right_dose": dose, "wrong_dose": wrong,
                    "direction": str(t.get("direction") or ""),
                    "transform": str(t.get("id") or ""),
                    "note": str(t.get("note") or ""),
                    "display": f"{drug} {wrong} instead of {dose} "
                               f"({t.get('display')})",
                })

    elif err_type == "interaction":
        formulary = _formulary_names()
        for pair in cat.get("interaction_pairs") or []:
            for on_med, new_med in ((pair["a"], pair["b"]), (pair["b"], pair["a"])):
                found, _ = _on_session(session_id, on_med)
                if not found:
                    continue
                if not any(_name_match(new_med, f) for f in formulary):
                    continue
                out.append({
                    "type": err_type, "vector": vector, "encounter": encounter,
                    "on_med": on_med, "new_med": new_med,
                    "risk": str(pair.get("risk") or ""),
                    "note": str(pair.get("note") or ""),
                    "display": f"{new_med} ordered while on {on_med} "
                               f"(risk: {pair.get('risk')})",
                })

    elif err_type == "allergy":
        formulary = _formulary_names()
        documented = _documented_allergies(session_id)
        for entry in cat.get("allergy_map") or []:
            allergen = str(entry.get("allergen") or "")
            doc = next((a for a in documented
                        if _name_match(allergen, str(a.get("substance") or ""))), None)
            if doc is None:
                continue
            for med in entry.get("meds") or []:
                if not any(_name_match(med, f) for f in formulary):
                    continue
                out.append({
                    "type": err_type, "vector": vector, "encounter": encounter,
                    "allergen": allergen, "drug": med,
                    "documented_reaction": str(doc.get("reaction") or ""),
                    "note": str(entry.get("note") or ""),
                    "display": f"{med} ordered despite documented {allergen} "
                               f"allergy ({doc.get('reaction')})",
                })

    elif err_type == "admin":
        rng = _rng(session_id, err_type)
        days = rng.randint(10, 120)
        hours = rng.choice([2, 3, 4])
        board = _board_items(session_id)
        mar = _mar_names(session_id)
        drugs = [str(it.get("drug")) for it in board] + mar
        pairs = {str(p["a"]): str(p["b"])
                 for p in catalog().get("sound_alike_pairs") or []}
        for drug in drugs[:8]:
            for t in cat.get("admin_error_templates") or []:
                kind = str(t.get("kind") or "")
                item = next((it for it in board
                             if _name_match(drug, str(it.get("drug") or ""))), None)
                dose = str((item or {}).get("dose") or "")
                payload: dict[str, Any] = {
                    "type": err_type, "vector": vector, "encounter": encounter,
                    "kind": kind, "drug": drug, "note": str(t.get("note") or ""),
                }
                if kind == "expired":
                    payload["days"] = days
                    payload["display"] = f"{drug}: stock expired {days} days ago"
                elif kind == "wrong_time":
                    payload["hours"] = hours
                    payload["display"] = f"{drug}: MAR time {hours}h off the order"
                elif kind == "wrong_dose":
                    wrong = transform_dose(dose, {"op": "mul", "factor": 2})
                    if not dose or wrong is None:
                        continue
                    payload["right"], payload["wrong"] = dose, wrong
                    payload["display"] = f"{drug}: prepared {wrong}, MAR says {dose}"
                elif kind == "wrong_med":
                    other = next((b for a, b in pairs.items()
                                  if _name_match(a, drug)), None)
                    if other is None:
                        continue
                    payload["other"] = other
                    payload["display"] = f"{drug} slot stocked with {other}"
                else:
                    continue
                out.append(payload)

    # Deterministic per (session, axes): stable shuffle, capped.
    _rng(session_id, err_type, vector, encounter).shuffle(out)
    return out[:_MAX_SUGGESTIONS]


# ── lifecycle ──────────────────────────────────────────────────────────────────

def _validate_axes(err_type: str, vector: str, encounter: str) -> None:
    if err_type not in TYPES:
        raise ValueError(f"unknown error type {err_type!r}")
    if vector not in VECTORS_BY_TYPE[err_type]:
        raise ValueError(
            f"{err_type!r} cannot be introduced via {vector!r} "
            f"(taxonomy allows: {', '.join(VECTORS_BY_TYPE[err_type])})")
    if encounter not in ENCOUNTERS:
        raise ValueError(f"unknown encounter point {encounter!r}")


def _bucket(session_id: str) -> dict[str, Any]:
    return _SESSION_ERRORS.setdefault(session_id, {"seq": 0, "errors": []})


def arm(session_id: str, *, err_type: str, vector: str, encounter: str,
        payload: dict[str, Any], impact: dict[str, Any] | None = None,
        note: str = "") -> dict[str, Any]:
    """Stage an error. S1: records only (application lands in S2/S3); `impact`
    must stay None until the S4 consequence catalog exists — bounded means no
    free-form impact can be smuggled in early."""
    _validate_axes(err_type, vector, encounter)
    if impact is not None:
        raise ValueError("patient impact arrives in S4 — not yet armable")
    if not isinstance(payload, dict) or not payload.get("display"):
        raise ValueError("payload must be a suggestion dict (with display)")
    b = _bucket(session_id)
    b["seq"] += 1
    rec: dict[str, Any] = {
        "id": f"e{b['seq']}",
        "type": err_type, "vector": vector, "encounter": encounter,
        "payload": dict(payload), "impact": None, "note": str(note or ""),
        "status": "armed", "outcome": None,
        "armed_at": time.time(), "delivered_at": None,
        "triggered_at": None, "resolved_at": None,
        "snapshot": None,   # S2: original chart slice for byte-exact restore
    }
    b["errors"].append(rec)
    return rec


def get(session_id: str, error_id: str) -> dict[str, Any] | None:
    for rec in _bucket(session_id)["errors"]:
        if rec["id"] == error_id:
            return rec
    return None


def disarm(session_id: str, error_id: str) -> bool:
    """Remove a staged error. S2 adds chart-snapshot restore before removal."""
    b = _bucket(session_id)
    rec = get(session_id, error_id)
    if rec is None:
        return False
    b["errors"].remove(rec)
    return True


def resolve(session_id: str, error_id: str, outcome: str, note: str = "") -> bool:
    """Instructor marks the teaching outcome: 'caught' or 'missed' (debrief arc)."""
    if outcome not in ("caught", "missed"):
        raise ValueError("outcome must be 'caught' or 'missed'")
    rec = get(session_id, error_id)
    if rec is None:
        return False
    rec["status"] = "resolved"
    rec["outcome"] = outcome
    rec["resolved_at"] = time.time()
    if note:
        rec["note"] = (rec["note"] + " | " if rec["note"] else "") + str(note)
    return True


def state(session_id: str) -> dict[str, Any]:
    return {"errors": [dict(r) for r in _bucket(session_id)["errors"]]}


def clear_session(session_id: str) -> None:
    _SESSION_ERRORS.pop(session_id, None)
