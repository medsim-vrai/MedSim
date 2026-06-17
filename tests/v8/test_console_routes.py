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
                  'id="wiz-bed-scenarios"', 'id="wiz-scenario-chars"', 'id="wiz-shared-chars"',
                  'id="wiz-launch"', 'id="console-bootstrap"'):
        assert mount in html


def test_patients_rooms_step_comes_first(client):
    """Per field feedback: patients & rooms must precede scenario + characters."""
    html = client.get("/portal/console").text
    first_pill = html.split('data-pill="1"', 1)[1].split("</li>", 1)[0]
    assert "Patients" in first_pill                         # step 1 is patients & rooms
    # patients pill precedes the scenario pill, which precedes the common-characters pill
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
    assert 'id="wiz-devices"' in html and 'id="wiz-common"' in html
    assert 'id="wiz-nurse-station"' in html                    # common resource


def test_bootstrap_carries_device_catalog(client):
    """Devices step reuses the SAME registry: 7 kinds, grouped Basic/Advanced,
    each with a default model to mint at launch; med cart flagged common; the PIA
    relabeled to the call/intercom/alarm name."""
    boot = _bootstrap(client.get("/portal/console").text)
    devs = {d["kind"]: d for d in boot["devices"]}
    assert set(devs) == {"pump_iv", "pump_enteral", "cabinet", "patient_integrated_alarm",
                         "telemetry_monitor", "vent_monitor", "ventilator"}
    assert devs["telemetry_monitor"]["group"] == "Advanced"
    assert devs["pump_iv"]["group"] == "Basic"
    assert devs["telemetry_monitor"]["model"] == "generic_tele"   # default model present
    assert all(d["model"] for d in boot["devices"])
    assert devs["cabinet"]["common"] is True and devs["cabinet"]["name"] == "Med cart"
    assert devs["patient_integrated_alarm"]["name"] == "Integrated Com & Alarm"
    assert devs["patient_integrated_alarm"]["common"] is False     # PIA stays per-bed


def test_common_devices_section_present(client):
    html = client.get("/portal/console").text
    assert "Scenario characters" in html and "Shared characters" in html   # two character sections
    for mount in ('id="wiz-common"', 'id="wiz-med-cart"', 'id="wiz-med-cart-mars"',
                  'id="wiz-ehr-terminal"', 'id="wiz-nurse-station"', 'id="wiz-ehr-confirm-name"'):
        assert mount in html
    assert "medical records" in html.lower()                      # patient-in-records confirmation


def test_client_wires_common_devices():
    js = (_STATIC / "console.js").read_text()
    assert "/api/room/med_cart/register" in js                    # shared cart linked to beds
    assert "/launch_ehr" in js                                    # medical-records terminal
    assert "/portal/control/launch_nurse_station" in js           # nursing station
    assert "function launchRoomCommon" in js and "function commonPlan" in js
    assert "!d.common" in js                                       # med cart excluded from per-bed


def test_client_mints_devices_at_launch():
    js = (_STATIC / "console.js").read_text()
    assert "/api/device/register" in js                       # per-bed device minting
    assert "/portal/control/launch_nurse_station" in js       # group nursing station
    for fn in ("function rebuildDevices", "function bedDevices", "function registerDevices"):
        assert fn in js


def test_room_start_stores_shared_personas_and_qr_sheet_groups(monkeypatch):
    """room.shared_personas is stored, and the QR sheet groups patient items under
    each character + prints common characters (avatars/voice) and common devices."""
    from portal import server, ehr_db, control_room, auth
    monkeypatch.setattr(ehr_db, "_conn", lambda: None)
    ehr_db._mem_session_state = None
    _ensure_vault()
    c = TestClient(server.app)
    c.post("/login", data={"password": TEST_PASSWORD})
    for v in auth._active_vaults.values():
        v._data["ANTHROPIC_API_KEY"] = "dummy-key"
    if control_room.get_active_room() is not None:
        control_room.end_active_room()
    try:
        r = c.post("/api/room/start", json={
            "label": "Ward", "shared_personas": ["P-001"],   # Dr. Reyes shared
            "encounters": [
                {"scenario_name": "Bed 1", "persona_id": "P-014",
                 "personas": ["P-014", "P-004", "P-001"], "ehr_id": "cyrus"},  # P-004 = bed cast
                {"scenario_name": "Bed 2", "persona_id": "P-013",
                 "personas": ["P-013", "P-001"], "ehr_id": "cyrus"},
            ]})
        assert r.status_code == 200 and r.json()["ok"] is True
        room = control_room.get_active_room()
        assert room.shared_personas == ["P-001"]
        html = c.get("/portal/control/qr_print").text
        assert "Common characters" in html and "Dr. Reyes" in html        # shared cast, common
        assert "Common devices" in html and "Nursing Station" in html     # nursing station = common
        assert "Scenario characters" in html and "Charge Nurse Kim" in html  # per-bed cast
        assert "Mr. Hayes" in html                                        # patient heading
        assert "/qr/face/P-001.svg" in html                               # avatar/voice QR
    finally:
        if control_room.get_active_room() is not None:
            control_room.end_active_room()
        ehr_db._mem_session_state = None


def test_qr_sheet_numbers_duplicate_scenario_chars(monkeypatch):
    """V1..Vn on the live QR sheet: a non-shared character in two beds' scenarios
    prints as distinct people (· V1 / · V2)."""
    from portal import server, ehr_db, control_room, auth
    monkeypatch.setattr(ehr_db, "_conn", lambda: None)
    ehr_db._mem_session_state = None
    _ensure_vault()
    c = TestClient(server.app)
    c.post("/login", data={"password": TEST_PASSWORD})
    for v in auth._active_vaults.values():
        v._data["ANTHROPIC_API_KEY"] = "dummy-key"
    if control_room.get_active_room() is not None:
        control_room.end_active_room()
    try:
        r = c.post("/api/room/start", json={        # P-004 in BOTH beds, NOT shared
            "label": "Ward",
            "encounters": [
                {"scenario_name": "Bed 1", "persona_id": "P-014",
                 "personas": ["P-014", "P-004"], "ehr_id": "cyrus"},
                {"scenario_name": "Bed 2", "persona_id": "P-013",
                 "personas": ["P-013", "P-004"], "ehr_id": "cyrus"},
            ]})
        assert r.status_code == 200 and r.json()["ok"] is True
        html = c.get("/portal/control/qr_print").text
        assert "Charge Nurse Kim · V1" in html and "Charge Nurse Kim · V2" in html
    finally:
        if control_room.get_active_room() is not None:
            control_room.end_active_room()
        ehr_db._mem_session_state = None


def test_client_builds_shared_cast():
    """FR-007: the non-patient checked characters become a universal cast added to
    every bed's roster; client sends each encounter a `personas` roster."""
    js = (_STATIC / "console.js").read_text()
    for fn in ("function sharedCast", "function isPatientPersona"):
        assert fn in js
    assert "personas: roster" in js                    # each bed gets patient + shared roster
    assert "shared_personas: shared" in js             # shared cast sent to room/start (room-level)
    html = (_STATIC.parent / "templates" / "console.html").read_text()
    assert "universal" in html.lower()                 # the Characters-step hint


def test_room_start_shares_cast_across_every_bed(monkeypatch):
    """FR-007 end-to-end (no new backend): a per-encounter `personas` roster of
    [patient + shared clinician] lands in each bed's selected_personas, which is
    what runtime reads to make the shared character reachable at that bed."""
    from portal import server, ehr_db, control_room, auth
    monkeypatch.setattr(ehr_db, "_conn", lambda: None)
    ehr_db._mem_session_state = None
    _ensure_vault()
    c = TestClient(server.app)
    c.post("/login", data={"password": TEST_PASSWORD})
    for v in auth._active_vaults.values():
        v._data["ANTHROPIC_API_KEY"] = "dummy-key"
    if control_room.get_active_room() is not None:
        control_room.end_active_room()
    try:
        r = c.post("/api/room/start", json={
            "label": "Test ward",
            "encounters": [
                {"scenario_name": "Bed 1", "persona_id": "P-014",
                 "personas": ["P-014", "P-001"], "ehr_id": "cyrus"},   # P-001 = shared doctor
                {"scenario_name": "Bed 2", "persona_id": "P-013",
                 "personas": ["P-013", "P-001"], "ehr_id": "cyrus"},
            ],
        })
        assert r.status_code == 200 and r.json()["ok"] is True
        room = control_room.get_active_room()
        encs = list(room.encounters.values() if hasattr(room.encounters, "values") else room.encounters)
        assert len(encs) == 2
        for e in encs:                                   # the shared doctor is at every bed
            assert "P-001" in e.selected_personas
        assert {e.patient_persona_id for e in encs} == {"P-014", "P-013"}   # patients still per-bed
    finally:
        if control_room.get_active_room() is not None:
            control_room.end_active_room()
        ehr_db._mem_session_state = None


def test_ecosystem_board_present(client):
    """G6: a Board view of the SAME setup state — 3 layers + a launch bar + the
    Wizard|Board toggle."""
    html = client.get("/portal/console").text
    assert 'data-view="wizard"' in html and 'data-view="board"' in html   # the toggle
    for mount in ('id="setup-wizard-view"', 'id="setup-board-view"',
                  'id="board-scenario"', 'id="board-shared"',
                  'id="board-resources"', 'id="board-rooms"', 'id="board-launch-btn"'):
        assert mount in html


def test_cockpit_wires_resumed_note():
    """G7 — the cockpit confirms an auto-restored session."""
    html = (_STATIC.parent / "templates" / "console.html").read_text()
    assert 'id="resumed-note"' in html
    js = (_STATIC / "console.js").read_text()
    assert "function renderResumedNote" in js and "renderResumedNote(snap)" in js


def test_scenario_character_variants():
    """Duplicate-titled scenario characters (e.g. a 'concerned wife' in two beds)
    get V1..Vn designations so each is unique to its patient — never shared."""
    js = (_STATIC / "console.js").read_text()
    assert "function scenarioCharList" in js
    assert '"V" + nameSeen[nm]' in js          # V1..Vn numbering for recurring names
    assert "scenarioCharList()" in js          # used by the wizard + board scenario layer


def test_avatar_hardware_info_and_audio_default(client):
    """Audio-only is the default; an info disclosure explains the avatar rig's
    hardware (so instructors understand the cost before opting in)."""
    html = client.get("/portal/console").text
    assert "audio-only" in html.lower()                     # default stated in the UI
    assert "Avatar hardware" in html and "WebGPU" in html   # the info disclosure


def test_board_inline_popover_editing():
    """G6 polish — board cards open an inline edit popover (bed scenario, EHR,
    nursing station) that drives the live wizard control, not just a jump."""
    js = (_STATIC / "console.js").read_text()
    for fn in ("function openBoardPopover", "function bedScenarioPopover",
               "function ehrPopover", "function nursePopover"):
        assert fn in js
    html = (_STATIC.parent / "templates" / "console.html").read_text()
    assert 'id="board-popover"' in html


def test_board_shares_the_wizard_builder():
    """No logic divergence: the board reads the wizard's state and its Launch reuses
    the same launchScenario (it does not post via a separate path)."""
    js = (_STATIC / "console.js").read_text()
    for fn in ("function renderBoard", "function setView", "function boardCard"):
        assert fn in js
    # board launch is wired to the shared launchScenario, not a new launcher
    assert 'boardLaunch.addEventListener("click", launchScenario)' in js
    # the board reads the same state helpers as the wizard
    assert "sharedCast()" in js and "bedScenarios()" in js and "bedDevices()" in js


def test_room_aware_system_prompt():
    """FR-007 v2 — a shared character's prompt lists EVERY bed's patient, so one
    instance answers across the room."""
    from portal import runtime
    sp = runtime._build_system_prompt(
        {"name": "Dr. Patel", "role": "Hospitalist"},
        {"name": "Ward", "room_patients": [
            {"label": "Bed 1 — Hayes", "history": "septic"},
            {"label": "Bed 2 — Diaz", "history": "postop"}]})
    assert "PATIENTS IN THIS ROOM" in sp
    assert "Bed 1 — Hayes" in sp and "Bed 2 — Diaz" in sp


def test_shared_station_is_room_scoped(monkeypatch):
    """FR-007 v2 — one room-level station per shared persona (idempotent), with a
    LAN-reachable chat surface + a room-scoped turn guard."""
    from portal import server, ehr_db, control_room, auth
    monkeypatch.setattr(ehr_db, "_conn", lambda: None)
    ehr_db._mem_session_state = None
    _ensure_vault()
    c = TestClient(server.app)
    c.post("/login", data={"password": TEST_PASSWORD})
    for v in auth._active_vaults.values():
        v._data["ANTHROPIC_API_KEY"] = "dummy-key"
    if control_room.get_active_room() is not None:
        control_room.end_active_room()
    try:
        c.post("/api/room/start", json={
            "label": "Ward", "shared_personas": ["P-001"],
            "encounters": [
                {"scenario_name": "Bed 1", "persona_id": "P-014",
                 "personas": ["P-014", "P-001"], "ehr_id": "cyrus"},
                {"scenario_name": "Bed 2", "persona_id": "P-013",
                 "personas": ["P-013", "P-001"], "ehr_id": "cyrus"},
            ]})
        room = control_room.get_active_room()
        st1 = room.shared_station("P-001"); st2 = room.shared_station("P-001")
        assert st1 is st2 and st1.persona_id == "P-001"             # one instance, idempotent
        assert c.get("/portal/room/shared/P-001").status_code == 200   # the chat surface renders
        assert c.get("/portal/room/shared/P-014").status_code == 404   # a patient is not a shared char
        assert c.post("/api/room/shared/P-014/turn",
                      data={"message": "hi"}).status_code == 404       # turn guards on membership
    finally:
        if control_room.get_active_room() is not None:
            control_room.end_active_room()
        ehr_db._mem_session_state = None


def test_client_wires_unified_room_flow():
    js = (_STATIC / "console.js").read_text()
    assert "/api/room/start" in js and "/portal/control/start" in js   # >1 bed vs 1 bed
    for fn in ("function launchRoom", "function rebuildBedScenarios", "function isMulti",
               "function validBeds", "function modeValid", "function bedCount",
               "function rebuildScenarioChars", "function fillSharedChars",
               "function scenarioCastFor"):
        assert fn in js
    assert "setMode" not in js                      # single/multi toggle machinery removed
    assert "persona_id" in js and "patient_id" in js and "encounters" in js
    # scenario cast routed per-bed (incl. patient), shared cast added to every bed
    assert "scenarioCastFor(i).concat(shared)" in js


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


def test_operate_endpoint_requires_auth():
    from portal import server
    c = TestClient(server.app)
    assert c.get("/api/control/operate").status_code == 401


def test_operate_endpoint_shape(client):
    """FR-011 — the Operate cockpit's live-operations feed: auth'd, always a
    well-formed {ok, mode, entities[]} the client renders as entity cards."""
    r = client.get("/api/control/operate")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["mode"] in ("none", "single", "room")
    assert isinstance(data["entities"], list)


def test_operate_endpoint_live_session(client):
    """A live session surfaces exactly one patient card with a join code and the
    focused open_url the instructor opens in place or pops out. (A single start
    is a one-encounter room under the v7 model, so mode may be 'room'.)"""
    from portal import auth, control_room, control_session, ehr_db
    ehr_db._mem_session_state = None
    for v in auth._active_vaults.values():        # in-memory only
        v._data["ANTHROPIC_API_KEY"] = "dummy-key"
    control_room.end_active_room()                # the endpoint is room-first — isolate
    if control_session.get_active() is not None:
        control_session.end_active()
    try:
        r = client.post("/portal/control/start", data={
            "scenario_name": "Operate cards test",
            "personas": ["P-014", "P-001"],
            "ehr_id": "cyrus",
        })
        assert r.status_code == 200
        data = client.get("/api/control/operate").json()
        assert data["mode"] in ("single", "room")
        patients = [e for e in data["entities"] if e["kind"] == "patient"]
        assert len(patients) == 1
        assert patients[0]["open_url"] and patients[0]["join"]
    finally:
        if control_session.get_active() is not None:
            control_session.end_active()
        control_room.end_active_room()
        ehr_db._mem_session_state = None


def test_console_operate_panel_has_operations_buildout(client):
    """The Operate panel ships the live-operations container, the pop-out-ready
    cards mount, and the collapsible readiness block (FR-011 Operate build-out)."""
    html = client.get("/portal/console").text
    assert 'id="operate-cards"' in html        # live entity cards mount
    assert 'id="op-empty"' in html             # empty-state copy
    assert 'class="readiness-block"' in html   # collapsible readiness
    assert 'id="readiness-mini"' in html       # collapsed summary status line
