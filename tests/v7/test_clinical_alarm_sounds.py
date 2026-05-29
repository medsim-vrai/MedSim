"""M49 — Clinical-alarm WAV library wired to the alarm bus.

15 production-ready WAV files (HR / SpO2 / RR / ECG × HIGH / MEDIUM /
LOW priority, plus code blue / bed exit / call bell) live in
``portal/static/sounds/clinical_alarms/``.

`portal/alarm_sounds.py` maps an alarm dict (the M48-shape that
``alarms.active_alarms()`` emits) to an `audio_url` pointing at one
of those files. `alarms.active_alarms()` calls `alarm_sounds.annotate`
so every alarm carries an `audio_url` + `audio_priority` field.

The Nursing Station JS plays the WAV on a NEW alarm and dedupes by
alarm_id so subsequent 3s polls don't replay the sound.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from portal import alarm_sounds


# ── Asset library shipped with the project ───────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOUNDS_DIR   = PROJECT_ROOT / "portal" / "static" / "sounds" / "clinical_alarms"
NURSE_JS     = PROJECT_ROOT / "portal" / "static" / "nurse_station.js"


def test_clinical_alarm_wavs_shipped() -> None:
    """All 15 WAV files plus the manifest are present in the
    static asset directory."""
    expected = [
        "01_bed_exit_alarm.wav",
        "02_call_bell.wav",
        "03_code_blue.wav",
        "04_nurses_station_ecg_high_priority.wav",
        "05_nurses_station_hr_high_priority.wav",
        "06_nurses_station_spo2_high_priority.wav",
        "07_nurses_station_rr_high_priority.wav",
        "08_nurses_station_ecg_medium_priority.wav",
        "09_nurses_station_hr_medium_priority.wav",
        "10_nurses_station_spo2_medium_priority.wav",
        "11_nurses_station_rr_medium_priority.wav",
        "12_nurses_station_ecg_low_priority.wav",
        "13_nurses_station_hr_low_priority.wav",
        "14_nurses_station_spo2_low_priority.wav",
        "15_nurses_station_rr_low_priority.wav",
    ]
    for name in expected:
        assert (SOUNDS_DIR / name).exists(), f"missing asset {name!r}"
    assert (SOUNDS_DIR / "MANIFEST.txt").exists()


# ── alarm_sounds module unit tests ───────────────────────────────────

def test_severity_to_priority_mapping() -> None:
    assert alarm_sounds.severity_to_priority("critical") == "high"
    assert alarm_sounds.severity_to_priority("warning")  == "medium"
    assert alarm_sounds.severity_to_priority("info")     == "low"
    assert alarm_sounds.severity_to_priority("")         == "low"   # fallback


def test_audio_url_for_threshold_hr_critical() -> None:
    """A threshold-source HR breach at critical severity → HIGH
    priority HR WAV (file 05)."""
    url = alarm_sounds.audio_url_for({
        "source": "threshold", "metric": "hr", "severity": "critical",
    })
    assert url and url.endswith("05_nurses_station_hr_high_priority.wav")


def test_audio_url_for_threshold_spo2_critical() -> None:
    """SpO2 breach @ critical → file 06 (HIGH)."""
    url = alarm_sounds.audio_url_for({
        "source": "threshold", "metric": "spo2", "severity": "critical",
    })
    assert url and url.endswith("06_nurses_station_spo2_high_priority.wav")


def test_audio_url_for_threshold_rr_warning() -> None:
    """RR warning → MEDIUM priority RR WAV (file 11)."""
    url = alarm_sounds.audio_url_for({
        "source": "threshold", "metric": "rr", "severity": "warning",
    })
    assert url and url.endswith("11_nurses_station_rr_medium_priority.wav")


def test_audio_url_for_threshold_rhythm_mapped_to_ecg_family() -> None:
    """Dangerous rhythm (metric=rhythm) maps to the ECG WAV family."""
    url = alarm_sounds.audio_url_for({
        "source": "threshold", "metric": "rhythm", "severity": "critical",
    })
    assert url and url.endswith("04_nurses_station_ecg_high_priority.wav")


def test_audio_url_for_scene_code_blue() -> None:
    url = alarm_sounds.audio_url_for({
        "source": "scene", "kind": "code.blue", "severity": "critical",
    })
    assert url and url.endswith("03_code_blue.wav")


def test_audio_url_for_device_call_bell() -> None:
    url = alarm_sounds.audio_url_for({
        "source": "device", "kind": "alarm.injected.call_bell",
        "severity": "info",
    })
    assert url and url.endswith("02_call_bell.wav")


def test_audio_url_for_device_bed_alarm() -> None:
    url = alarm_sounds.audio_url_for({
        "source": "device", "kind": "alarm.injected.bed_alarm",
        "severity": "warning",
    })
    assert url and url.endswith("01_bed_exit_alarm.wav")


def test_audio_url_none_for_pump_alarm() -> None:
    """Pump alarms keep their own device-side audio; alarm_sounds
    doesn't override (returns None — UI just flashes the badge)."""
    url = alarm_sounds.audio_url_for({
        "source": "device", "kind": "pump.alarm",
        "severity": "warning", "metric": None,
    })
    assert url is None


def test_audio_url_none_for_unknown_alarm() -> None:
    """Unknown shape → None (no crash, UI silently skips audio)."""
    url = alarm_sounds.audio_url_for({"source": "??", "kind": "??"})
    assert url is None


def test_annotate_adds_audio_fields_to_all_alarms() -> None:
    alarms = [
        {"source": "threshold", "metric": "hr", "severity": "warning"},
        {"source": "scene", "kind": "code.blue", "severity": "critical"},
        {"source": "device", "kind": "pump.alarm.injected", "severity": "info"},
    ]
    annotated = alarm_sounds.annotate(alarms)
    assert annotated is alarms   # mutates in place
    assert "audio_url" in alarms[0]
    assert "audio_priority" in alarms[0]
    assert alarms[0]["audio_url"].endswith("hr_medium_priority.wav")
    assert alarms[1]["audio_url"].endswith("code_blue.wav")
    # Pump alarm gets audio_priority but no audio_url (none curated).
    assert alarms[2]["audio_url"] is None
    assert alarms[2]["audio_priority"] == "low"


# ── End-to-end through /api/room/alarms ─────────────────────────────

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


def test_room_alarms_response_carries_audio_url_per_alarm(client) -> None:
    """When /api/room/alarms returns a threshold breach (the easiest
    one to trigger in a test), the response includes an audio_url
    field per alarm."""
    from portal import control_room
    r = client.post("/api/room/start", json={
        "label": "M49 sounds",
        "encounters": [{"scenario_name": "Bed 1", "persona_id": "P-014",
                         "patient_persona_id": "P-014", "ehr_id": "helix"}],
    })
    assert r.status_code == 200
    eid = r.json()["encounters"][0]["encounter_id"]
    # Force an SpO2 deep breach via the M25 override (default low=90).
    # M54 — severity now scales with magnitude; need >=20% below to
    # land in "critical" → "high" priority audio. 70 vs 90 = 22% below.
    room = control_room.get_active_room()
    room.encounters[eid].telemetry_overrides["spo2"] = 70
    body = client.get("/api/room/alarms").json()
    alarms = body.get("alarms", [])
    assert alarms
    # Every alarm now has the new fields.
    for a in alarms:
        assert "audio_url" in a
        assert "audio_priority" in a
    # SpO2 critical → high-priority SpO2 WAV.
    spo2 = next(a for a in alarms if a.get("metric") == "spo2")
    assert spo2["audio_priority"] == "high"
    assert spo2["audio_url"].endswith("06_nurses_station_spo2_high_priority.wav")


def test_static_wav_route_serves_actual_file(client) -> None:
    """FastAPI's static handler serves the WAV bytes."""
    r = client.get("/static/sounds/clinical_alarms/03_code_blue.wav")
    assert r.status_code == 200
    # Standard WAV header.
    assert r.content[:4] == b"RIFF"
    # Sensible content-type (audio/* family).
    ct = r.headers.get("content-type", "")
    assert ct.startswith("audio/") or ct == "audio/wav" or ct == "audio/x-wav"


# ── Nurse Station JS plays audio + dedupes ───────────────────────────

def test_nurse_station_js_plays_audio_url_on_new_alarm() -> None:
    src = NURSE_JS.read_text(encoding="utf-8")
    # The dispatcher function is wired into renderAlarmBoard.
    assert "function _playNewAlarmSounds" in src
    # It instantiates Audio() with the alarm's audio_url and calls
    # play().
    fn_idx = src.find("function _playNewAlarmSounds")
    body = src[fn_idx:fn_idx + 1500]
    assert "new Audio(url)" in body
    assert ".play()" in body
    # And reads `a.audio_url` from each alarm dict.
    assert "a.audio_url" in body


def test_nurse_station_js_repeats_audio_by_cadence() -> None:
    """M52 — Operator: "Repeat alarm sounds until cleared". The JS
    used to fire each alarm's WAV ONCE on first sight (deduped by a
    `_seenAlarmIds` set). M52 replaces that with a per-alarm
    `_audioLastAt` map + per-priority cadence so the alarm keeps
    sounding until the breach clears or the operator silences."""
    src = NURSE_JS.read_text(encoding="utf-8")
    assert "_audioLastAt" in src
    assert "AUDIO_REPEAT_MS" in src
    # The map drops ids that are no longer active so a re-occurrence
    # of the same alarm_id fires immediately. M54 — function body
    # grew with tier/concurrency comments; widen the search window.
    fn_idx = src.find("function _playNewAlarmSounds")
    body = src[fn_idx:fn_idx + 2500]
    assert "_audioLastAt.get(sid)" in body
    assert "_audioLastAt.set(sid" in body
    assert "_audioLastAt.delete(sid)" in body
