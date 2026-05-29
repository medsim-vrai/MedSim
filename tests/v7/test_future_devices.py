"""Phase 7 M29 — future-device stub tests.

Four new in-sim device kinds (call_bell, bed_alarm,
code_blue_button, fire_alarm) emit alarm.injected device_events
when pressed. The M26 alarm bus surfaces them with the right
severity. Public route — bedside students can press without
operator auth.
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
        "label": "M29 stubs",
        "encounters": [
            {"scenario_name": f"Bed {i+1}", "persona_id": f"P-{i+1:03d}",
             "patient_persona_id": f"P-{i+1:03d}", "ehr_id": "helix"}
            for i in range(n)
        ],
    })
    assert r.status_code == 200
    return r.json()


def test_kinds_route_lists_four(client) -> None:
    r = client.get("/api/future_devices/kinds")
    assert r.status_code == 200
    kinds = {k["id"] for k in r.json()["kinds"]}
    assert kinds == {"call_bell", "bed_alarm",
                      "code_blue_button", "fire_alarm"}


def test_call_bell_press_appears_on_alarm_bus(client) -> None:
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    r = client.post(
        f"/api/encounter/{eid}/future_device/call_bell/press",
        json={"by": "bedside_patient"},
    )
    assert r.status_code == 200, r.text
    # Alarm bus surfaces it with severity=info (call_bell mapping).
    alarms = client.get("/api/room/alarms").json()["alarms"]
    bell_alarms = [a for a in alarms if a["kind"] == "call_bell"]
    assert len(bell_alarms) == 1
    assert bell_alarms[0]["severity"] == "info"
    assert bell_alarms[0]["encounter_id"] == eid
    assert bell_alarms[0]["source"] == "device"


def test_fire_alarm_press_appears_critical(client) -> None:
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    r = client.post(
        f"/api/encounter/{eid}/future_device/fire_alarm/press",
        json={"by": "bedside"},
    )
    assert r.status_code == 200, r.text
    alarms = client.get("/api/room/alarms").json()["alarms"]
    fire_alarms = [a for a in alarms if a["kind"] == "fire_alarm"]
    assert len(fire_alarms) == 1
    assert fire_alarms[0]["severity"] == "critical"


def test_bed_alarm_press_warning_severity(client) -> None:
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    r = client.post(
        f"/api/encounter/{eid}/future_device/bed_alarm/press",
        json={},
    )
    assert r.status_code == 200
    alarms = client.get("/api/room/alarms").json()["alarms"]
    bed = next(a for a in alarms if a["kind"] == "bed_alarm")
    assert bed["severity"] == "warning"


def test_code_blue_button_press_critical(client) -> None:
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    r = client.post(
        f"/api/encounter/{eid}/future_device/code_blue_button/press",
        json={},
    )
    assert r.status_code == 200
    alarms = client.get("/api/room/alarms").json()["alarms"]
    btn = next(a for a in alarms if a["kind"] == "code_blue_button")
    # M54 — code_blue_button promoted from "critical" to "danger" to
    # match the code.blue scene; both get top sort + near-continuous audio.
    assert btn["severity"] == "danger"


def test_unknown_kind_400s(client) -> None:
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    r = client.post(f"/api/encounter/{eid}/future_device/not_a_kind/press",
                     json={})
    assert r.status_code == 400


def test_unknown_encounter_404s(client) -> None:
    _start_room(client, n=1)
    r = client.post("/api/encounter/encounter_xyz/future_device/call_bell/press",
                     json={})
    assert r.status_code == 404


def test_no_active_room_404s(client) -> None:
    r = client.post("/api/encounter/x/future_device/call_bell/press", json={})
    assert r.status_code == 404


def test_press_pushes_ws_event(client) -> None:
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    room_code = client.get("/api/room/state").json()["room_code"]
    with client.websocket_connect(f"/ws/room/{room_code}") as ws:
        client.post(f"/api/encounter/{eid}/future_device/call_bell/press",
                     json={})
        msg = ws.receive_json()
        assert msg["type"] == "future_device_press"
        assert msg["payload"]["kind"] == "call_bell"
