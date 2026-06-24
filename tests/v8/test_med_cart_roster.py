"""Med cart v2 — shared-terminal access: open vs restrict, roster scoping, and
server-side enforcement (#74/#75/#77/#81).

Regression for the field report "nurse assigned 2 patients could reach all 4":
the backend must scope the bootstrap roster to a nurse's assigned encounters and
REJECT a cabinet.administer for a patient outside that set — while open mode (the
default) stays unrestricted.
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
    monkeypatch.setenv("MEDSIM_RESUME", "0")   # no resume-on-boot leak between tests
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    from portal import auth, control_room, credentials, server as server_mod
    sandbox = fake_home / ".medsim"
    sandbox.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(credentials, "VAULT_DIR", sandbox)
    monkeypatch.setattr(credentials, "VAULT_PATH", sandbox / "vault.enc")
    monkeypatch.setattr(server_mod, "_anthropic_runtime_key", "")
    control_room._reset_for_tests()
    if not credentials.is_initialized():
        credentials.initialize(TEST_PASSWORD)
    vault = credentials.unlock(TEST_PASSWORD)
    vault.set("ANTHROPIC_API_KEY", "sk-ant-dummy")
    from portal import server
    from fastapi.testclient import TestClient
    with TestClient(server.app) as c:
        c.cookies.set(auth.COOKIE_NAME, auth.issue_session_token(vault))
        yield c
    control_room._reset_for_tests()


def _room4(client) -> list[str]:
    """Start a 4-bed room (running) and return the encounter ids in bed order."""
    pool = ["P-014", "P-001", "P-013", "P-003"]
    r = client.post("/api/room/start", json={"label": "T", "encounters": [
        {"scenario_name": f"Bed {i + 1}", "persona_id": p, "patient_persona_id": p,
         "personas": [p], "ehr_id": "helix"} for i, p in enumerate(pool)]})
    assert r.status_code == 200, r.text
    eids = [e["encounter_id"] for e in r.json()["encounters"]]
    client.post("/api/room/start_all")
    return eids


def _cart(client, eids) -> str:
    rc = client.post("/api/room/med_cart/register",
                     json={"label": "Cart A", "encounter_ids": eids})
    assert rc.status_code == 200, rc.text
    return rc.json()["station_id"]


def _patient_cid(eid: str) -> str:
    from portal import control_room
    return control_room.get_active_room().encounters[eid].patient_persona_id


def _administer(client, sid, character_id, staff_id):
    return client.post(f"/api/device/{sid}/event", json={
        "type": "cabinet.administer",
        "payload": {"action": "administer", "character_id": character_id,
                    "med_name": "Heparin", "staff_id": staff_id}})


# ── Open mode (default) ────────────────────────────────────────────────

def test_open_mode_default_empty_roster(client):
    """Open access (the default): the cart gets an empty roster (→ ad-hoc
    initials sign-in) and every patient is on the cart."""
    eids = _room4(client)
    b = client.get(f"/api/device/{_cart(client, eids)}/bootstrap").json()
    assert b["session_state"] == "running"
    assert b["roster"] == []
    assert len(b["characters"]) == 4


def test_open_mode_no_enforcement(client):
    """Open mode never blocks — even a stray staff_id is allowed."""
    eids = _room4(client)
    sid = _cart(client, eids)
    r = _administer(client, sid, _patient_cid(eids[2]), "stf_whoever")
    assert r.status_code == 200 and r.json().get("ok") is True


# ── Restrict mode — roster scoping ─────────────────────────────────────

def test_restrict_scopes_nurse_to_assigned(client):
    eids = _room4(client)
    assert client.post("/api/room/med_access", json={"open": False}).status_code == 200
    nid = client.post("/api/room/staff", json={
        "display_name": "Alice P.", "initials": "AP", "role": "nurse",
        "assignments": eids[:2]}).json()["staff_id"]
    b = client.get(f"/api/device/{_cart(client, eids)}/bootstrap").json()
    nurse = next(s for s in b["roster"] if s["staff_id"] == nid)
    assert sorted(nurse["accessible"]) == sorted(eids[:2])   # ONLY the 2 assigned
    assert len(b["characters"]) == 4                          # cart still holds all 4


def test_restrict_charge_nurse_sees_all(client):
    eids = _room4(client)
    client.post("/api/room/med_access", json={"open": False})
    cid = client.post("/api/room/staff", json={
        "display_name": "Carol N.", "initials": "CN",
        "role": "charge_nurse"}).json()["staff_id"]
    b = client.get(f"/api/device/{_cart(client, eids)}/bootstrap").json()
    charge = next(s for s in b["roster"] if s["staff_id"] == cid)
    assert sorted(charge["accessible"]) == sorted(eids)       # all 4


# ── Restrict mode — server-side enforcement (HTTP event path) ──────────

def test_enforcement_blocks_unassigned_administer(client):
    eids = _room4(client)
    client.post("/api/room/med_access", json={"open": False})
    nid = client.post("/api/room/staff", json={
        "display_name": "Alice P.", "initials": "AP", "role": "nurse",
        "assignments": eids[:2]}).json()["staff_id"]
    sid = _cart(client, eids)
    r = _administer(client, sid, _patient_cid(eids[2]), nid)   # bed 3 — not assigned
    assert r.status_code == 403
    assert r.json().get("reason") == "not_assigned"


def test_enforcement_allows_assigned_administer(client):
    eids = _room4(client)
    client.post("/api/room/med_access", json={"open": False})
    nid = client.post("/api/room/staff", json={
        "display_name": "Alice P.", "initials": "AP", "role": "nurse",
        "assignments": eids[:2]}).json()["staff_id"]
    sid = _cart(client, eids)
    r = _administer(client, sid, _patient_cid(eids[0]), nid)   # bed 1 — assigned
    assert r.status_code == 200 and r.json().get("ok") is True
