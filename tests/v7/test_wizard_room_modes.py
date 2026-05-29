"""M6 acceptance — wizard step-0 mode toggle.

Verifies that both wizard finalize pathways produce the right
ControlRoom shape:

  1. Single-patient finalize (POST /portal/control/start) — a form
     submit that creates one encounter. v6-compat call. In v7 this
     transparently makes a ControlRoom-of-1 (M2 wiring), so the
     active room ends with exactly one encounter and `get_active()`
     returns it.

  2. Room finalize (POST /api/room/start) — JSON submit that creates
     N encounters. M4 route. The active room ends with exactly N
     encounters and N distinct join codes.

These two pathways are what the M6 wizard JS exposes through its
Single Patient / Room of N toggle.
"""
from __future__ import annotations

from pathlib import Path

import pytest


TEST_PASSWORD = "test_passwd_xyz_8chars"


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    """Sandboxed TestClient mirroring test_room_api.py — fresh HOME,
    fresh vault, control_room singleton reset between tests."""
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
    c = TestClient(server.app)
    c.cookies.set(auth.COOKIE_NAME, auth.issue_session_token(vault))
    yield c
    control_room._reset_for_tests()


def test_wizard_single_patient_creates_implicit_room_of_one(client) -> None:
    """The v6 single-patient finalize path keeps working in v7. The
    underlying create_session call (M2 wiring) creates a ControlRoom
    holding exactly one Encounter; `control_room.get_active()` returns
    that encounter."""
    from portal import control_room

    r = client.post("/portal/control/start", data={
        "scenario_name":  "Wizard single-mode test",
        "scenario_notes": "single-patient finalize",
        "scenario_text":  "Postop day 1, 58yo F.",
        "program_id":     "BSN-RN",
        "week":           "8",
        "modules":        ["M22"],
        "personas":       ["P-013"],
        "ehr_id":         "helix",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True, body
    assert body["redirect_url"] == "/portal/control/ops"
    assert len(body["join_code"]) == 6

    # The active room has exactly one encounter.
    room = control_room.get_active_room()
    assert room is not None
    assert len(room.encounters) == 1

    # v6-compat get_active() returns that sole encounter.
    enc = control_room.get_active()
    assert enc is not None
    assert enc.join_code == body["join_code"]
    assert enc.id == body["session_id"]
    assert enc.room_id == room.room_id
    # Scenario fields carried through.
    assert enc.scenario_name == "Wizard single-mode test"
    assert "P-013" in enc.selected_personas


def test_wizard_room_of_4_creates_4_encounters(client) -> None:
    """The room-mode finalize path (M4 /api/room/start) creates exactly
    N encounters with distinct join codes. This is what the M6 wizard's
    Room-of-N branch POSTs after collecting N encounter configs."""
    from portal import control_room

    payload = {
        "label": "M6 wizard test — 4-bed room",
        "encounters": [
            {"scenario_name": "Bed 1 — Mr. Diaz",
             "persona_id":    "P-001", "ehr_id": "helix",
             "chart_mode":    "shared"},
            {"scenario_name": "Bed 2 — Ms. Kowalski",
             "persona_id":    "P-013", "ehr_id": "cyrus",
             "chart_mode":    "shared"},
            {"scenario_name": "Bed 3 — Mr. Patel",
             "persona_id":    "P-005", "ehr_id": "meridian",
             "chart_mode":    "shared"},
            {"scenario_name": "Bed 4 — Mrs. O'Connor",
             "persona_id":    "P-015", "ehr_id": "helix",
             "chart_mode":    "private_clone"},
        ],
    }
    r = client.post("/api/room/start", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert len(body["encounters"]) == 4

    # All 4 join codes are distinct + 6 chars.
    join_codes = [e["join_code"] for e in body["encounters"]]
    assert len(set(join_codes)) == 4
    assert all(len(jc) == 6 for jc in join_codes)

    # The active room owns exactly the 4 encounters we asked for.
    room = control_room.get_active_room()
    assert room is not None
    assert len(room.encounters) == 4
    assert room.label == "M6 wizard test — 4-bed room"

    # Encounter fields carried through.
    diaz = next(e for e in room.encounters.values()
                 if e.scenario_name == "Bed 1 — Mr. Diaz")
    assert diaz.patient_persona_id == "P-001"
    assert diaz.ehr_id == "helix"
    assert diaz.chart_mode == "shared"

    oconnor = next(e for e in room.encounters.values()
                    if e.scenario_name.startswith("Bed 4"))
    assert oconnor.chart_mode == "private_clone"


def test_wizard_room_of_4_dashboard_state_reflects_each_encounter(client) -> None:
    """End-to-end sanity: after the room-mode finalize, the dashboard
    poll (/api/room/state) returns one row per encounter — which is
    what the charge-nurse dashboard (M5) consumes."""
    r = client.post("/api/room/start", json={
        "label": "Dashboard state test",
        "encounters": [
            {"scenario_name": f"Bed {i + 1}", "persona_id": f"P-{i + 1:03d}",
             "ehr_id": "helix"} for i in range(4)
        ],
    })
    assert r.status_code == 200, r.text

    state = client.get("/api/room/state").json()
    assert state["status"] == "active"
    assert len(state["encounters"]) == 4
    join_codes = [e["join_code"] for e in state["encounters"]]
    assert len(set(join_codes)) == 4


def test_wizard_room_finalize_replaces_prior_single_patient_room(client) -> None:
    """Operator demos a single-patient session, then switches to room
    mode. The room finalize must end the prior single-patient
    encounter and stand up the fresh multi-encounter room. (Without
    this, the wizard's behavior would be 'sometimes you get a room of
    N+1 by accident' — bad UX.)"""
    from portal import control_room

    # First: single-patient finalize.
    r = client.post("/portal/control/start", data={
        "scenario_name": "demo-single",
        "personas": ["P-001"],
        "ehr_id":   "helix",
    })
    assert r.status_code == 200
    assert len(control_room.get_active_room().encounters) == 1

    # Now: room finalize — must end the prior room.
    r = client.post("/api/room/start", json={
        "label": "Switching to room mode",
        "encounters": [
            {"scenario_name": "Bed 1", "persona_id": "P-013", "ehr_id": "helix"},
            {"scenario_name": "Bed 2", "persona_id": "P-005", "ehr_id": "cyrus"},
        ],
    })
    assert r.status_code == 200
    room = control_room.get_active_room()
    assert room is not None
    assert len(room.encounters) == 2
    # The old single-patient encounter is gone.
    assert all(e.scenario_name != "demo-single"
                for e in room.encounters.values())
