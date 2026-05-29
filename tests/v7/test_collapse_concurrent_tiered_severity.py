"""M54 — Threshold panel collapse + concurrent tiered repeating
audio + magnitude-based threshold severity.

Operator: "Nursing station- alarm threshold click to drop down and
open, click header of Alarm threshold and have it roll up. Alarms
need to run concurrently. For higher priority alarms (low- medium-
High) the alarms sound more frequently. For example the sound loop
for a code blue should run continuously with minimal time gap
running the sound loop. Low level alarms sound when parameters are
10% below lower threshold or 10% Higher than upper threshold.
Medium is between 10% and 20% of threshold limits and high if above
20% of the threshold limits"

Delivered:
  1. Nursing-station threshold section becomes collapsible. Default
     collapsed; clicking the H2 header toggles.
  2. Alarm-audio cadence reworked into four tiers based on
     `audio_priority` (with `severity` overriding to "danger"):
       danger  2500 ms (near-continuous — code blue, dangerous rhythm)
       high    5000 ms (critical)
       medium 15000 ms (warning)
       low    35000 ms (info)
     A 700 ms fast ticker re-evaluates the cached alarm list so the
     danger tier truly fires at 2.5 s instead of being capped by the
     3 s state poll. Each alarm gets its own `new Audio` so multiple
     alarms play CONCURRENTLY.
  3. Threshold-source severity now scales with the MAGNITUDE of the
     breach: 0-10% past bound → "info", 10-20% → "warning",
     ≥20% → "critical". Pre-M54: fixed severity per metric.
  4. code.blue scene + code_blue_button promoted to severity="danger"
     so they get top sort position + near-continuous audio cadence.
  5. PIA cascade audio cadence dropped 8 s → 2.5 s to match.
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
        "label": "M54",
        "encounters": [{"scenario_name": "Bed 1", "persona_id": "P-014",
                         "patient_persona_id": "P-014", "ehr_id": "helix"}],
    })
    assert r.status_code == 200
    return r.json()


# ── 1. Magnitude-based threshold severity ──────────────────────────

def test_low_severity_when_breach_is_under_10_pct(client) -> None:
    """HR.high=100, value=105 → 5% over → info (LOW tier)."""
    from portal import control_room
    body = _start_room(client)
    eid = body["encounters"][0]["encounter_id"]
    client.post("/api/room/alarm_thresholds",
                 json={"hr": {"low": 50, "high": 100}})
    room = control_room.get_active_room()
    room.encounters[eid].telemetry_overrides["hr"] = 105
    alarms = client.get("/api/room/alarms").json()["alarms"]
    hr = next(a for a in alarms if a.get("metric") == "hr")
    assert hr["severity"] == "info"
    # Surface the magnitude so the UI can render a "+5%" badge.
    assert hr["deviation_pct"] == 5.0


def test_warning_severity_between_10_and_20_pct(client) -> None:
    """HR.high=100, value=115 → 15% over → warning (MEDIUM tier)."""
    from portal import control_room
    body = _start_room(client)
    eid = body["encounters"][0]["encounter_id"]
    client.post("/api/room/alarm_thresholds",
                 json={"hr": {"low": 50, "high": 100}})
    room = control_room.get_active_room()
    room.encounters[eid].telemetry_overrides["hr"] = 115
    alarms = client.get("/api/room/alarms").json()["alarms"]
    hr = next(a for a in alarms if a.get("metric") == "hr")
    assert hr["severity"] == "warning"
    assert hr["deviation_pct"] == 15.0


def test_critical_severity_when_breach_above_20_pct(client) -> None:
    """HR.high=100, value=125 → 25% over → critical (HIGH tier)."""
    from portal import control_room
    body = _start_room(client)
    eid = body["encounters"][0]["encounter_id"]
    client.post("/api/room/alarm_thresholds",
                 json={"hr": {"low": 50, "high": 100}})
    room = control_room.get_active_room()
    room.encounters[eid].telemetry_overrides["hr"] = 125
    alarms = client.get("/api/room/alarms").json()["alarms"]
    hr = next(a for a in alarms if a.get("metric") == "hr")
    assert hr["severity"] == "critical"
    assert hr["deviation_pct"] == 25.0


def test_severity_scales_for_below_low_bound(client) -> None:
    """Below-bound breaches also scale by magnitude. HR.low=60,
    value=42 → 18/60 = 30% below → critical."""
    from portal import control_room
    body = _start_room(client)
    eid = body["encounters"][0]["encounter_id"]
    client.post("/api/room/alarm_thresholds",
                 json={"hr": {"low": 60, "high": 100}})
    room = control_room.get_active_room()
    room.encounters[eid].telemetry_overrides["hr"] = 42
    alarms = client.get("/api/room/alarms").json()["alarms"]
    hr = next(a for a in alarms if a.get("metric") == "hr")
    assert hr["severity"] == "critical"


def test_deep_spo2_drop_still_critical(client) -> None:
    """Default SpO2.low=90, value=70 → 22% below → critical."""
    from portal import control_room
    body = _start_room(client)
    eid = body["encounters"][0]["encounter_id"]
    room = control_room.get_active_room()
    room.encounters[eid].telemetry_overrides["spo2"] = 70
    alarms = client.get("/api/room/alarms").json()["alarms"]
    spo2 = next(a for a in alarms if a.get("metric") == "spo2")
    assert spo2["severity"] == "critical"


def test_shallow_spo2_dip_is_info(client) -> None:
    """SpO2.low=90, value=86 → 4/90 = ~4.4% below → info."""
    from portal import control_room
    body = _start_room(client)
    eid = body["encounters"][0]["encounter_id"]
    room = control_room.get_active_room()
    room.encounters[eid].telemetry_overrides["spo2"] = 86
    alarms = client.get("/api/room/alarms").json()["alarms"]
    spo2 = next(a for a in alarms if a.get("metric") == "spo2")
    assert spo2["severity"] == "info"


# ── 2. Code blue promoted to danger ────────────────────────────────

def test_code_blue_scene_is_danger_severity(client) -> None:
    """M54 — code.blue promoted from 'critical' to 'danger' so it
    sorts to the TOP of the alarm board and gets the near-continuous
    audio cadence (same WAV)."""
    body = _start_room(client)
    eid = body["encounters"][0]["encounter_id"]
    r = client.post(f"/api/encounter/{eid}/scene",
                     json={"scene": {"kind": "code.blue"}})
    assert r.status_code == 200
    alarms = client.get("/api/room/alarms").json()["alarms"]
    cb = next(a for a in alarms if a.get("kind") == "code.blue")
    assert cb["severity"] == "danger"


def test_code_blue_audio_url_unchanged() -> None:
    """Same WAV — only the severity / cadence changes."""
    from portal import alarm_sounds
    url = alarm_sounds.audio_url_for({
        "source": "scene", "kind": "code.blue", "severity": "danger",
    })
    assert url and url.endswith("03_code_blue.wav")


def test_code_blue_button_promoted_to_danger() -> None:
    """M29 future-device stub `code_blue_button` follows code.blue."""
    from portal.alarms import _classify
    assert _classify("code_blue_button") == "danger"


# ── 3. Nursing-station JS: tiered cadence + concurrent + ticker ────

def test_nurse_station_js_has_four_cadence_tiers() -> None:
    """AUDIO_REPEAT_MS now carries danger/high/medium/low with the
    danger tier set to the near-continuous 2.5 s."""
    js_path = (
        Path(__file__).resolve().parents[2]
        / "portal" / "static" / "nurse_station.js"
    )
    src = js_path.read_text(encoding="utf-8")
    # The TABLE itself starts at `const AUDIO_REPEAT_MS = {` —
    # earlier occurrences of the symbol are in comment / call sites.
    fn_idx = src.find("const AUDIO_REPEAT_MS")
    assert fn_idx > 0, "AUDIO_REPEAT_MS table not found"
    body = src[fn_idx:fn_idx + 400]
    assert "danger" in body
    assert "2500" in body
    # Other tiers got tightened too (M54 spec).
    assert "5000" in body   # high (was 8000)
    assert "15000" in body  # medium (was 20000)
    assert "35000" in body  # low (was 45000)


def test_nurse_station_js_severity_routes_to_danger_tier() -> None:
    """The dispatcher picks the cadence tier off `severity` first
    (so 'danger' routes to its own bucket even though the WAV
    lookup still treats danger == high)."""
    src = (Path(__file__).resolve().parents[2]
           / "portal" / "static" / "nurse_station.js").read_text("utf-8")
    fn_idx = src.find("function _audioCadenceTier")
    assert fn_idx > 0
    body = src[fn_idx:fn_idx + 400]
    assert "'danger'" in body
    assert "a.severity" in body


def test_nurse_station_js_has_fast_ticker() -> None:
    """A 700 ms ticker re-runs the dispatcher off the cached alarms
    list so the danger 2.5 s cadence isn't capped by the 3 s state
    poll."""
    src = (Path(__file__).resolve().parents[2]
           / "portal" / "static" / "nurse_station.js").read_text("utf-8")
    # The ticker uses setInterval at 700 ms reading from the cache.
    assert "_lastAlarmsForAudio" in src
    assert "700" in src


def test_nurse_station_js_alarms_play_concurrently() -> None:
    """Each iteration creates a fresh `new Audio(...)` and calls
    .play() — independent Audio instances so multiple alarms
    overlap. M54 inline comment names this out explicitly."""
    src = (Path(__file__).resolve().parents[2]
           / "portal" / "static" / "nurse_station.js").read_text("utf-8")
    fn_idx = src.find("function _playNewAlarmSounds")
    body = src[fn_idx:fn_idx + 2000]
    # The dispatcher iterates and creates one Audio per alarm.
    assert "alarms.forEach" in body
    assert "new Audio(url)" in body
    # And the M54 comment captures the concurrency intent so future
    # editors don't accidentally serialise the playback.
    assert "CONCURRENTLY" in body or "concurrently" in body


# ── 4. PIA cascade tightened to 2.5 s ──────────────────────────────

def test_pia_cascade_uses_25s_repeat() -> None:
    src = (Path(__file__).resolve().parents[2]
           / "portal" / "static" / "pia_app.js").read_text("utf-8")
    assert "CASCADE_AUDIO_REPEAT_MS = 2500" in src
    # Old 8 s constant is gone.
    assert "CASCADE_AUDIO_REPEAT_MS = 8000" not in src


# ── 5. Collapsible threshold panel ─────────────────────────────────

def test_threshold_section_renders_collapsed_by_default(client) -> None:
    """Operator wants the threshold panel rolled up by default so
    the alarm board owns the top of the page. Click the H2 to
    expand."""
    _start_room(client)
    r = client.get("/portal/control/launch_nurse_station",
                   follow_redirects=False)
    nurse_url = r.headers["location"]
    html = client.get(nurse_url).text
    # Section has the collapsed class baked in for first paint.
    assert 'class="ns-thresholds ns-collapsed"' in html
    # Header is a real toggle with ARIA attributes.
    assert 'id="ns-thresholds-toggle"' in html
    assert 'aria-expanded="false"' in html
    assert 'aria-controls="ns-thresholds-form"' in html
    # Caret marker for the operator's visual cue.
    assert "ns-thresholds-caret" in html


def test_threshold_panel_js_wires_toggle() -> None:
    src = (Path(__file__).resolve().parents[2]
           / "portal" / "static" / "nurse_station.js").read_text("utf-8")
    # Toggle handler reads the section + the toggle element and
    # flips the `ns-collapsed` class.
    assert "wireThresholdToggle" in src
    assert "ns-thresholds-toggle" in src
    assert "ns-collapsed" in src
    # Keyboard accessibility — space/enter also toggles.
    assert "'Enter'" in src or '"Enter"' in src


def test_threshold_panel_css_hides_form_when_collapsed() -> None:
    css = (Path(__file__).resolve().parents[2]
           / "portal" / "static" / "nurse_station.css").read_text("utf-8")
    assert ".ns-thresholds.ns-collapsed" in css
    # The form is the thing that hides; header stays visible.
    assert ".ns-thresholds.ns-collapsed .ns-thresholds-form" in css
    # Caret rotates when expanded.
    assert "ns-thresholds-caret" in css
