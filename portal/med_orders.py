"""FR-001/FR-002 — the medication-orders engine for the doctor/pharmacist teaching loop.

Authored data (`portal/data/med_orders.json`, DRAFT → instructor-reviewed) maps each
condition to primary + alternative medication options at conservative starting doses.
This module turns that into:

  * per-session med state — the instructor's availability board: which options populate
    the med cart, which the pharmacy stocks, which are flagged NOT available (FR-002),
    plus instructor-added custom meds (level 2);
  * a SEEDED recommendation for the simulated DOCTOR (random primary, excluding meds the
    patient is already on, escalating to alternatives — FR-001) — the doctor deliberately
    does NOT see availability, so supply problems surface at the pharmacist and the
    student carries the alternative back for approval (the teaching loop);
  * an availability-aware view for the simulated PHARMACIST;
  * system-prompt context blocks for both roles — the model is instructed to name ONLY
    the injected authored options, never to invent a drug or dose.

Clinical safety: the AI never selects medications — CODE selects from authored data and
the prompt pins the model to that selection. PHI posture unchanged (ADR-0014).
State is in-memory per control session (consistent with control_session lifetimes).
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

_DATA_PATH = Path(__file__).resolve().parent / "data" / "med_orders.json"
_catalog_cache: dict[str, Any] | None = None

# session_id → med state. In-memory, like the control session it belongs to.
_SESSION_MEDS: dict[str, dict[str, Any]] = {}

DOCTOR_ROLE_HINTS = ("attending", "hospitalist", "physician", "pediatrician", "doctor", " md")
PHARMACIST_ROLE_HINTS = ("pharmacist", "pharmacy")


def catalog() -> dict[str, Any]:
    """The authored condition → options table (cached; `_meta` stripped)."""
    global _catalog_cache
    if _catalog_cache is None:
        try:
            raw = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — missing/broken data file → empty catalog
            raw = {}
        _catalog_cache = {k: v for k, v in raw.items() if not k.startswith("_")}
    return _catalog_cache


def conditions() -> list[dict[str, str]]:
    """[{id, display}] for the instructor's condition picker."""
    return [{"id": k, "display": str(v.get("display") or k)} for k, v in catalog().items()]


def _items_for(condition: str) -> list[dict[str, Any]]:
    """Materialize the authored options into instructor-editable session items.
    Defaults: everything available + stocked in pharmacy; the CART starts empty —
    the instructor decides what the med cart holds at scenario start (level 1)."""
    entry = catalog().get(condition) or {}
    items: list[dict[str, Any]] = []
    n = 0
    for tier in ("primary", "alternative"):
        for opt in entry.get(tier) or []:
            n += 1
            items.append({
                "id": f"m{n}",
                "drug": str(opt.get("drug") or ""),
                "dose": str(opt.get("dose") or ""),
                "route": str(opt.get("route") or ""),
                "frequency": str(opt.get("frequency") or ""),
                "note": str(opt.get("note") or ""),
                "tier": tier,
                "in_cart": False,
                "in_pharmacy": True,
                "available": True,
                "custom": False,
            })
    return items


def init_session(session_id: str, condition: str) -> dict[str, Any]:
    """(Re)initialize the session med board for a condition."""
    state = {
        "condition": condition,
        "display": str((catalog().get(condition) or {}).get("display") or condition),
        "adjunct_note": str((catalog().get(condition) or {}).get("adjunct_note") or ""),
        "items": _items_for(condition),
    }
    _SESSION_MEDS[session_id] = state
    return state


def get_state(session_id: str) -> dict[str, Any] | None:
    return _SESSION_MEDS.get(session_id)


def update_item(session_id: str, item_id: str, **flags: Any) -> bool:
    state = _SESSION_MEDS.get(session_id)
    if not state:
        return False
    for it in state["items"]:
        if it["id"] == item_id:
            for k in ("in_cart", "in_pharmacy", "available"):
                if k in flags and flags[k] is not None:
                    it[k] = bool(flags[k])
            return True
    return False


def add_custom(session_id: str, *, drug: str, dose: str, route: str,
               frequency: str, tier: str, in_cart: bool, in_pharmacy: bool,
               available: bool) -> dict[str, Any] | None:
    """Level 2 — instructor adds a medication beyond the authored list."""
    state = _SESSION_MEDS.get(session_id)
    if not state or not drug.strip():
        return None
    item = {
        "id": f"c{len(state['items']) + 1}",
        "drug": drug.strip()[:80],
        "dose": dose.strip()[:60],
        "route": route.strip()[:40],
        "frequency": frequency.strip()[:60],
        "note": "instructor-added",
        "tier": tier if tier in ("primary", "alternative") else "alternative",
        "in_cart": bool(in_cart),
        "in_pharmacy": bool(in_pharmacy),
        "available": bool(available),
        "custom": True,
    }
    state["items"].append(item)
    return item


def _already_on(drug: str, active_meds: list[str]) -> bool:
    d = drug.lower().split()[0] if drug else ""
    return bool(d) and any(d in (m or "").lower() for m in active_meds)


def recommend_for_doctor(session_id: str,
                         active_meds: list[str]) -> dict[str, Any] | None:
    """FR-001 — the doctor's single recommendation: seeded-random PRIMARY the patient
    is not already on; primaries exhausted → seeded-random alternative; nothing fits →
    None (the doctor defers to the instructor). Availability is deliberately IGNORED
    here (the pharmacist owns supply — that's the teaching loop)."""
    state = _SESSION_MEDS.get(session_id)
    if not state:
        return None
    rng = random.Random(f"{session_id}:med-orders")  # seeded per session (reproducible)
    for tier in ("primary", "alternative"):
        pool = [it for it in state["items"]
                if it["tier"] == tier and not _already_on(it["drug"], active_meds)]
        if pool:
            return rng.choice(pool)
    return None


def _fmt(it: dict[str, Any]) -> str:
    bits = [it["drug"], it["dose"], it["route"], it["frequency"]]
    s = " ".join(b for b in bits if b)
    return s + (f"  ({it['note']})" if it.get("note") else "")


def doctor_prompt_block(session_id: str, active_meds: list[str]) -> str:
    """System-prompt context for DOCTOR personas. Pins the model to the code-selected
    authored order; never lets it invent drugs or doses."""
    state = _SESSION_MEDS.get(session_id)
    if not state:
        return ""
    rec = recommend_for_doctor(session_id, active_meds)
    lines = [
        "MEDICATION ORDERS (teaching simulation — authored data, follow EXACTLY):",
        f"Working condition: {state['display']}.",
    ]
    if active_meds:
        lines.append("Patient is already on: " + ", ".join(sorted(set(active_meds))[:12]) + ".")
    if rec is not None:
        order = f"{rec['drug']} {rec['dose']} {rec['route']} {rec['frequency']}".strip()
        lines += [
            "YOU are the prescriber. When the trainee asks what to give, asks for orders,",
            "or describes this indication, you PLACE THE ORDER YOURSELF, DECISIVELY, in",
            f"that same utterance — say it complete: \"I'm ordering {order}.\" plus at",
            "most one short line of rationale, in your own voice.",
            "PROHIBITED: asking the trainee (or anyone) what is available or in stock —",
            "supply is the pharmacy's job, not yours; offering a menu of options; asking",
            "clarifying questions instead of ordering; naming, suggesting, or dosing ANY",
            "medication other than the order above.",
            "EXCEPTION — approval turn: if the trainee returns saying YOUR ordered drug is",
            "unavailable and relays the pharmacy's alternative (from the authored list),",
            "approve it decisively and restate that alternative's full dose, route, and",
            "frequency exactly as the trainee relayed it.",
        ]
    else:
        lines += [
            "No suitable authored option remains (the patient is already on the listed",
            "options). Tell the trainee you want to review with the care team rather than",
            "ordering something new. NEVER invent a medication or dose.",
        ]
    if state.get("adjunct_note"):
        lines.append(f"Adjunct teaching note: {state['adjunct_note']}")
    return "\n".join(lines)


def pharmacist_prompt_block(session_id: str) -> str:
    """System-prompt context for PHARMACIST personas — the availability board (FR-002).
    Unavailable primaries are the teaching lever; the pharmacist offers the first
    AVAILABLE option (primary first, then alternatives) at its authored dose, framed
    as 'take it back to the doctor for approval'."""
    state = _SESSION_MEDS.get(session_id)
    if not state:
        return ""
    avail = [it for it in state["items"] if it["available"]]
    unavail = [it for it in state["items"] if not it["available"]]
    lines = [
        "PHARMACY STOCK BOARD (teaching simulation — authored data, follow EXACTLY):",
        f"Working condition: {state['display']}.",
        "Available now: " + ("; ".join(_fmt(it) for it in avail) if avail else "(nothing)") + ".",
    ]
    if unavail:
        lines.append("NOT available (supply issue): "
                     + "; ".join(it["drug"] for it in unavail) + ".")
    lines += [
        "If the trainee asks about an unavailable medication: say it is not available,",
        "then offer the FIRST available option from the list above (primary tier first,",
        "then alternatives) at exactly its written dose/route/frequency — and frame it as",
        "something to take back to the ordering doctor to review/approve, not a directive.",
        "NEVER name, suggest, or dose any medication outside the list above.",
        "Meds marked here also reflect what the med cart was stocked with at scenario start.",
    ]
    return "\n".join(lines)


def role_kind(role: str) -> str | None:
    """'doctor' | 'pharmacist' | None for a persona's role string."""
    r = f" {(role or '').lower()} "
    if any(h in r for h in PHARMACIST_ROLE_HINTS):
        return "pharmacist"
    if any(h in r for h in DOCTOR_ROLE_HINTS):
        return "doctor"
    return None


def active_med_names(session_id: str) -> list[str]:
    """Best-effort 'what is the patient already on' from the seeded chart MAR + runtime
    orders (ehr_db). Empty list on any failure — the doctor then simply has no
    exclusions, which is safe."""
    names: list[str] = []
    try:
        from portal import ehr_db
        chart = ehr_db.seed(session_id) or {}
        # The seeded chart's MAR key is "medications" (ChartSeed); "meds" kept
        # as a fallback for older stored seeds. Reading only "meds" silently
        # emptied the doctor's already-on exclusions (found by FR-008 S2 tests).
        for m in (chart.get("medications") or chart.get("meds") or []):
            n = str((m or {}).get("drug") or (m or {}).get("name") or "").strip()
            if n:
                names.append(n)
        for o in ehr_db.orders(session_id) or []:
            n = str((o or {}).get("label") or (o or {}).get("code") or "").strip()
            if n:
                names.append(n)
    except Exception:  # noqa: BLE001 — chart access is best-effort
        return names
    return names


def prompt_block_for(session_id: str, card: dict[str, Any]) -> str:
    """The med-context block for this character, or '' for non-clinical roles."""
    kind = role_kind(str(card.get("role") or ""))
    if kind is None or get_state(session_id) is None:
        return ""
    if kind == "doctor":
        return doctor_prompt_block(session_id, active_med_names(session_id))
    return pharmacist_prompt_block(session_id)
