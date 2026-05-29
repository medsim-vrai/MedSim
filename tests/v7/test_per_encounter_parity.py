"""M30 — Per-encounter parity tests.

Four new instructor surfaces under each encounter:
  1. Live transcript poll via /api/encounter/{id}/transcript
  2. Per-persona voice picker via /api/encounter/{id}/voices
  3. Lead student assignment via /api/encounter/{id}/lead_student
  4. Pop-out console URL surfaced in /api/room/state for the
     dashboard's per-card pop-out button + the cohort debrief
     facet's lead_student_name.
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


def _start_room(client, n: int = 2):
    entries = [
        {"scenario_name": f"Bed {i+1}", "persona_id": f"P-{i+1:03d}",
         "patient_persona_id": f"P-{i+1:03d}", "ehr_id": "helix"}
        for i in range(n)
    ]
    r = client.post("/api/room/start",
                     json={"label": "M30 parity test", "encounters": entries})
    assert r.status_code == 200
    return r.json()


# ── Transcript ─────────────────────────────────────────────────────

def test_transcript_route_returns_empty_for_fresh_encounter(client) -> None:
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    r = client.get(f"/api/encounter/{eid}/transcript")
    assert r.status_code == 200
    body = r.json()
    assert body["encounter_id"] == eid
    assert body["transcript"] == []
    assert body["total_entries"] == 0


def test_transcript_route_returns_logged_turns(client) -> None:
    from portal import control_room
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    enc = control_room.get_active_room().encounters[eid]
    enc.log_turn(
        source="station:s1", source_label="Bed 1 tablet",
        persona_id="P-001", persona_name="Mr. Diaz",
        student_text="How are you feeling?",
        character_text="Pain is about a 6.",
        latency_ms=420,
    )
    r = client.get(f"/api/encounter/{eid}/transcript")
    body = r.json()
    assert body["total_entries"] == 2  # student + character entries
    assert body["transcript"][0]["direction"] == "student"
    assert body["transcript"][1]["direction"] == "character"
    assert body["transcript"][1]["text"] == "Pain is about a 6."


def test_transcript_route_404s_on_unknown_encounter(client) -> None:
    _start_room(client, n=1)
    r = client.get("/api/encounter/encounter_xyz/transcript")
    assert r.status_code == 404


# ── Voices ────────────────────────────────────────────────────────

def test_voices_route_round_trip(client) -> None:
    from portal import control_room
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    # Add a second persona so we have something to assign.
    room = control_room.get_active_room()
    room.encounters[eid].selected_personas = ["P-001", "P-004"]

    # GET — initial state has empty voice_assignments.
    body = client.get(f"/api/encounter/{eid}/voices").json()
    assert body["voice_assignments"] == {}
    assert "P-001" in body["selected_personas"]

    # POST — assign two voices.
    r = client.post(f"/api/encounter/{eid}/voices", json={
        "P-001": "voice-mr-diaz-1",
        "P-004": "voice-charge-rn-1",
    })
    assert r.status_code == 200
    assert r.json()["voice_assignments"]["P-001"] == "voice-mr-diaz-1"

    # POST null to clear one.
    r = client.post(f"/api/encounter/{eid}/voices",
                     json={"P-001": None})
    assert r.status_code == 200
    body = r.json()
    assert "P-001" not in body["voice_assignments"]
    assert body["voice_assignments"]["P-004"] == "voice-charge-rn-1"


def test_voices_route_requires_instructor(client) -> None:
    from portal import auth, credentials
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    # Re-cookie as observer.
    vault = credentials.unlock(TEST_PASSWORD)
    client.cookies.set(auth.COOKIE_NAME,
                        auth.issue_session_token(vault, role="observer"))
    r = client.post(f"/api/encounter/{eid}/voices",
                     json={"P-001": "any-voice"})
    assert r.status_code == 403


# ── Lead student ──────────────────────────────────────────────────

def test_lead_student_set_and_clear(client) -> None:
    from portal import control_room
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    room_code = control_room.get_active_room().room_code

    # Register a bedside student.
    r = client.post("/portal/students/register", data={
        "room_code": room_code, "encounter_id": eid,
        "display_name": "Alice Pham",
    })
    sid = r.json()["student_id"]

    # GET — lead unset.
    body = client.get(f"/api/encounter/{eid}/lead_student").json()
    assert body["lead_student_id"] is None
    assert body["lead_student_name"] is None
    # Roster surfaces Alice + her assignment.
    assert any(s["student_id"] == sid and s["assigned_to_this"]
               for s in body["roster"])

    # POST — set Alice as lead.
    r = client.post(f"/api/encounter/{eid}/lead_student",
                     json={"lead_student_id": sid})
    assert r.status_code == 200
    body = r.json()
    assert body["lead_student_id"] == sid
    assert body["lead_student_name"] == "Alice Pham"
    # Persists on the in-memory encounter.
    enc = control_room.get_active_room().encounters[eid]
    assert enc.lead_student_id == sid

    # GET again — surfaces.
    body = client.get(f"/api/encounter/{eid}/lead_student").json()
    assert body["lead_student_id"] == sid

    # Clear.
    r = client.post(f"/api/encounter/{eid}/lead_student",
                     json={"lead_student_id": None})
    assert r.status_code == 200
    assert r.json()["lead_student_id"] is None


def test_lead_student_route_404s_on_unknown_student(client) -> None:
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    r = client.post(f"/api/encounter/{eid}/lead_student",
                     json={"lead_student_id": "stu_does_not_exist"})
    assert r.status_code == 404


def test_lead_student_roster_excludes_nurse_station_students(client) -> None:
    """Nurse-station students don't lead a bed."""
    from portal import control_room
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    room_code = control_room.get_active_room().room_code
    # Add 1 bedside + 1 nurse-station.
    client.post("/portal/students/register", data={
        "room_code": room_code, "encounter_id": eid, "display_name": "Bedside",
    })
    client.post("/portal/students/register_nurse", data={
        "room_code": room_code, "display_name": "Charge Nurse",
    })
    body = client.get(f"/api/encounter/{eid}/lead_student").json()
    names = [s["display_name"] for s in body["roster"]]
    assert "Bedside" in names
    assert "Charge Nurse" not in names


# ── /api/room/state surfaces lead + console_url ──────────────────────

def test_room_state_carries_lead_student_and_console_url(client) -> None:
    from portal import control_room
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    room_code = control_room.get_active_room().room_code
    r = client.post("/portal/students/register", data={
        "room_code": room_code, "encounter_id": eid, "display_name": "Pat Lin",
    })
    sid = r.json()["student_id"]
    client.post(f"/api/encounter/{eid}/lead_student",
                 json={"lead_student_id": sid})

    state = client.get("/api/room/state").json()
    enc = state["encounters"][0]
    assert enc["lead_student_id"]   == sid
    assert enc["lead_student_name"] == "Pat Lin"
    assert enc["console_url"] == f"/portal/room/encounter/{eid}"
    assert enc["station_join_url"] == f"/join?code={enc['join_code']}"


# ── Cohort debrief surfaces lead student ────────────────────────────

def test_cohort_debrief_facet_includes_lead_student_name(client) -> None:
    from portal import control_room
    body = _start_room(client, n=2)
    eid_a = body["encounters"][0]["encounter_id"]
    room_code = control_room.get_active_room().room_code
    r = client.post("/portal/students/register", data={
        "room_code": room_code, "encounter_id": eid_a,
        "display_name": "Lead A",
    })
    sid = r.json()["student_id"]
    client.post(f"/api/encounter/{eid_a}/lead_student",
                 json={"lead_student_id": sid})
    # End the room → debrief saves.
    r = client.post("/api/room/end")
    body = r.json()
    cohort_url = body["cohort_debrief_url"]
    # Pull the JSON read.
    room_id = body["room_id"]
    body = client.get(f"/api/debrief/cohort/{room_id}").json()
    facets = body["encounters"]
    bed_a = next(f for f in facets if f["session_id"] == eid_a)
    assert bed_a["lead_student_id"]   == sid
    assert bed_a["lead_student_name"] == "Lead A"
    bed_b = next(f for f in facets if f["session_id"] != eid_a)
    assert bed_b["lead_student_id"]   is None
    assert bed_b["lead_student_name"] is None
    # HTML render carries the lead pill.
    html = client.get(cohort_url).text
    assert "Lead A" in html


# ── Encounter console template wiring ────────────────────────────

def test_encounter_console_template_includes_new_cards(client) -> None:
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    r = client.get(f"/portal/room/encounter/{eid}")
    assert r.status_code == 200
    html = r.text
    # All four M30 surfaces are wired into the template.
    assert "card-lead-student"  in html
    assert "card-transcript"    in html
    assert "card-voice"         in html
    assert "btn-popout"         in html
    # The header lead banner is in the markup (hidden by default,
    # revealed when JS sets a lead).
    assert "lead-student-banner" in html
    # Link to v6 ops view per encounter for full device + medication
    # management.
    assert "/portal/control/ops?join=" in html
