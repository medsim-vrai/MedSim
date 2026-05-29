"""M19 acceptance — capacity caps.

The v1 deployment scale is one classroom: 10 concurrent encounters,
24 student stations. Beyond those, the system fails closed (409)
with a clear message. The dashboard's /api/room/state payload
includes a `capacity` block surfacing current/max for both
dimensions.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from portal import control_room
from portal.control_session import ControlSession


@pytest.fixture(autouse=True)
def _reset():
    control_room._reset_for_tests()
    yield
    control_room._reset_for_tests()


TEST_PASSWORD = "test_passwd_xyz_8chars"


def test_add_encounter_blocks_11th_at_data_layer() -> None:
    room = control_room.create_room()
    for i in range(control_room.MAX_ENCOUNTERS_PER_ROOM):
        room.add_encounter(ControlSession(
            id=f"e{i}", join_code=f"JC0000{i}",
            scenario_name=f"Bed {i}", api_key=""))
    assert len(room.encounters) == control_room.MAX_ENCOUNTERS_PER_ROOM
    with pytest.raises(control_room.CapacityExceeded) as exc_info:
        room.add_encounter(ControlSession(
            id="overflow", join_code="OVERFL",
            scenario_name="Too many", api_key=""))
    assert "capacity reached" in str(exc_info.value).lower()


def test_count_student_stations_sums_across_encounters() -> None:
    room = control_room.create_room()
    e1 = room.add_encounter(ControlSession(
        id="e1", join_code="JC11111", scenario_name="A", api_key=""))
    e2 = room.add_encounter(ControlSession(
        id="e2", join_code="JC22222", scenario_name="B", api_key=""))
    e1.add_station("s1")
    e1.add_station("s2")
    e2.add_station("s3")
    assert control_room._count_student_stations(room) == 3


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    from portal import (
        auth, credentials, voices as _voices,
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


def test_api_room_start_blocks_11_encounter_room(client) -> None:
    encounters = [
        {"scenario_name": f"Bed {i+1}", "persona_id": f"P-{i+1:03d}",
         "patient_persona_id": f"P-{i+1:03d}", "ehr_id": "helix"}
        for i in range(11)   # 11 > MAX_ENCOUNTERS_PER_ROOM (10)
    ]
    r = client.post("/api/room/start",
                     json={"label": "Too many", "encounters": encounters})
    assert r.status_code == 409
    assert "capacity reached" in r.json()["detail"].lower()


def test_api_room_state_includes_capacity_block(client) -> None:
    r = client.post("/api/room/start", json={
        "label": "Capacity probe",
        "encounters": [{"scenario_name": "Bed 1", "persona_id": "P-001",
                         "patient_persona_id": "P-001", "ehr_id": "helix"}],
    })
    assert r.status_code == 200
    state = client.get("/api/room/state").json()
    cap = state["capacity"]
    assert cap["encounters_used"]       == 1
    assert cap["encounters_max"]        == control_room.MAX_ENCOUNTERS_PER_ROOM
    assert cap["student_stations_used"] == 0
    assert cap["student_stations_max"]  == control_room.MAX_STUDENT_STATIONS_PER_ROOM


def test_student_station_cap_blocks_25th_join(client, monkeypatch) -> None:
    # Drop the cap so we don't have to register 25 fake students.
    monkeypatch.setattr(control_room, "MAX_STUDENT_STATIONS_PER_ROOM", 3)
    r = client.post("/api/room/start", json={
        "label": "Station cap",
        "encounters": [{"scenario_name": "Bed", "persona_id": "P-001",
                         "patient_persona_id": "P-001", "ehr_id": "helix"}],
    })
    room_code = client.get("/api/room/state").json()["room_code"]
    eid = client.get("/api/room/state").json()["encounters"][0]["encounter_id"]
    for name in ("A", "B", "C"):
        r = client.post("/portal/students/register", data={
            "room_code": room_code, "encounter_id": eid, "display_name": name,
        })
        assert r.status_code == 200
    # 4th join exceeds the cap.
    r = client.post("/portal/students/register", data={
        "room_code": room_code, "encounter_id": eid, "display_name": "D",
    })
    assert r.status_code == 409
    assert "room is full" in r.json()["detail"].lower()


def test_room_state_capacity_updates_as_students_join(client) -> None:
    r = client.post("/api/room/start", json={
        "label": "Live capacity",
        "encounters": [{"scenario_name": "Bed", "persona_id": "P-001",
                         "patient_persona_id": "P-001", "ehr_id": "helix"}],
    })
    room_code = client.get("/api/room/state").json()["room_code"]
    eid = client.get("/api/room/state").json()["encounters"][0]["encounter_id"]
    for name in ("X", "Y"):
        r = client.post("/portal/students/register", data={
            "room_code": room_code, "encounter_id": eid, "display_name": name,
        })
        assert r.status_code == 200
    state = client.get("/api/room/state").json()
    assert state["capacity"]["student_stations_used"] == 2
