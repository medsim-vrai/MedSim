"""M12 acceptance — picking an Activity in the wizard seeds the
encounter with the activity's content.

The wizard's room-mode submit (handled client-side in control.js)
attaches the activity-derived fields to the POST body. The server
side of the contract: ``POST /api/room/start`` must carry
``activity_id`` onto the Encounter and respect the activity's
``seed_modules`` (merged with the wizard's wide modules) and its
``scenario_text`` (used when the wizard's wide scenario_text is
empty for that row).

We exercise the contract end-to-end by sending the JSON the JS
would build — bypassing the browser — and asserting the resulting
Encounter carries the right fields.
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
    with TestClient(server.app) as c:
        c.cookies.set(auth.COOKIE_NAME, auth.issue_session_token(vault))
        yield c
    control_room._reset_for_tests()


def test_wizard_picking_activity_seeds_encounter(client) -> None:
    from portal import activities, control_room
    # Fetch the activity-as-encounter-entry shape (what the JS does
    # to pre-fill the row before submit).
    r = client.get("/api/activities/builtin_msurg_dka/encounter_entry")
    assert r.status_code == 200
    entry = r.json()

    # Now finalize a room using that entry, exactly as the JS would
    # send it to /api/room/start.
    r = client.post("/api/room/start", json={
        "label": "Activity-seeded room",
        "encounters": [entry],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["encounters"]) == 1

    # The active encounter carries the activity's content.
    room = control_room.get_active_room()
    enc_id = body["encounters"][0]["encounter_id"]
    enc = room.encounters[enc_id]
    assert enc.activity_id == "builtin_msurg_dka"
    assert enc.scenario_name == "Med-surg · DKA management"
    assert enc.patient_persona_id == "P-005"
    assert "DKA" in enc.scenario_text
    assert "M22" in enc.selected_modules
    assert enc.chart_mode == "shared"


def test_wizard_picking_activity_in_one_of_many_rows(client) -> None:
    """The wizard's room-mode editor allows MIXING activity-seeded
    rows and free-form rows in the same room. Verify a 3-row room
    where rows 1 and 3 are activity-seeded but row 2 is custom."""
    from portal import control_room

    activity_entry_1 = client.get(
        "/api/activities/builtin_ed_sepsis_delirium/encounter_entry"
    ).json()
    activity_entry_3 = client.get(
        "/api/activities/builtin_msurg_resp_failure/encounter_entry"
    ).json()
    free_form_2 = {
        "scenario_name":      "Bed 2 — Custom",
        "persona_id":         "P-013",
        "patient_persona_id": "P-013",
        "ehr_id":             "helix",
        "chart_mode":         "shared",
    }

    r = client.post("/api/room/start", json={
        "label": "Mixed activity + custom room",
        "encounters": [activity_entry_1, free_form_2, activity_entry_3],
    })
    assert r.status_code == 200, r.text
    eids = [e["encounter_id"] for e in r.json()["encounters"]]
    room = control_room.get_active_room()

    enc_a = room.encounters[eids[0]]
    enc_b = room.encounters[eids[1]]
    enc_c = room.encounters[eids[2]]

    assert enc_a.activity_id == "builtin_ed_sepsis_delirium"
    assert enc_a.patient_persona_id == "P-014"

    assert enc_b.activity_id is None
    assert enc_b.scenario_name == "Bed 2 — Custom"
    assert enc_b.patient_persona_id == "P-013"

    assert enc_c.activity_id == "builtin_msurg_resp_failure"
    assert enc_c.patient_persona_id == "P-006"


def test_wizard_picking_custom_activity_round_trips(client) -> None:
    """An instructor-authored custom activity (not a built-in) seeds
    an encounter just the same."""
    from portal import control_room

    created = client.post("/api/activities", json={
        "label": "Custom · OR handoff",
        "seed_persona_id": "P-008",
        "seed_modules": ["M02", "M08"],
        "scenario_text": "Patient POD #0 status post lap chole.",
        "default_chart_mode": "private_clone",
    }).json()
    aid = created["activity_id"]
    entry = client.get(f"/api/activities/{aid}/encounter_entry").json()
    assert entry["chart_mode"] == "private_clone"

    r = client.post("/api/room/start", json={
        "label": "Custom-activity room",
        "encounters": [entry],
    })
    assert r.status_code == 200, r.text
    eid = r.json()["encounters"][0]["encounter_id"]
    enc = control_room.get_active_room().encounters[eid]
    assert enc.activity_id == aid
    assert enc.patient_persona_id == "P-008"
    assert enc.chart_mode == "private_clone"
    assert "M02" in enc.selected_modules
    assert "M08" in enc.selected_modules


def test_wizard_seed_builtins_runs_on_first_request(client) -> None:
    """The startup hook in `server._seed_activity_catalog` should have
    populated the 8 built-ins by the time the first request lands."""
    r = client.get("/api/activities?builtin_only=true")
    assert r.status_code == 200
    assert len(r.json()["activities"]) == 8
