"""M9 acceptance — student-side end-to-end join flow.

A student posts the room_code, display_name, and encounter_id to
``/portal/students/register``. The handler:
  1. Creates (or reattaches) a Student row in the M1 student table.
  2. Assigns the student to the chosen encounter.
  3. Creates a chat Station on that encounter with the encounter's
     patient persona as the conversational partner.
  4. Returns a JSON body with a ``redirect_url`` that points at the
     existing v6 chat-station UI.

This file also covers the reattach path — when a student picks their
pre-loaded roster entry, the existing Student row is reused (no
duplicate row in the DB).
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
    )
    sandbox_vault_dir = fake_home / ".medsim"
    sandbox_vault_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(credentials, "VAULT_DIR", sandbox_vault_dir)
    monkeypatch.setattr(credentials, "VAULT_PATH",
                         sandbox_vault_dir / "vault.enc")
    monkeypatch.setattr(_voices, "KEYFILE", tmp_path / "no-such.key")
    monkeypatch.setattr(_voices, "_runtime_key", "")
    control_room._reset_for_tests()

    if not credentials.is_initialized():
        credentials.initialize(TEST_PASSWORD)
    vault = credentials.unlock(TEST_PASSWORD)
    vault.set("ANTHROPIC_API_KEY", "sk-ant-dummy")
    vault.set("ELEVENLABS_API_KEY", "")

    from portal import server
    from fastapi.testclient import TestClient
    c = TestClient(server.app)
    c.cookies.set(auth.COOKIE_NAME, auth.issue_session_token(vault))
    yield c
    control_room._reset_for_tests()


def _start_room(client, n: int = 2):
    entries = [
        {"scenario_name": f"Bed {i + 1} — patient {i + 1}",
         "persona_id":    f"P-{i + 1:03d}",
         "patient_persona_id": f"P-{i + 1:03d}",
         "ehr_id":        "helix"}
        for i in range(n)
    ]
    r = client.post("/api/room/start",
                     json={"label": "M9 register test", "encounters": entries})
    assert r.status_code == 200, r.text
    return r.json()


def test_student_register_then_pick_encounter(client) -> None:
    """Full happy path — free-form student types a name, picks Bed 1,
    lands on the right /station/<jc>/<sid> URL with a Station bound to
    the encounter's patient persona."""
    from portal import control_room, ehr_db

    body = _start_room(client, n=2)
    eid_a = body["encounters"][0]["encounter_id"]
    eid_b = body["encounters"][1]["encounter_id"]
    join_a = body["encounters"][0]["join_code"]
    room_code = control_room.get_active_room().room_code

    # Note: /portal/students/register is PUBLIC — no operator cookie
    # needed. TestClient doesn't strip cookies automatically; whatever
    # we send is allowed since the route doesn't require_vault.
    r = client.post("/portal/students/register", data={
        "room_code":    room_code,
        "encounter_id": eid_a,
        "display_name": "Alice Pham",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["display_name"] == "Alice Pham"
    assert body["encounter_id"] == eid_a
    assert body["redirect_url"].startswith(f"/station/{join_a}/")
    assert body["redirect_url"].endswith(body["station_id"])

    # State assertions ────────────────────────────────────────────
    room = control_room.get_active_room()
    student_id = body["student_id"]
    # Student persisted in-memory and in DB.
    assert student_id in room.students
    assert room.students[student_id].display_name == "Alice Pham"
    assert room.students[student_id].assigned_encounter_id == eid_a
    db_rows = ehr_db.students_for_room(room.room_id)
    assert len(db_rows) == 1
    assert db_rows[0]["assigned_encounter_id"] == eid_a

    # Encounter A's roster + chat station reflect the join; encounter
    # B is untouched (isolation).
    enc_a = room.encounters[eid_a]
    enc_b = room.encounters[eid_b]
    assert student_id in enc_a.assigned_student_ids
    assert body["station_id"] in enc_a.stations
    station = enc_a.stations[body["station_id"]]
    # The encounter's patient persona is the chat partner.
    assert station.persona_id == enc_a.patient_persona_id == "P-001"
    assert enc_b.stations == {}
    assert enc_b.assigned_student_ids == []


def test_student_pick_existing_roster_entry_reattaches(client) -> None:
    """Operator pre-loaded the roster (e.g. via a future bulk import).
    The student picks their existing entry — POST carries
    ``existing_student_id``. No duplicate row is created."""
    from portal import control_room, ehr_db

    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    room = control_room.get_active_room()
    pre_loaded = room.add_student("Bob Lin")
    assert pre_loaded.assigned_encounter_id is None  # not yet assigned

    r = client.post("/portal/students/register", data={
        "room_code":           room.room_code,
        "encounter_id":        eid,
        "display_name":        "Bob Lin",
        "existing_student_id": pre_loaded.student_id,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["student_id"] == pre_loaded.student_id

    # No duplicate: exactly one row in the DB.
    rows = ehr_db.students_for_room(room.room_id)
    assert len(rows) == 1
    assert rows[0]["student_id"] == pre_loaded.student_id
    assert rows[0]["assigned_encounter_id"] == eid


def test_student_join_page_renders_room_state(client) -> None:
    """GET /portal/students/join?code=<ROOM_CODE> shows the room's
    encounter cards and any pre-loaded roster."""
    from portal import control_room

    _start_room(client, n=3)
    room = control_room.get_active_room()
    room.add_student("Roster Rita")
    room.add_student("Roster Sam")

    r = client.get(f"/portal/students/join?code={room.room_code}")
    assert r.status_code == 200, r.text
    html = r.text
    assert room.room_code in html
    # All 3 encounters rendered.
    for enc in room.encounters.values():
        assert enc.join_code in html
        assert (enc.encounter_label or enc.scenario_name) in html
    # Roster names present.
    assert "Roster Rita" in html
    assert "Roster Sam" in html


def test_student_register_rejects_blank_display_name(client) -> None:
    """A new-student register without display_name must 400 — the
    join page validates client-side but the server is the final gate."""
    from portal import control_room

    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    room_code = control_room.get_active_room().room_code

    r = client.post("/portal/students/register", data={
        "room_code":    room_code,
        "encounter_id": eid,
        "display_name": "",  # explicit blank
    })
    assert r.status_code == 400, r.text


def test_student_register_handles_unknown_encounter_id(client) -> None:
    from portal import control_room
    _start_room(client, n=1)
    room_code = control_room.get_active_room().room_code

    r = client.post("/portal/students/register", data={
        "room_code":    room_code,
        "encounter_id": "ENC-DOES-NOT-EXIST",
        "display_name": "Alice",
    })
    assert r.status_code == 404, r.text
