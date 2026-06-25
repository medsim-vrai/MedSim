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
