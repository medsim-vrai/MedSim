"""M48 — Operator-settable alarm thresholds + ECG cosmetic fix.

Three pieces verified here:
  1. New GET/POST /api/room/alarm_thresholds round-trip.
  2. Threshold breaches surface on the room alarm feed via the
     existing /api/room/alarms route (alarms.py merges
     threshold-breach alarms with device + scene alarms).
  3. ECG trace styling: thinner stroke + muted color (no glow).
"""
from __future__ import annotations

from pathlib import Path

import pytest


TEST_PASSWORD = "test_passwd_xyz_8chars"
ECG_JS = (
    Path(__file__).resolve().parents[2]
    / "portal" / "static" / "ecg_strip.js"
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


def _start_room(client):
    r = client.post("/api/room/start", json={
        "label": "M48 thresholds",
        "encounters": [
            {"scenario_name": "Bed 1", "persona_id": "P-014",
             "patient_persona_id": "P-014", "personas": ["P-014"],
             "ehr_id": "helix"},
        ],
    })
    assert r.status_code == 200, r.text
    return r.json()


# ── 1. Threshold GET/POST round-trip ────────────────────────────────

def test_thresholds_get_returns_defaults(client) -> None:
    """Brand-new room → /api/room/alarm_thresholds returns the
    dataclass defaults (HR 50-120, SpO2 90-null, RR 8-30, plus
    standard dangerous rhythms)."""
    _start_room(client)
    r = client.get("/api/room/alarm_thresholds")
    assert r.status_code == 200
    t = r.json()["thresholds"]
    assert t["hr"]["low"] == 50 and t["hr"]["high"] == 120
    assert t["spo2"]["low"] == 90 and t["spo2"]["high"] is None
    assert t["rr"]["low"] == 8 and t["rr"]["high"] == 30
    assert "vfib" in t["dangerous_rhythms"]
    assert "asystole" in t["dangerous_rhythms"]
    assert "vtach" in t["dangerous_rhythms"]


def test_thresholds_post_updates_and_persists(client) -> None:
    _start_room(client)
    r = client.post("/api/room/alarm_thresholds", json={
        "hr":   {"low": 55, "high": 110},
        "spo2": {"low": 92, "high": None},
        "rr":   {"low": 10, "high": 28},
        "dangerous_rhythms": ["vfib", "asystole"],
    })
    assert r.status_code == 200, r.text
    # GET reflects the update.
    t = client.get("/api/room/alarm_thresholds").json()["thresholds"]
    assert t["hr"]["high"] == 110
    assert t["rr"]["low"] == 10
    assert set(t["dangerous_rhythms"]) == {"vfib", "asystole"}


def test_thresholds_post_rejects_non_numeric_bound(client) -> None:
    _start_room(client)
    r = client.post("/api/room/alarm_thresholds", json={
        "hr": {"low": "not-a-number", "high": 120},
    })
    assert r.status_code == 400


# ── 2. Threshold breaches show up on /api/room/alarms ────────────────

def test_threshold_breach_surfaces_on_room_alarms(client) -> None:
    """Set HR.high=80, force the encounter's HR override to 130 →
    /api/room/alarms includes a threshold-source 'Heart rate high'
    alarm."""
    from portal import control_room
    body = _start_room(client)
    eid = body["encounters"][0]["encounter_id"]
    # Tight HR ceiling.
    client.post("/api/room/alarm_thresholds",
                 json={"hr": {"low": 50, "high": 80}})
    # Force the encounter's HR via the M25 override route.
    room = control_room.get_active_room()
    room.encounters[eid].telemetry_overrides["hr"] = 130
    r = client.get("/api/room/alarms")
    assert r.status_code == 200
    alarms = r.json().get("alarms", [])
    threshold_alarms = [a for a in alarms if a.get("source") == "threshold"]
    assert len(threshold_alarms) >= 1
    breach = threshold_alarms[0]
    assert breach["metric"] == "hr"
    assert "Heart rate" in breach["label"]
    assert "130" in breach["label"]
    # M54 — severity now scales with magnitude of breach. HR.high=80,
    # value=130 → 50/80 = 62.5% above → "critical" (>=20% past bound).
    # Pre-M54 this was a fixed "warning" for HR. Test renamed to
    # cover the deep-breach case.
    assert breach["severity"] == "critical"


def test_threshold_breach_spo2_deep_drop_is_critical(client) -> None:
    """SpO2 deep drop (>20% below threshold) is critical. M54 — was
    a fixed 'critical' for any SpO2 breach; now severity scales with
    magnitude. Default SpO2.low=90; force to 70 → (90-70)/90 = 22%
    below, satisfies the >=20% rule → critical."""
    from portal import control_room
    body = _start_room(client)
    eid = body["encounters"][0]["encounter_id"]
    room = control_room.get_active_room()
    room.encounters[eid].telemetry_overrides["spo2"] = 70
    r = client.get("/api/room/alarms")
    alarms = [a for a in r.json().get("alarms", [])
              if a.get("source") == "threshold" and a.get("metric") == "spo2"]
    assert alarms
    assert alarms[0]["severity"] == "critical"


def test_threshold_breach_below_low_bound(client) -> None:
    """An HR below the LOW bound also raises an alarm."""
    from portal import control_room
    body = _start_room(client)
    eid = body["encounters"][0]["encounter_id"]
    client.post("/api/room/alarm_thresholds",
                 json={"hr": {"low": 60, "high": 100}})
    room = control_room.get_active_room()
    room.encounters[eid].telemetry_overrides["hr"] = 40
    alarms = client.get("/api/room/alarms").json().get("alarms", [])
    hr_alarms = [a for a in alarms
                  if a.get("source") == "threshold" and a.get("metric") == "hr"]
    assert hr_alarms
    assert "low" in hr_alarms[0]["label"].lower()


def test_threshold_dangerous_rhythm_raises_when_ecg_enabled(client) -> None:
    """Encounter's `ecg_rhythm_id` is checked against the dangerous-
    rhythms list — but only when `ecg_enabled=True`. Operator
    toggles the strip off → no rhythm alarm even if it's on the
    list.

    M50 — Dangerous waveforms now use severity="danger" (rank 4)
    instead of "critical" (rank 3) so they sort to the TOP of the
    alarm board.
    """
    from portal import control_room
    body = _start_room(client)
    eid = body["encounters"][0]["encounter_id"]
    room = control_room.get_active_room()
    enc = room.encounters[eid]
    enc.ecg_enabled = True
    enc.ecg_rhythm_id = "vfib"
    r = client.get("/api/room/alarms")
    rhythm_alarms = [a for a in r.json().get("alarms", [])
                     if a.get("metric") == "rhythm"]
    assert rhythm_alarms
    assert rhythm_alarms[0]["severity"] == "danger"
    # Disable the strip — alarm goes away on the next read.
    enc.ecg_enabled = False
    r = client.get("/api/room/alarms")
    rhythm_alarms = [a for a in r.json().get("alarms", [])
                     if a.get("metric") == "rhythm"]
    assert not rhythm_alarms


# ── 3. ECG trace cosmetic fix ────────────────────────────────────────

def test_ecg_trace_uses_thinner_stroke_and_muted_color() -> None:
    """Pre-M48: stroke-width 1.4 + saturated `#5dffae` neon → looked
    like the trace was glowing. Post-M48: 0.7 stroke + muted
    `#7fc99a` matches real bedside monitor appearance."""
    src = ECG_JS.read_text(encoding="utf-8")
    # Stroke width is now 0.7.
    assert "stroke-width', '0.7'" in src
    # No more 1.4 stroke-width.
    assert "stroke-width', '1.4'" not in src
    # Color is the muted green.
    assert "#7fc99a" in src
    # The saturated neon is gone from setAttribute calls (it can still
    # appear in the explanatory comment — we check only the live SVG
    # attribute setters).
    assert "setAttribute('stroke', '#5dffae'" not in src
    assert "setAttribute('fill', '#5dffae'" not in src


def test_ecg_canvas_color_matches_trace() -> None:
    """The ECG canvas text color (used by the 'ECG library loads…'
    placeholder) also got muted to match the new trace color."""
    css_path = (
        Path(__file__).resolve().parents[2]
        / "portal" / "static" / "encounter_console.css"
    )
    css = css_path.read_text(encoding="utf-8")
    assert ".ecg-canvas" in css
    assert "color: #7fc99a" in css


# ── Per-metric refresh cadence (M48 part 3) ─────────────────────────

def test_encounter_console_js_has_per_metric_cadence_table() -> None:
    """The telemetry display now commits per-metric on a cadence:
    HR/SpO2 every 10s, RR every 30s, temp every minute, BP every
    2 minutes. Operator inject/override forces immediate refresh
    because the latest server value differs from the last committed."""
    js_path = (
        Path(__file__).resolve().parents[2]
        / "portal" / "static" / "encounter_console.js"
    )
    src = js_path.read_text(encoding="utf-8")
    # Cadence map exists with the expected per-metric intervals.
    assert "METRIC_CADENCE_MS" in src
    cad_idx = src.find("METRIC_CADENCE_MS")
    cad_block = src[cad_idx:cad_idx + 600]
    assert "spo2" in cad_block and "10_000" in cad_block
    assert "rr" in cad_block and "30_000" in cad_block
    assert "temp_f" in cad_block and "60_000" in cad_block
    assert "sbp" in cad_block and "120_000" in cad_block
    # The _maybeCommit function lives in the same module.
    assert "function _maybeCommit" in src
    # Display reads committed values, not raw `t.hr` etc.
    assert "_committed.hr" in src
    assert "_committed.spo2" in src


# ── Nurse Station UI ────────────────────────────────────────────────

def test_nurse_station_renders_threshold_form(client) -> None:
    """Nurse Station page carries the threshold-settings card with
    inputs for HR/SpO2/RR + checkboxes for dangerous rhythms."""
    from portal import auth as _auth
    body = _start_room(client)
    # Have to register as a nurse-station student first (M27 flow).
    r = client.get("/portal/control/launch_nurse_station",
                   follow_redirects=False)
    assert r.status_code == 303
    nurse_url = r.headers["location"]
    r = client.get(nurse_url)
    assert r.status_code == 200
    html = r.text
    assert 'id="ns-thresholds"' in html
    assert 'id="th-hr-low"' in html
    assert 'id="th-hr-high"' in html
    assert 'id="th-spo2-low"' in html
    assert 'id="th-rr-low"' in html
    # Dangerous-rhythm checkboxes are present with data-danger attrs.
    assert 'data-danger="vfib"' in html
    assert 'data-danger="asystole"' in html
    assert 'data-danger="vtach"' in html
