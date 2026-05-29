"""M43 — Device routes work in multi-patient mode.

The v6 device routes used `control_session.get_active()` which
returns None in v7 multi-encounter rooms (per the M2 contract).
Every operator-facing device action 409d with "No active session"
when the operator opened the device manager from a v7 encounter
console. M43 swaps `get_active()` for:

- `_session_for_station(station)` — finds the encounter via the
  station's stored `session_id` (per-station routes: inject, clear,
  advance_time, assign).
- `_session_for_join(join)` — accepts `?join=<code>` so the
  encounter-scoped register + roster routes work (the JS appends
  `?join=` from `window.MEDSIM2_OPS.join_code`).

Also: rename "Manage devices" → "Managed devices" per operator
feedback.
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
        debrief as debrief_mod, server as server_mod,
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
    monkeypatch.setattr(server_mod, "_anthropic_runtime_key", "")
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


def _start_2enc_room(client):
    r = client.post("/api/room/start", json={
        "label": "M43 device routes",
        "encounters": [
            {"scenario_name": "Bed 1", "persona_id": "P-014",
             "patient_persona_id": "P-014",
             "personas": ["P-014"], "ehr_id": "helix"},
            {"scenario_name": "Bed 2", "persona_id": "P-003",
             "patient_persona_id": "P-003",
             "personas": ["P-003"], "ehr_id": "helix"},
        ],
    })
    assert r.status_code == 200, r.text
    return r.json()


# ── /api/device/register works with ?join in multi-patient mode ─────

def test_device_register_works_via_join_in_multi_patient(client) -> None:
    """The exact failure the operator reported: opening the device
    manager from an encounter and trying to add a device → 409
    'No active session'. After M43, with ?join=<code> the route
    resolves the encounter and the device registers cleanly."""
    body = _start_2enc_room(client)
    join = body["encounters"][0]["join_code"]
    r = client.post(
        f"/api/device/register?join={join}",
        json={"device_kind": "pump_iv", "device_model": "alaris",
              "label": "Bed 1 IV"},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["ok"] is True
    assert "station_id" in out
    # The new station is bound to the right encounter.
    from portal import control_room
    enc = control_room.get_active_room().encounters[body["encounters"][0]["encounter_id"]]
    assert out["station_id"] in enc.device_stations


def test_device_register_without_join_in_multi_patient_still_errors(client) -> None:
    """No `?join=` AND no v6 singleton → friendly 409 with the new
    hint pointing at the encounter console."""
    _start_2enc_room(client)
    r = client.post(
        "/api/device/register",
        json={"device_kind": "pump_iv", "device_model": "alaris", "label": "x"},
    )
    assert r.status_code == 409
    # The new error message points the operator at the Per-Patient
    # Console flow instead of leaving them stuck.
    assert "Per-Patient Console" in r.text or "?join=" in r.text


# ── Per-station routes resolve via station.session_id ───────────────

def _register_pump_on(client, body, bed_idx: int) -> str:
    join = body["encounters"][bed_idx]["join_code"]
    r = client.post(
        f"/api/device/register?join={join}",
        json={"device_kind": "pump_iv", "device_model": "alaris",
              "label": f"Bed {bed_idx + 1} IV"},
    )
    assert r.status_code == 200, r.text
    return r.json()["station_id"]


def test_device_inject_works_in_multi_patient_via_station_session_id(client) -> None:
    """Per-station routes don't need ?join — they look up the right
    session via the station's stored session_id. Verify inject works
    in multi-patient mode."""
    body = _start_2enc_room(client)
    sid = _register_pump_on(client, body, 0)
    r = client.post(
        f"/api/device/{sid}/inject",
        json={"tone": "low_battery"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


def test_device_clear_works_in_multi_patient(client) -> None:
    body = _start_2enc_room(client)
    sid = _register_pump_on(client, body, 0)
    # Inject one alarm first so there's something to clear.
    client.post(f"/api/device/{sid}/inject", json={"tone": "low_battery"})
    r = client.post(f"/api/device/{sid}/clear", json={"all": True})
    assert r.status_code == 200, r.text


def test_device_assign_works_in_multi_patient(client) -> None:
    body = _start_2enc_room(client)
    sid = _register_pump_on(client, body, 0)
    r = client.post(
        f"/api/device/{sid}/assign",
        json={"character_id": "P-014"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["character_id"] == "P-014"


def test_device_advance_time_works_in_multi_patient(client) -> None:
    body = _start_2enc_room(client)
    sid = _register_pump_on(client, body, 0)
    r = client.post(
        f"/api/device/{sid}/advance_time",
        json={"minutes": 5},
    )
    assert r.status_code == 200, r.text


# ── /api/device/roster scoped by ?join in multi-patient mode ────────

def test_device_roster_filters_by_join_in_multi_patient(client) -> None:
    """Two encounters each register their own pump. The roster scoped
    to bed 1's join code shows ONLY bed 1's pump."""
    body = _start_2enc_room(client)
    sid1 = _register_pump_on(client, body, 0)
    sid2 = _register_pump_on(client, body, 1)
    join1 = body["encounters"][0]["join_code"]
    r = client.get(f"/api/device/roster?join={join1}")
    assert r.status_code == 200
    stations = r.json().get("stations", [])
    station_ids = {s.get("station_id") for s in stations}
    assert sid1 in station_ids
    assert sid2 not in station_ids, (
        "roster scoped by ?join must NOT include another encounter's "
        "device stations.")


def test_device_roster_empty_when_no_session(client) -> None:
    """No active room AND no `?join` → empty roster (200), not 409."""
    r = client.get("/api/device/roster")
    assert r.status_code == 200
    assert r.json() == {"stations": []}


# ── Frontend: JS adds ?join to register + roster ─────────────────────

def test_devices_js_appends_join_query_to_register_and_roster() -> None:
    """control_ops_devices.js builds a `?join=<code>` suffix from
    `window.MEDSIM2_OPS.join_code` and appends it to register +
    roster calls. Per-station routes don't need this (they use
    station.session_id server-side)."""
    js_path = (
        Path(__file__).resolve().parents[2]
        / "portal" / "static" / "control_ops_devices.js"
    )
    src = js_path.read_text(encoding="utf-8")
    # Helper exists and reads MEDSIM2_OPS.join_code.
    assert "function _joinQuery" in src
    assert "MEDSIM2_OPS" in src and "join_code" in src
    # /api/device/roster + /api/device/register call sites include _joinQuery().
    assert "/api/device/roster' + _joinQuery()" in src
    assert "/api/device/register' + _joinQuery()" in src


# ── Button + dialog title renamed to "Managed devices" ──────────────

def test_encounter_console_button_label_renamed_to_managed_devices(client) -> None:
    body = _start_2enc_room(client)
    eid = body["encounters"][0]["encounter_id"]
    r = client.get(f"/portal/room/encounter/{eid}")
    html = r.text
    assert "Managed devices" in html
    # The old verb form is gone (avoid false positive — the button's
    # title attribute may still contain "manager" which is fine).
    assert "🔧 Manage devices" not in html


def test_devices_dialog_title_uses_managed_devices(client) -> None:
    body = _start_2enc_room(client)
    eid = body["encounters"][0]["encounter_id"]
    html = client.get(f"/portal/room/encounter/{eid}").text
    idx = html.find('id="devices-dialog-title"')
    assert idx >= 0
    snippet = html[idx:idx + 200]
    assert "Managed devices" in snippet
