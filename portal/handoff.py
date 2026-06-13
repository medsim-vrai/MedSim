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

def _abnormal_count(seed: dict[str, Any]) -> int:
    """How many of the latest vitals sit outside the normal (stable_baseline)
    ranges — the acuity signal behind severity + cross-patient prioritization."""
    norm = _ranges().get("stable_baseline") or {}
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
    return abn


def severity_for(seed: dict[str, Any]) -> str:
    """One-word illness severity from the chart: stable / watcher / unstable.

    Uses the condition's trend (CLINICAL_RANGES) + how far the latest vitals sit
    outside the normal ranges. Conservative + deterministic."""
    cond = str(seed.get("condition") or "stable_baseline")
    trend = str((_ranges().get(cond) or {}).get("trend", "flat"))
    abn = _abnormal_count(seed)
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


# ── H2: handoff session mode + AI counterpart ─────────────────────────────────
#
# A handoff runs as a phase over a live session. The instructor chooses:
#   • mode — OFFGOING (student GIVES report; the AI is the oncoming nurse who
#     RECEIVES, then probes the gaps) or ONCOMING (student RECEIVES; the AI is the
#     off-going nurse who GIVES report, at a chosen completeness dial).
#   • counterpart_id — which character (from the roster) is that AI nurse.
#   • persona_ids — the patient(s) the handoff covers (multi-patient is H3).
# The pack (H1) is the AI's knowledge AND the gap-detector. Only the counterpart
# character receives the handoff prompt block; everyone else gets "".

MODES = ("offgoing", "oncoming")
DIALS = ("complete", "typical_gaps", "staged_error")

# session_id -> handoff state
_HANDOFFS: dict[str, dict[str, Any]] = {}

# Coarse, RECALL-BIASED keyword cues per element — drives the receiver's probes
# (if unsure, leave an element "unsaid" so the AI asks about it). NOT the score:
# real coverage scoring is AI-assisted in H5.
_ELEMENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "identity":   ("admitted", "came in", "here for", "year-old", "year old", "room", "bed "),
    "severity":   ("stable", "unstable", "watcher", "critical", "sick", "deteriorat",
                   "improving", "worsening", "severity", "guarded", "sats are", "holding"),
    "background": ("allerg", "code status", "full code", "dnr", "dni", "history of",
                   " hx", "diagnos", "known ", "background"),
    "assessment": ("vital", "temp", "fever", "heart rate", " hr ", "blood pressure",
                   " bp ", " sat", "spo2", "respirat", "resp rate", "lab", "wbc",
                   "white count", "glucose", "afebrile"),
    "meds":       ("medication", " med ", "meds", "dose", "milligram", " mg", "ordered",
                   "antibiotic", "drip", "infus", "giving", "administer", "due at", "next dose"),
    "access":     (" iv", "i.v", "line", "catheter", "drain", "access", "picc",
                   "central", "peripheral", "foley", "gauge"),
    "pending":    ("pending", "awaiting", "waiting on", "culture", "follow up", "follow-up",
                   "result", "consult", "still out", "ordered but"),
    "safety":     ("fall", "risk", "precaution", "airway", "isolation", "bleeding",
                   "aspiration", "seizure", "bed alarm"),
    "anticipate": ("watch for", "watch out", "if ", "escalate", "call ", "contingency",
                   "keep an eye", "look out", "may need", "be ready"),
    "synthesis":  ("so to summarize", "to summarize", "just to confirm", "read back",
                   "let me confirm", "so the plan"),
    "transfer":   ("i've got", "i have got", "i have them", "taking over", "i'll take",
                   "got them", "i have him", "i have her", "i'll pick"),
}


def get(session_id: str) -> dict[str, Any] | None:
    return _HANDOFFS.get(session_id)


MAX_PATIENTS = 3   # charge-nurse turnover cap (ratified FR-009 v1)


def start_handoff(session_id: str, *, mode: str, persona_ids: list[str],
                  counterpart_id: str, dial: str = "complete",
                  patient_sources: dict[str, str] | None = None) -> dict[str, Any]:
    """Begin a handoff phase. Builds a pack per covered patient.

    Multi-patient (H3, charge-nurse turnover): pass up to MAX_PATIENTS persona_ids;
    `patient_sources` maps each persona → the session/encounter whose chart to
    build its pack from (default: this session). The handoff walks the patients in
    order; after the last, it asks the trainee to PRIORITIZE.

    ONCOMING with the 'staged_error' dial requires an FR-008 error already armed."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    if not persona_ids:
        raise ValueError("persona_ids: at least one patient required")
    if len(persona_ids) > MAX_PATIENTS:
        raise ValueError(f"at most {MAX_PATIENTS} patients per handoff (v1 cap)")
    if not counterpart_id:
        raise ValueError("counterpart_id required (the AI nurse/charge-nurse)")
    if mode == "oncoming":
        if dial not in DIALS:
            raise ValueError(f"dial must be one of {DIALS}")
        if dial == "staged_error" and not _has_armed_error(session_id):
            raise ValueError("the 'staged_error' report dial needs an FR-008 error "
                             "armed first (arm one in the staged-error builder)")
    sources = patient_sources or {}
    packs = {pid: build_pack(sources.get(pid, session_id), pid) for pid in persona_ids}
    rec = {
        "mode": mode, "dial": dial, "counterpart_id": counterpart_id,
        "persona_ids": list(persona_ids), "order": list(persona_ids),
        "packs": packs, "phase": "handoff", "cursor": 0,
        "said": {pid: set() for pid in persona_ids},
        "started_at": time.time(),
    }
    _HANDOFFS[session_id] = rec
    return rec


def current_patient(session_id: str) -> str | None:
    """The persona being handed off right now (cursor), or None when complete."""
    h = _HANDOFFS.get(session_id)
    if not h or h.get("phase") not in ("handoff",):
        return None
    order = h["order"]
    cur = h.get("cursor", 0)
    return order[cur] if 0 <= cur < len(order) else None


def advance_patient(session_id: str) -> str | None:
    """Close the current patient and move on. Returns the next persona, or None
    when the last patient is done — which (multi-patient) flips to the
    'prioritization' phase (the cross-patient 'who first and why' question)."""
    h = _HANDOFFS.get(session_id)
    if not h:
        return None
    order = h["order"]
    cur = h.get("cursor", 0)
    if cur < len(order) - 1:
        h["cursor"] = cur + 1
        return order[h["cursor"]]
    # last patient just closed
    h["phase"] = "prioritization" if len(order) > 1 else "done"
    return None


def expected_priority(session_id: str) -> list[dict[str, Any]]:
    """The rubric answer for 'who do you see first': patients ranked by severity
    tier (unstable > watcher > stable), then acuity (abnormal-vital count), then
    report order. The instructor can override (H6); H5 scores the student vs this."""
    h = _HANDOFFS.get(session_id)
    if not h:
        return []
    rank = {"unstable": 0, "watcher": 1, "stable": 2}
    rows = []
    for i, pid in enumerate(h["order"]):
        pack = h["packs"].get(pid) or {}
        rows.append((rank.get(pack.get("severity", "stable"), 2),
                     -int(pack.get("_acuity", 0)), i, pid, pack))
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    return [{"persona_id": pid, "name": pack.get("patient", {}).get("name", pid),
             "severity": pack.get("severity", "stable"), "rank": idx + 1}
            for idx, (_s, _a, _i, pid, pack) in enumerate(rows)]


def end_handoff(session_id: str) -> bool:
    return _HANDOFFS.pop(session_id, None) is not None


def clear_session(session_id: str) -> None:
    _HANDOFFS.pop(session_id, None)


def state(session_id: str) -> dict[str, Any]:
    """JSON-safe snapshot (sets → sorted lists)."""
    h = _HANDOFFS.get(session_id)
    if not h:
        return {"active": False}
    return {
        "active": True, "mode": h["mode"], "dial": h["dial"],
        "counterpart_id": h["counterpart_id"], "persona_ids": h["persona_ids"],
        "phase": h["phase"], "cursor": h.get("cursor", 0),
        "current_patient": current_patient(session_id),
        "n_patients": len(h["order"]),
        "covered": {pid: sorted(s) for pid, s in h["said"].items()},
        "still_unsaid": {pid: still_unsaid(session_id, pid) for pid in h["persona_ids"]},
        "expected_priority": expected_priority(session_id) if len(h["order"]) > 1 else [],
    }


def _has_armed_error(session_id: str) -> bool:
    try:
        from portal import med_errors
        return any(e.get("status") != "resolved"
                   for e in med_errors.state(session_id).get("errors", []))
    except Exception:  # noqa: BLE001
        return False


def note_student_utterance(session_id: str, text: str) -> None:
    """Mark elements the student has TOUCHED (off-going mode), to drive the
    receiver's gap probes. Recall-biased + best-effort; never raises."""
    try:
        h = _HANDOFFS.get(session_id)
        if not h or not text:
            return
        low = " " + text.lower() + " "
        hit = {eid for eid, kws in _ELEMENT_KEYWORDS.items()
               if any(k in low for k in kws)}
        # Drug/allergen mentions count as meds/background coverage.
        for pid, pack in h["packs"].items():
            for v in pack.get("_vocab", []):
                if v.lower() in low:
                    hit.add("meds")
                    break
            h["said"][pid] |= hit
    except Exception:  # noqa: BLE001
        return


def still_unsaid(session_id: str, persona_id: str) -> list[str]:
    """Element displays NOT yet covered for this patient, HIGH-RISK first —
    the receiver's probe targets. Synthesis/transfer are the receiver's own job,
    so they're excluded from the giver's gap list."""
    h = _HANDOFFS.get(session_id)
    if not h:
        return []
    said = h["said"].get(persona_id, set())
    skip = {"synthesis", "transfer"}
    pending = [(eid, eid in HIGH_RISK) for eid, _d, _hr in ELEMENTS
               if eid not in said and eid not in skip]
    pending.sort(key=lambda x: (not x[1], x[0]))   # high-risk first
    return [DISPLAY[eid] for eid, _ in pending]


# ── prompt blocks (only the counterpart character receives one) ───────────────

_CONTAIN = ("Stay fully in character as a busy but professional nurse. Introduce nothing "
            "beyond this patient's chart, and NEVER hint that this is a drill or that "
            "anything is staged.")


def _render_elements(pack: dict[str, Any], include: set[str]) -> str:
    return "\n".join(f"  - {el['display']}: {el['content']}"
                     for eid, el in pack["elements"].items() if eid in include)


def _dial_includes(dial: str) -> tuple[set[str], str]:
    """Elements the off-going AI should volunteer, + a delivery note, per dial."""
    allids = {e[0] for e in ELEMENTS}
    if dial == "typical_gaps":
        # The evidence-backed common omissions: anticipatory guidance + a pending item.
        return (allids - {"anticipate"},
                "Give a realistic, slightly rushed report. It's fine to UNDER-cover the "
                "pending items and to skip the 'watch-for' contingencies unless the "
                "student asks — that mirrors a typical real handoff.")
    if dial == "staged_error":
        return (allids,
                "Deliver the report normally; the staged discrepancy already in the chart "
                "rides along — present it as fact without flagging it.")
    return (allids, "Give a complete, well-organized report.")


def prompt_block_for(session_id: str, card: dict[str, Any]) -> str:
    """The handoff context for THIS character's turn. '' for everyone except the
    chosen counterpart (matched by card id)."""
    h = _HANDOFFS.get(session_id)
    if not h or h.get("phase") not in ("handoff", "prioritization"):
        return ""
    if str(card.get("id") or "") != str(h["counterpart_id"]):
        return ""

    # Cross-patient prioritization (charge-nurse, after the last patient).
    if h["phase"] == "prioritization":
        names = "; ".join(h["packs"][p]["patient"].get("name", p) for p in h["order"])
        return (
            f"HANDOFF — PRIORITIZATION. You have now received report on all "
            f"{len(h['order'])} patients ({names}). Ask the trainee: \"Of these "
            f"patients, who will you see first, and why?\" Listen to their reasoning "
            f"and follow up briefly. Do NOT rank the patients for them or reveal the "
            f"answer. {_CONTAIN}"
        )

    pid = current_patient(session_id) or (h["order"][0] if h["order"] else None)
    pack = h["packs"].get(pid) if pid else None
    if not pack:
        return ""
    name = pack["patient"].get("name", "the patient")

    # Sequence frame for charge-nurse turnover (>1 patient).
    seq = ""
    if len(h["order"]) > 1:
        cur = h.get("cursor", 0)
        seq = (f"[Charge-nurse turnover — patient {cur + 1} of {len(h['order'])}: {name}. "
               f"Focus on THIS patient now; move on only once this one is handed off "
               f"with a read-back.]\n")

    if h["mode"] == "offgoing":
        gaps = still_unsaid(session_id, pid)
        gap_line = ("Still uncovered so far: " + "; ".join(gaps[:6]) + "."
                    if gaps else "They appear to have covered the key elements.")
        return seq + (
            f"HANDOFF — you are the ONCOMING nurse RECEIVING end-of-shift report on {name} "
            f"from the trainee. Listen to their report. You hold this patient's chart as your "
            f"reference, so you know what a complete handoff should cover.\n"
            f"After they report: ask 2–4 focused follow-up QUESTIONS about what they did not "
            f"cover — HIGH-RISK items first. {gap_line}\n"
            f"If they never summarized the key points back to you, ASK them to confirm "
            f"severity, next-due meds, pending items, and what to watch for (a read-back). "
            f"Then accept responsibility (\"I've got them\"). Probe gaps through questions — "
            f"do NOT recite the chart yourself. {_CONTAIN}\n"
            f"CHART REFERENCE (your knowledge — do not read it aloud):\n"
            f"{_render_elements(pack, {e[0] for e in ELEMENTS})}"
        )
    # oncoming: the AI GIVES report (student receives + asks questions)
    include, note = _dial_includes(h["dial"])
    return seq + (
        f"HANDOFF — you are the OFF-GOING nurse GIVING end-of-shift report on {name} to the "
        f"trainee (the oncoming nurse). Give a structured verbal report, then answer their "
        f"follow-up questions HONESTLY from this chart. {note} {_CONTAIN}\n"
        f"REPORT CONTENT (your chart):\n{_render_elements(pack, include)}"
    )


def handoff_vocab(session_id: str) -> list[str]:
    """Drug/allergen names across the active handoff's packs — merged into the
    room-STT hints during the handoff phase so they transcribe faithfully."""
    h = _HANDOFFS.get(session_id)
    if not h:
        return []
    out: list[str] = []
    for pack in h["packs"].values():
        out += pack.get("_vocab", [])
    seen, dedup = set(), []
    for v in out:
        if v.lower() not in seen:
            seen.add(v.lower())
            dedup.append(v)
    return dedup


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
        "_acuity": _abnormal_count(seed),   # abnormal-vital count → priority secondary
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
