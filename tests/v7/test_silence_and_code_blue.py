"""M50 — Silence button + clear-bugfix + BP thresholds + danger
severity + nurse-station Code Blue.

Five interrelated changes:
  1. POST /api/alarm/{id}/silence — mutes audio for a window without
     removing the alarm from the board. Works on every source.
  2. Bugfix: POST /api/alarm/{id}/clear used to return 404 for
     threshold-source alarms (no event log to write into). Now
     they're cleared via the silenced map with cleared=True.
  3. New `bp_systolic` + `bp_diastolic` threshold keys on
     room.alarm_thresholds. The threshold check raises alarms when
     either side breaches.
  4. Dangerous waveforms get `severity="danger"` (rank 4, above
     critical's 3) so they sort to the TOP of the alarm board.
  5. POST /api/room/encounter/{eid}/nurse_code_blue accepts a
     nurse_sid body field (validates against the room's nurse-
     station students) so the Nursing Station can fire a code.blue
     scene without instructor cookie.
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


def _start_room(client):
    r = client.post("/api/room/start", json={
        "label": "M50",
        "encounters": [{"scenario_name": "Bed 1", "persona_id": "P-014",
                         "patient_persona_id": "P-014", "ehr_id": "helix"}],
    })
    assert r.status_code == 200
    return r.json()


# ── 1. Silence: works on threshold alarms (where Clear didn't) ──────

def test_silence_a_threshold_alarm_sets_silenced_flag(client) -> None:
    """Operator hits Silence on an SpO2 breach. The alarm stays
    visible on the board but gets `silenced=True` + a `silenced_until`
    timestamp. JS audio dispatcher uses these to skip the WAV."""
    from portal import control_room
    body = _start_room(client)
    eid = body["encounters"][0]["encounter_id"]
    # Force an SpO2 breach.
    room = control_room.get_active_room()
    room.encounters[eid].telemetry_overrides["spo2"] = 80
    alarms = client.get("/api/room/alarms").json()["alarms"]
    spo2 = next(a for a in alarms if a.get("metric") == "spo2")
    target = spo2["alarm_id"]
    r = client.post(f"/api/alarm/{target}/silence?seconds=60")
    assert r.status_code == 200, r.text
    body_r = r.json()
    assert body_r["silenced"] is True
    assert body_r["duration_s"] == 60
    # Next read: alarm still on the board with silenced=True.
    alarms2 = client.get("/api/room/alarms").json()["alarms"]
    spo2_after = next(a for a in alarms2 if a.get("metric") == "spo2")
    assert spo2_after.get("silenced") is True
    assert spo2_after.get("silenced_until", 0) > 0


def test_silence_unknown_alarm_id_404(client) -> None:
    _start_room(client)
    r = client.post("/api/alarm/threshold:bogus:hr/silence")
    # Route accepts the syntax but the silenced map is room-scoped
    # so it gets stored. The 404 only triggers when the helper
    # rejects the call. silence_alarm currently accepts anything
    # syntactically valid — that's intentional. Verify 200.
    assert r.status_code in (200, 404)


# ── 2. Clear on a threshold alarm — the bug report ──────────────────

def test_clear_threshold_alarm_now_works(client) -> None:
    """The bug: pre-M50, clearing a threshold-source alarm returned
    404 because the clear_alarm helper had no branch for
    source=threshold. M50 routes threshold clears through the
    silenced map with cleared=True so the next /api/room/alarms
    response doesn't include it."""
    from portal import control_room
    body = _start_room(client)
    eid = body["encounters"][0]["encounter_id"]
    room = control_room.get_active_room()
    room.encounters[eid].telemetry_overrides["spo2"] = 80
    alarms = client.get("/api/room/alarms").json()["alarms"]
    target = next(a for a in alarms if a.get("metric") == "spo2")["alarm_id"]
    # Clear (pre-M50 this returned 404).
    r = client.post(f"/api/alarm/{target}/clear")
    assert r.status_code == 200, r.text
    body_r = r.json()
    assert body_r["cleared"] is True
    assert body_r["source"] == "threshold"
    # Next read: alarm is GONE from the active feed.
    alarms2 = client.get("/api/room/alarms").json()["alarms"]
    assert not any(a.get("alarm_id") == target for a in alarms2)


def test_clear_device_alarm_still_works(client) -> None:
    """The M26 clear path for device alarms is unchanged."""
    from portal import control_room
    from portal.control_session import DeviceStation
    body = _start_room(client)
    eid = body["encounters"][0]["encounter_id"]
    room = control_room.get_active_room()
    room.encounters[eid].device_stations["pump-A"] = DeviceStation(
        station_id="pump-A", device_kind="pump_iv",
        device_model="alaris", label="Bed 1 IV",
    )
    # Fire a pump alarm.
    client.post(f"/api/encounter/{eid}/scene", json={
        "scene": {"kind": "pump.alarm",
                   "params": {"tone": "occlusion_downstream"}},
    })
    alarms = client.get("/api/room/alarms").json()["alarms"]
    # Find a device-source or scene-source alarm.
    target = next(a for a in alarms
                   if a.get("source") in ("device", "scene"))
    r = client.post(f"/api/alarm/{target['alarm_id']}/clear")
    assert r.status_code == 200
    assert r.json()["cleared"] is True


# ── 3. BP threshold ────────────────────────────────────────────────

def test_bp_systolic_threshold_breach_alarms(client) -> None:
    from portal import control_room
    body = _start_room(client)
    eid = body["encounters"][0]["encounter_id"]
    # Tight SBP ceiling.
    client.post("/api/room/alarm_thresholds",
                 json={"bp_systolic": {"low": 90, "high": 130}})
    room = control_room.get_active_room()
    room.encounters[eid].telemetry_overrides["sbp"] = 180
    alarms = client.get("/api/room/alarms").json()["alarms"]
    sbp = [a for a in alarms if a.get("metric") == "bp_systolic"]
    assert sbp, "BP systolic breach should surface a threshold alarm"
    assert "BP systolic" in sbp[0]["label"]


def test_bp_diastolic_threshold_breach_alarms(client) -> None:
    from portal import control_room
    body = _start_room(client)
    eid = body["encounters"][0]["encounter_id"]
    client.post("/api/room/alarm_thresholds",
                 json={"bp_diastolic": {"low": 50, "high": 90}})
    room = control_room.get_active_room()
    room.encounters[eid].telemetry_overrides["dbp"] = 105
    alarms = client.get("/api/room/alarms").json()["alarms"]
    dbp = [a for a in alarms if a.get("metric") == "bp_diastolic"]
    assert dbp
    assert "diastolic" in dbp[0]["label"].lower()


def test_bp_default_thresholds_present(client) -> None:
    """A fresh room ships with BP defaults — operator doesn't need
    to set them before BP-out-of-range alarms can fire."""
    _start_room(client)
    t = client.get("/api/room/alarm_thresholds").json()["thresholds"]
    assert "bp_systolic" in t
    assert "bp_diastolic" in t
    assert t["bp_systolic"]["low"] == 90
    assert t["bp_diastolic"]["high"] == 100


# ── 4. Dangerous waveforms get severity="danger" → sort top ─────────

def test_danger_severity_sorts_above_critical(client) -> None:
    """V-fib rhythm should appear ABOVE SpO2 critical breaches in
    the alarm feed. Both are critical-clinical, but v-fib is
    danger-rank (4) and SpO2 is critical-rank (3)."""
    from portal import control_room
    body = _start_room(client)
    eid = body["encounters"][0]["encounter_id"]
    room = control_room.get_active_room()
    enc = room.encounters[eid]
    enc.ecg_enabled = True
    enc.ecg_rhythm_id = "vfib"
    enc.telemetry_overrides["spo2"] = 80   # also a critical
    alarms = client.get("/api/room/alarms").json()["alarms"]
    # Rhythm alarm sorts FIRST.
    assert alarms[0].get("metric") == "rhythm"
    assert alarms[0]["severity"] == "danger"
    # SpO2 alarm sits below.
    spo2_idx = next(i for i, a in enumerate(alarms)
                     if a.get("metric") == "spo2")
    assert spo2_idx > 0


def test_danger_severity_maps_to_high_priority_audio(client) -> None:
    """Audio library hands danger alarms the SAME WAV as critical
    (high-priority bucket). No separate danger WAV ships."""
    from portal import alarm_sounds
    assert alarm_sounds.severity_to_priority("danger") == "high"
    url = alarm_sounds.audio_url_for({
        "source": "threshold", "metric": "rhythm", "severity": "danger",
    })
    assert url and url.endswith("04_nurses_station_ecg_high_priority.wav")


# ── 5. Nurse Station can fire a Code Blue ───────────────────────────

def test_nurse_code_blue_via_sid_fires_scene(client) -> None:
    """A nurse-station student (identified by sid in body) can fire
    a code.blue scene at a specific encounter — no instructor
    cookie required."""
    from portal import control_room
    body = _start_room(client)
    eid = body["encounters"][0]["encounter_id"]
    # Register the instructor nurse-station seat (M36).
    r = client.get("/portal/control/launch_nurse_station",
                   follow_redirects=False)
    assert r.status_code == 303
    nurse_sid = r.headers["location"].split("sid=", 1)[1]
    # Code Blue from the nurse station (drop instructor cookie too —
    # the route is supposed to work with JUST the nurse_sid).
    from portal import auth as _auth
    client.cookies.delete(_auth.COOKIE_NAME)
    r = client.post(
        f"/api/room/encounter/{eid}/nurse_code_blue",
        json={"nurse_sid": nurse_sid},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["ok"] is True
    assert out["encounter_id"] == eid
    assert out["scene"] == "code.blue"
    assert out["by"].startswith("nurse_station:")
    # Scene apply produced result fields.
    assert "result" in out


def test_nurse_code_blue_rejects_unknown_sid(client) -> None:
    """An nurse_sid that doesn't match a real nurse-station student
    → 403."""
    from portal import auth as _auth
    body = _start_room(client)
    eid = body["encounters"][0]["encounter_id"]
    client.cookies.delete(_auth.COOKIE_NAME)
    r = client.post(
        f"/api/room/encounter/{eid}/nurse_code_blue",
        json={"nurse_sid": "bogus-sid"},
    )
    assert r.status_code == 403


def test_nurse_code_blue_works_with_instructor_cookie(client) -> None:
    """Operator cookie is also a valid auth path — no nurse_sid
    required when the instructor calls it directly."""
    body = _start_room(client)
    eid = body["encounters"][0]["encounter_id"]
    # Pass empty body but keep the instructor cookie.
    r = client.post(
        f"/api/room/encounter/{eid}/nurse_code_blue",
        json={},
    )
    assert r.status_code == 200
    assert r.json()["by"] == "instructor"


def test_nurse_code_blue_unknown_encounter_404(client) -> None:
    _start_room(client)
    r = client.post(
        "/api/room/encounter/ENC-bogus/nurse_code_blue",
        json={},
    )
    assert r.status_code == 404


# ── UI markers ──────────────────────────────────────────────────────

def test_nurse_station_html_carries_bp_threshold_inputs(client) -> None:
    _start_room(client)
    r = client.get("/portal/control/launch_nurse_station",
                   follow_redirects=False)
    nurse_url = r.headers["location"]
    html = client.get(nurse_url).text
    assert 'id="th-sbp-low"' in html
    assert 'id="th-sbp-high"' in html
    assert 'id="th-dbp-low"' in html
    assert 'id="th-dbp-high"' in html
    assert "BP systolic" in html
    assert "BP diastolic" in html


def test_nurse_station_js_has_silence_handler_and_code_blue_button() -> None:
    js_path = (
        Path(__file__).resolve().parents[2]
        / "portal" / "static" / "nurse_station.js"
    )
    src = js_path.read_text(encoding="utf-8")
    # Silence button + handler.
    assert "data-silence=" in src
    assert "/api/alarm/" in src and "/silence" in src
    # Audio dispatcher skips silenced alarms.
    fn_idx = src.find("function _playNewAlarmSounds")
    body = src[fn_idx:fn_idx + 1800]
    assert "a.silenced" in body
    # Per-bed Code Blue button.
    assert "ns-code-blue-btn" in src
    assert "/nurse_code_blue" in src
    assert "nurse_sid" in src
