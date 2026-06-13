"""FR-009 H5 — handoff evaluation engine (coverage, perception delta, receiver
metrics, debrief section)."""
from __future__ import annotations

import pytest

from portal import handoff, handoff_eval


HAYES_SEED = {
    "name": "Margaret Hale", "persona_id": "P-099",
    "chief_complaint": "community-acquired pneumonia", "condition": "pneumonia",
    "code_status": "Full Code",
    "allergies": [{"substance": "Penicillin", "reaction": "rash"}],
    "problem_list": [{"name": "CAP"}],
    "medications": [{"name": "Ceftriaxone", "dose": "1 g", "route": "IV", "frequency": "q24h"}],
    "vitals_baseline": [{"t": "38.1", "hr": "92", "rr": "22", "bp": "128/76", "spo2": "94"}],
    "iv_fluids": [{"name": "20G PIV", "site": "left forearm"}],
    "safety_class": "fall_risk",
}
SID = "s-eval"


@pytest.fixture
def handoff_started(monkeypatch):
    from portal import ehr_db, med_orders, med_errors
    monkeypatch.setattr(ehr_db, "seed", lambda sid: dict(HAYES_SEED))
    monkeypatch.setattr(ehr_db, "fold", lambda sid: {"orders": [{"label": "Blood cultures x2"}]})
    monkeypatch.setattr(med_orders, "get_state", lambda sid: None)
    monkeypatch.setattr(med_errors, "state", lambda sid: {"errors": []})
    handoff.start_handoff(SID, mode="offgoing", persona_ids=["P-099"], counterpart_id="P-040")
    yield
    handoff.clear_session(SID)


# A partial report: covers meds + vitals + identity, but NOT allergy/code status,
# pending items, or watch-fors (the classic high-risk misses).
PARTIAL_REPORT = ("This is Margaret Hale, admitted with pneumonia. Her temp is 38.1, "
                  "heart rate 92, sats 94 on oxygen. She's on Ceftriaxone IV. "
                  "She has a 20-gauge IV in the left forearm and she's a fall risk.")


def test_coverage_is_binary_and_quotes_evidence(handoff_started):
    cov = handoff_eval.score_coverage(SID, "P-099", transcript_text=PARTIAL_REPORT)
    assert set(cov) == set(handoff.DISPLAY)               # all 11 elements scored
    for c in cov.values():
        assert c["said"] in (True, False)                # strictly binary
        assert c["confirmed"] is False                   # instructor gate not yet toggled
    assert cov["meds"]["said"] and "Ceftriaxone" in cov["meds"]["evidence"]
    assert cov["identity"]["said"] and cov["assessment"]["said"]
    # The high-risk omissions are caught as NOT said.
    assert cov["background"]["said"] is False             # allergy/code status missing
    assert cov["pending"]["said"] is False
    assert cov["anticipate"]["said"] is False


def test_injected_scorer_is_used(handoff_started):
    calls = []
    def fake(el, eid, text, vocab):
        calls.append(eid)
        return (eid == "severity", "model said so", "ai")
    cov = handoff_eval.score_coverage(SID, "P-099", transcript_text="x", scorer=fake)
    assert len(calls) == 11
    assert cov["severity"]["said"] and cov["severity"]["confidence"] == "ai"
    assert cov["meds"]["said"] is False


def test_perception_delta_flags_overestimate(handoff_started):
    cov = handoff_eval.score_coverage(SID, "P-099", transcript_text=PARTIAL_REPORT)
    # Student rates themselves 8/10 but the record shows a partial report.
    answers = {"completeness": {"text": "Eight out of ten, I covered everything important."},
               "missed": {"text": "Nothing really."}}
    delta = handoff_eval.perception_delta(cov, answers)
    comp = next(r for r in delta["rows"] if r["q"] == "completeness")
    assert comp["self_pct"] == 80
    assert comp["measured_pct"] < 80
    assert comp["verdict"] == "overestimate"             # the published 8.1-vs-7.1 effect
    # They claimed they missed nothing, but high-risk items WERE missed → blind spot.
    missed = next(r for r in delta["rows"] if r["q"] == "missed")
    assert missed["verdict"] == "blind_spot"
    assert delta["high_risk_misses"]                     # allergy/code, pending, watch-fors


def test_build_evaluation_aggregates_and_auto_prompts(handoff_started):
    handoff.record_survey_answer(SID, "completeness", "Eight, covered everything.")
    ev = handoff_eval.build_evaluation(SID, "P-099", transcript_text=PARTIAL_REPORT)
    assert ev["mode"] == "offgoing"
    assert ev["perception_delta"]["measured_pct"] < 80
    assert ev["auto_prompts"]                            # at least one discussion prompt
    assert any("rated" in p for p in ev["auto_prompts"])  # the overestimate prompt leads
    assert handoff_eval.get_evaluation(SID, "P-099") is ev   # cached on the handoff


def test_instructor_confirm_gates_and_can_override(handoff_started):
    handoff_eval.build_evaluation(SID, "P-099", transcript_text=PARTIAL_REPORT)
    ev = handoff_eval.get_evaluation(SID, "P-099")
    assert ev["coverage"]["background"]["confirmed"] is False
    # The instructor overrides: the student DID mention the allergy verbally.
    assert handoff_eval.confirm_coverage(SID, "P-099", "background", said=True)
    assert ev["coverage"]["background"]["confirmed"] is True
    assert ev["coverage"]["background"]["said"] is True
    # Overriding a miss → measured coverage % goes up.
    assert handoff_eval.confirm_coverage(SID, "P-099", "nonexistent") is False


def test_receiver_metrics_for_oncoming(monkeypatch):
    from portal import ehr_db, med_orders, med_errors
    monkeypatch.setattr(ehr_db, "seed", lambda sid: dict(HAYES_SEED))
    monkeypatch.setattr(ehr_db, "fold", lambda sid: {})
    monkeypatch.setattr(med_orders, "get_state", lambda sid: None)
    monkeypatch.setattr(med_errors, "state", lambda sid: {"errors": []})
    handoff.start_handoff(SID, mode="oncoming", persona_ids=["P-099"], counterpart_id="P-040")
    try:
        questions = ("What are her allergies and code status? Any pending labs? "
                     "So to summarize, she's a watcher on Ceftriaxone with cultures pending.")
        ev = handoff_eval.build_evaluation(SID, "P-099", transcript_text=questions)
        rm = ev["receiver_metrics"]
        assert "Background (allergies, code status)" in rm["questions_touched"]
        assert rm["synthesis"] is True                   # they read back
        assert rm["discrepancy_caught"] is None          # none staged
    finally:
        handoff.clear_session(SID)


def test_debrief_section_renders(handoff_started):
    from types import SimpleNamespace
    from portal import debrief
    handoff.record_survey_answer(SID, "completeness", "Eight.")
    # A session object whose id matches the handoff + a student transcript.
    entry = SimpleNamespace(direction="student", text=PARTIAL_REPORT)
    sess = SimpleNamespace(id=SID, transcript=[entry])
    section = debrief._handoff_section(sess)
    assert section is not None and section["mode"] == "offgoing"
    assert len(section["patients"]) == 1
    pt = section["patients"][0]
    assert pt["coverage"]["meds"]["said"] is True
    assert pt["perception_delta"]["high_risk_misses"]


def test_no_handoff_means_no_debrief_section():
    from types import SimpleNamespace
    from portal import debrief
    sess = SimpleNamespace(id="never", transcript=[])
    assert debrief._handoff_section(sess) is None
