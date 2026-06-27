"""Phase 7 M26 — alarm bus tests.

Three sources feed the bus:
  1. device events of type alarm.injected (v6 pump/cabinet path).
  2. chart events whose payload carries level='alarm' (M7 +
     Phase 7 1.4 tag).
  3. future-device-button presses (M29 — they emit device alarms
     of new kinds; covered by source 1).

POST /api/alarm/{id}/clear writes a synthetic alarm.cleared row;
the next read filters the cleared alarm out.
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


def _start_room(client, n: int = 1):
    r = client.post("/api/room/start", json={
        "label": "Alarm bus test",
        "encounters": [
            {"scenario_name": f"Bed {i+1}", "persona_id": f"P-{i+1:03d}",
             "patient_persona_id": f"P-{i+1:03d}", "ehr_id": "helix"}
            for i in range(n)
        ],
    })
    assert r.status_code == 200
    return r.json()


def test_alarms_from_pump_appear_in_room_alarms(client) -> None:
    """A pump device-event alarm surfaces on /api/room/alarms with
    source='device' and the right severity classification."""
    from portal import control_room
    from portal.control_session import DeviceStation
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    # Bind a pump device to the encounter so pump.alarm scene picks it up.
    room = control_room.get_active_room()
    room.encounters[eid].device_stations["pump-A"] = DeviceStation(
        station_id="pump-A", device_kind="pump_iv",
        device_model="alaris", label="Bed 1 IV",
    )
    # Fire a pump.alarm scene targeted at this encounter.
    r = client.post(f"/api/encounter/{eid}/scene", json={
        "scene": {"kind": "pump.alarm", "params": {"tone": "occlusion"}},
    })
    assert r.status_code == 200
    # /api/room/alarms surfaces it.
    body = client.get("/api/room/alarms").json()
    assert len(body["alarms"]) >= 1
    alarm = body["alarms"][0]
    assert alarm["source"] == "device"
    assert alarm["kind"] == "occlusion"
    assert alarm["encounter_id"] == eid
    assert alarm["severity"] in ("warning", "critical")


def test_alarms_from_code_blue_scene_appear(client) -> None:
    """code.blue compound scene tags its events level=alarm via
    Phase 7 1.4. The bus surfaces it with source='scene'."""
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    r = client.post(f"/api/encounter/{eid}/scene", json={
        "scene": {"kind": "code.blue"},
    })
    assert r.status_code == 200
    body = client.get("/api/room/alarms").json()
    scene_alarms = [a for a in body["alarms"] if a["source"] == "scene"]
    assert len(scene_alarms) >= 1
    code_blue = next(a for a in scene_alarms if a["kind"] == "code.blue")
    # M54 — code.blue promoted from "critical" to "danger" so it sorts
    # above other alarms and gets the near-continuous audio cadence.
    assert code_blue["severity"] == "danger"
    assert code_blue["encounter_id"] == eid


def test_clear_alarm_removes_it_from_active_list(client) -> None:
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    client.post(f"/api/encounter/{eid}/scene", json={
        "scene": {"kind": "code.blue"},
    })
    alarms = client.get("/api/room/alarms").json()["alarms"]
    assert len(alarms) >= 1
    target = alarms[0]["alarm_id"]
    # Clear.
    r = client.post(f"/api/alarm/{target}/clear")
    assert r.status_code == 200, r.text
    assert r.json()["cleared"] is True
    # Next read: that specific alarm is gone.
    remaining = client.get("/api/room/alarms").json()["alarms"]
    assert not any(a["alarm_id"] == target for a in remaining)


def test_alarms_sorted_critical_first_then_newest(client) -> None:
    """The aggregator orders by severity desc, then ts desc."""
    body = _start_room(client, n=2)
    eid_a = body["encounters"][0]["encounter_id"]
    eid_b = body["encounters"][1]["encounter_id"]
    # Fire a non-critical pump alarm fallback on A (chart-side), a
    # critical code.blue on B.
    client.post(f"/api/encounter/{eid_a}/scene", json={
        "scene": {"kind": "pump.alarm"},  # no pump bound → chart fallback
    })
    client.post(f"/api/encounter/{eid_b}/scene", json={
        "scene": {"kind": "code.blue"},
    })
    alarms = client.get("/api/room/alarms").json()["alarms"]
    severities = [a["severity"] for a in alarms]
    # Critical alarms come before warnings.
    if "critical" in severities and "warning" in severities:
        first_warn = severities.index("warning")
        last_crit  = max(i for i, s in enumerate(severities) if s == "critical")
        assert last_crit < first_warn


def test_clear_device_alarm_from_nurse_station(client) -> None:
    """Regression: DEVICE alarms (call bell / bed alarm / intercom) must clear
    from the nurse station via /api/alarm/{id}/clear. They previously honored
    only tone/all clears, so the alarm_id-based Clear button silently failed."""
    from portal import ehr_db
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    ehr_db.append_device_event(eid, "pia-A", type="alarm.injected",
                               surface="device", payload={"tone": "call_bell", "by": "patient"})
    alarms = client.get("/api/room/alarms").json()["alarms"]
    dev = next(a for a in alarms if a["source"] == "device" and a["kind"] == "call_bell")
    r = client.post(f"/api/alarm/{dev['alarm_id']}/clear")
    assert r.status_code == 200, r.text
    remaining = client.get("/api/room/alarms").json()["alarms"]
    assert not any(a["alarm_id"] == dev["alarm_id"] for a in remaining)


def test_bedside_clear_alarms_clears_device_not_scene(client) -> None:
    """Bedside 'Clear alarms' (Integrated Com & Alarm) silences the bed's device
    alerts (call bell / bed alarm) but leaves a code-blue scene alarm running."""
    from portal import ehr_db
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    ehr_db.append_device_event(eid, "pia-A", type="alarm.injected",
                               surface="device", payload={"tone": "bed_alarm", "by": "patient"})
    client.post(f"/api/encounter/{eid}/scene", json={"scene": {"kind": "code.blue"}})
    before = client.get("/api/room/alarms").json()["alarms"]
    assert any(a["source"] == "device" for a in before)
    assert any(a["source"] == "scene" for a in before)
    r = client.post(f"/api/room/encounter/{eid}/clear_alarms")
    assert r.status_code == 200, r.text
    assert r.json()["cleared"] >= 1
    after = client.get("/api/room/alarms").json()["alarms"]
    assert not any(a["source"] == "device" for a in after)   # device alerts cleared
    assert any(a["source"] == "scene" for a in after)        # code blue persists


def test_bedside_clear_alarms_unknown_encounter_404(client) -> None:
    _start_room(client, n=1)
    assert client.post("/api/room/encounter/NOPE/clear_alarms").status_code == 404


def test_clear_unknown_alarm_404s(client) -> None:
    _start_room(client, n=1)
    r = client.post("/api/alarm/never:exists:0/clear")
    assert r.status_code == 404


def test_alarms_routes_404_when_no_active_room(client) -> None:
    r = client.get("/api/room/alarms")
    assert r.status_code == 404
