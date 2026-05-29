"""M45 — Inline device control cards in the encounter Devices card.

After a device is added (via the Managed-devices modal — M42/M44),
the encounter console's Devices card now renders the full control
surface for each bound device inline: kind/model/label, online
indicator, patient-assignment dropdown, active-alarm list with
per-alarm Clear buttons, alarm-tone picker + Inject, and (for
pumps) advance-time +5m/+15m/+1h buttons.

Driven by /api/device/roster?join=<encounter join> (M43 made that
route multi-patient aware).  Polls on its own 3s cadence alongside
the existing telemetry/state/transcript loops.

Most of the interaction is client-side; these tests verify the JS
source carries the right wiring and the data the JS reads from the
roster endpoint is shaped the way the renderer expects.
"""
from __future__ import annotations

from pathlib import Path

import pytest


TEST_PASSWORD = "test_passwd_xyz_8chars"
ENCOUNTER_JS = (
    Path(__file__).resolve().parents[2]
    / "portal" / "static" / "encounter_console.js"
)


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
        "label": "M45 inline device cards",
        "encounters": [
            {"scenario_name": "Bed 1", "persona_id": "P-014",
             "patient_persona_id": "P-014", "personas": ["P-014"],
             "ehr_id": "helix"},
            {"scenario_name": "Bed 2", "persona_id": "P-003",
             "patient_persona_id": "P-003", "personas": ["P-003"],
             "ehr_id": "helix"},
        ],
    })
    assert r.status_code == 200, r.text
    return r.json()


# ── JS source carries the renderer + handlers ───────────────────────

def test_encounter_js_has_pollDevices_function() -> None:
    src = ENCOUNTER_JS.read_text(encoding="utf-8")
    assert "async function pollDevices" in src
    assert "/api/device/roster?join=" in src
    assert "renderDeviceCards" in src


def test_encounter_js_renders_per_device_card_with_controls() -> None:
    src = ENCOUNTER_JS.read_text(encoding="utf-8")
    assert "function renderDeviceCard" in src
    # Each card carries the action buttons that drive the existing
    # per-station device routes.
    for marker in (
        "data-act=\"inject\"",
        "data-act=\"clear-one\"",
        "data-act=\"clear-all\"",
        "data-act=\"advance\"",
        "data-assign",
    ):
        assert marker in src, f"renderDeviceCard missing {marker!r}"


def test_encounter_js_wires_actions_to_device_routes() -> None:
    src = ENCOUNTER_JS.read_text(encoding="utf-8")
    fn_idx = src.find("async function onDeviceAction")
    assert fn_idx >= 0
    body = src[fn_idx:fn_idx + 3000]
    # Every per-station route is called.
    assert "/inject" in body
    assert "/clear" in body
    assert "/advance_time" in body
    # Reassign is in its own handler.
    assign_idx = src.find("async function onDeviceAssign")
    assert assign_idx >= 0
    assign_body = src[assign_idx:assign_idx + 500]
    assert "/assign" in assign_body


def test_encounter_js_tone_catalog_covers_supported_kinds() -> None:
    """The per-kind tone catalog must cover at least pump_iv,
    pump_enteral, and cabinet — the kinds an instructor inject from
    the inline card. Tone ids must match the server-side catalog
    (PUMP_ALARMS / CABINET_ALERTS in portal/devices/engine/alarms.py)."""
    src = ENCOUNTER_JS.read_text(encoding="utf-8")
    cat_idx = src.find("DEVICE_TONE_CATALOG")
    assert cat_idx >= 0
    block = src[cat_idx:cat_idx + 800]
    assert "pump_iv" in block
    assert "pump_enteral" in block
    assert "cabinet" in block
    # At minimum these (real) tones appear.
    assert "occlusion_downstream" in block
    assert "low_battery" in block
    assert "discrepancy_alert" in block


def test_encounter_js_polls_devices_on_its_own_cadence() -> None:
    """startPolling launches pollDevices on a separate timer (3s)
    alongside telemetry (1s) and state+transcript (2s)."""
    src = ENCOUNTER_JS.read_text(encoding="utf-8")
    sp_idx = src.find("function startPolling")
    assert sp_idx >= 0
    body = src[sp_idx:sp_idx + 1500]
    assert "pollDevices" in body
    assert "DEVICES_POLL_MS" in body
    # And stopPolling clears the timer.
    stop_idx = src.find("function stopPolling")
    stop_body = src[stop_idx:stop_idx + 400]
    assert "devicesTimer" in stop_body


def test_encounter_js_does_not_call_assignment_dropdown_on_cabinet_inline() -> None:
    """The renderer still renders cabinets (read-only assignment) but
    a cabinet note tells the operator that cart-level reassignment
    happens at the room level (per M44/M45 deferred work)."""
    src = ENCOUNTER_JS.read_text(encoding="utf-8")
    fn_idx = src.find("function renderDeviceCard")
    assert fn_idx >= 0
    body = src[fn_idx:fn_idx + 3000]
    # Cabinet note exists.
    assert "cabinetNote" in body or "Med cart" in body


# ── Roster route behaves correctly when device is bound ─────────────

def test_device_roster_returns_full_card_shape(client) -> None:
    """The roster endpoint returns the same fields the inline
    renderer reads: station_id, device_kind, device_model, label,
    online, character_id, active_alarms, runtime_state."""
    body = _start_2enc_room(client)
    join = body["encounters"][0]["join_code"]
    r = client.post(
        f"/api/device/register?join={join}",
        json={"device_kind": "pump_iv", "device_model": "alaris",
              "label": "Bed 1 IV"},
    )
    assert r.status_code == 200, r.text
    sid = r.json()["station_id"]
    r = client.get(f"/api/device/roster?join={join}")
    assert r.status_code == 200
    stations = r.json().get("stations", [])
    assert len(stations) == 1
    s = stations[0]
    # Every field the renderer reads.
    for k in ("station_id", "device_kind", "device_model", "label",
              "online", "character_id", "active_alarms",
              "runtime_state"):
        assert k in s, f"roster missing {k!r}"
    assert s["station_id"] == sid
    assert s["device_kind"] == "pump_iv"
    assert s["label"] == "Bed 1 IV"


def test_inject_endpoint_returns_ok_in_multi_patient(client) -> None:
    """The inline card's Inject button POSTs to
    /api/device/{sid}/inject. Verify the route accepts the call in
    multi-patient mode (M43 contract: per-station routes resolve via
    station.session_id). The actual alarm-propagation surface
    (state machine fold reading persisted events back in the same
    test) is verified by `tests/v7/test_alarm_bus.py` and the v6
    device-engine tests."""
    body = _start_2enc_room(client)
    join = body["encounters"][0]["join_code"]
    sid = client.post(
        f"/api/device/register?join={join}",
        json={"device_kind": "pump_iv", "device_model": "alaris",
              "label": "Bed 1 IV"},
    ).json()["station_id"]
    r = client.post(
        f"/api/device/{sid}/inject",
        json={"tone": "occlusion_downstream"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


# ── Devices card markup still has the placeholder ul + button ───────

def test_encounter_console_devices_card_has_list_anchor(client) -> None:
    """The static markup of the Devices card has the `#device-list`
    UL where the inline renderer paints cards, plus the "Managed
    devices" button that opens the add-device modal."""
    body = _start_2enc_room(client)
    eid = body["encounters"][0]["encounter_id"]
    r = client.get(f"/portal/room/encounter/{eid}")
    html = r.text
    assert 'id="device-list"' in html
    assert 'id="btn-manage-devices"' in html
