"""FR-009 H2 — handoff session mode + AI counterpart prompt blocks."""
from __future__ import annotations

import pytest

from portal import handoff


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
NURSE = {"id": "P-040", "name": "Charge Nurse Kim", "role": "Charge Nurse"}
DOCTOR = {"id": "P-001", "name": "Dr. Patel", "role": "Attending"}
PATIENT = {"id": "P-099", "name": "Margaret Hale", "role": "Patient"}
SID = "s-handoff"


@pytest.fixture
def chart(monkeypatch):
    from portal import ehr_db, med_orders, med_errors
    monkeypatch.setattr(ehr_db, "seed", lambda sid: dict(HAYES_SEED))
    monkeypatch.setattr(ehr_db, "fold", lambda sid: {"orders": [{"label": "Blood cultures x2"}]})
    monkeypatch.setattr(med_orders, "get_state", lambda sid: None)
    monkeypatch.setattr(med_errors, "state", lambda sid: {"errors": []})
    yield
    handoff.clear_session(SID)


def test_lifecycle(chart):
    assert handoff.state(SID)["active"] is False
    handoff.start_handoff(SID, mode="offgoing", persona_ids=["P-099"], counterpart_id="P-040")
    st = handoff.state(SID)
    assert st["active"] and st["mode"] == "offgoing" and st["counterpart_id"] == "P-040"
    assert handoff.end_handoff(SID) is True
    assert handoff.state(SID)["active"] is False


def test_block_targets_only_the_counterpart(chart):
    handoff.start_handoff(SID, mode="offgoing", persona_ids=["P-099"], counterpart_id="P-040")
    assert handoff.prompt_block_for(SID, NURSE) != ""        # the counterpart
    assert handoff.prompt_block_for(SID, DOCTOR) == ""       # not the counterpart
    assert handoff.prompt_block_for(SID, PATIENT) == ""
    # No handoff active → empty for everyone.
    handoff.end_handoff(SID)
    assert handoff.prompt_block_for(SID, NURSE) == ""


def test_offgoing_receiver_block_has_arc_and_containment(chart):
    handoff.start_handoff(SID, mode="offgoing", persona_ids=["P-099"], counterpart_id="P-040")
    b = handoff.prompt_block_for(SID, NURSE)
    assert "RECEIVING" in b and "follow-up QUESTION" in b
    assert "read-back" in b or "confirm" in b               # synthesis ask
    assert "I've got them" in b                              # responsibility transfer
    assert "NEVER hint" in b                                 # containment
    assert "Penicillin" in b and "Ceftriaxone" in b         # chart reference present


def test_oncoming_dial_filters_content(chart):
    # complete → anticipatory guidance present.
    handoff.start_handoff(SID, mode="oncoming", dial="complete",
                          persona_ids=["P-099"], counterpart_id="P-040")
    assert "Anticipatory guidance" in handoff.prompt_block_for(SID, NURSE)
    handoff.end_handoff(SID)
    # typical_gaps → anticipatory guidance dropped from what the AI volunteers.
    handoff.start_handoff(SID, mode="oncoming", dial="typical_gaps",
                          persona_ids=["P-099"], counterpart_id="P-040")
    b = handoff.prompt_block_for(SID, NURSE)
    assert "GIVING" in b and "Anticipatory guidance" not in b


def test_staged_error_dial_requires_an_armed_error(chart, monkeypatch):
    with pytest.raises(ValueError):
        handoff.start_handoff(SID, mode="oncoming", dial="staged_error",
                              persona_ids=["P-099"], counterpart_id="P-040")
    # Arm one → now allowed.
    from portal import med_errors
    monkeypatch.setattr(med_errors, "state",
                        lambda sid: {"errors": [{"status": "armed"}]})
    rec = handoff.start_handoff(SID, mode="oncoming", dial="staged_error",
                                persona_ids=["P-099"], counterpart_id="P-040")
    assert rec["dial"] == "staged_error"


def test_probe_list_shrinks_as_the_student_covers_elements(chart):
    handoff.start_handoff(SID, mode="offgoing", persona_ids=["P-099"], counterpart_id="P-040")
    gaps0 = handoff.still_unsaid(SID, "P-099")
    assert "Background (allergies, code status)" in gaps0
    # Student reports allergy + code status + the antibiotic.
    handoff.note_student_utterance(
        SID, "She's allergic to penicillin, full code, on Ceftriaxone IV.")
    gaps1 = handoff.still_unsaid(SID, "P-099")
    assert "Background (allergies, code status)" not in gaps1
    assert len(gaps1) < len(gaps0)
    # High-risk items sort first in the probe list.
    hr = set(handoff.DISPLAY[e] for e in handoff.HIGH_RISK)
    if gaps1:
        assert gaps1[0] in hr


def test_bad_mode_and_missing_args_rejected(chart):
    with pytest.raises(ValueError):
        handoff.start_handoff(SID, mode="sideways", persona_ids=["P-099"], counterpart_id="P-040")
    with pytest.raises(ValueError):
        handoff.start_handoff(SID, mode="offgoing", persona_ids=[], counterpart_id="P-040")
    with pytest.raises(ValueError):
        handoff.start_handoff(SID, mode="offgoing", persona_ids=["P-099"], counterpart_id="")


# ── routes (auth'd instructor API) ──────────────────────────────────────────────
from pathlib import Path
from fastapi.testclient import TestClient

TEST_PASSWORD = "test_passwd_xyz_8chars"


def _ensure_vault():
    from portal import credentials
    vp = Path.home() / ".medsim" / "vault.enc"
    if vp.exists():
        try:
            credentials.unlock(TEST_PASSWORD); return
        except ValueError:
            vp.unlink()
    credentials.initialize(TEST_PASSWORD)


@pytest.fixture
def client(monkeypatch):
    _ensure_vault()
    from portal import control_session, ehr_db, med_orders, med_errors, server
    monkeypatch.setattr(ehr_db, "seed", lambda sid: dict(HAYES_SEED))
    monkeypatch.setattr(ehr_db, "fold", lambda sid: {"orders": []})
    monkeypatch.setattr(med_orders, "get_state", lambda sid: None)
    monkeypatch.setattr(med_errors, "state", lambda sid: {"errors": []})
    c = TestClient(server.app)
    c.post("/login", data={"password": TEST_PASSWORD})
    sess = control_session.create_session(
        scenario_name="handoff-route-test",
        selected_personas=["P-099", "P-040"], selected_modules=[], api_key="dummy")
    c._sess = sess
    yield c
    handoff.clear_session(sess.id)
    control_session.end_active()


def test_routes_require_auth():
    _ensure_vault()
    from portal import server
    raw = TestClient(server.app)
    assert raw.get("/api/control/handoff").status_code in (303, 401, 403)


def test_start_state_end_via_routes(client):
    assert client.get("/api/control/handoff").json()["active"] is False
    j = client.post("/api/control/handoff/start",
                    json={"mode": "offgoing", "counterpart_id": "P-040"}).json()
    assert j["ok"] and j["active"] and j["mode"] == "offgoing"
    # persona_ids defaulted to the session's patient.
    assert j["persona_ids"]
    assert client.get("/api/control/handoff").json()["active"] is True
    assert client.post("/api/control/handoff/end").json()["ended"] is True
    assert client.get("/api/control/handoff").json()["active"] is False


def test_start_bad_mode_is_400(client):
    r = client.post("/api/control/handoff/start",
                    json={"mode": "nope", "counterpart_id": "P-040"})
    assert r.status_code == 400
