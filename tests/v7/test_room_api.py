"""M4 acceptance — the new room HTTP API surface.

Exercises the 8 new routes added to ``portal/server.py``:

  POST /api/room/start                            create N encounters
  GET  /api/room/state                            aggregate poll body
  POST /api/room/freeze_all                       pause each encounter
  POST /api/room/resume_all                       inverse
  POST /api/room/end                              end + clear singleton
  POST /api/room/scene_broadcast                  scene → N encounters
  POST /api/encounter/{id}/scene                  scene → one encounter
  POST /api/encounter/{id}/assign_students        re-roster

Each test stands up an isolated FastAPI TestClient, redirects HOME to
a sandbox so the real vault isn't touched, and authenticates via the
operator login flow.

This file consolidates the five "tests/v7/test_api_*" names from the
Development Plan into one module (one app boot, faster, easier to
read). The acceptance criteria from M4's spec are mapped 1:1 to the
top-level functions below.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


TEST_PASSWORD = "test_passwd_xyz_8chars"


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    """Sandboxed TestClient. Each test gets a clean room singleton and
    a tmp HOME / vault so the operator's real machine state is
    untouched."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)

    from portal import (
        auth, control_room, credentials, voices as _voices,
    )
    # Redirect credentials VAULT_PATH to the sandbox (it was bound at
    # module import time to the real ~/.medsim/vault.enc).
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
    vault.set("ELEVENLABS_API_KEY", "")  # explicit empty so /api/voices is offline

    from portal import server
    from fastapi.testclient import TestClient
    c = TestClient(server.app)
    c.cookies.set(auth.COOKIE_NAME, auth.issue_session_token(vault))
    yield c
    control_room._reset_for_tests()


def _start_room(client, n: int = 2, label: str = "Test Room") -> dict[str, Any]:
    """Helper: start a room with n encounters and return the response body."""
    entries = [
        {
            "scenario_name": f"Bed {i + 1} — patient {i + 1}",
            "persona_id":    f"P-{i + 1:03d}",
            "ehr_id":        "helix",
            "chart_mode":    "shared",
        }
        for i in range(n)
    ]
    r = client.post("/api/room/start",
                     json={"label": label, "encounters": entries})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert len(body["encounters"]) == n
    return body


def test_api_room_start_creates_room_with_n_encounters(client) -> None:
    body = _start_room(client, n=3, label="Triple")
    assert body["room_code"]
    # Distinct encounter ids and distinct join codes.
    eids = [e["encounter_id"] for e in body["encounters"]]
    jcs  = [e["join_code"]    for e in body["encounters"]]
    assert len(set(eids)) == 3
    assert len(set(jcs))  == 3
    # /api/room/state immediately reflects the new room.
    r = client.get("/api/room/state")
    assert r.status_code == 200
    state = r.json()
    assert state["room_id"] == body["room_id"]
    assert state["status"] == "active"
    assert len(state["encounters"]) == 3


def test_api_room_freeze_all_pauses_each_encounter(client) -> None:
    _start_room(client, n=2)
    r = client.post("/api/room/freeze_all")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["status"] == "frozen"
    assert body["encounter_count"] == 2
    # Each encounter's state in /api/room/state shows paused.
    state = client.get("/api/room/state").json()
    assert state["status"] == "frozen"
    assert all(e["state"] == "paused" for e in state["encounters"])


def test_api_room_resume_all_restores_state(client) -> None:
    _start_room(client, n=2)
    # Move encounters to running first (they default to 'configured').
    from portal import control_room
    for enc in control_room.get_active_room().encounters.values():
        enc.state = "running"
    client.post("/api/room/freeze_all")
    r = client.post("/api/room/resume_all")
    assert r.status_code == 200, r.text
    state = client.get("/api/room/state").json()
    assert state["status"] == "active"
    assert all(e["state"] == "running" for e in state["encounters"])


def test_api_room_state_returns_per_encounter_summary(client) -> None:
    body = _start_room(client, n=2)
    r = client.get("/api/room/state")
    assert r.status_code == 200
    state = r.json()
    # Aggregate fields
    assert state["room_code"] == body["room_code"]
    assert state["label"] == "Test Room"
    assert isinstance(state["created_at"], (int, float))
    # Per-encounter rows
    assert len(state["encounters"]) == 2
    first = state["encounters"][0]
    expected_fields = {
        "encounter_id", "join_code", "label", "scenario_name",
        "patient_persona_id", "state", "chart_mode", "ehr_id",
        "chat_stations", "ehr_stations", "device_stations",
        "chart_event_count", "assigned_student_ids", "last_event_ts",
    }
    assert expected_fields <= set(first.keys())
    # Initial counts are zero.
    assert first["chart_stations" if False else "chart_event_count"] == 0
    assert first["chat_stations"] == 0
    assert first["ehr_stations"] == 0


def test_api_scene_broadcast_writes_chart_event_per_target(client) -> None:
    """The scene broadcast must persist one chart_event per targeted
    encounter, never bleed across encounters. With M7 wiring, a
    vitals.drop scene writes a `vitals.record` event (not the M4 stub
    `instructor.trigger`)."""
    from portal import ehr_db
    body = _start_room(client, n=3)
    eids = [e["encounter_id"] for e in body["encounters"]]
    # Targeted broadcast: hit the first two only.
    r = client.post("/api/room/scene_broadcast", json={
        "scene": {"kind": "vitals.drop",
                  "params": {"sbp": 72, "hr": 138}},
        "targets": eids[:2],
    })
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["ok"] is True
    assert payload["fired"] == 2
    # ehr_db.events confirms persistence per encounter.
    events_a = ehr_db.events(eids[0])
    events_b = ehr_db.events(eids[1])
    events_c = ehr_db.events(eids[2])
    assert len(events_a) == 1
    assert len(events_b) == 1
    assert len(events_c) == 0
    # M7 scenes engine wrote a real vitals.record, not the M4 stub.
    assert events_a[0]["type"] == "vitals.record"
    assert events_a[0]["payload"]["scene_kind"] == "vitals.drop"
    assert events_a[0]["payload"]["source"] == "scene"
    assert events_a[0]["payload"]["sbp"] == 72
    # Broadcast to "all" hits every encounter (including the previously
    # untouched one).
    r = client.post("/api/room/scene_broadcast", json={
        "scene": {"kind": "lab.result",
                  "params": {"panel": "BMP", "values": {"k": 5.4}}},
        "targets": "all",
    })
    assert r.status_code == 200
    assert r.json()["fired"] == 3
    assert len(ehr_db.events(eids[2])) == 1


def test_api_encounter_scene_targets_one_encounter(client) -> None:
    from portal import ehr_db
    body = _start_room(client, n=2)
    a, b = body["encounters"][0]["encounter_id"], body["encounters"][1]["encounter_id"]
    r = client.post(f"/api/encounter/{a}/scene", json={
        "scene": {"kind": "family.arrives",
                  "params": {"who": "daughter"}},
    })
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    assert len(ehr_db.events(a)) == 1
    assert len(ehr_db.events(b)) == 0


def test_api_room_end_clears_singleton_and_404s_subsequent_state(client) -> None:
    _start_room(client, n=2)
    r = client.post("/api/room/end")
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    # Subsequent state hit 404s.
    r = client.get("/api/room/state")
    assert r.status_code == 404


def test_api_encounter_assign_students_replaces_roster(client) -> None:
    body = _start_room(client, n=2)
    eid = body["encounters"][0]["encounter_id"]
    # Manually register students via the in-process ControlRoom (the
    # public /portal/students/register route is M9; we exercise the
    # M4 route on top of the existing roster API).
    from portal import control_room as _cr
    room = _cr.get_active_room()
    s1 = room.add_student("Alice")
    s2 = room.add_student("Bob")
    s3 = room.add_student("Cara")
    # Assign s1 + s2 to encounter A.
    r = client.post(f"/api/encounter/{eid}/assign_students",
                     json={"student_ids": [s1.student_id, s2.student_id]})
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["ok"] is True
    assert set(payload["assigned_student_ids"]) == {s1.student_id, s2.student_id}
    # Re-roster: now just s3 — s1 and s2 lose their encounter binding.
    r = client.post(f"/api/encounter/{eid}/assign_students",
                     json={"student_ids": [s3.student_id]})
    assert r.status_code == 200, r.text
    assert r.json()["assigned_student_ids"] == [s3.student_id]
    # Sweep behavior: previously-bound students get their
    # assigned_encounter_id cleared.
    assert room.students[s1.student_id].assigned_encounter_id is None
    assert room.students[s2.student_id].assigned_encounter_id is None
    assert room.students[s3.student_id].assigned_encounter_id == eid


def test_api_room_routes_404_when_no_room(client) -> None:
    # No room started — every room-aggregate route returns 404.
    assert client.get("/api/room/state").status_code == 404
    assert client.post("/api/room/freeze_all").status_code == 404
    assert client.post("/api/room/resume_all").status_code == 404
    assert client.post("/api/room/end").status_code == 404
    assert client.post("/api/room/scene_broadcast",
                       json={"scene": {}, "targets": "all"}).status_code == 404


def test_api_encounter_routes_404_on_unknown_encounter(client) -> None:
    _start_room(client, n=1)
    r = client.post("/api/encounter/does-not-exist/scene",
                     json={"scene": {"kind": "noop"}})
    assert r.status_code == 404
    r = client.post("/api/encounter/does-not-exist/assign_students",
                     json={"student_ids": []})
    assert r.status_code == 404
