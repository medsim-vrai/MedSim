"""Entry-page role sign-in: Admin / Instructor / Observer on one shared vault
password (MVP — role is a label; admin == instructor powers). The real
separate-credential separation is tracked separately (docs/SECURITY-auth-rollout.md)."""
from __future__ import annotations

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("MEDSIM_RESUME", "0")
    from portal import auth, control_room, credentials, server as server_mod
    sb = fake_home / ".medsim"
    sb.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(credentials, "VAULT_DIR", sb)
    monkeypatch.setattr(credentials, "VAULT_PATH", sb / "vault.enc")
    monkeypatch.setattr(server_mod, "_anthropic_runtime_key", "")
    control_room._reset_for_tests()
    if not credentials.is_initialized():
        credentials.initialize("test_passwd_xyz_8chars")
    from portal import server
    from fastapi.testclient import TestClient
    with TestClient(server.app) as c:
        yield c, "test_passwd_xyz_8chars"
    control_room._reset_for_tests()


def _login(c, password, role=None):
    data = {"password": password}
    if role is not None:
        data["role"] = role
    return c.post("/login", data=data, follow_redirects=False)


# ── entry page ──────────────────────────────────────────────────────────────

def test_login_page_offers_admin_and_instructor(client):
    c, _ = client
    r = c.get("/login")
    assert r.status_code == 200
    assert 'value="admin"' in r.text
    assert 'value="instructor"' in r.text
    assert 'value="observer"' in r.text
    assert "Sign in &amp; launch" in r.text          # prominent launch CTA


# ── role assignment ──────────────────────────────────────────────────────────

def test_login_as_admin_sets_admin_role(client):
    c, pw = client
    from portal import auth
    assert _login(c, pw, "admin").status_code == 303
    cookie = c.cookies.get(auth.COOKIE_NAME)
    assert auth.session_role(cookie) == "admin"
    assert auth.is_admin(cookie) is True


def test_login_defaults_to_instructor(client):
    c, pw = client
    from portal import auth
    _login(c, pw)                                     # no role field
    assert auth.session_role(c.cookies.get(auth.COOKIE_NAME)) == "instructor"


# ── permission parity / observer read-only ───────────────────────────────────

def test_admin_passes_instructor_gate_but_observer_blocked(client):
    c, pw = client
    # admin reaches an instructor-gated route (same powers as instructor)
    _login(c, pw, "admin")
    assert c.get("/api/local-context/items").status_code == 200
    # observer is read-only → blocked on the same gate
    c.cookies.clear()
    _login(c, pw, "observer")
    assert c.get("/api/local-context/items").status_code == 403


def test_unknown_role_falls_back_to_instructor(client):
    c, pw = client
    from portal import auth
    _login(c, pw, "superuser")                        # not a valid role
    assert auth.session_role(c.cookies.get(auth.COOKIE_NAME)) == "instructor"


# ── task #94: REAL credential separation (which password unlocks = the seat) ─

def test_master_password_is_admin_seat_and_radio_only_lowers(client):
    c, pw = client
    from portal import auth
    # master + admin radio → admin
    _login(c, pw, "admin")
    assert auth.session_role(c.cookies.get(auth.COOKIE_NAME)) == "admin"
    # master + observer radio → observer (down-privilege allowed)
    c.cookies.clear()
    _login(c, pw, "observer")
    assert auth.session_role(c.cookies.get(auth.COOKIE_NAME)) == "observer"


def test_seat_password_cannot_reach_admin(client):
    c, pw = client
    from portal import auth, credentials
    # admin sets an instructor seat password
    _login(c, pw, "admin")
    r = c.post("/portal/credentials/seat_password",
               data={"seat": "instructor", "password": "instr-pass-123"},
               follow_redirects=False)
    assert r.status_code == 303
    # sign in with the INSTRUCTOR password while claiming the admin radio
    c.cookies.clear()
    _login(c, "instr-pass-123", "admin")
    cookie = c.cookies.get(auth.COOKIE_NAME)
    assert auth.session_role(cookie) == "instructor"     # radio could NOT raise
    assert c.get("/portal/credentials").status_code == 403
    # the instructor seat still opens the SAME vault data
    assert credentials.role_passwords_set()["instructor"] is True


def test_wrong_seat_password_rejected(client):
    c, _ = client
    r = _login(c, "not-a-real-password", "admin")
    assert r.status_code == 303 and "error=invalid" in r.headers["location"]


def test_admin_only_routes_gated(client):
    c, pw = client
    # instructor: blocked from credentials + ehr_admin (read AND write)
    _login(c, pw, "instructor")
    assert c.get("/portal/credentials").status_code == 403
    assert c.get("/portal/ehr_admin").status_code == 403
    assert c.post("/portal/ehr_admin/purge", follow_redirects=False).status_code == 403
    assert c.post("/portal/credentials",
                  data={"key": "ANTHROPIC_API_KEY", "value": "x"},
                  follow_redirects=False).status_code == 403
    # admin: all pass
    c.cookies.clear()
    _login(c, pw, "admin")
    r = c.get("/portal/credentials")
    assert r.status_code == 200 and "Seat passwords" in r.text
    assert c.get("/portal/ehr_admin").status_code == 200


def test_clear_seat_password(client):
    c, pw = client
    from portal import credentials
    _login(c, pw, "admin")
    c.post("/portal/credentials/seat_password",
           data={"seat": "observer", "password": "observer-pass-1"})
    assert credentials.role_passwords_set()["observer"] is True
    c.post("/portal/credentials/seat_password",
           data={"seat": "observer", "password": ""})
    assert credentials.role_passwords_set()["observer"] is False


# ── task #94: hub identity overlay (guide §2 step 3 — flag-gated) ────────────

def _sample(case_substr):
    import json
    from pathlib import Path
    data = json.loads((Path(__file__).parent / "fixtures"
                       / "hub_identity_provide.samples.json").read_text())
    for s in data["samples"]:
        if case_substr in s["_case"]:
            return s
    raise AssertionError(f"no sample matching {case_substr!r}")


def test_contract_samples_map_to_v8_seats():
    """Consumer-driven fixtures: the published identity.provide samples map to
    the seats V8 grants — and the unknown role (CHAPLAIN) is denied, not an error."""
    from portal.hub_adapter import mappers
    assert mappers.seat_from_identity(_sample("org-admin")) == "admin"
    assert mappers.seat_from_identity(_sample("V8 on-prem")) == "instructor"
    assert mappers.seat_from_identity(_sample("TB-SA")) == "admin"
    assert mappers.seat_from_identity(_sample("researcher")) is None
    assert mappers.seat_from_identity(_sample("student")) is None
    assert mappers.seat_from_identity(_sample("UNKNOWN role")) is None
    assert mappers.seat_from_identity({}) is None


def test_hub_overlay_flag_off_is_noop(client, monkeypatch):
    c, pw = client
    from portal import auth
    monkeypatch.setenv("HUB_OPERATOR_USER_ID", "u_site1")
    # flag stays OFF (config.ENABLED read at import; default 0) → local seat wins
    _login(c, pw, "admin")
    assert auth.session_role(c.cookies.get(auth.COOKIE_NAME)) == "admin"


def test_hub_overlay_flag_on_uses_authority_role(client, monkeypatch):
    c, pw = client
    from portal import auth
    from portal.hub_adapter import config as hub_config, consume
    monkeypatch.setattr(hub_config, "ENABLED", True)
    monkeypatch.setenv("HUB_OPERATOR_USER_ID", "u_site1")
    monkeypatch.setattr(consume, "identity", lambda uid, tenant_id=None: _sample("V8 on-prem"))
    _login(c, pw, "admin")   # locally admin, but the authority says INSTR
    assert auth.session_role(c.cookies.get(auth.COOKIE_NAME)) == "instructor"


def test_hub_overlay_unknown_role_keeps_local_seat(client, monkeypatch):
    c, pw = client
    from portal import auth
    from portal.hub_adapter import config as hub_config, consume
    monkeypatch.setattr(hub_config, "ENABLED", True)
    monkeypatch.setenv("HUB_OPERATOR_USER_ID", "u_site1")
    monkeypatch.setattr(consume, "identity", lambda uid, tenant_id=None: _sample("UNKNOWN role"))
    _login(c, pw, "admin")
    assert auth.session_role(c.cookies.get(auth.COOKIE_NAME)) == "admin"


def test_hub_overlay_failure_never_blocks_login(client, monkeypatch):
    c, pw = client
    from portal import auth
    from portal.hub_adapter import config as hub_config, consume
    monkeypatch.setattr(hub_config, "ENABLED", True)
    monkeypatch.setenv("HUB_OPERATOR_USER_ID", "u_site1")
    def _boom(uid, tenant_id=None):
        raise RuntimeError("hub down")
    monkeypatch.setattr(consume, "identity", _boom)
    r = _login(c, pw, "instructor")
    assert r.status_code == 303 and "error" not in r.headers["location"]
    assert auth.session_role(c.cookies.get(auth.COOKIE_NAME)) == "instructor"
