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


# ══ Records terminal — sign-in gate + scope (#82) ══════════════════════
# The records terminal is the SAME shared-device / roster model as the cart:
# a student must sign in before any chart is shown, then sees every patient
# under open access but only their assignments under restrict access. The
# chart view (where full PHI renders) re-checks scope so a direct link can't
# bypass the picker.

def _roomcode(client) -> str:
    from portal import control_room
    return control_room.get_active_room().room_code


def _cids_by_eid(eids):
    """Map encounter ids → picker character ids (bed order)."""
    from portal import control_room, control_session, medical_records as _mr
    rows = _mr.patients_for_picker(control_room_mod=control_room,
                                   control_session_mod=control_session)
    by_eid = {r["encounter_id"]: r["character_id"] for r in rows}
    return [by_eid[e] for e in eids]


def _entry(client, *, code, initials="", role="", user=""):
    return client.get("/students/medical_records", params={
        "code": code, "initials": initials, "role": role, "user": user})


def _ncards(html: str) -> int:
    return html.count('data-character-id="')   # one per patient card


def _restrict_nurse(client, eids):
    client.post("/api/room/med_access", json={"open": False})
    client.post("/api/room/staff", json={
        "display_name": "Alice P.", "initials": "AP", "role": "nurse",
        "assignments": eids[:2]})


def test_records_open_gates_on_signin(client):
    """Open access still GATES: a walk-up with no initials sees the sign-in
    card and ZERO patient cards — never an ungated patient list."""
    eids = _room4(client)
    html = _entry(client, code=_roomcode(client)).text
    assert "Who's charting?" in html
    assert _ncards(html) == 0


def test_records_open_signed_in_sees_all(client):
    eids = _room4(client)
    html = _entry(client, code=_roomcode(client),
                  initials="ZZ", user="Walk Up").text
    assert _ncards(html) == 4
    assert "Open access" in html


def test_records_restrict_scopes_to_assigned(client):
    eids = _room4(client)
    _restrict_nurse(client, eids)
    html = _entry(client, code=_roomcode(client),
                  initials="AP", user="Alice P.").text
    assert _ncards(html) == 2                    # only the 2 assigned
    assert "assigned to you" in html


def test_records_restrict_unknown_initials_blocked(client):
    eids = _room4(client)
    _restrict_nurse(client, eids)
    html = _entry(client, code=_roomcode(client),
                  initials="ZZ", user="Stranger").text
    assert _ncards(html) == 0
    assert "roster" in html                      # "aren't on this room's roster"


def test_records_restrict_charge_sees_all(client):
    eids = _room4(client)
    client.post("/api/room/med_access", json={"open": False})
    client.post("/api/room/staff", json={
        "display_name": "Carol N.", "initials": "CN", "role": "charge_nurse"})
    html = _entry(client, code=_roomcode(client),
                  initials="CN", user="Carol N.").text
    assert _ncards(html) == 4


def test_records_supervisor_button_sees_all_in_restrict(client):
    """The nursing-station 'supervisor' entry stays an all-patient view even
    under restrict access (it's the instructor's trusted button)."""
    eids = _room4(client)
    client.post("/api/room/med_access", json={"open": False})
    html = _entry(client, code=_roomcode(client), role="supervisor").text
    assert _ncards(html) == 4


# ── Chart view — the real PHI gate (direct-link enforcement) ───────────

def _chart(client, cid, *, initials="", role="", user=""):
    return client.get(f"/students/medical_records/{cid}", params={
        "initials": initials, "role": role, "user": user})


def test_chart_blocks_unassigned_patient(client):
    eids = _room4(client)
    _restrict_nurse(client, eids)
    cids = _cids_by_eid(eids)
    r = _chart(client, cids[2], initials="AP", role="student", user="Alice P.")
    assert r.status_code == 403


def test_chart_allows_assigned_patient(client):
    eids = _room4(client)
    _restrict_nurse(client, eids)
    cids = _cids_by_eid(eids)
    r = _chart(client, cids[0], initials="AP", role="student", user="Alice P.")
    assert r.status_code == 200


def test_chart_deeplink_without_signin_blocked(client):
    eids = _room4(client)
    _restrict_nurse(client, eids)
    cids = _cids_by_eid(eids)
    assert _chart(client, cids[0]).status_code == 403   # no initials/role


def test_chart_open_mode_allows_signed_in(client):
    eids = _room4(client)                                # open (default)
    cids = _cids_by_eid(eids)
    r = _chart(client, cids[3], initials="ZZ", role="student", user="Walk Up")
    assert r.status_code == 200


# ── Instructor records page (/portal/medical_records) — gated too ───────
# The vault-authed sidebar "Medical Records" page now requires the same EHR
# sign-in + scoping, EXCEPT unrecognized initials fall back to the full
# supervisor view (the authed instructor can never lock themselves out).

def _portal_records(client, *, role="", initials="", user=""):
    return client.get("/portal/medical_records", params={
        "role": role, "initials": initials, "user": user})


def _nrows_portal(html: str) -> int:
    return html.count('href="/portal/medical_records/')   # one per patient row


def test_student_signin_is_fullscreen_gate(client):
    """The student terminal sign-in screen carries the full-screen gate class."""
    _room4(client)
    html = _entry(client, code=_roomcode(client)).text     # no initials → signin
    assert "hh-gate" in html


def test_portal_records_requires_signin(client):
    _room4(client)
    html = _portal_records(client).text                    # authed, no identity
    assert "Sign in to Helix Health" in html
    assert _nrows_portal(html) == 0


def test_portal_records_supervisor_sees_all(client):
    _room4(client)
    html = _portal_records(client, role="supervisor", user="Sup").text
    assert _nrows_portal(html) == 4


def test_portal_records_nurse_scoped(client):
    eids = _room4(client)
    _restrict_nurse(client, eids)                          # AP assigned eids[:2]
    html = _portal_records(client, role="student", initials="AP",
                           user="Alice P.").text
    assert _nrows_portal(html) == 2


def test_portal_records_unknown_initials_falls_back_to_all(client):
    eids = _room4(client)
    _restrict_nurse(client, eids)
    html = _portal_records(client, role="student", initials="ZZ",
                           user="Whoever").text
    assert _nrows_portal(html) == 4        # authed instructor never locked out
