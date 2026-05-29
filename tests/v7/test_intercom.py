"""Phase 7 M28 — intercom tests.

Acceptance bars from the spec:
  1. Intercom page records a `comm.intercom` chart event.
  2. The voice resolution uses the staff persona's voice when one
     is bound.
"""
from __future__ import annotations

from pathlib import Path

import pytest


TEST_PASSWORD = "test_passwd_xyz_8chars"


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    from portal import (
        auth, control_room, credentials, voices as _voices,
        debrief as debrief_mod,
    )
    sandbox_vault_dir = fake_home / ".medsim"
    sandbox_vault_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(credentials, "VAULT_DIR", sandbox_vault_dir)
    monkeypatch.setattr(credentials, "VAULT_PATH",
                         sandbox_vault_dir / "vault.enc")
    monkeypatch.setattr(_voices, "KEYFILE", tmp_path / "no-such.key")
    monkeypatch.setattr(_voices, "_runtime_key", "")
    sandbox_debriefs = tmp_path / "data" / "debriefs"
    monkeypatch.setattr(debrief_mod, "DEBRIEFS_DIR", sandbox_debriefs)
    monkeypatch.setattr(debrief_mod, "COHORT_DEBRIEFS_DIR",
                         sandbox_debriefs / "cohort")
    control_room._reset_for_tests()
    if not credentials.is_initialized():
        credentials.initialize(TEST_PASSWORD)
    vault = credentials.unlock(TEST_PASSWORD)
    vault.set("ANTHROPIC_API_KEY", "sk-ant-dummy")
    vault.set("ELEVENLABS_API_KEY", "")
    from portal import server
    from fastapi.testclient import TestClient
    with TestClient(server.app) as c:
        c.cookies.set(auth.COOKIE_NAME, auth.issue_session_token(vault))
        yield c
    control_room._reset_for_tests()


def _setup(client, *, with_staff_persona: bool = False):
    """Start a 2-bed room (the second with staff persona bound) + a
    nurse-station student. Returns (room_code, nurse_sid,
    eid_with_staff, eid_no_staff)."""
    from portal import control_room
    encounters = [
        {"scenario_name": "Bed 1 (patient only)",
         "persona_id": "P-001", "patient_persona_id": "P-001",
         "ehr_id": "helix"},
        {"scenario_name": "Bed 2 (patient + nurse)",
         "persona_id": "P-013", "patient_persona_id": "P-013",
         "ehr_id": "helix"},
    ]
    r = client.post("/api/room/start", json={"label": "Intercom test",
                                               "encounters": encounters})
    assert r.status_code == 200
    body = r.json()
    eid_a = body["encounters"][0]["encounter_id"]
    eid_b = body["encounters"][1]["encounter_id"]
    room_code = client.get("/api/room/state").json()["room_code"]
    # Optionally bind a staff persona + voice to Bed 2.
    if with_staff_persona:
        room = control_room.get_active_room()
        enc = room.encounters[eid_b]
        enc.selected_personas = ["P-013", "P-004"]   # patient + Charge Nurse Kim
        enc.voice_assignments = {"P-004": "voice-kim-charge"}
    # Register nurse-station student.
    r = client.post("/portal/students/register_nurse",
                     data={"room_code": room_code, "display_name": "Pat"})
    assert r.status_code == 200
    nurse_sid = r.json()["student_id"]
    return room_code, nurse_sid, eid_b, eid_a


def test_intercom_page_records_comm_event(client) -> None:
    """A successful page POST writes one comm.intercom chart event
    to the target encounter."""
    from portal import ehr_db
    _, nurse_sid, eid_b, _ = _setup(client)
    r = client.post(f"/api/intercom/{eid_b}/page", json={
        "text": "Bed 2, can you confirm pain reassessment in 15 min?",
        "from_student_id": nurse_sid,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["text"].startswith("Bed 2")
    # The chart_event log has the row.
    events = [e for e in ehr_db.events(eid_b) if e["type"] == "comm.intercom"]
    assert len(events) == 1
    payload = events[0]["payload"]
    assert payload["from_student_id"] == nurse_sid
    assert payload["source"] == "nurse_station"


def test_intercom_uses_staff_persona_voice_when_available(client) -> None:
    """When the encounter has a staff persona with a voice assignment,
    the intercom resolves voice_id to that voice."""
    _, nurse_sid, eid_with_staff, _ = _setup(client, with_staff_persona=True)
    r = client.post(f"/api/intercom/{eid_with_staff}/page", json={
        "text": "Test page", "from_student_id": nurse_sid,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["persona_id"] == "P-004"
    assert body["voice_id"] == "voice-kim-charge"


def test_intercom_falls_back_to_no_voice_when_no_staff_persona(client) -> None:
    """When no staff persona is bound, voice_id is None → bedside
    falls back to browser TTS."""
    _, nurse_sid, _, eid_no_staff = _setup(client)
    r = client.post(f"/api/intercom/{eid_no_staff}/page", json={
        "text": "Bed 1 page", "from_student_id": nurse_sid,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["persona_id"] is None
    assert body["voice_id"] is None


def test_intercom_404s_on_unknown_encounter(client) -> None:
    _, nurse_sid, _, _ = _setup(client)
    r = client.post("/api/intercom/encounter_does_not_exist/page", json={
        "text": "x", "from_student_id": nurse_sid,
    })
    assert r.status_code == 404


def test_intercom_403s_when_from_student_is_not_nurse(client) -> None:
    """A bedside-role student can't fire the intercom — even if they
    pass their valid student id."""
    from portal import control_room
    _, _, eid_b, _ = _setup(client)
    # Create a bedside student.
    room_code = control_room.get_active_room().room_code
    r = client.post("/portal/students/register", data={
        "room_code": room_code, "encounter_id": eid_b,
        "display_name": "Bedside Bob",
    })
    bedside_sid = r.json()["student_id"]
    # Try to fire intercom as the bedside student.
    r = client.post(f"/api/intercom/{eid_b}/page", json={
        "text": "should fail", "from_student_id": bedside_sid,
    })
    assert r.status_code == 403


def test_intercom_400s_on_empty_text(client) -> None:
    _, nurse_sid, eid_b, _ = _setup(client)
    r = client.post(f"/api/intercom/{eid_b}/page", json={
        "text": "   ", "from_student_id": nurse_sid,
    })
    assert r.status_code == 400


def test_intercom_emits_ws_push(client) -> None:
    """The intercom POST emits a `type: intercom` WS push so the
    bedside reacts in real time. M16 WS hook."""
    _, nurse_sid, eid_b, _ = _setup(client)
    room_code = client.get("/api/room/state").json()["room_code"]
    with client.websocket_connect(f"/ws/room/{room_code}") as ws:
        client.post(f"/api/intercom/{eid_b}/page", json={
            "text": "WS hello",
            "from_student_id": nurse_sid,
        })
        msg = ws.receive_json()
        assert msg["type"] == "intercom"
        assert msg["encounter_id"] == eid_b
        assert msg["payload"]["text"] == "WS hello"
