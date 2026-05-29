"""Phase 7 M22 — Per-Patient Console scaffold tests.

The route renders the right encounter; 404s on unknown id or when
no active room. The dashboard card click target updated to the new
URL.
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
        debrief as debrief_mod,
    )
    sandbox_vault_dir = fake_home / ".medsim"
    sandbox_vault_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(credentials, "VAULT_DIR", sandbox_vault_dir)
    monkeypatch.setattr(credentials, "VAULT_PATH",
                         sandbox_vault_dir / "vault.enc")
    monkeypatch.setattr(_voices, "KEYFILE", tmp_path / "no-such.key")
    monkeypatch.setattr(_voices, "_runtime_key", "")
    sandbox_debriefs = tmp_path / "data" / "debriefs"
    monkeypatch.setattr(debrief_mod, "DEBRIEFS_DIR", sandbox_debriefs)
    monkeypatch.setattr(debrief_mod, "COHORT_DEBRIEFS_DIR",
                         sandbox_debriefs / "cohort")
    control_room._reset_for_tests()
    if not credentials.is_initialized():
        credentials.initialize(TEST_PASSWORD)
    vault = credentials.unlock(TEST_PASSWORD)
    vault.set("ANTHROPIC_API_KEY", "sk-ant-dummy")
    vault.set("ELEVENLABS_API_KEY", "")

    from portal import server
    from fastapi.testclient import TestClient
    with TestClient(server.app) as c:
        c.cookies.set(auth.COOKIE_NAME, auth.issue_session_token(vault))
        yield c
    control_room._reset_for_tests()


def _start_room(client, n: int = 2):
    entries = [
        {"scenario_name": f"Bed {i+1}", "persona_id": f"P-{i+1:03d}",
         "patient_persona_id": f"P-{i+1:03d}", "ehr_id": "helix"}
        for i in range(n)
    ]
    r = client.post("/api/room/start",
                     json={"label": "M22 console test", "encounters": entries})
    assert r.status_code == 200
    return r.json()


def test_encounter_console_route_renders(client) -> None:
    body = _start_room(client, n=2)
    eid = body["encounters"][0]["encounter_id"]
    r = client.get(f"/portal/room/encounter/{eid}")
    assert r.status_code == 200, r.text
    html = r.text
    assert "Per-Patient Console" in html
    # Encounter label, join code, persona id all surfaced.
    assert "Bed 1" in html
    join_code = body["encounters"][0]["join_code"]
    assert join_code in html
    # The scaffold's six cards render.
    for card_id in ("card-telemetry", "card-ecg", "card-devices",
                     "card-overrides", "card-scene", "card-chart"):
        assert card_id in html


def test_encounter_console_404s_on_unknown_encounter(client) -> None:
    _start_room(client, n=1)
    r = client.get("/portal/room/encounter/encounter-does-not-exist")
    assert r.status_code == 404


def test_encounter_console_404s_when_no_active_room(client) -> None:
    r = client.get("/portal/room/encounter/anything")
    assert r.status_code == 404


def test_encounter_console_shows_clone_indicator(client) -> None:
    """Private-clone encounters surface the CLONE badge so the operator
    knows they're looking at a per-student clone, not a template."""
    from portal import control_room

    r = client.post("/api/room/start", json={
        "label": "M22 clone test",
        "encounters": [{
            "scenario_name": "Bed 1 (template)",
            "persona_id": "P-001", "patient_persona_id": "P-001",
            "ehr_id": "helix", "chart_mode": "private_clone",
        }],
    })
    assert r.status_code == 200
    template_id = r.json()["encounters"][0]["encounter_id"]
    # A student join clones the template; the clone gets a different id.
    room = control_room.get_active_room()
    r = client.post("/portal/students/register", data={
        "room_code": room.room_code, "encounter_id": template_id,
        "display_name": "Alice",
    })
    assert r.status_code == 200
    clone_id = r.json()["encounter_id"]

    r = client.get(f"/portal/room/encounter/{clone_id}")
    assert r.status_code == 200
    html = r.text
    assert "CLONE of" in html
