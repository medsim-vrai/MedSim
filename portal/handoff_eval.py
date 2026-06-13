# FR-009 H5 — shift-handoff evaluation engine.
#
# Turns the handoff into the teaching artifact:
#   • score_coverage   — BINARY per-element coverage of the trainee's report vs
#     the context pack (the SBAR-LA design lesson: binary scores reliably,
#     "partial" does not). Each line carries quoted evidence + confirmed=False
#     until the instructor toggles it (only confirmed lines render to the student).
#   • perception_delta — the survey self-assessment set against the MEASURED
#     coverage (the research's core finding: self-rating runs high vs observed).
#   • receiver_metrics — oncoming mode: questions asked, read-back synthesis, and
#     whether a planted FR-008 discrepancy was caught.
#
# Scoring is AI-ASSISTABLE but defaults to a deterministic keyword/vocab
# heuristic so the engine works offline and tests are reproducible (inject a
# `scorer` to use a model). Instructor confirmation gates everything shown.

from __future__ import annotations

import re
import time
from typing import Any, Callable

from portal import handoff

# scorer(el, eid, transcript_text, vocab) -> (said: bool, evidence: str, confidence: str)
Scorer = Callable[[dict[str, Any], str, str, list[str]], tuple[bool, str, str]]


def _session_obj(session_id: str) -> Any:
    try:
        from portal import control_room, control_session
        room = control_room.get_active_room()
        if room and session_id in room.encounters:
            return room.encounters[session_id]
        s = control_session.get_active()
        return s if s is not None and getattr(s, "id", None) == session_id else None
    except Exception:  # noqa: BLE001
        return None


def _student_text(session_id: str) -> str:
    """The trainee's utterances this session (their report / questions)."""
    sess = _session_obj(session_id)
    if sess is None:
        return ""
    try:
        return " ".join(e.text for e in sess.transcript
                        if getattr(e, "direction", "") == "student" and e.text)
    except Exception:  # noqa: BLE001
        return ""


def _evidence_for(text: str, kw: str) -> str:
    """The sentence in the transcript that contains the matched cue (the quote)."""
    low = text.lower()
    i = low.find(kw.lower())
    if i < 0:
        return ""
    start = max(low.rfind(".", 0, i), low.rfind("?", 0, i),
                low.rfind("!", 0, i), -1) + 1
    ends = [x for x in (low.find(".", i), low.find("?", i), low.find("!", i)) if x >= 0]
    end = min(ends) + 1 if ends else len(text)
    return text[start:end].strip()


def _heuristic_scorer(el: dict[str, Any], eid: str, text: str,
                      vocab: list[str]) -> tuple[bool, str, str]:
    low = " " + text.lower() + " "
    for kw in handoff._ELEMENT_KEYWORDS.get(eid, ()):
        if kw in low:
            return True, _evidence_for(text, kw.strip()) or text[:140], "heuristic"
    if eid == "meds":
        for v in vocab:
            if v and v.lower() in low:
                return True, _evidence_for(text, v) or v, "heuristic"
    return False, "", "heuristic"


def score_coverage(session_id: str, persona_id: str, *,
                   transcript_text: str | None = None,
                   scorer: Scorer | None = None) -> dict[str, Any]:
    """Binary per-element coverage map for one patient's handoff. Default scorer
    is the deterministic heuristic; pass `scorer` to use an AI model."""
    h = handoff.get(session_id)
    if not h:
        return {}
    pack = h["packs"].get(persona_id)
    if not pack:
        return {}
    text = transcript_text if transcript_text is not None else _student_text(session_id)
    vocab = list(pack.get("_vocab") or [])
    use = scorer or _heuristic_scorer
    coverage: dict[str, Any] = {}
    for eid, el in pack["elements"].items():
        said, ev, conf = use(el, eid, text, vocab)
        coverage[eid] = {
            "display": el["display"], "said": bool(said), "evidence": ev or "",
            "confidence": conf, "high_risk": bool(el["high_risk"]), "confirmed": False,
        }
    return coverage


_WORD_NUM = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
             "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
# Dismissive "I missed nothing" non-answers (→ blind spot when misses exist).
_NO_GAP = re.compile(
    r"\b(nothing|none|no(t)?\s+really|nope|all good|covered everything|"
    r"didn'?t\s+miss|don'?t\s+think\s+so)\b", re.IGNORECASE)


def _parse_self_score(text: str) -> int | None:
    """0–10 self-rating from the completeness answer — the FIRST number, written
    as a digit OR a word (voice transcripts say "eight", not "8")."""
    t = str(text or "").lower()
    tok = re.search(r"\b(10|[0-9]|" + "|".join(_WORD_NUM) + r")\b", t)
    if not tok:
        return None
    g = tok.group(1)
    return int(g) if g.isdigit() else _WORD_NUM[g]


def perception_delta(coverage: dict[str, Any],
                     answers: dict[str, Any]) -> dict[str, Any]:
    """Survey self-assessment vs the measured coverage map — the perception gap."""
    total = len(coverage) or 1
    said = sum(1 for c in coverage.values() if c["said"])
    measured = round(100 * said / total)
    high_risk_misses = [c["display"] for c in coverage.values()
                        if not c["said"] and c["high_risk"]]
    rows: list[dict[str, Any]] = []

    a1 = str((answers.get("completeness") or {}).get("text", ""))
    sc = _parse_self_score(a1)
    if sc is not None:
        self_pct = sc * 10
        gap = self_pct - measured
        verdict = ("overestimate" if gap >= 20
                   else "underestimate" if gap <= -20 else "aligned")
        rows.append({"q": "completeness", "answer": a1, "self_pct": self_pct,
                     "measured_pct": measured, "gap": gap, "verdict": verdict})

    a3 = str((answers.get("missed") or {}).get("text", "")).strip()
    # A dismissive non-answer ("nothing", "no, not really") while high-risk items
    # WERE actually missed is the blind spot the survey is designed to expose.
    dismissive = bool(_NO_GAP.search(a3))
    missed_blind = high_risk_misses and (not a3 or dismissive)
    rows.append({"q": "missed", "answer": a3,
                 "actual_high_risk_misses": high_risk_misses,
                 "verdict": "blind_spot" if missed_blind else "noted"})

    return {"measured_pct": measured, "high_risk_misses": high_risk_misses, "rows": rows}


def _discrepancy_caught(session_id: str) -> bool | None:
    """Was a staged FR-008 discrepancy caught? None = none was staged."""
    try:
        from portal import med_errors
        errs = med_errors.state(session_id).get("errors", [])
        if not errs:
            return None
        return any(e.get("outcome") == "caught" for e in errs)
    except Exception:  # noqa: BLE001
        return None


def receiver_metrics(session_id: str, persona_id: str, *,
                     transcript_text: str | None = None) -> dict[str, Any]:
    """Oncoming mode: what the student (receiver) did — questions touched, read-back
    synthesis, and whether a planted discrepancy was caught."""
    text = transcript_text if transcript_text is not None else _student_text(session_id)
    low = " " + text.lower() + " "
    touched = sorted(eid for eid, kws in handoff._ELEMENT_KEYWORDS.items()
                     if eid not in ("synthesis", "transfer")
                     and any(k in low for k in kws))
    synthesis = any(k in low for k in handoff._ELEMENT_KEYWORDS["synthesis"])
    return {
        "questions_touched": [handoff.DISPLAY.get(e, e) for e in touched],
        "n_touched": len(touched),
        "synthesis": synthesis,
        "discrepancy_caught": _discrepancy_caught(session_id),
    }


_PROMPT_TEMPLATES = {
    "background": "The allergy / code status wasn't handed off — what happens overnight "
                  "when nobody asks?",
    "meds": "Medication details were missed — which med error does that invite?",
    "pending": "Pending results/tasks weren't passed on — who follows them up if they're "
               "not mentioned?",
    "anticipate": "No 'watch-for' was given — the next nurse can't pre-empt what they don't "
                  "know is coming. What should it have been?",
    "safety": "A safety risk wasn't handed off — what's the consequence on the next shift?",
    "severity": "The illness severity wasn't stated up front — how does that change how the "
                "oncoming nurse prioritizes?",
    "access": "Lines/access weren't mentioned — why does that matter for the next shift?",
    "synthesis": "There was no read-back — how do you confirm the receiver actually got it?",
}


def auto_prompts(coverage: dict[str, Any], delta: dict[str, Any]) -> list[str]:
    """Debrief discussion starters generated from the misses (high-risk first)."""
    out: list[str] = []
    for eid, c in coverage.items():
        if not c["said"] and c["high_risk"] and eid in _PROMPT_TEMPLATES:
            out.append(_PROMPT_TEMPLATES[eid])
    rows = {r["q"]: r for r in delta.get("rows", [])}
    comp = rows.get("completeness")
    if comp and comp.get("verdict") == "overestimate":
        out.insert(0, f"You rated the handoff {comp['self_pct']}% complete; the record shows "
                       f"{comp['measured_pct']}%. Where does that gap come from — and what's "
                       f"its clinical cost?")
    return out


def build_evaluation(session_id: str, persona_id: str, *,
                     transcript_text: str | None = None,
                     scorer: Scorer | None = None) -> dict[str, Any]:
    """Full evaluation for one patient: coverage + delta + (oncoming) receiver
    metrics + auto debrief prompts. Cached on the handoff state so the
    instructor's confirm toggles persist."""
    h = handoff.get(session_id)
    if not h:
        return {}
    coverage = score_coverage(session_id, persona_id,
                              transcript_text=transcript_text, scorer=scorer)
    answers = handoff.survey_answers(session_id)
    delta = perception_delta(coverage, answers)
    ev: dict[str, Any] = {
        "persona_id": persona_id,
        "patient": h["packs"].get(persona_id, {}).get("patient", {}),
        "mode": h["mode"],
        "coverage": coverage,
        "perception_delta": delta,
        "auto_prompts": auto_prompts(coverage, delta),
        "built_at": time.time(),
    }
    if h["mode"] == "oncoming":
        ev["receiver_metrics"] = receiver_metrics(
            session_id, persona_id, transcript_text=transcript_text)
    h.setdefault("evaluation", {})[persona_id] = ev
    return ev


def get_evaluation(session_id: str, persona_id: str) -> dict[str, Any] | None:
    h = handoff.get(session_id)
    return (h.get("evaluation") or {}).get(persona_id) if h else None


def confirm_coverage(session_id: str, persona_id: str, element_id: str, *,
                     said: bool | None = None, confirmed: bool = True) -> bool:
    """Instructor gate: confirm a coverage line (and optionally override said)
    before it renders to the student."""
    ev = get_evaluation(session_id, persona_id)
    if not ev or element_id not in ev["coverage"]:
        return False
    line = ev["coverage"][element_id]
    line["confirmed"] = bool(confirmed)
    if said is not None:
        line["said"] = bool(said)
    # delta refreshes off the confirmed-overridden map.
    ev["perception_delta"] = perception_delta(ev["coverage"],
                                              handoff.survey_answers(session_id))
    ev["auto_prompts"] = auto_prompts(ev["coverage"], ev["perception_delta"])
    return True
