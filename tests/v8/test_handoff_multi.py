"""FR-009 H3 — multi-patient (charge-nurse) handoff sequencing + prioritization."""
from __future__ import annotations

import pytest

from portal import handoff

# Three patients on different charts (different source sessions).
POSTOP = {  # fresh post-op, soft BP → UNSTABLE
    "name": "Daniel Reyes", "persona_id": "P-050", "condition": "stable_baseline",
    "code_status": "Full Code", "chief_complaint": "POD#0 lap chole",
    "vitals_baseline": [{"hr": "112", "rr": "20", "bp": "86/52", "spo2": "95"}],
    "medications": [{"name": "Oxycodone", "dose": "5 mg", "frequency": "q4h PRN"}],
}
PNEUMONIA = {  # improving pneumonia → WATCHER
    "name": "Margaret Hale", "persona_id": "P-099", "condition": "stable_baseline",
    "code_status": "Full Code", "chief_complaint": "CAP, improving",
    "vitals_baseline": [{"hr": "88", "rr": "18", "bp": "124/78", "spo2": "93"}],
    "medications": [{"name": "Ceftriaxone", "dose": "1 g", "frequency": "q24h"}],
}
CHF = {  # stable CHF → STABLE
    "name": "Alma Whitfield", "persona_id": "P-060", "condition": "stable_baseline",
    "code_status": "DNR", "chief_complaint": "compensated CHF",
    "vitals_baseline": [{"hr": "74", "rr": "16", "bp": "118/72", "spo2": "97"}],
    "medications": [{"name": "Furosemide", "dose": "40 mg", "frequency": "daily"}],
}
SEEDS = {"bed-postop": POSTOP, "bed-pna": PNEUMONIA, "bed-chf": CHF}
NURSE = {"id": "P-040", "name": "Charge Nurse Kim", "role": "Charge Nurse"}
SID = "s-charge"


@pytest.fixture
def charts(monkeypatch):
    from portal import ehr_db, med_orders, med_errors
    monkeypatch.setattr(ehr_db, "seed", lambda sid: dict(SEEDS.get(sid, {})))
    monkeypatch.setattr(ehr_db, "fold", lambda sid: {})
    monkeypatch.setattr(med_orders, "get_state", lambda sid: None)
    monkeypatch.setattr(med_errors, "state", lambda sid: {"errors": []})
    yield
    handoff.clear_session(SID)


def _start_three(mode="offgoing"):
    return handoff.start_handoff(
        SID, mode=mode, persona_ids=["P-050", "P-099", "P-060"], counterpart_id="P-040",
        patient_sources={"P-050": "bed-postop", "P-099": "bed-pna", "P-060": "bed-chf"})


def test_per_patient_packs_built_from_their_own_charts(charts):
    rec = _start_three()
    assert rec["packs"]["P-050"]["patient"]["name"] == "Daniel Reyes"
    assert rec["packs"]["P-099"]["patient"]["name"] == "Margaret Hale"
    assert rec["packs"]["P-060"]["patient"]["name"] == "Alma Whitfield"
    # Severity differs per chart.
    assert rec["packs"]["P-050"]["severity"] == "unstable"
    assert rec["packs"]["P-060"]["severity"] == "stable"


def test_patient_cap_enforced(charts):
    with pytest.raises(ValueError):
        handoff.start_handoff(SID, mode="offgoing", counterpart_id="P-040",
                              persona_ids=["P-050", "P-099", "P-060", "P-001"])


def test_cursor_advances_through_patients_then_prioritization(charts):
    _start_three()
    assert handoff.current_patient(SID) == "P-050"
    assert handoff.advance_patient(SID) == "P-099"
    assert handoff.current_patient(SID) == "P-099"
    assert handoff.advance_patient(SID) == "P-060"
    # Closing the LAST patient flips to the prioritization phase.
    assert handoff.advance_patient(SID) is None
    assert handoff.state(SID)["phase"] == "prioritization"
    assert handoff.current_patient(SID) is None


def test_sequence_frame_targets_the_current_patient(charts):
    _start_three()
    b0 = handoff.prompt_block_for(SID, NURSE)
    assert "patient 1 of 3" in b0 and "Daniel Reyes" in b0
    handoff.advance_patient(SID)
    b1 = handoff.prompt_block_for(SID, NURSE)
    assert "patient 2 of 3" in b1 and "Margaret Hale" in b1


def test_prioritization_block_asks_who_first(charts):
    _start_three()
    handoff.advance_patient(SID); handoff.advance_patient(SID); handoff.advance_patient(SID)
    b = handoff.prompt_block_for(SID, NURSE)
    assert "PRIORITIZATION" in b and "who will you see first" in b
    assert "Daniel Reyes" in b and "Alma Whitfield" in b   # names listed
    assert "NEVER hint" in b                                # containment


def test_expected_priority_ranks_unstable_first(charts):
    _start_three()
    pri = handoff.expected_priority(SID)
    # Post-op (unstable) outranks improving pneumonia (watcher) outranks stable CHF —
    # the samples-workbook teaching case.
    assert [p["persona_id"] for p in pri] == ["P-050", "P-099", "P-060"]
    assert pri[0]["severity"] == "unstable" and pri[0]["rank"] == 1


def test_single_patient_unaffected_no_sequence_frame(charts):
    handoff.start_handoff(SID, mode="offgoing", persona_ids=["P-099"],
                          counterpart_id="P-040", patient_sources={"P-099": "bed-pna"})
    b = handoff.prompt_block_for(SID, NURSE)
    assert "Charge-nurse turnover" not in b               # no sequence frame for 1 patient
    assert handoff.advance_patient(SID) is None
    assert handoff.state(SID)["phase"] == "done"          # not prioritization for single
