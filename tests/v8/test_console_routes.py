"""FR-011 G3 — Mission Control shell + classic fallback.

The 3-mode GUI shell renders auth'd, keeps a 'switch to classic control room'
escape on every screen, carries the mode in the URL, and ships a client that
polls the G2 readiness API. The shell is a NEW front-end over the SAME portal
APIs — these tests pin the contract that lets G4-G6 fill the panels."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TEST_PASSWORD = "test_passwd_xyz_8chars"
_STATIC = Path(__file__).resolve().parents[2] / "portal" / "static"


def _ensure_vault():
    from portal import credentials
    vault_path = Path.home() / ".medsim" / "vault.enc"
    if vault_path.exists():
        try:
            credentials.unlock(TEST_PASSWORD)
            return
        except ValueError:
            vault_path.unlink()
    credentials.initialize(TEST_PASSWORD)


@pytest.fixture
def client():
    _ensure_vault()
    from portal import server
    c = TestClient(server.app)
    c.post("/login", data={"password": TEST_PASSWORD})
    return c


def test_console_requires_auth():
    from portal import server
    c = TestClient(server.app)
    r = c.get("/portal/console")
    assert r.status_code == 401          # Depends(require_vault), like every portal page


def test_console_renders_three_mode_shell(client):
    r = client.get("/portal/console")
    assert r.status_code == 200
    html = r.text
    # the three modes + their tabs
    for mode in ("setup", "operate", "debrief"):
        assert f'data-tab="{mode}"' in html
        assert f'data-panel="{mode}"' in html
    assert "Operate" in html and "Debrief" in html


def test_classic_control_fallback_present(client):
    """Hard requirement: the classic control room is one click away on every screen."""
    html = client.get("/portal/console").text
    assert "/portal/control/setup" in html
    assert "classic control room" in html.lower()


def test_readiness_bar_and_client_present(client):
    html = client.get("/portal/console").text
    assert 'id="readiness-bar"' in html          # the persistent readiness bar
    assert "/static/console.js" in html          # ...and the client that drives it
    assert "/static/console.css" in html


def test_mode_carried_in_url(client):
    # server honours ?mode= by setting the root [data-mode] (CSS shows that panel)
    assert 'class="console" data-mode="setup"' in client.get("/portal/console?mode=setup").text
    assert 'class="console" data-mode="operate"' in client.get("/portal/console?mode=operate").text
    # default + invalid both fall back to a valid mode, never error
    assert 'class="console" data-mode="operate"' in client.get("/portal/console").text
    assert client.get("/portal/console?mode=bogus").status_code == 200


def test_client_polls_the_g2_readiness_api():
    js = (_STATIC / "console.js").read_text()
    assert "/api/control/readiness" in js                 # GET poll
    assert "/api/control/readiness/action" in js          # POST one-tap actions


def test_console_css_drives_panel_visibility_from_root_mode():
    """Panels show from the root [data-mode] so the server-rendered ?mode= is
    correct before JS runs (progressive enhancement)."""
    css = (_STATIC / "console.css").read_text()
    assert '.console[data-mode="operate"] .console-panel[data-panel="operate"]' in css


# ── G4 — Operate cockpit ──────────────────────────────────────────────────────

def test_operate_cockpit_mounts_present(client):
    html = client.get("/portal/console").text
    assert 'id="readiness-tiles"' in html       # the tile grid
    assert 'id="resume-banner"' in html         # the Resume banner
    assert 'id="test-all-btn"' in html          # Test all
    for mount in ("mc-meds", "mc-errors", "mc-handoff"):
        assert mount in html                    # live mgmt cards


def test_resume_endpoint_requires_auth():
    from portal import server
    c = TestClient(server.app)
    assert c.post("/api/control/session/resume").status_code == 401


def test_resume_endpoint_restores_last_session(monkeypatch):
    """The cockpit's Resume banner posts here; it must restore the G1 snapshot."""
    from portal import server, ehr_db, control_session, control_room, session_state
    monkeypatch.setattr(ehr_db, "_conn", lambda: None)        # in-memory store, no real DB
    ehr_db._mem_session_state = None
    _ensure_vault()
    c = TestClient(server.app)
    c.post("/login", data={"password": TEST_PASSWORD})
    sess = control_session.create_session(
        scenario_name="ED · Resume me", selected_personas=["P-014"],
        selected_modules=[], api_key="k", ehr_id="cyrus")
    sid = sess.id
    assert session_state.persist() is True
    control_room.end_active_room()
    assert control_session.get_active() is None
    try:
        r = c.post("/api/control/session/resume")
        assert r.status_code == 200 and r.json()["ok"] is True
        restored = control_session.get_active()
        assert restored is not None and restored.id == sid
    finally:
        control_room.end_active_room()
        ehr_db._mem_session_state = None


def test_resume_endpoint_ok_false_when_nothing_to_resume(monkeypatch):
    from portal import server, ehr_db, control_session
    monkeypatch.setattr(ehr_db, "_conn", lambda: None)
    ehr_db._mem_session_state = None
    _ensure_vault()
    c = TestClient(server.app)
    c.post("/login", data={"password": TEST_PASSWORD})
    assert control_session.get_active() is None
    r = c.post("/api/control/session/resume")
    assert r.status_code == 200 and r.json()["ok"] is False


def test_cockpit_client_wires_resume_tiles_and_testall():
    js = (_STATIC / "console.js").read_text()
    assert "/api/control/session/resume" in js   # Resume banner -> POST
    assert "readiness-tiles" in js               # tile grid render target
    assert "test_all" in js                      # Test all action id
    assert "renderResumeBanner" in js and "renderTiles" in js


# ── G5 — Launch Wizard ────────────────────────────────────────────────────────

def _bootstrap(html: str):
    import json
    import re
    m = re.search(r'<script id="console-bootstrap"[^>]*>(.*?)</script>', html, re.S)
    return json.loads(m.group(1)) if m else None


def test_wizard_mounts_and_bootstrap_present(client):
    html = client.get("/portal/console").text
    for mount in ('id="launch-wizard"', 'id="wiz-ehr"', 'id="wiz-bed-count"',
                  'id="wiz-bed-scenarios"', 'id="wiz-personas"', 'id="wiz-launch"',
                  'id="console-bootstrap"'):
        assert mount in html


def test_patients_rooms_step_comes_first(client):
    """Per field feedback: patients & rooms must precede scenario + characters."""
    html = client.get("/portal/console").text
    first_pill = html.split('data-pill="1"', 1)[1].split("</li>", 1)[0]
    assert "Patients" in first_pill                         # step 1 is patients & rooms
    # patients pill precedes the scenario pill, which precedes the characters pill
    assert html.find('data-pill="1"') < html.find("Scenario") < html.find("Characters")


def test_ehr_options_rendered_server_side(client):
    """The one session-wide EHR picker is rendered server-side, so it works even
    with stale/blocked console.js (the original 'no place to select the EHR' fix)."""
    html = client.get("/portal/console").text
    for ehr in ("helix", "cyrus", "meridian"):
        assert 'value="%s"' % ehr in html                  # EHR <option>s present
    assert "Helix Health" in html
    assert "fillOptions" not in (_STATIC / "console.js").read_text()


def test_bootstrap_carries_full_sample_roster(client):
    """The wizard auto-fills from the SAME sample catalog the classic room uses,
    and each sample carries its FULL persona roster (not just a seed)."""
    boot = _bootstrap(client.get("/portal/console").text)
    assert boot is not None
    assert boot["samples"] and boot["ehrs"] and boot["personas"]
    # every sample exposes a roster, and at least one is a real multi-persona roster
    assert all("personas" in s for s in boot["samples"])
    assert any(len(s.get("personas") or []) >= 4 for s in boot["samples"])
    # EHRs carry id+name and a default is named
    assert all({"id", "name"} <= set(e) for e in boot["ehrs"])
    assert boot["default_ehr"]
    # personas trimmed to picker fields
    assert all({"id", "name"} <= set(p) for p in boot["personas"])


def test_wizard_posts_the_same_body_as_classic_start():
    """No divergent submission: the wizard builds FormData with exactly the fields
    POST /portal/control/start consumes, against that same (unchanged) endpoint."""
    js = (_STATIC / "console.js").read_text()
    assert '"/portal/control/start"' in js
    for field in ("scenario_name", "scenario_notes", "scenario_text", "program_id",
                  "week", "modules", "personas", "avatar_personas", "ehr_id"):
        assert '"' + field + '"' in js
    # the gate rule exists and a red check blocks launch
    assert "function launchAllowed" in js and '"red"' in js


def test_bed_count_and_per_bed_scenario_present(client):
    """One flow, no single/multi toggle: a bed count defaulting to 1, plus the
    per-bed scenario container that the next step fills."""
    html = client.get("/portal/console").text
    assert 'id="wiz-bed-count"' in html and 'id="wiz-bed-scenarios"' in html
    assert 'name="wiz-mode"' not in html                          # toggle removed
    assert 'min="1" max="12" value="1"' in html                  # defaults to one bed


def test_bootstrap_samples_carry_a_derived_patient(client):
    """Patients come from scenario selection: each sample exposes its patient_id
    (the roleGroup=Patient persona), so picking a bed's scenario picks its patient."""
    boot = _bootstrap(client.get("/portal/console").text)
    sepsis = [s for s in boot["samples"] if s["id"] == "ed-sepsis-delirium"]
    assert sepsis and sepsis[0]["patient_id"] == "P-014"     # Mr. Hayes
    assert all(s.get("patient_id") for s in boot["samples"])


def test_devices_step_present(client):
    html = client.get("/portal/console").text
    assert 'data-pill="4"' in html and "Devices" in html      # the 5-step wizard
    assert 'id="wiz-devices"' in html and 'id="wiz-group"' in html
    assert 'id="wiz-nurse-station"' in html                    # group resource


def test_bootstrap_carries_device_catalog(client):
    """Devices step reuses the SAME registry: 7 kinds, grouped Basic/Advanced,
    each with a default model to mint at launch."""
    boot = _bootstrap(client.get("/portal/console").text)
    devs = {d["kind"]: d for d in boot["devices"]}
    assert set(devs) == {"pump_iv", "pump_enteral", "cabinet", "patient_integrated_alarm",
                         "telemetry_monitor", "vent_monitor", "ventilator"}
    assert devs["telemetry_monitor"]["group"] == "Advanced"
    assert devs["pump_iv"]["group"] == "Basic"
    assert devs["telemetry_monitor"]["model"] == "generic_tele"   # default model present
    assert all(d["model"] for d in boot["devices"])


def test_client_mints_devices_at_launch():
    js = (_STATIC / "console.js").read_text()
    assert "/api/device/register" in js                       # per-bed device minting
    assert "/portal/control/launch_nurse_station" in js       # group nursing station
    for fn in ("function rebuildDevices", "function bedDevices", "function registerDevices"):
        assert fn in js


def test_client_wires_unified_room_flow():
    js = (_STATIC / "console.js").read_text()
    assert "/api/room/start" in js and "/portal/control/start" in js   # >1 bed vs 1 bed
    for fn in ("function launchRoom", "function rebuildBedScenarios", "function isMulti",
               "function validBeds", "function modeValid", "function bedCount",
               "function prefillCharacters"):
        assert fn in js
    assert "setMode" not in js                      # single/multi toggle machinery removed
    assert "persona_id" in js and "patient_id" in js and "encounters" in js


def test_multi_patient_room_launch_creates_room(monkeypatch):
    """End-to-end: a multi-bed payload posted to /api/room/start — one shared EHR
    for the session, one patient per bed — creates a room with one encounter/bed."""
    from portal import server, ehr_db, control_room, auth
    monkeypatch.setattr(ehr_db, "_conn", lambda: None)
    ehr_db._mem_session_state = None
    _ensure_vault()
    c = TestClient(server.app)
    c.post("/login", data={"password": TEST_PASSWORD})
    for v in auth._active_vaults.values():          # in-memory only — no vault-file write
        v._data["ANTHROPIC_API_KEY"] = "dummy-key"
    if control_room.get_active_room() is not None:
        control_room.end_active_room()
    try:
        r = c.post("/api/room/start", json={
            "label": "Test ward",
            "encounters": [
                {"scenario_name": "Bed 1 · ED sepsis", "persona_id": "P-014", "ehr_id": "cyrus"},
                {"scenario_name": "Bed 2 · Geri GOC", "persona_id": "P-013", "ehr_id": "cyrus"},
            ],
        })
        assert r.status_code == 200 and r.json()["ok"] is True
        room = control_room.get_active_room()
        assert room is not None and len(room.encounters) == 2
        encs = room.encounters.values() if hasattr(room.encounters, "values") else room.encounters
        assert {e.ehr_id for e in encs} == {"cyrus"}          # one EHR for the session
    finally:
        if control_room.get_active_room() is not None:
            control_room.end_active_room()
        ehr_db._mem_session_state = None


def test_wizard_launch_creates_session_like_classic(monkeypatch):
    """End-to-end: a wizard-shaped FormData posted to the classic start creates the
    session and returns the live-ops redirect — proving body-equivalence."""
    from portal import server, ehr_db, control_session, auth
    monkeypatch.setattr(ehr_db, "_conn", lambda: None)
    ehr_db._mem_session_state = None
    _ensure_vault()
    c = TestClient(server.app)
    c.post("/login", data={"password": TEST_PASSWORD})
    for v in auth._active_vaults.values():        # in-memory only — no vault-file write
        v._data["ANTHROPIC_API_KEY"] = "dummy-key"
    if control_session.get_active() is not None:
        control_session.end_active()
    try:
        r = c.post("/portal/control/start", data={
            "scenario_name": "Wizard launch test",
            "personas": ["P-014", "P-001"],
            "avatar_personas": ["P-014"],
            "ehr_id": "cyrus",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True and data["redirect_url"] == "/portal/control/ops"
        restored = control_session.get_active()
        assert restored is not None
        assert set(restored.selected_personas) == {"P-014", "P-001"}
    finally:
        if control_session.get_active() is not None:
            control_session.end_active()
        ehr_db._mem_session_state = None
