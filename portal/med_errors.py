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

import copy
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
                    "route": str(it.get("route") or ""),
                    "frequency": str(it.get("frequency") or ""),
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
        # Administration errors live on meds being ADMINISTERED — the MAR only.
        # (Board-only drugs have no MAR row to tag; offering them would make
        # arm() reject its own suggestion — bounded means offer only what applies.)
        drugs = _mar_names(session_id)
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


# ── S2: document vector — plant the discrepancy in the student-visible chart ──
#
# The EHR app renders fold(events) + the stored session seed (server.py
# projection["seed"]) — so a surgical update_seed IS the student-visible path.
# Encounter → artifact (revised from the plan after recon: `seed_report` is the
# OPERATOR QA card, not the handoff — the handoff is realistically a note):
#   report   → notes_recent  + one "Shift Handoff (SBAR)" note (off-going RN)
#   charting → notes_recent  + one progress/clarification note
#   prep     → medications   — ONE row's preparation fields (dose / stock tags)
#   med_pass → medications   — ONE row's administration fields (+ due-now tag)
# Exactly one artifact changes; everything else stays the truth (design rule 2).
# The original artifact value is snapshotted on the record → disarm restores it
# byte-for-byte. resolve() deliberately does NOT restore — the chart keeps what
# the student saw, for the debrief.

def _formulary_entry(drug: str) -> dict[str, str]:
    """First authored dose/route/frequency for a drug, for planted MAR rows."""
    try:
        from . import med_orders
        for key, entry in med_orders.catalog().items():
            if key.startswith("_"):
                continue
            for tier in ("primary", "alternative"):
                for opt in entry.get(tier) or []:
                    if _name_match(drug, str(opt.get("drug") or "")):
                        return {"dose": str(opt.get("dose") or "per order"),
                                "route": str(opt.get("route") or "PO"),
                                "frequency": str(opt.get("frequency") or "per order")}
    except Exception:  # noqa: BLE001
        pass
    return {"dose": "per order", "route": "PO", "frequency": "per order"}


def _staged_note(rec: dict[str, Any], body: str) -> dict[str, Any]:
    """A note shaped exactly like its ehr_seed siblings (render-true)."""
    if rec["encounter"] == "report":
        note_type, author = "Shift Handoff (SBAR)", "Off-going RN"
    else:
        note_type, author = "Progress", "Covering provider"
    return {
        "note_id": f"n_staged_{rec['id']}",
        "note_type": note_type,
        "author": author,
        "ts": "T-0h",
        "body": body,
        "signed": True,
    }


def _note_body(rec: dict[str, Any]) -> str:
    """The discrepancy line for note encounters — written the way a busy
    clinician would, NOT self-announcing (except admin, where the documented
    deviation itself is the error to notice)."""
    p = rec["payload"]
    t = rec["type"]
    if t == "wrong_dose":
        if rec["encounter"] == "report":
            return (f"Handoff: {p['drug']} running at {p['wrong_dose']} — "
                    f"continue current plan. Otherwise stable overnight.")
        return (f"Med review: {p['drug']} dose clarified with team as "
                f"{p['wrong_dose']}. Continue.")
    if t == "interaction":
        if rec["encounter"] == "report":
            return (f"Handoff: team added {p['new_med']} overnight; first dose "
                    f"due this shift. No other changes.")
        return f"Plan: start {p['new_med']} for symptom control; reassess in 24h."
    if t == "allergy":
        if rec["encounter"] == "report":
            return (f"Handoff: new order for {p['drug']} — first dose due this "
                    f"shift. No other changes.")
        return f"Plan: start {p['drug']} for coverage; first dose today."
    # admin: the documented deviation is itself the catchable error.
    return f"Note: {p.get('display', 'medication administration deviation')}."


def _mutate_mar(rows: list[dict[str, Any]], rec: dict[str, Any]) -> list[dict[str, Any]]:
    """Apply the discrepancy to ONE MAR row (or plant one row) — returns a new
    list; raises if the payload can't be applied to this chart."""
    p, t, enc = rec["payload"], rec["type"], rec["encounter"]
    rows = copy.deepcopy(rows)
    due_tag = " — due this pass" if enc == "med_pass" else ""

    def find(drug: str) -> dict[str, Any] | None:
        return next((r for r in rows
                     if _name_match(drug, str(r.get("name") or ""))), None)

    if t == "wrong_dose":
        row = find(p["drug"])
        if row is None:
            row = {"name": p["drug"], "dose": p["right_dose"],
                   "route": p.get("route") or "PO",
                   "frequency": p.get("frequency") or "per order",
                   "status": "active"}
            rows.append(row)
        row["dose"] = p["wrong_dose"]
        if due_tag:
            row["frequency"] = str(row.get("frequency") or "per order") + due_tag
        return rows

    if t in ("interaction", "allergy"):
        drug = p["new_med"] if t == "interaction" else p["drug"]
        if find(drug) is not None:
            raise ValueError(f"{drug} already on the MAR — pick another suggestion")
        entry = _formulary_entry(drug)
        rows.append({"name": drug, "dose": entry["dose"], "route": entry["route"],
                     "frequency": entry["frequency"] + due_tag, "status": "active"})
        return rows

    if t == "admin":
        row = find(p["drug"])
        if row is None:
            raise ValueError(f"{p['drug']} not on the MAR — pick another suggestion")
        kind = p.get("kind")
        if kind == "expired":
            row["dose"] = (str(row.get("dose") or "") +
                           f" (lot expired {p.get('days', '?')}d ago)").strip()
        elif kind == "wrong_time":
            row["frequency"] = (str(row.get("frequency") or "") +
                                f" (next dose charted {p.get('hours', '?')}h early)").strip()
        elif kind == "wrong_dose":
            row["dose"] = str(p.get("wrong") or row.get("dose") or "")
        elif kind == "wrong_med":
            row["name"] = (str(row.get("name") or "") +
                           f" (cart slot stocked: {p.get('other', '?')})")
        else:
            raise ValueError(f"unknown admin error kind {kind!r}")
        return rows

    raise ValueError(f"no document mutation for type {t!r}")


def apply_document(session_id: str, rec: dict[str, Any]) -> None:
    """Plant the discrepancy in the session's PRIVATE chart record. Snapshots
    the original artifact onto the record first (byte-exact disarm restore).
    Raises on any failure — arm() then stages nothing (atomic)."""
    from . import ehr_db
    seed = ehr_db.seed(session_id) or {}
    key = "notes_recent" if rec["encounter"] in ("report", "charting") else "medications"
    original_present = key in seed
    original_value = copy.deepcopy(seed.get(key))

    if key == "notes_recent":
        notes = list(seed.get("notes_recent") or [])
        notes.append(_staged_note(rec, _note_body(rec)))
        new_value: Any = notes
    else:
        new_value = _mutate_mar(list(seed.get("medications") or []), rec)

    rec["snapshot"] = {"key": key, "present": original_present,
                       "value": original_value}
    rec["applied"] = {"artifact": key,
                      "summary": rec["payload"].get("display", "")}
    seed[key] = new_value
    ehr_db.update_seed(session_id, seed)


def _restore_document(session_id: str, rec: dict[str, Any]) -> None:
    snap = rec.get("snapshot")
    if not snap:
        return
    from . import ehr_db
    seed = ehr_db.seed(session_id) or {}
    if snap.get("present"):
        seed[snap["key"]] = snap["value"]
    else:
        seed.pop(snap["key"], None)
    ehr_db.update_seed(session_id, seed)
    rec["snapshot"] = None


# ── S3: verbal vector — the ordering character SPEAKS the staged error ────────
#
# The block rides the same `_extra_context` channel as the med board (FR-001/002)
# and goes ONLY to the ordering character (role_kind == "doctor"). Arc per the
# plan's containment rule: deliver naturally ONCE → defend briefly if questioned
# (busy-clinician realism) → catch yourself and CORRECT when the trainee presses
# with specifics (read-back, indication mismatch, allergy, interaction). The
# block persists until the error is RESOLVED so repeat-backs stay consistent.

_ENCOUNTER_DISPLAY = {
    "report": "during report/handoff",
    "charting": "while charting is being reviewed",
    "prep": "as medications are being prepared",
    "med_pass": "during the med pass",
}

_CONTAINMENT = (
    "CONTAINMENT (absolute): this staged slip is the ONLY error you introduce. "
    "Do not invent any other mistakes, do not exaggerate, never hint that this "
    "is a drill or that anything is staged — stay fully in character."
)


def _verbal_arc(deliver: str, defend: str, correct: str, encounter: str) -> str:
    when = _ENCOUNTER_DISPLAY.get(encounter, "at the next natural moment")
    return (
        f"STAGED VERBAL ORDER (instructor-armed teaching error): at your next "
        f"natural ordering moment — ideally {when} — {deliver} Say it once, "
        f"naturally, as a busy clinician would. If the trainee questions it or "
        f"asks you to repeat, FIRST {defend} If the trainee presses a second "
        f"time, reads the order back precisely, or names the specific safety "
        f"problem, catch yourself and correct: {correct} Acknowledge plainly "
        f"that their check caught a real error. {_CONTAINMENT}"
    )


def _verbal_block(rec: dict[str, Any]) -> str:
    p, enc = rec["payload"], rec["encounter"]
    if rec["type"] == "transcription":
        return _verbal_arc(
            f"give a VERBAL ORDER for {p['wrong_drug']}"
            + (f" {p['dose']}" if p.get("dose") else "")
            + f" — a sound-alike slip; the situation actually calls for "
              f"{p['intended_drug']}.",
            f"repeat \"{p['wrong_drug']}\" as if certain.",
            f"the order is {p['intended_drug']}"
            + (f" {p['dose']}" if p.get("dose") else "") + ".",
            enc)
    if rec["type"] == "wrong_dose":
        return _verbal_arc(
            f"give a VERBAL ORDER for {p['drug']} {p['wrong_dose']} — "
            f"the correct dose is {p['right_dose']}.",
            f"insist \"{p['wrong_dose']}, that's what I said.\"",
            f"the order is {p['drug']} {p['right_dose']}.",
            enc)
    if rec["type"] == "interaction":
        return _verbal_arc(
            f"give a VERBAL ORDER to start {p['new_med']} — without mentioning "
            f"that the patient is already on {p['on_med']} (risk: {p['risk']}).",
            "say the team wants it started today.",
            f"hold {p['new_med']} given the {p['on_med']} (risk: {p['risk']}) and "
            f"ask for a pharmacy consult instead.",
            enc)
    if rec["type"] == "allergy":
        return _verbal_arc(
            f"give a VERBAL ORDER to start {p['drug']} — without checking "
            f"allergies (the chart documents a {p['allergen']} allergy: "
            f"{p.get('documented_reaction') or 'reaction documented'}).",
            "say it's the standard choice here.",
            f"stop {p['drug']} for the documented {p['allergen']} allergy and "
            f"ask what the formulary alternative is.",
            enc)
    return ""


def prompt_block_for(session_id: str, card: dict[str, Any]) -> str:
    """The staged-error context for THIS character's turn ('' for everyone but
    the ordering character). Active while armed OR delivered-but-unresolved —
    repeat-backs must stay consistent; resolve() retires it."""
    # S4: the PATIENT shows triggered (unstabilized, unresolved) impacts.
    if _is_patient(card):
        blocks = [
            _impact_block(rec)
            for rec in _bucket(session_id)["errors"]
            if rec.get("impact_state")
            and not rec["impact_state"].get("stabilized_at")
            and rec["status"] != "resolved"
        ]
        return "\n\n".join(b for b in blocks if b)
    try:
        from . import med_orders
        role = med_orders.role_kind(str(card.get("role") or ""))
    except Exception:  # noqa: BLE001
        return ""
    if role != "doctor":
        return ""
    blocks = [
        _verbal_block(rec)
        for rec in _bucket(session_id)["errors"]
        if rec["vector"] == "verbal" and rec["status"] in ("armed", "delivered")
    ]
    return "\n\n".join(b for b in blocks if b)


def _verbal_marker(rec: dict[str, Any]) -> str:
    """The string whose appearance in a doctor reply means 'the error was
    spoken': the wrong drug / wrong dose / planted med."""
    p = rec["payload"]
    return str({
        "transcription": p.get("wrong_drug"),
        "wrong_dose": p.get("wrong_dose"),
        "interaction": p.get("new_med"),
        "allergy": p.get("drug"),
    }.get(rec["type"]) or "")


def note_character_reply(session_id: str, character_id: str, text: str,
                         role: str | None = None) -> None:
    """Delivered-stamping: called wherever a character's FULL reply is logged.
    If an armed verbal error's marker appears in an ORDERING character's reply,
    stamp it delivered (debrief timeline). Best-effort — never raises."""
    try:
        armed = [r for r in _bucket(session_id)["errors"]
                 if r["vector"] == "verbal" and r["status"] == "armed"]
        if not armed or not text:
            return
        if role is None:
            from . import med_orders, vrai_faces
            card = vrai_faces.resolve_card(character_id) or {}
            role = med_orders.role_kind(str(card.get("role") or ""))
        if role != "doctor":
            return
        low = text.lower()
        for rec in armed:
            marker = _verbal_marker(rec)
            if marker and marker.lower() in low:
                rec["status"] = "delivered"
                rec["delivered_at"] = time.time()
    except Exception:  # noqa: BLE001 — stamping must never break a turn
        return


def vocab_extras(session_id: str) -> list[str]:
    """Drug names the recognizer must hear faithfully BECAUSE an error is staged
    — including the WRONG sound-alike: if the student repeats back 'Hespan', the
    transcript must say Hespan, never auto-correct toward the intended drug
    (design rule: STT must not un-teach the error)."""
    out: list[str] = []
    for rec in _bucket(session_id)["errors"]:
        if rec["status"] == "resolved":
            continue
        p, t = rec["payload"], rec["type"]
        if t == "transcription":
            out += [str(p.get("intended_drug") or ""), str(p.get("wrong_drug") or "")]
        elif t == "wrong_dose":
            out.append(str(p.get("drug") or ""))
        elif t == "interaction":
            out += [str(p.get("on_med") or ""), str(p.get("new_med") or "")]
        elif t == "allergy":
            out.append(str(p.get("drug") or ""))
    return [w for w in out if w]


# ── S4: patient impact — the consequence arm ──────────────────────────────────
#
# Curated profiles × severity tiers (catalog `impacts`); applied via two
# EXISTING levers, nothing new invented (design rule 6):
#   • a vitals.record chart event — the EHR vitals tab shows the deterioration
#     when anyone checks vitals (v8 sessions have no bedside-monitor device;
#     the M7 room mode's telemetry reads the same event type, so this composes);
#   • the PATIENT character's prompt context — symptoms + behavior, the primary
#     live signal in a character-driven sim.
# Triggers are explicit, never timed (rule 7): the instructor's button, or
# per-error opt-in auto-trigger when the staged med is ADMINISTERED. Severe
# tier double-confirms (at trigger for manual; at arm for auto). stabilize()
# walks vitals back to the captured baseline and retires the symptom script.

IMPACT_TRIGGERS = ("manual", "on_administer")
SEVERITIES = ("mild", "moderate", "severe")

_IMPACT_STATION = "instructor-impact"   # station_id stamped on staged vitals events


def _impact_catalog() -> dict[str, Any]:
    return catalog().get("impacts") or {}


def allowed_profiles(err_type: str, payload: dict[str, Any]) -> list[str]:
    """Profile ids this error may cause, per the curated mapping (wrong_dose by
    direction, interaction by risk label, admin by kind)."""
    allowed = _impact_catalog().get("allowed") or {}
    if err_type == "wrong_dose":
        by_dir = allowed.get("wrong_dose") or {}
        return list(by_dir.get(str(payload.get("direction") or "")) or [])
    if err_type == "interaction":
        by_risk = allowed.get("interaction_by_risk") or {}
        return list(by_risk.get(str(payload.get("risk") or "")) or [])
    if err_type == "admin":
        by_kind = allowed.get("admin") or {}
        return list(by_kind.get(str(payload.get("kind") or "")) or [])
    return list(allowed.get(err_type) or [])


# Plain-English display names (the UI never shows internal ids — house rule).
TYPE_DISPLAY = {
    "transcription": "Transcription — sound-alike medications",
    "wrong_dose": "Right medication, wrong dose",
    "interaction": "Dangerous interaction",
    "allergy": "Allergy oversight",
    "admin": "Administration error",
}
VECTOR_DISPLAY = {
    "verbal": "Verbal / phone order (a character speaks it)",
    "document": "Document conflict (planted in the chart)",
}
ENCOUNTER_DISPLAY_SHORT = {
    "report": "During report / handoff",
    "charting": "During charting review",
    "prep": "Preparing for med pass",
    "med_pass": "During the med pass",
}


def taxonomy() -> dict[str, Any]:
    """The wizard's option tree (step 1–3), display-named, vectors filtered per
    the instructor's taxonomy."""
    return {
        "types": [{"id": t, "display": TYPE_DISPLAY[t],
                   "vectors": [{"id": v, "display": VECTOR_DISPLAY[v]}
                               for v in VECTORS_BY_TYPE[t]]} for t in TYPES],
        "encounters": [{"id": e, "display": ENCOUNTER_DISPLAY_SHORT[e]}
                       for e in ENCOUNTERS],
        "severities": list(SEVERITIES),
        "triggers": [
            {"id": "manual", "display": "I trigger it (button in the Live window)"},
            {"id": "on_administer",
             "display": "Automatically when the staged med is administered"},
        ],
    }


def impact_menu(err_type: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Step-5 menu BEFORE arming: curated profiles for this candidate payload,
    with per-tier previews (symptoms/behavior/exact staged vitals)."""
    profiles = _impact_catalog().get("profiles") or {}
    out = []
    for pid in allowed_profiles(err_type, payload):
        prof = profiles.get(pid)
        if prof:
            out.append({"profile": pid, "display": str(prof.get("display") or pid),
                        "tiers": prof.get("tiers") or {}})
    return out


def impact_options(session_id: str, error_id: str) -> list[dict[str, Any]]:
    """The S5 wizard's step-5 menu: profiles this armed error may cause, with
    per-tier symptom/vitals previews (plain-English review material)."""
    rec = get(session_id, error_id)
    if rec is None:
        return []
    profiles = _impact_catalog().get("profiles") or {}
    out = []
    for pid in allowed_profiles(rec["type"], rec["payload"]):
        prof = profiles.get(pid)
        if prof:
            out.append({"profile": pid, "display": str(prof.get("display") or pid),
                        "tiers": prof.get("tiers") or {}})
    return out


def _validate_impact(err_type: str, payload: dict[str, Any],
                     impact: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(impact, dict):
        raise ValueError("impact must be a dict {profile, severity, trigger}")
    profile = str(impact.get("profile") or "")
    severity = str(impact.get("severity") or "")
    trigger = str(impact.get("trigger") or "manual")
    if profile not in allowed_profiles(err_type, payload):
        raise ValueError(f"impact profile {profile!r} is not in the curated set "
                         f"for this error (allowed: "
                         f"{', '.join(allowed_profiles(err_type, payload)) or 'none'})")
    tiers = ((_impact_catalog().get("profiles") or {}).get(profile) or {}).get("tiers") or {}
    if severity not in SEVERITIES or severity not in tiers:
        raise ValueError(f"severity must be one of {', '.join(SEVERITIES)}")
    if trigger not in IMPACT_TRIGGERS:
        raise ValueError(f"trigger must be one of {', '.join(IMPACT_TRIGGERS)}")
    confirmed = bool(impact.get("confirmed"))
    if severity == "severe" and trigger == "on_administer" and not confirmed:
        raise ValueError("a SEVERE auto-triggered impact requires explicit "
                         "confirmation at arm time (confirmed: true)")
    return {"profile": profile, "severity": severity, "trigger": trigger,
            "confirmed": confirmed}


def _tier(rec: dict[str, Any]) -> dict[str, Any]:
    imp = rec.get("impact") or {}
    prof = (_impact_catalog().get("profiles") or {}).get(imp.get("profile")) or {}
    return (prof.get("tiers") or {}).get(imp.get("severity")) or {}


def _latest_baseline_vitals(session_id: str,
                            keys: list[str]) -> dict[str, str]:
    """The most recent seeded vitals row, restricted to the keys the impact
    will change — captured at trigger time so stabilize() has a target."""
    try:
        from . import ehr_db
        rows = (ehr_db.seed(session_id) or {}).get("vitals_baseline") or []
        last = rows[-1] if rows else {}
        return {k: str(last[k]) for k in keys if k in last}
    except Exception:  # noqa: BLE001
        return {}


def trigger_impact(session_id: str, error_id: str, *,
                   confirm_severe: bool = False) -> dict[str, Any]:
    """Fire the configured consequence NOW (the instructor's button — or the
    administration hook, which passes confirm_severe=True because severe+auto
    was already explicitly confirmed at arm time)."""
    rec = get(session_id, error_id)
    if rec is None:
        raise ValueError(f"no staged error {error_id!r}")
    imp = rec.get("impact")
    if not imp:
        raise ValueError("this staged error has no patient impact configured")
    if rec["status"] == "resolved":
        raise ValueError("error already resolved — impact can no longer fire")
    if rec.get("impact_state"):
        raise ValueError("impact already triggered")
    if imp["severity"] == "severe" and not confirm_severe:
        raise ValueError("severe impact: confirm explicitly (second click)")

    tier = _tier(rec)
    vitals: dict[str, Any] = dict(tier.get("vitals") or {})
    baseline = _latest_baseline_vitals(session_id, list(vitals.keys()))
    now = time.time()
    rec["impact_state"] = {
        "profile": imp["profile"], "severity": imp["severity"],
        "applied_vitals": vitals, "baseline_vitals": baseline,
        "triggered_at": now, "stabilized_at": None,
    }
    rec["triggered_at"] = now
    try:
        from . import ehr_db
        ehr_db.append_event(
            session_id, _IMPACT_STATION,
            type="vitals.record", surface="impact",
            payload={"time": "now", **vitals, "source": "staged-impact"},
        )
    except Exception:  # noqa: BLE001 — the symptom script still carries the impact
        pass
    return rec


def stabilize(session_id: str, error_id: str) -> dict[str, Any]:
    """Walk the patient back: vitals toward the captured baseline, symptom
    script retired. The chart keeps both records — an honest timeline."""
    rec = get(session_id, error_id)
    if rec is None:
        raise ValueError(f"no staged error {error_id!r}")
    state = rec.get("impact_state")
    if not state:
        raise ValueError("impact has not been triggered")
    if state.get("stabilized_at"):
        raise ValueError("already stabilized")
    state["stabilized_at"] = time.time()
    try:
        from . import ehr_db
        ehr_db.append_event(
            session_id, _IMPACT_STATION,
            type="vitals.record", surface="impact",
            payload={"time": "now", **(state.get("baseline_vitals") or {}),
                     "source": "stabilized"},
        )
    except Exception:  # noqa: BLE001
        pass
    return rec


def note_med_administered(session_id: str, med_text: str) -> None:
    """Administration hook (device event path): if a staged error with an
    auto-trigger impact matches the administered med, fire the consequence.
    Severe was confirmed at arm time. Best-effort — never raises."""
    try:
        low = (med_text or "").lower()
        if not low:
            return
        for rec in list(_bucket(session_id)["errors"]):
            imp = rec.get("impact")
            if (not imp or imp.get("trigger") != "on_administer"
                    or rec.get("impact_state") or rec["status"] == "resolved"):
                continue
            marker = _verbal_marker(rec)
            if marker and marker.lower() in low:
                trigger_impact(session_id, rec["id"], confirm_severe=True)
    except Exception:  # noqa: BLE001 — must never break a device event
        return


def _is_patient(card: dict[str, Any]) -> bool:
    blob = f"{card.get('role') or ''} {card.get('roleGroup') or ''}".lower()
    return "patient" in blob


def _impact_block(rec: dict[str, Any]) -> str:
    tier = _tier(rec)
    return (
        f"PATIENT STATE CHANGE (instructor-staged): you are NOW experiencing "
        f"{tier.get('symptoms') or 'feeling distinctly unwell'}. Show it the "
        f"way a real patient would — "
        f"{tier.get('behavior') or 'let it color your voice and answers'}. "
        f"Answer questions about how you feel honestly and in your own words. "
        f"Do NOT name a diagnosis, do NOT speculate about causes or "
        f"medications unless asked directly, and NEVER hint that this is "
        f"staged. If you feel very unwell, say so plainly."
    )


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
    """Stage an error. `impact` (optional) = {profile, severity, trigger
    manual|on_administer, confirmed} — validated against the CURATED consequence
    catalog (severe + auto-trigger demands confirmed=true at arm time)."""
    _validate_axes(err_type, vector, encounter)
    if not isinstance(payload, dict) or not payload.get("display"):
        raise ValueError("payload must be a suggestion dict (with display)")
    if impact is not None:
        impact = _validate_impact(err_type, payload, impact)
    b = _bucket(session_id)
    b["seq"] += 1
    rec: dict[str, Any] = {
        "id": f"e{b['seq']}",
        "type": err_type, "vector": vector, "encounter": encounter,
        "payload": dict(payload), "impact": impact, "note": str(note or ""),
        "impact_state": None,
        "status": "armed", "outcome": None,
        "armed_at": time.time(), "delivered_at": None,
        "triggered_at": None, "resolved_at": None,
        "snapshot": None,   # document vector: original chart slice (restore)
    }
    # Document vector plants the discrepancy NOW (atomic: a failed apply
    # stages nothing). Verbal vector applies at turn time (S3) — no chart touch.
    if vector == "document":
        apply_document(session_id, rec)
        rec["delivered_at"] = rec["armed_at"]  # visible in the chart immediately
        rec["status"] = "delivered"
    b["errors"].append(rec)
    return rec


def get(session_id: str, error_id: str) -> dict[str, Any] | None:
    for rec in _bucket(session_id)["errors"]:
        if rec["id"] == error_id:
            return rec
    return None


def disarm(session_id: str, error_id: str) -> bool:
    """Un-stage an error: restore the chart artifact byte-for-byte (document
    vector), then remove the record. resolve() deliberately does NOT restore —
    the chart keeps what the student actually saw, for the debrief."""
    b = _bucket(session_id)
    rec = get(session_id, error_id)
    if rec is None:
        return False
    _restore_document(session_id, rec)
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


# ── FR-011 G1 (ADR-0039) — resumability snapshot (staged errors + chart-restore) ──
def snapshot() -> dict[str, Any]:
    """The per-session armed-error state (incl. each error's chart-restore
    snapshot), for the resumability blob. All structured / JSON-safe."""
    return {sid: copy.deepcopy(bucket) for sid, bucket in _SESSION_ERRORS.items()}


def restore(blob: dict[str, Any]) -> None:
    _SESSION_ERRORS.clear()
    for sid, bucket in (blob or {}).items():
        if isinstance(bucket, dict):
            _SESSION_ERRORS[sid] = copy.deepcopy(bucket)
