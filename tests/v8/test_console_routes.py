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
