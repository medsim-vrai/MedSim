"""M15 acceptance — cohort debrief route renders after end_room.

The /api/room/end flow should save a cohort debrief before clearing
the singleton, and /portal/debrief/cohort/{room_id} should then
render that saved JSON as HTML.
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
    # Sandbox debrief save paths so we don't pollute the repo's data/.
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


def test_end_room_saves_cohort_debrief(client) -> None:
    r = client.post("/api/room/start", json={
        "label": "End-then-debrief test",
        "encounters": [
            {"scenario_name": "Bed 1", "persona_id": "P-001",
             "patient_persona_id": "P-001", "ehr_id": "helix"},
            {"scenario_name": "Bed 2", "persona_id": "P-013",
             "patient_persona_id": "P-013", "ehr_id": "helix"},
        ],
    })
    assert r.status_code == 200
    room_id = r.json()["room_id"]

    r = client.post("/api/room/end")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["cohort_debrief_saved"] is True
    assert body["cohort_debrief_url"] == f"/portal/debrief/cohort/{room_id}"


def test_cohort_debrief_route_renders_for_ended_room(client) -> None:
    client.post("/api/room/start", json={
        "label": "Render route test",
        "encounters": [{"scenario_name": "Bed 1", "persona_id": "P-001",
                         "patient_persona_id": "P-001", "ehr_id": "helix"}],
    })
    room_id = client.get("/api/room/state").json()["room_id"]
    client.post("/api/room/end")

    r = client.get(f"/portal/debrief/cohort/{room_id}")
    assert r.status_code == 200, r.text
    html = r.text
    # Page renders the PEARLS tab structure.
    assert "Cohort debrief" in html
    assert "Reactions" in html and "Description" in html
    assert "Analysis" in html and "Application" in html
    # The room code from the saved debrief surfaces in the header.
    assert "Render route test" in html


def test_cohort_debrief_route_404s_for_unknown_room(client) -> None:
    r = client.get("/portal/debrief/cohort/room_never_existed")
    assert r.status_code == 404


def test_cohort_debrief_json_endpoint_returns_data(client) -> None:
    client.post("/api/room/start", json={
        "label": "JSON read test",
        "encounters": [{"scenario_name": "Bed", "persona_id": "P-001",
                         "patient_persona_id": "P-001", "ehr_id": "helix"}],
    })
    room_id = client.get("/api/room/state").json()["room_id"]
    client.post("/api/room/end")

    r = client.get(f"/api/debrief/cohort/{room_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["room_id"] == room_id
    assert "pearls" in body
    assert "reactions" in body["pearls"]


def test_cohort_debrief_save_notes_round_trips(client) -> None:
    client.post("/api/room/start", json={
        "label": "Notes save",
        "encounters": [{"scenario_name": "Bed", "persona_id": "P-001",
                         "patient_persona_id": "P-001", "ehr_id": "helix"}],
    })
    room_id = client.get("/api/room/state").json()["room_id"]
    client.post("/api/room/end")

    r = client.post(f"/api/debrief/cohort/{room_id}/notes", json={
        "reactions_notes": "Students felt rushed in the first 5 min.",
        "commitments": ["Run a pre-brief walkthrough next week.",
                         "Sequence ABG draws earlier."],
    })
    assert r.status_code == 200

    # Round-trip via the JSON endpoint.
    r = client.get(f"/api/debrief/cohort/{room_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["pearls"]["reactions"]["notes"] == \
        "Students felt rushed in the first 5 min."
    assert body["pearls"]["application"]["commitments"] == [
        "Run a pre-brief walkthrough next week.",
        "Sequence ABG draws earlier.",
    ]


def test_cohort_debrief_index_renders(client) -> None:
    # Create + end a couple of rooms to populate the index.
    for label in ("Index test A", "Index test B"):
        client.post("/api/room/start", json={
            "label": label,
            "encounters": [{"scenario_name": "Bed", "persona_id": "P-001",
                             "patient_persona_id": "P-001", "ehr_id": "helix"}],
        })
        client.post("/api/room/end")

    r = client.get("/portal/cohort-debriefs")
    assert r.status_code == 200
    html = r.text
    assert "Cohort debriefs" in html
    assert "Index test A" in html
    assert "Index test B" in html
