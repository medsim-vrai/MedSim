"""M52 — Three operator asks bundled:

  1. Alarm sounds REPEAT until cleared (or until the user silences).
     The nurse-station JS used to play each WAV ONCE on first sight;
     now it re-fires on a cadence per priority (high=8s, medium=20s,
     low=45s). PIA cascade poller likewise repeats the code-blue
     tone every 8 s while the alarm is live.

  2. Silence default 45 s (was 120 s). Operator: "silence of an alarm
     last 45 seconds then it goes active if the condition is not
     resolved or cleared". The alarm bus's existing `_apply_silenced`
     filter auto-expires past the `until` timestamp, so a still-
     active breach surfaces its audio again the moment 45 s lapses.

  3. Brand: every user-facing screen + the printable QR sheet says
     "Training Bridge VRAI- MedSim" (exact spacing per operator).
     Code-level JS globals (window.MEDSIM2_OPS etc) + filesystem paths
     (~/.medsim/) are NOT renamed — those are code identifiers, not
     user-visible brand.
"""
from __future__ import annotations

from pathlib import Path

import pytest


TEST_PASSWORD = "test_passwd_xyz_8chars"
BRAND = "Training Bridge VRAI- MedSim"


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
        "label": "M52",
        "encounters": [{"scenario_name": "Bed 1", "persona_id": "P-014",
                         "patient_persona_id": "P-014", "ehr_id": "helix"}],
    })
    assert r.status_code == 200
    return r.json()


# ── 1. Silence default is now 45 s ─────────────────────────────────

def test_silence_default_is_45_seconds(client) -> None:
    """No `?seconds=N` querystring — should land at 45 s, not 120."""
    from portal import control_room
    import time as _time
    body = _start_room(client)
    eid = body["encounters"][0]["encounter_id"]
    room = control_room.get_active_room()
    room.encounters[eid].telemetry_overrides["spo2"] = 80
    alarms = client.get("/api/room/alarms").json()["alarms"]
    target = next(a for a in alarms if a.get("metric") == "spo2")["alarm_id"]
    before = _time.time()
    r = client.post(f"/api/alarm/{target}/silence")
    assert r.status_code == 200, r.text
    body_r = r.json()
    assert body_r["duration_s"] == 45
    # silenced_until should be within a couple seconds of (now + 45).
    expected = before + 45
    assert abs(body_r["silenced_until"] - expected) < 5


def test_silence_explicit_seconds_still_overrides(client) -> None:
    """Operator can still pass `?seconds=N` to override the 45 s
    default — useful if they want a longer mute for a known noisy
    breach."""
    from portal import control_room
    body = _start_room(client)
    eid = body["encounters"][0]["encounter_id"]
    room = control_room.get_active_room()
    room.encounters[eid].telemetry_overrides["spo2"] = 80
    alarms = client.get("/api/room/alarms").json()["alarms"]
    target = next(a for a in alarms if a.get("metric") == "spo2")["alarm_id"]
    r = client.post(f"/api/alarm/{target}/silence?seconds=120")
    assert r.status_code == 200
    assert r.json()["duration_s"] == 120


def test_silence_helper_default_is_45() -> None:
    """The python helper signature itself defaults to 45 s. If a
    future caller forgets to pass duration_s they get the operator's
    preferred default."""
    import inspect
    from portal import alarms as alarms_mod
    sig = inspect.signature(alarms_mod.silence_alarm)
    assert sig.parameters["duration_s"].default == 45


# ── 2. Repeating-audio dispatcher in nurse_station.js ──────────────

def test_nurse_station_js_uses_repeating_audio_dispatcher() -> None:
    """The new dispatcher must (a) keep per-alarm last-played
    timestamps, (b) replay when (now - last) ≥ cadence, (c) honor
    `audio_priority` to pick the cadence, (d) skip silenced alarms,
    (e) clear its map when active list is empty so re-occurrences
    fire immediately."""
    js_path = (
        Path(__file__).resolve().parents[2]
        / "portal" / "static" / "nurse_station.js"
    )
    src = js_path.read_text(encoding="utf-8")
    # (a) per-alarm last-played map
    assert "_audioLastAt" in src
    # (b) cadence table — high/medium/low keys present + plausible ms values
    assert "AUDIO_REPEAT_MS" in src
    assert "high"   in src and "medium" in src and "low" in src
    # (c) `audio_priority` is consulted
    assert "audio_priority" in src
    # (d) silenced alarms still skipped
    assert "a.silenced" in src
    # (e) clear() on empty list
    fn_idx = src.find("function renderAlarmBoard")
    body = src[fn_idx:fn_idx + 800]
    assert "_audioLastAt.clear" in body
    # The old once-per-occurrence Set/seenAlarmIds should be gone.
    assert "_seenAlarmIds" not in src


def test_nurse_station_silence_button_title_says_45() -> None:
    """The Silence button's tooltip should reflect the new default
    so the operator's expectation matches what they get when they
    click it."""
    js_path = (
        Path(__file__).resolve().parents[2]
        / "portal" / "static" / "nurse_station.js"
    )
    src = js_path.read_text(encoding="utf-8")
    assert 'title="Mute audio for 45 s' in src


# ── 3. PIA cascade audio repeats while code blue is active ─────────

def test_pia_cascade_repeats_audio_until_cleared() -> None:
    """The PIA's cascade poller used to play `03_code_blue.wav`
    exactly once per new code-blue cluster (deduped via
    `_cascadeKey`). Now it must replay every 8 s while the alarm is
    live so the bedside actually keeps hearing the alarm."""
    js_path = (
        Path(__file__).resolve().parents[2]
        / "portal" / "static" / "pia_app.js"
    )
    src = js_path.read_text(encoding="utf-8")
    # Per-alarm last-played map for the cascade audio specifically.
    assert "_cascadeAudioLastAt" in src
    # M54 — Cascade cadence dropped 8 s → 2.5 s for near-continuous
    # code-blue playback per operator: "the sound loop for a code
    # blue should run continuously with minimal time gap".
    assert "CASCADE_AUDIO_REPEAT_MS" in src
    assert "2500" in src
    # Silenced alarms still skip.
    assert "a.silenced" in src
    # Map cleared when the cascade is empty so re-occurrences fire
    # immediately.
    assert "_cascadeAudioLastAt.clear" in src
    # Flash stays gated by `_cascadeKey` (we don't want to restart
    # the CSS animation every 2.5 s — just the audio).
    assert "_cascadeKey" in src
    assert "playSound('code_blue')" in src


# ── 4. Brand: "Training Bridge VRAI- MedSim" ───────────────────────

def test_base_template_carries_brand() -> None:
    """The shared layout's <title> and topbar should carry the brand
    so every page that extends base.html picks it up."""
    p = (Path(__file__).resolve().parents[2]
         / "portal" / "templates" / "base.html")
    src = p.read_text(encoding="utf-8")
    assert BRAND in src
    # Old MEDSIM 2 wordmark should be gone.
    assert "MEDSIM 2" not in src
    # The version-pill still ships; just check it didn't accidentally
    # carry the old brand string in.
    assert "v-pill" in src


def test_home_template_carries_brand() -> None:
    p = (Path(__file__).resolve().parents[2]
         / "portal" / "templates" / "home.html")
    src = p.read_text(encoding="utf-8")
    assert BRAND in src
    assert "<h1>MEDSIM 2</h1>" not in src


def test_login_template_carries_brand() -> None:
    p = (Path(__file__).resolve().parents[2]
         / "portal" / "templates" / "login.html")
    src = p.read_text(encoding="utf-8")
    assert BRAND in src
    assert "medsim portal · sign in" not in src
    assert "<h1>medsim portal</h1>" not in src


def test_join_template_carries_brand() -> None:
    p = (Path(__file__).resolve().parents[2]
         / "portal" / "templates" / "join.html")
    src = p.read_text(encoding="utf-8")
    assert BRAND in src
    assert "MEDSIM 2 session" not in src


def test_ehr_join_template_carries_brand() -> None:
    p = (Path(__file__).resolve().parents[2]
         / "portal" / "templates" / "ehr_join.html")
    src = p.read_text(encoding="utf-8")
    assert BRAND in src
    assert "MEDSIM V3" not in src


def test_device_app_template_carries_brand() -> None:
    p = (Path(__file__).resolve().parents[2]
         / "portal" / "templates" / "device_app.html")
    src = p.read_text(encoding="utf-8")
    # Tab title.
    assert BRAND in src
    # The home-screen icon title (apple-mobile-web-app-title) was
    # "MEDSIM Device"; now reads "VRAI- MedSim Device".
    assert "VRAI- MedSim Device" in src
    assert 'content="MEDSIM Device"' not in src


def test_device_join_template_carries_brand() -> None:
    p = (Path(__file__).resolve().parents[2]
         / "portal" / "templates" / "device_join.html")
    src = p.read_text(encoding="utf-8")
    assert BRAND in src
    assert "MEDSIM v6" not in src


def test_device_pia_template_carries_brand() -> None:
    p = (Path(__file__).resolve().parents[2]
         / "portal" / "templates" / "device_pia.html")
    src = p.read_text(encoding="utf-8")
    assert BRAND in src


def test_nurse_station_template_carries_brand() -> None:
    p = (Path(__file__).resolve().parents[2]
         / "portal" / "templates" / "nurse_station.html")
    src = p.read_text(encoding="utf-8")
    assert BRAND in src


def test_qr_print_sheet_carries_brand() -> None:
    """The printable QR sheet (M41) is the operator's primary
    printed artifact. Brand must appear in BOTH the document <title>
    AND the visible header on the printed page."""
    p = (Path(__file__).resolve().parents[2]
         / "portal" / "templates" / "qr_print.html")
    src = p.read_text(encoding="utf-8")
    # Two occurrences: title + brand-title h1.
    assert src.count(BRAND) >= 2
    # Old "Training Bridge MedSim-VRAI" wording must be gone.
    assert "Training Bridge MedSim-VRAI" not in src


# ── 5. Brand renders end-to-end via a live HTTP fetch ──────────────

def test_login_page_renders_brand(client) -> None:
    """Hitting the login page over HTTP should show the new brand."""
    # The client has the auth cookie set, so /portal/home renders.
    r = client.get("/portal/home")
    assert r.status_code == 200
    assert BRAND in r.text


def test_qr_print_sheet_renders_brand_via_http(client) -> None:
    """Live render of the printable QR sheet must include the brand.
    The route is scoped by query param, not path segment."""
    _start_room(client)
    r = client.get("/portal/control/qr_print")
    assert r.status_code == 200
    assert BRAND in r.text
    assert "Training Bridge MedSim-VRAI" not in r.text
