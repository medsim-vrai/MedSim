"""FR-013a P1 — local-context library store + CRUD + prompt overlay."""
from __future__ import annotations

import pytest

from portal import local_context as lc


@pytest.fixture(autouse=True)
def _isolated_library(tmp_path, monkeypatch):
    """Each test gets its own empty library file (the store reads the module
    globals at call time, so monkeypatching them isolates per test)."""
    monkeypatch.setattr(lc, "LIBRARY_DIR", tmp_path)
    monkeypatch.setattr(lc, "LIBRARY_PATH", tmp_path / "library.json")


# ── CRUD ────────────────────────────────────────────────────────────────

def test_add_list_get_roundtrip():
    a = lc.add_item(type="standing_order", title="Sepsis bundle",
                    content="Lactate q2h until normalized.")
    assert a["id"].startswith("lc_")
    assert a["active"] is False             # nothing live until confirmed
    assert a["source"] == "manual"
    assert len(lc.list_items()) == 1
    assert lc.get_item(a["id"])["title"] == "Sepsis bundle"
    assert lc.get_item("lc_nope") is None


def test_add_validation():
    with pytest.raises(ValueError):
        lc.add_item(type="bogus", title="x", content="y")
    with pytest.raises(ValueError):
        lc.add_item(type="medication", title="", content="y")
    with pytest.raises(ValueError):
        lc.add_item(type="medication", title="x", content="   ")


def test_update_edit_and_activate():
    a = lc.add_item(type="medication", title="Norepi", content="First-line pressor.")
    upd = lc.update_item(a["id"],
                         content="First-line pressor; max 30 mcg/min.", active=True)
    assert upd["content"].endswith("30 mcg/min.")
    assert upd["active"] is True
    assert lc.update_item("lc_nope", active=True) is None
    with pytest.raises(ValueError):
        lc.update_item(a["id"], type="bogus")


def test_active_items_filter():
    a = lc.add_item(type="standing_order", title="A", content="aaa", active=True)
    lc.add_item(type="standing_order", title="B", content="bbb")   # inactive
    assert [x["id"] for x in lc.active_items()] == [a["id"]]


def test_remove_item():
    a = lc.add_item(type="treatment_priority", title="Airway first", content="ABC.")
    assert lc.remove_item(a["id"]) is True
    assert lc.list_items() == []
    assert lc.remove_item(a["id"]) is False


# ── Prompt overlay ──────────────────────────────────────────────────────

def test_prompt_block_empty_when_no_active_items():
    lc.add_item(type="medication", title="X", content="y")          # inactive only
    assert lc.prompt_block(enabled=True) == ""


def test_prompt_block_empty_when_disabled():
    lc.add_item(type="medication", title="X", content="y", active=True)
    assert lc.prompt_block(enabled=False) == ""


def test_prompt_block_renders_active_grouped_by_type():
    lc.add_item(type="standing_order", title="Sepsis bundle",
                content="Lactate q2h.", active=True)
    lc.add_item(type="medication", title="Norepi",
                content="First-line pressor.", active=True)
    lc.add_item(type="medication", title="OldDrug", content="unused")   # inactive
    block = lc.prompt_block(enabled=True)
    assert "LOCAL PRACTICE OVERLAY" in block
    assert "FOLLOW THE LOCAL ITEM" in block          # override directive
    assert "Standing orders:" in block
    assert "Local formulary / medications:" in block
    assert "Sepsis bundle: Lactate q2h." in block
    assert "Norepi: First-line pressor." in block
    assert "OldDrug" not in block                     # inactive excluded


# ── Program-wide overlay toggle + overlay_block (P5) ─────────────────────

def test_enabled_default_off_and_persists():
    assert lc.is_enabled() is False                   # default OFF = best practice
    assert lc.set_enabled(True) is True
    assert lc.is_enabled() is True
    assert lc.set_enabled(False) is False
    assert lc.is_enabled() is False


def test_overlay_block_follows_toggle_and_active_items():
    lc.add_item(type="standing_order", title="Sepsis bundle",
                content="Lactate q2h.", active=True)
    assert lc.overlay_block() == ""                   # toggle still off → no-op
    lc.set_enabled(True)
    block = lc.overlay_block()
    assert "LOCAL PRACTICE OVERLAY" in block
    assert "Sepsis bundle: Lactate q2h." in block


def test_overlay_block_empty_when_enabled_but_no_active_items():
    lc.add_item(type="medication", title="X", content="y")   # inactive only
    lc.set_enabled(True)
    assert lc.overlay_block() == ""


# ── CRUD API (instructor-authed) ────────────────────────────────────────

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
    vault = credentials.unlock("test_passwd_xyz_8chars")
    vault.set("ANTHROPIC_API_KEY", "sk-ant-dummy")
    from portal import server
    from fastapi.testclient import TestClient
    with TestClient(server.app) as c:
        c.cookies.set(auth.COOKIE_NAME, auth.issue_session_token(vault))
        yield c
    control_room._reset_for_tests()


def test_api_add_then_list(client):
    r = client.post("/api/local-context/items", json={
        "type": "standing_order", "title": "Sepsis", "content": "Lactate q2h."})
    assert r.status_code == 200, r.text
    assert r.json()["item"]["id"].startswith("lc_")
    body = client.get("/api/local-context/items").json()
    assert "standing_order" in body["types"]
    assert [it["title"] for it in body["items"]] == ["Sepsis"]


def test_api_add_rejects_bad_type(client):
    r = client.post("/api/local-context/items",
                    json={"type": "bogus", "title": "x", "content": "y"})
    assert r.status_code == 400


def test_api_update_and_delete(client):
    item = client.post("/api/local-context/items", json={
        "type": "medication", "title": "Norepi", "content": "Pressor."}).json()["item"]
    r = client.patch(f"/api/local-context/items/{item['id']}", json={"active": True})
    assert r.status_code == 200 and r.json()["item"]["active"] is True
    assert client.patch("/api/local-context/items/lc_nope",
                        json={"active": True}).status_code == 404
    assert client.delete(f"/api/local-context/items/{item['id']}").status_code == 200
    assert client.delete(f"/api/local-context/items/{item['id']}").status_code == 404


def test_api_requires_instructor_auth(client):
    from portal import auth
    client.cookies.delete(auth.COOKIE_NAME)
    assert client.get("/api/local-context/items").status_code in (401, 403)


def test_api_list_includes_toggle_state(client):
    body = client.get("/api/local-context/items").json()
    assert body["enabled"] is False
    assert body["active_count"] == 0


def test_api_set_enabled_roundtrip(client):
    client.post("/api/local-context/items", json={
        "type": "standing_order", "title": "Sepsis", "content": "Lactate q2h.",
        "active": True})
    r = client.post("/api/local-context/enabled", json={"enabled": True})
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is True
    assert r.json()["active_count"] == 1
    assert client.get("/api/local-context/items").json()["enabled"] is True
    assert client.post("/api/local-context/enabled",
                       json={"enabled": False}).json()["enabled"] is False


def test_api_set_enabled_requires_auth(client):
    from portal import auth
    client.cookies.delete(auth.COOKIE_NAME)
    assert client.post("/api/local-context/enabled",
                       json={"enabled": True}).status_code in (401, 403)


def test_management_page_renders(client):
    r = client.get("/portal/local-context")
    assert r.status_code == 200
    assert "Local context" in r.text
    assert "/api/local-context/items" in r.text       # CRUD JS wired
    assert "/api/local-context/enabled" in r.text      # overlay toggle wired
