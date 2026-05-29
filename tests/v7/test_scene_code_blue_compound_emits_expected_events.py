"""M7 acceptance — code.blue is a compound scene.

Firing code.blue at an encounter emits, in order:
  1. ``vitals.record``    — crash vitals (HR 40, SBP 60, SpO2 70, etc.)
  2. ``note.save``        — "CODE BLUE — patient unresponsive" announcement
  3. ``instructor.trigger`` — a marker row carrying the scene metadata

And ONE EXTRA when a pump is bound:
  4. ``device_event:alarm.injected`` — high-priority alarm on the pump

Each event carries ``compound_role`` in its payload so the M14 cohort
debrief can group them visually as a single compound event.
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


def test_code_blue_without_pump_emits_three_chart_events(client) -> None:
    from portal import ehr_db

    r = client.post("/api/room/start", json={
        "label": "code blue test",
        "encounters": [{"scenario_name": "Bed 1", "persona_id": "P-001",
                         "ehr_id": "helix"}],
    })
    assert r.status_code == 200
    eid = r.json()["encounters"][0]["encounter_id"]

    r = client.post(f"/api/encounter/{eid}/scene", json={
        "scene": {"kind": "code.blue"},
    })
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["ok"] is True
    assert result["kind"] == "code.blue"
    assert result["category"] == "compound"
    assert len(result["event_ids"]) == 3
    assert result["device_event_id"] is None  # no pump bound

    chart_events = ehr_db.events(eid)
    assert len(chart_events) == 3
    types = [e["type"] for e in chart_events]
    assert types == ["vitals.record", "note.save", "instructor.trigger"]

    # Compound roles tag each event.
    roles = [e["payload"].get("compound_role") for e in chart_events]
    assert roles == ["crash_vitals", "code_announcement", "marker"]

    # Crash vitals look like an arrest, not a normal vitals reading.
    crash = chart_events[0]["payload"]
    assert crash["hr"] <= 50
    assert crash["sbp"] <= 70
    assert crash["spo2"] <= 75
    # Announcement note text contains CODE BLUE.
    note_body = chart_events[1]["payload"]["body"]
    assert "CODE BLUE" in note_body
    # Marker payload carries the scene reference.
    marker_payload = chart_events[2]["payload"]
    assert marker_payload["scene"]["kind"] == "code.blue"

    # No device events without a bound pump.
    assert ehr_db.device_events(session_id=eid) == []


def test_code_blue_with_pump_also_emits_alarm(client) -> None:
    from portal import control_room, ehr_db
    from portal.control_session import DeviceStation

    r = client.post("/api/room/start", json={
        "label": "code blue + pump",
        "encounters": [{"scenario_name": "Bed 1", "persona_id": "P-001",
                         "ehr_id": "helix"}],
    })
    assert r.status_code == 200
    eid = r.json()["encounters"][0]["encounter_id"]
    enc = control_room.get_active_room().encounters[eid]
    enc.device_stations["pump-A"] = DeviceStation(
        station_id="pump-A", device_kind="pump_iv",
        device_model="alaris", label="Bed 1 IV",
    )

    r = client.post(f"/api/encounter/{eid}/scene", json={
        "scene": {"kind": "code.blue"},
    })
    assert r.status_code == 200, r.text
    result = r.json()
    assert len(result["event_ids"]) == 3
    assert isinstance(result["device_event_id"], int)

    # 3 chart events + 1 device event.
    assert len(ehr_db.events(eid)) == 3
    dev_events = ehr_db.device_events(session_id=eid)
    assert len(dev_events) == 1
    alarm = dev_events[0]
    assert alarm["type"] == "alarm.injected"
    assert alarm["payload"]["tone"] == "high_priority"
    assert alarm["payload"]["scene_kind"] == "code.blue"
    assert alarm["payload"]["compound_role"] == "pump_alarm"


def test_code_blue_via_room_broadcast_fires_each_encounter(client) -> None:
    """The room-broadcast path applies the compound to every targeted
    encounter, persisting the same three chart events per encounter."""
    from portal import ehr_db

    r = client.post("/api/room/start", json={
        "label": "broadcast code blue",
        "encounters": [
            {"scenario_name": "Bed 1", "persona_id": "P-001", "ehr_id": "helix"},
            {"scenario_name": "Bed 2", "persona_id": "P-013", "ehr_id": "helix"},
            {"scenario_name": "Bed 3", "persona_id": "P-005", "ehr_id": "helix"},
        ],
    })
    assert r.status_code == 200
    eids = [e["encounter_id"] for e in r.json()["encounters"]]

    r = client.post("/api/room/scene_broadcast", json={
        "scene": {"kind": "code.blue"}, "targets": "all",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["fired"] == 3
    for eid in eids:
        assert len(ehr_db.events(eid)) == 3


def test_palette_endpoint_lists_all_built_in_scenes(client) -> None:
    r = client.get("/api/scenes/palette")
    assert r.status_code == 200, r.text
    body = r.json()
    kinds = {entry["kind"] for entry in body["palette"]}
    assert {
        "vitals.drop", "vitals.rise", "lab.result", "order.new",
        "family.arrives", "pump.alarm", "code.blue", "note.instructor",
    } <= kinds
