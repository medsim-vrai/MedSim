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
