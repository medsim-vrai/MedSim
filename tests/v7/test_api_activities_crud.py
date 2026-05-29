"""M12 acceptance — Activity CRUD HTTP API.

Exercises every route on /api/activities:
  GET    /api/activities                       — list, with builtin_only filter
  GET    /api/activities/{id}                  — one row
  POST   /api/activities                       — create (custom only)
  PATCH  /api/activities/{id}                  — partial update
  DELETE /api/activities/{id}                  — delete (refuses built-ins)
  GET    /api/activities/{id}/encounter_entry  — translate to wizard row
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
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)

    from portal import (
        auth, control_room, credentials, voices as _voices,
    )
    sandbox_vault_dir = fake_home / ".medsim"
    sandbox_vault_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(credentials, "VAULT_DIR", sandbox_vault_dir)
    monkeypatch.setattr(credentials, "VAULT_PATH",
                         sandbox_vault_dir / "vault.enc")
    monkeypatch.setattr(_voices, "KEYFILE", tmp_path / "no-such.key")
    monkeypatch.setattr(_voices, "_runtime_key", "")
    control_room._reset_for_tests()

    if not credentials.is_initialized():
        credentials.initialize(TEST_PASSWORD)
    vault = credentials.unlock(TEST_PASSWORD)
    vault.set("ANTHROPIC_API_KEY", "sk-ant-dummy")
    vault.set("ELEVENLABS_API_KEY", "")

    from portal import server
    from fastapi.testclient import TestClient

    # The seed-on-startup hook is registered on the app but FastAPI's
    # TestClient runs lifespan events when entered as a context
    # manager. Use it that way so the 8 built-ins land in the
    # sandboxed DB before tests run.
    with TestClient(server.app) as c:
        c.cookies.set(auth.COOKIE_NAME, auth.issue_session_token(vault))
        yield c
    control_room._reset_for_tests()


def test_api_activities_list_returns_built_ins(client) -> None:
    r = client.get("/api/activities")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "activities" in body
    builtins = [a for a in body["activities"] if a["is_builtin"]]
    assert len(builtins) == 8, (
        f"Expected the 8 seeded built-ins on first start; got "
        f"{len(builtins)}"
    )
    # Built-ins listed first (alphabetical within group).
    is_builtin_flags = [a["is_builtin"] for a in body["activities"]]
    # The transition from True to False (if any) happens once.
    transitions = sum(1 for i in range(1, len(is_builtin_flags))
                       if is_builtin_flags[i - 1] != is_builtin_flags[i])
    assert transitions <= 1


def test_api_activities_list_builtin_only_filter(client) -> None:
    r = client.get("/api/activities?builtin_only=true")
    assert r.status_code == 200
    body = r.json()
    assert all(a["is_builtin"] for a in body["activities"])
    assert len(body["activities"]) == 8


def test_api_activities_get_404s_on_unknown(client) -> None:
    r = client.get("/api/activities/act_does_not_exist")
    assert r.status_code == 404


def test_api_activities_get_returns_one(client) -> None:
    r = client.get("/api/activities/builtin_msurg_dka")
    assert r.status_code == 200
    body = r.json()
    assert body["activity_id"] == "builtin_msurg_dka"
    assert body["is_builtin"] is True
    assert "M22" in body["seed_modules"]
    assert body["seed_persona_id"] == "P-005"


def test_api_activities_create_custom_activity(client) -> None:
    r = client.post("/api/activities", json={
        "label": "Custom · M12 test",
        "seed_persona_id": "P-001",
        "seed_modules": ["M02"],
        "scenario_text": "Operator-authored.",
        "default_chart_mode": "shared",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_builtin"] is False
    assert body["activity_id"].startswith("act_")
    # Round-trips via the list.
    listed = client.get("/api/activities").json()["activities"]
    assert any(a["activity_id"] == body["activity_id"] for a in listed)


def test_api_activities_create_rejects_invalid_chart_mode(client) -> None:
    r = client.post("/api/activities", json={
        "label": "Bad",
        "default_chart_mode": "broken_value",
    })
    assert r.status_code == 400


def test_api_activities_create_rejects_blank_label(client) -> None:
    r = client.post("/api/activities", json={"label": "   "})
    assert r.status_code == 400


def test_api_activities_patch_updates_field(client) -> None:
    # Build a custom activity first so we don't mutate a built-in here.
    created = client.post("/api/activities",
                            json={"label": "Patch test"}).json()
    aid = created["activity_id"]
    r = client.patch(f"/api/activities/{aid}",
                      json={"label": "Patched", "seed_modules": ["M02", "M06"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["label"] == "Patched"
    assert body["seed_modules"] == ["M02", "M06"]


def test_api_activities_patch_404s_on_unknown(client) -> None:
    r = client.patch("/api/activities/act_unknown",
                      json={"label": "ignored"})
    assert r.status_code == 404


def test_api_activities_delete_refuses_builtins(client) -> None:
    r = client.delete("/api/activities/builtin_msurg_dka")
    assert r.status_code == 409
    # Row still exists.
    r2 = client.get("/api/activities/builtin_msurg_dka")
    assert r2.status_code == 200


def test_api_activities_delete_drops_custom(client) -> None:
    created = client.post("/api/activities",
                            json={"label": "Delete me"}).json()
    aid = created["activity_id"]
    r = client.delete(f"/api/activities/{aid}")
    assert r.status_code == 200
    assert client.get(f"/api/activities/{aid}").status_code == 404


def test_api_activities_delete_idempotent_on_missing(client) -> None:
    r = client.delete("/api/activities/act_never_existed")
    assert r.status_code == 200


def test_api_activities_encounter_entry_round_trips(client) -> None:
    r = client.get("/api/activities/builtin_msurg_dka/encounter_entry")
    assert r.status_code == 200
    entry = r.json()
    assert entry["scenario_name"] == "Med-surg · DKA management"
    assert entry["patient_persona_id"] == "P-005"
    assert "M22" in entry["modules"]
    assert entry["activity_id"] == "builtin_msurg_dka"
