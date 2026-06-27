"""M51 — Patient Integrated Alarm (PIA) device.

A new bedside device that combines four functions on one tablet:

  - Call bell      → alarm.injected (tone=call_bell)   info severity
  - Bed alarm      → alarm.injected (tone=bed_alarm)   warning severity
  - Code Blue      → scenes.apply(code.blue)           danger/critical
  - Intercom       → comm.intercom_request + transcript line

The PIA renders a dedicated `device_pia.html` template (NOT the
vendor skin overlay used for pumps/cabinets). Every other PIA in the
room polls /api/room/alarms and flashes red when ANY code blue is
active anywhere — that's the "location-aware cascade" the operator
asked for: every bed announces WHERE the code is happening.

Tests cover:
  1. Registry — kind + model are registered.
  2. Engine factory — make_engine returns a PiaEngine without raising.
  3. Device-side template — /device/{join}/{station} renders the PIA UI
     when the station is a PIA.
  4. Button presses route through pia.button → side-effects:
        call_bell    → alarm.injected on the alarm bus
        bed_alarm    → alarm.injected on the alarm bus
        code_blue    → code.blue scene + alarm on EVERY PIA in the room
                       (encounter_label populated for the cascade)
        intercom     → comm.intercom_request chart event + transcript line
  5. Sound mapping — the M49 wav files referenced in pia_app.js exist.
  6. Encounter console — renders the instructor mirror panel + the PIA
     kind label.
  7. CSS — flash keyframes are defined per kind.
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


def _start_room(client, n: int = 1):
    r = client.post("/api/room/start", json={
        "label": "M51",
        "encounters": [
            {"scenario_name": f"Bed {i+1}", "persona_id": f"P-{i+1:03d}",
             "patient_persona_id": f"P-{i+1:03d}", "ehr_id": "helix"}
            for i in range(n)
        ],
    })
    assert r.status_code == 200
    return r.json()


def _register_pia(client, sess) -> str:
    """Register a PIA station against the given encounter and return
    its station_id."""
    r = client.post(
        f"/api/device/register?join={sess['join_code']}",
        json={"device_kind": "patient_integrated_alarm",
              "device_model": "pia_v1",
              "label": f"PIA @ {sess['scenario_name']}"},
    )
    assert r.status_code == 200, r.text
    return r.json()["station_id"]


# ── 1. Registry ─────────────────────────────────────────────────────

def test_pia_kind_registered() -> None:
    from portal.devices import registry
    assert "patient_integrated_alarm" in registry.list_kinds()
    models = registry.available_models("patient_integrated_alarm")
    assert "pia_v1" in models


def test_pia_spec_declares_four_controls() -> None:
    from portal.devices import registry
    spec = registry.load_spec("patient_integrated_alarm", "pia_v1")
    controls = spec.get("controls") or {}
    assert {"call_bell", "bed_alarm", "code_blue", "intercom"} <= set(controls)


# ── 2. Engine factory ───────────────────────────────────────────────

def test_make_engine_returns_pia_engine_without_raising() -> None:
    """Before M51 this raised KeyError('no engine for device_kind
    patient_integrated_alarm') and broke the /event route."""
    from portal.devices.engine.state_machine import make_engine, PiaEngine
    eng = make_engine(session_id="sess_xyz", station_id="dev_abc",
                      device_kind="patient_integrated_alarm",
                      device_model="pia_v1")
    assert isinstance(eng, PiaEngine)
    assert eng.device_kind == "patient_integrated_alarm"


# ── 3. Device template ──────────────────────────────────────────────

def test_pia_route_renders_device_pia_template(client) -> None:
    """Hitting /device/{join}/{station_id} for a PIA station should
    serve the PIA template (4 big buttons), not the generic device
    skin template."""
    body = _start_room(client, n=1)
    enc = body["encounters"][0]
    station_id = _register_pia(client, enc)
    r = client.get(f"/device/{enc['join_code']}/{station_id}")
    assert r.status_code == 200
    html = r.text
    # PIA-specific markers from device_pia.html.
    assert "pia-frame" in html
    assert "pia-grid" in html
    assert 'data-action="call_bell"' in html
    assert 'data-action="bed_alarm"' in html
    assert 'data-action="code_blue"' in html
    # FR-016 — Intercom is now a hold-to-talk PTT (live audio over the room WS),
    # not a tap→alert data-action. The server-side intercom_request handler is
    # still exercised by test_intercom_request_surfaces_on_bus_and_writes_chart.
    assert 'id="pia-intercom-btn"' in html
    assert "/static/intercom.js" in html
    # Loads the PIA JS bundle.
    assert "/static/pia_app.js" in html
    # Generic device skin chrome should NOT be present.
    assert "device-skin-svg" not in html


# ── 4. Button presses → side effects ────────────────────────────────

def test_call_bell_press_surfaces_on_alarm_bus(client) -> None:
    body = _start_room(client, n=1)
    enc = body["encounters"][0]
    station_id = _register_pia(client, enc)
    r = client.post(
        f"/api/device/{station_id}/event",
        json={"type": "pia.button",
              "payload": {"action": "call_bell", "by": "patient"}},
    )
    assert r.status_code == 200, r.text
    alarms = client.get("/api/room/alarms").json()["alarms"]
    bell = [a for a in alarms if a.get("kind") == "call_bell"]
    assert len(bell) == 1
    assert bell[0]["source"] == "device"
    assert bell[0]["encounter_id"] == enc["encounter_id"]


def test_bed_alarm_press_surfaces_on_alarm_bus(client) -> None:
    body = _start_room(client, n=1)
    enc = body["encounters"][0]
    station_id = _register_pia(client, enc)
    r = client.post(
        f"/api/device/{station_id}/event",
        json={"type": "pia.button",
              "payload": {"action": "bed_alarm", "by": "patient"}},
    )
    assert r.status_code == 200, r.text
    alarms = client.get("/api/room/alarms").json()["alarms"]
    bed = [a for a in alarms if a.get("kind") == "bed_alarm"]
    assert len(bed) == 1
    assert bed[0]["source"] == "device"


def test_code_blue_press_fires_scene_and_cascades(client) -> None:
    """The Code Blue button on Bed 1's PIA must surface as a code-blue
    alarm on the room bus AND be visible from a second encounter's
    perspective (because /api/room/alarms is room-wide). This is the
    cascade behaviour the operator described — every other PIA polls
    the same endpoint and flashes red when ANY code blue is live."""
    body = _start_room(client, n=2)
    bed1, bed2 = body["encounters"]
    pia1 = _register_pia(client, bed1)
    _ = _register_pia(client, bed2)   # second PIA exists in same room
    r = client.post(
        f"/api/device/{pia1}/event",
        json={"type": "pia.button",
              "payload": {"action": "code_blue", "by": "patient"}},
    )
    assert r.status_code == 200, r.text
    alarms = client.get("/api/room/alarms").json()["alarms"]
    blues = [a for a in alarms
             if str(a.get("kind", "")).startswith("code.blue")
                or str(a.get("kind", "")).startswith("code_blue")]
    assert blues, f"no code blue alarm surfaced. Got: {alarms!r}"
    # The cascade banner on every OTHER PIA needs to know WHERE the
    # code is. The alarm carries encounter_label so the bedside can
    # say "CODE BLUE — Bed 1".
    blue = blues[0]
    assert blue["encounter_id"] == bed1["encounter_id"]
    assert blue.get("encounter_label")    # e.g. "Bed 1"
    # Severity is critical or higher so it pulls top-priority audio.
    assert blue["severity"] in ("danger", "critical")


def test_intercom_request_surfaces_on_bus_and_writes_chart(client) -> None:
    body = _start_room(client, n=1)
    enc = body["encounters"][0]
    eid = enc["encounter_id"]
    station_id = _register_pia(client, enc)
    r = client.post(
        f"/api/device/{station_id}/event",
        json={"type": "pia.button",
              "payload": {"action": "intercom_request", "by": "patient"}},
    )
    assert r.status_code == 200, r.text
    # #83 — the request now surfaces on the alarm bus the SAME way a call bell
    # does, so the nurse station board + operator actually see/hear it (before,
    # it was only a quiet chart entry nobody was alerted to).
    alarms = client.get("/api/room/alarms").json()["alarms"]
    inter = [a for a in alarms if a.get("kind") == "intercom_request"]
    assert len(inter) == 1, f"intercom request did not surface on the bus: {alarms!r}"
    assert inter[0]["source"] == "device"
    assert inter[0]["encounter_id"] == eid
    # Chart event exists.
    from portal import ehr_db
    events = ehr_db.events(eid) or []
    requests = [ev for ev in events
                if ev.get("type") == "comm.intercom_request"]
    assert requests, "intercom_request chart event missing"
    assert requests[-1]["payload"].get("station_id") == station_id
    # Transcript line landed (last 4 entries — log_turn writes 2 rows
    # per call: student "🎙 Intercom requested" + empty character).
    transcript = client.get(f"/api/encounter/{eid}/transcript").json()
    rows = transcript.get("transcript") or []
    assert any("Intercom" in (r.get("text") or "")
               or "🎙" in (r.get("text") or "")
               for r in rows[-4:])


def test_unknown_pia_action_is_ignored_not_500(client) -> None:
    """If a malformed button payload arrives the route should still
    return 200 (the engine persists the event) — but no alarm should
    be raised."""
    body = _start_room(client, n=1)
    enc = body["encounters"][0]
    station_id = _register_pia(client, enc)
    r = client.post(
        f"/api/device/{station_id}/event",
        json={"type": "pia.button",
              "payload": {"action": "not_a_real_button"}},
    )
    assert r.status_code == 200
    alarms = client.get("/api/room/alarms").json()["alarms"]
    assert not alarms


# ── 5. Sound files referenced by pia_app.js exist on disk ───────────

def test_pia_sound_files_exist() -> None:
    """pia_app.js plays three WAVs from the M49 library. Verify they
    actually ship — a 404 on these would mean the bedside hears
    nothing on a button press."""
    base = (
        Path(__file__).resolve().parents[2]
        / "portal" / "static" / "sounds" / "clinical_alarms"
    )
    assert (base / "01_bed_exit_alarm.wav").is_file()
    assert (base / "02_call_bell.wav").is_file()
    assert (base / "03_code_blue.wav").is_file()


def test_pia_js_references_clinical_alarm_wavs() -> None:
    js_path = (
        Path(__file__).resolve().parents[2]
        / "portal" / "static" / "pia_app.js"
    )
    src = js_path.read_text(encoding="utf-8")
    assert "02_call_bell.wav"      in src
    assert "01_bed_exit_alarm.wav" in src
    assert "03_code_blue.wav"      in src
    # Flash class names per kind.
    assert "pia-flash-call-bell"   in src
    assert "pia-flash-bed-alarm"   in src
    assert "pia-flash-code-blue"   in src
    assert "pia-flash-intercom"    in src
    # Cascade poller present.
    assert "/api/room/alarms"      in src
    assert "pia-cascade-active"    in src


# ── 6. Encounter console — instructor mirror panel ──────────────────

def test_encounter_console_js_has_pia_kind_label_and_mirror() -> None:
    js_path = (
        Path(__file__).resolve().parents[2]
        / "portal" / "static" / "encounter_console.js"
    )
    src = js_path.read_text(encoding="utf-8")
    # Kind label so the device card titles "📟 Patient Integrated Alarm".
    assert "patient_integrated_alarm" in src
    assert "Patient Integrated Alarm" in src
    # Mirror buttons — instructor can trigger from the encounter card.
    assert 'data-pia-action="call_bell"' in src
    assert 'data-pia-action="bed_alarm"' in src
    assert 'data-pia-action="code_blue"' in src
    assert 'data-pia-action="intercom_request"' in src
    # And the handler that POSTs the press.
    assert "pia.button" in src


# ── 7. CSS — flash keyframes per kind ───────────────────────────────

def test_pia_css_defines_flash_keyframes_per_kind() -> None:
    css_path = (
        Path(__file__).resolve().parents[2]
        / "portal" / "static" / "pia_app.css"
    )
    src = css_path.read_text(encoding="utf-8")
    assert "@keyframes flash-call-bell"  in src
    assert "@keyframes flash-bed-alarm"  in src
    assert "@keyframes flash-code-blue"  in src
    assert "@keyframes flash-intercom"   in src
    # Cascade banner pulse keyframes for room-wide code-blue.
    assert "@keyframes cascade-pulse"    in src
    # Frame classes that drive the alternating-color flash.
    assert ".pia-frame.pia-flash-code-blue" in src
    assert ".pia-cascade-active"            in src
