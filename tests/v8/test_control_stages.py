"""FR-005 — the two-stage control room: Scenario Setup → Live Operations."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TEST_PASSWORD = "test_passwd_xyz_8chars"


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
    from portal import server, control_session
    c = TestClient(server.app)
    c.post("/login", data={"password": TEST_PASSWORD})
    sess = control_session.create_session(
        scenario_name="stage-test",
        selected_personas=["P-001"], selected_modules=[], api_key="dummy")
    c._sess = sess
    yield c
    control_session.end_active()


def test_configured_session_lands_on_setup(client) -> None:
    """A freshly-configured session: /ops redirects to Setup; Setup renders the
    stage banner + the setup cards."""
    r = client.get("/portal/control/ops", follow_redirects=False)
    assert r.status_code == 303
    assert "/portal/control/setup" in r.headers["location"]
    r2 = client.get("/portal/control/setup")
    assert r2.status_code == 200
    assert 'id="stage-banner"' in r2.text          # the Setup banner
    assert "Invite stations" in r2.text             # setup card present
    assert 'id="meds-card" data-stage="setup"' in r2.text


def test_running_session_lands_on_live_ops(client) -> None:
    from portal import control_session
    control_session.set_state("running")
    r = client.get("/portal/control/ops")
    assert r.status_code == 200
    assert 'id="stage-banner"' not in r.text        # no setup banner on live
    assert "Scenario Setup page" in r.text          # the cross-link instead
    assert 'data-stage="live"' in r.text


def test_setup_page_reachable_while_running(client) -> None:
    """Level-2 mid-scenario changes: Setup stays reachable after start."""
    from portal import control_session
    control_session.set_state("running")
    r = client.get("/portal/control/setup")
    assert r.status_code == 200
    assert 'id="stage-banner"' in r.text


def test_add_persona_to_active_session(client) -> None:
    """FR-005 — add the pharmacist to a session without relaunching."""
    r = client.post("/api/control/personas/add",
                    json={"persona_id": "P-006", "avatar": False})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert "Pharmacist" in r.json()["name"]
    page = client.get("/portal/control/setup")
    assert "Pharmacist Lee" in page.text          # now in the persona surfaces
    r2 = client.post("/api/control/personas/add", json={"persona_id": "NOPE"})
    assert r2.status_code == 404
