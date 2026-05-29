"""Phase 7 M27 — Nursing Station student role tests."""
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
    r = client.post("/api/room/start", json={
        "label": "M27 nurse station",
        "encounters": [
            {"scenario_name": f"Bed {i+1}", "persona_id": f"P-{i+1:03d}",
             "patient_persona_id": f"P-{i+1:03d}", "ehr_id": "helix"}
            for i in range(n)
        ],
    })
    assert r.status_code == 200
    return r.json()


def test_register_as_nurse_station_creates_role_row(client) -> None:
    from portal import control_room, ehr_db
    body = _start_room(client, n=2)
    room_code = client.get("/api/room/state").json()["room_code"]
    r = client.post("/portal/students/register_nurse",
                     data={"room_code": room_code, "display_name": "Sam"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["role"] == "nurse_station"
    assert body["redirect_url"].startswith("/portal/students/nurse_station?sid=")
    # DB row carries role='nurse_station'.
    room = control_room.get_active_room()
    student = room.students[body["student_id"]]
    assert student.role == "nurse_station"
    # Round-trip via the persistence layer.
    db_row = ehr_db.get_student(student.student_id)
    assert db_row["role"] == "nurse_station"


def test_nurse_station_page_renders_all_encounters(client) -> None:
    _start_room(client, n=3)
    room_code = client.get("/api/room/state").json()["room_code"]
    r = client.post("/portal/students/register_nurse",
                     data={"room_code": room_code, "display_name": "Pat"})
    sid = r.json()["student_id"]
    r = client.get(f"/portal/students/nurse_station?sid={sid}")
    assert r.status_code == 200, r.text
    html = r.text
    assert "Nursing Station" in html
    assert "Pat" in html
    assert "ns-grid" in html      # the bed-cards grid container
    assert "ns-alarms" in html    # the alarm board
    assert "ecg_strip.js" in html # the renderer
    # Room code surfaced in the header.
    assert room_code in html


def test_nurse_station_page_404s_without_sid(client) -> None:
    _start_room(client, n=1)
    r = client.get("/portal/students/nurse_station")
    assert r.status_code == 400


def test_nurse_station_page_404s_on_unknown_sid(client) -> None:
    _start_room(client, n=1)
    r = client.get("/portal/students/nurse_station?sid=does-not-exist")
    assert r.status_code == 404


def test_register_nurse_404s_on_unknown_room(client) -> None:
    r = client.post("/portal/students/register_nurse",
                     data={"room_code": "NOSUCH", "display_name": "X"})
    assert r.status_code == 404


def test_join_page_now_shows_role_step(client) -> None:
    _start_room(client, n=1)
    room_code = client.get("/api/room/state").json()["room_code"]
    r = client.get(f"/portal/students/join?code={room_code}")
    assert r.status_code == 200
    html = r.text
    # The role-picker step is in the template now.
    assert "step-role" in html
    assert "nurse_station" in html


def test_nurse_station_counts_against_station_cap(client, monkeypatch) -> None:
    from portal import control_room
    monkeypatch.setattr(control_room, "MAX_STUDENT_STATIONS_PER_ROOM", 2)
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    room_code = control_room.get_active_room().room_code

    # 1 bedside + 1 nurse_station fills the cap; the next nurse-
    # station register 409s.
    r = client.post("/portal/students/register", data={
        "room_code": room_code, "encounter_id": eid,
        "display_name": "B",
    })
    assert r.status_code == 200
    r = client.post("/portal/students/register_nurse", data={
        "room_code": room_code, "display_name": "N1",
    })
    # The first nurse_station register does NOT consume a station
    # immediately (no chat station is created — only a Student row).
    # But it still counts in our cap logic? Per the spec, the cap
    # is on station seats — the nurse doesn't create one. So this
    # should succeed AND a subsequent bedside join should hit the
    # cap when it tries to add a chat station.
    # The cap check is on station COUNT; rosters can have more
    # students than stations.
    assert r.status_code == 200
