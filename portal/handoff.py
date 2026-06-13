# FR-009 H1 — shift-handoff context-pack generator.
#
# The "context pack" is the per-patient GROUND TRUTH for a turnover: it is
# simultaneously (1) the AI counterpart's knowledge, (2) the coverage rubric the
# student's handoff is scored against, and (3) the debrief artifact. Built from
# the live session — chart seed + event fold + medication board + any armed
# staged error — so it always matches THIS scenario.
#
# Structure (research-grounded, FR-009 strategy PDF): an SBAR skeleton enriched
# with the two I-PASS elements the evidence says matter most and students miss
# most — an up-front illness-SEVERITY statement and a closing receiver SYNTHESIS
# (read-back) — plus anticipatory guidance and an explicit responsibility
# transfer. high_risk marks the omissions that "would put a patient at risk."
#
# H1 scope: pure data generation. No AI counterpart (H2), no survey (H4), no
# scoring (H5). Read-only over existing chart/med/error machinery; tolerant of a
# missing chart section (each element degrades to "(not documented)", never
# raises) so a half-seeded session never breaks the pack.

from __future__ import annotations

import re
import time
from typing import Any

# The 11-element handoff checklist. (id, display, high_risk)
ELEMENTS: tuple[tuple[str, str, bool], ...] = (
    ("identity",   "Identity & situation",                    False),
    ("severity",   "Illness severity",                        True),
    ("background", "Background (allergies, code status)",      True),
    ("assessment", "Current assessment (vitals trend, labs)", False),
    ("meds",       "Medications & treatments",                True),
    ("access",     "Lines / drains / access",                 True),
    ("pending",    "Pending items",                           True),
    ("safety",     "Safety risks",                            True),
    ("anticipate", "Anticipatory guidance",                   True),
    ("synthesis",  "Receiver synthesis (read-back)",          True),
    ("transfer",   "Responsibility transfer",                 False),
)
HIGH_RISK: frozenset[str] = frozenset(e[0] for e in ELEMENTS if e[2])
DISPLAY: dict[str, str] = {e[0]: e[1] for e in ELEMENTS}

_MISSING = "(not documented)"
_NUM = re.compile(r"-?\d+(?:\.\d+)?")

# Display-only high-alert keywords (ISMP-flavored) — flags meds for the handoff,
# never drives dosing.
_HIGH_ALERT = ("insulin", "heparin", "enoxaparin", "apixaban", "warfarin", "fentanyl",
               "hydromorphone", "morphine", "oxycodone", "norepinephrine", "epinephrine",
               "vasopressin", "ketamine", "potassium chloride", "magnesium sulfate",
               "alteplase", "tenecteplase", "insulin")


def _num(s: Any) -> float | None:
    m = _NUM.search(str(s or ""))
    return float(m.group()) if m else None


def _ranges() -> dict[str, Any]:
    try:
        from portal import ehr_seed
        return ehr_seed.CLINICAL_RANGES or {}
    except Exception:  # noqa: BLE001
        return {}


# ── severity ────────────────────────────────────────────────────────────────

def severity_for(seed: dict[str, Any]) -> str:
    """One-word illness severity from the chart: stable / watcher / unstable.

    Uses the condition's trend (CLINICAL_RANGES) + how far the latest vitals sit
    outside the normal (stable_baseline) ranges. Conservative + deterministic."""
    ranges = _ranges()
    cond = str(seed.get("condition") or "stable_baseline")
    trend = str((ranges.get(cond) or {}).get("trend", "flat"))
    norm = ranges.get("stable_baseline") or {}
    snaps = seed.get("vitals_baseline") or []
    latest = snaps[-1] if snaps else {}

    abn = 0
    for key, rk in (("hr", "hr"), ("rr", "rr"), ("spo2", "spo2"), ("pain", "pain")):
        v, rng = _num(latest.get(key)), norm.get(rk)
        if v is not None and rng and (v < rng[0] or v > rng[1]):
            abn += 1
    bp = str(latest.get("bp") or "")
    if "/" in bp:
        sys_, rng = _num(bp.split("/")[0]), norm.get("bp_sys")
        if sys_ is not None and rng and (sys_ < rng[0] or sys_ > rng[1]):
            abn += 1

    if trend == "worsening" or abn >= 2:
        return "unstable"
    if abn >= 1 or trend in ("improving", "fluctuating"):
        return "watcher"
    return "stable"


# ── element builders (each returns a content string, never raises) ────────────

def _e_identity(seed: dict[str, Any]) -> str:
    name = str(seed.get("name") or _MISSING)
    enc = seed.get("encounter") or {}
    room = enc.get("room") or enc.get("bed") or ""
    chief = str(seed.get("chief_complaint") or "")
    bits = [name]
    if room:
        bits.append(f"Room {room}")
    if chief:
        bits.append(chief)
    return " · ".join(bits) if bits else _MISSING


def _e_severity(seed: dict[str, Any], sev: str) -> str:
    label = {"stable": "STABLE", "watcher": "WATCHER", "unstable": "UNSTABLE"}.get(sev, sev.upper())
    cond = str(seed.get("condition") or "").replace("_", " ")
    return f"{label}" + (f" — {cond}" if cond else "")


def _e_background(seed: dict[str, Any]) -> str:
    probs = ", ".join(str(p.get("name") or "").strip()
                      for p in (seed.get("problem_list") or []) if p.get("name")) or "no active problems listed"
    allergies = seed.get("allergies") or []
    if allergies:
        alg = "; ".join(f"{a.get('substance') or a.get('name')} ({a.get('reaction', 'reaction')})"
                        for a in allergies)
    else:
        alg = "NKDA"
    code = str(seed.get("code_status") or _MISSING)
    return f"Dx: {probs}. ALLERGIES: {alg}. CODE STATUS: {code}."


def _e_assessment(seed: dict[str, Any]) -> str:
    snaps = seed.get("vitals_baseline") or []
    if not snaps:
        return _MISSING
    latest = snaps[-1]
    parts = [f"{k.upper()} {latest[k]}" for k in ("t", "hr", "rr", "bp", "spo2")
             if latest.get(k) not in (None, "")]
    ranges = _ranges()
    trend = str((ranges.get(str(seed.get("condition") or "")) or {}).get("trend", "flat"))
    labs = seed.get("labs_recent") or []
    flagged = [f"{l.get('name')} {l.get('v')}" for l in labs
               if str(l.get("flag") or "").strip() and l.get("name")]
    out = f"Latest vitals: {', '.join(parts) or _MISSING} (trend: {trend})."
    if flagged:
        out += " Notable labs: " + ", ".join(flagged[:4]) + "."
    return out


def _med_line(m: dict[str, Any]) -> str:
    name = str(m.get("name") or m.get("drug") or "").strip()
    dose = str(m.get("dose") or "").strip()
    freq = str(m.get("frequency") or "").strip()
    flag = " ⚠high-alert" if any(h in name.lower() for h in _HIGH_ALERT) else ""
    return f"{name} {dose} {freq}".strip() + flag


def _e_meds(seed: dict[str, Any], board: dict[str, Any] | None) -> str:
    meds = seed.get("medications") or []
    if not meds:
        base = "no active medications on the MAR"
    else:
        base = "; ".join(_med_line(m) for m in meds if (m.get("name") or m.get("drug")))
    infusions = [str(f.get("name") or f.get("fluid") or "").strip()
                 for f in (seed.get("iv_fluids") or []) if (f.get("name") or f.get("fluid"))]
    if infusions:
        base += ". Infusions running: " + ", ".join(infusions)
    return base + "."


def _e_access(seed: dict[str, Any]) -> str:
    lines = []
    for f in seed.get("iv_fluids") or []:
        site = f.get("site") or f.get("access") or ""
        nm = f.get("name") or f.get("fluid") or "IV"
        lines.append(f"{nm}{(' — ' + site) if site else ''}")
    for t in seed.get("tube_feeds") or []:
        lines.append(str(t.get("name") or "enteral access"))
    return "; ".join(lines) if lines else "no lines/drains documented"


def _e_pending(seed: dict[str, Any], fold: dict[str, Any]) -> str:
    items: list[str] = []
    for o in (fold.get("orders") or []):
        lbl = o.get("label") or o.get("code") or o.get("name")
        if lbl:
            items.append(str(lbl))
    for l in (seed.get("labs_recent") or []):
        if str(l.get("flag") or "").strip() and l.get("name"):
            items.append(f"follow up {l.get('name')}")
    seen, uniq = set(), []
    for it in items:
        if it.lower() not in seen:
            seen.add(it.lower())
            uniq.append(it)
    return "; ".join(uniq[:8]) if uniq else "none documented"


def _e_safety(seed: dict[str, Any]) -> str:
    risks = []
    sc = str(seed.get("safety_class") or "").strip()
    if sc and sc not in ("baseline", "none"):
        risks.append(sc.replace("_", " "))
    alt = seed.get("altered_state")
    if alt:
        risks.append(f"altered: {alt}")
    return ", ".join(risks) if risks else "no special safety risks flagged"


def _e_anticipate(seed: dict[str, Any], sev: str, staged: list[dict[str, Any]]) -> str:
    """Watch-fors. Derived from severity (no per-condition authored watch-list
    yet — flagged for future authoring) + any active staged-error guidance."""
    base = {
        "unstable": "Watch closely — escalate on any further deterioration in vitals or mental status; "
                    "have the rapid-response pathway ready.",
        "watcher":  "Keep an eye on the trend — recheck vitals and reassess if anything shifts.",
        "stable":   "No specific contingencies anticipated; routine reassessment.",
    }.get(sev, "Reassess as indicated.")
    return base


def _e_synthesis() -> str:
    return ("Expected at the end of report: the receiver reads back the key points "
            "(severity, next-due meds, pending items, watch-fors) and the giver confirms.")


def _e_transfer() -> str:
    return "Expected: an explicit acceptance of responsibility (\"I've got them\")."


# ── pack assembly ─────────────────────────────────────────────────────────────

def pack_vocab(pack: dict[str, Any]) -> list[str]:
    """Drug + allergen names from the pack — merged into the recognizer hints
    during the handoff/survey phase so they transcribe faithfully."""
    return list(pack.get("_vocab") or [])


def build_pack(session_id: str, persona_id: str | None = None,
               *, now: float | None = None) -> dict[str, Any]:
    """Generate the per-patient handoff context pack from the live session.

    Tolerant of missing chart sections — each element degrades to
    "(not documented)" / a sensible default and never raises."""
    seed: dict[str, Any] = {}
    fold: dict[str, Any] = {}
    board: dict[str, Any] | None = None
    staged: list[dict[str, Any]] = []
    try:
        from portal import ehr_db
        seed = ehr_db.seed(session_id) or {}
        try:
            fold = ehr_db.fold(session_id) or {}
        except Exception:  # noqa: BLE001 — fold is best-effort
            fold = {}
    except Exception:  # noqa: BLE001
        seed = {}
    try:
        from portal import med_orders
        board = med_orders.get_state(session_id)
    except Exception:  # noqa: BLE001
        board = None
    try:
        from portal import med_errors
        staged = [e for e in med_errors.state(session_id).get("errors", [])
                  if e.get("status") != "resolved"]
    except Exception:  # noqa: BLE001
        staged = []

    sev = severity_for(seed)
    content = {
        "identity":   _e_identity(seed),
        "severity":   _e_severity(seed, sev),
        "background": _e_background(seed),
        "assessment": _e_assessment(seed),
        "meds":       _e_meds(seed, board),
        "access":     _e_access(seed),
        "pending":    _e_pending(seed, fold),
        "safety":     _e_safety(seed),
        "anticipate": _e_anticipate(seed, sev, staged),
        "synthesis":  _e_synthesis(),
        "transfer":   _e_transfer(),
    }
    elements = {
        eid: {"display": DISPLAY[eid], "content": content[eid], "high_risk": eid in HIGH_RISK}
        for eid, _disp, _hr in ELEMENTS
    }

    # Vocabulary: MAR + board drug names + allergens, deduped.
    vocab: list[str] = []
    for m in (seed.get("medications") or []):
        n = str(m.get("name") or m.get("drug") or "").strip()
        if n:
            vocab.append(n)
    if board:
        for it in board.get("items") or []:
            n = str(it.get("drug") or "").strip()
            if n:
                vocab.append(n)
    for a in (seed.get("allergies") or []):
        n = str(a.get("substance") or a.get("name") or "").strip()
        if n:
            vocab.append(n)
    seen, vdedup = set(), []
    for v in vocab:
        if v.lower() not in seen:
            seen.add(v.lower())
            vdedup.append(v)

    return {
        "patient": {
            "name": str(seed.get("name") or "(unknown)"),
            "persona_id": persona_id or seed.get("persona_id") or "",
            "chief_complaint": str(seed.get("chief_complaint") or ""),
            "condition": str(seed.get("condition") or ""),
        },
        "severity": sev,
        "elements": elements,
        "high_risk_elements": [e[0] for e in ELEMENTS if e[2]],
        # A staged FR-008 discrepancy is live in this chart → the survey should
        # probe whether the student noticed (chart-vs-report mismatch).
        "staged_discrepancy": bool(staged),
        "_vocab": vdedup,
        "generated_at": now if now is not None else time.time(),
        "sources": {
            "has_seed": bool(seed), "has_fold": bool(fold),
            "has_board": board is not None, "staged_errors": len(staged),
        },
    }
