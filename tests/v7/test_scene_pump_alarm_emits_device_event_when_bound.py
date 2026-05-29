"""M7 acceptance — pump.alarm scene targets a bound pump.

When a pump device station is bound to the encounter, the scene
emits a ``device_event`` of type ``alarm.injected`` on that pump.
The chart_event log stays untouched — the alarm lives in the device
event stream where ``device_events()`` reads it.

When NO pump is bound to the encounter, the scene falls back to a
chart-side ``instructor.trigger`` event so the operator still sees
a footprint in the chart. The result dict's ``category`` distinguishes
the two outcomes (``'device'`` vs ``'chart_fallback'``).
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


def test_pump_alarm_emits_device_event_when_pump_is_bound(client) -> None:
    from portal import control_room, ehr_db
    from portal.control_session import DeviceStation

    # Start a room with two encounters; bind a pump to the first one.
    r = client.post("/api/room/start", json={
        "label": "pump alarm test",
        "encounters": [
            {"scenario_name": "Bed 1 (with pump)",
             "persona_id": "P-001", "ehr_id": "helix"},
            {"scenario_name": "Bed 2 (no pump)",
             "persona_id": "P-013", "ehr_id": "helix"},
        ],
    })
    assert r.status_code == 200
    body = r.json()
    eid_with_pump = body["encounters"][0]["encounter_id"]
    eid_no_pump   = body["encounters"][1]["encounter_id"]

    # Bind a pump to encounter A directly (M4's API doesn't expose this
    # yet — devices bind via the v6 device routes — but for M7's
    # acceptance we inject the dataclass directly).
    room = control_room.get_active_room()
    enc_a = room.encounters[eid_with_pump]
    enc_a.device_stations["pump-A"] = DeviceStation(
        station_id="pump-A",
        device_kind="pump_iv",
        device_model="alaris",
        label="Bed 1 IV",
    )

    # Fire pump.alarm at A — device_event path.
    r = client.post(f"/api/encounter/{eid_with_pump}/scene", json={
        "scene": {"kind": "pump.alarm", "params": {"tone": "occlusion"}},
    })
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["ok"] is True
    assert result["kind"] == "pump.alarm"
    assert result["category"] == "device"
    assert result["station_id"] == "pump-A"
    assert isinstance(result["device_event_id"], int)

    # device_event log has the alarm row; chart_event log does NOT.
    chart_events = ehr_db.events(eid_with_pump)
    assert len(chart_events) == 0
    device_events = ehr_db.device_events(session_id=eid_with_pump)
    assert len(device_events) == 1
    dev = device_events[0]
    assert dev["type"] == "alarm.injected"
    assert dev["station_id"] == "pump-A"
    assert dev["payload"]["tone"] == "occlusion"
    assert dev["payload"]["source"] == "scene"
    assert dev["payload"]["scene_kind"] == "pump.alarm"

    # Fire pump.alarm at B (no pump bound) — chart_fallback path.
    r = client.post(f"/api/encounter/{eid_no_pump}/scene", json={
        "scene": {"kind": "pump.alarm", "params": {"tone": "occlusion"}},
    })
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["category"] == "chart_fallback"
    assert len(result["event_ids"]) == 1

    chart_events_b = ehr_db.events(eid_no_pump)
    device_events_b = ehr_db.device_events(session_id=eid_no_pump)
    assert len(chart_events_b) == 1
    assert len(device_events_b) == 0
    fallback = chart_events_b[0]
    assert fallback["type"] == "instructor.trigger"
    assert fallback["payload"]["fallback_reason"] == "no pump bound to this encounter"


def test_pump_alarm_does_not_alarm_cabinets(client) -> None:
    """Only IV / enteral pumps get the alarm — cabinets are a separate
    device kind and a pump-alarm scene should fall back even when a
    cabinet is bound."""
    from portal import control_room, ehr_db
    from portal.control_session import DeviceStation

    r = client.post("/api/room/start", json={
        "label": "cabinet only",
        "encounters": [
            {"scenario_name": "Bed 1", "persona_id": "P-001", "ehr_id": "helix"},
        ],
    })
    assert r.status_code == 200
    eid = r.json()["encounters"][0]["encounter_id"]
    enc = control_room.get_active_room().encounters[eid]
    enc.device_stations["cab-A"] = DeviceStation(
        station_id="cab-A",
        device_kind="cabinet",
        device_model="pyxis",
        label="Cart A",
    )

    r = client.post(f"/api/encounter/{eid}/scene", json={
        "scene": {"kind": "pump.alarm"},
    })
    assert r.status_code == 200
    assert r.json()["category"] == "chart_fallback"
    assert ehr_db.device_events(session_id=eid) == []
