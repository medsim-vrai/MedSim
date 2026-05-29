"""M31 — Multi-patient wizard depth (per-row personas + curriculum)
and Per-Patient Console QR codes.
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


# ── Part B — Per-Patient Console QR codes ───────────────────────────

def test_encounter_console_renders_qr_card(client) -> None:
    r = client.post("/api/room/start", json={
        "label": "M31 QR test",
        "encounters": [{"scenario_name": "Bed 1", "persona_id": "P-001",
                         "patient_persona_id": "P-001", "ehr_id": "helix"}],
    })
    assert r.status_code == 200
    eid = r.json()["encounters"][0]["encounter_id"]
    join = r.json()["encounters"][0]["join_code"]
    r = client.get(f"/portal/room/encounter/{eid}")
    assert r.status_code == 200
    html = r.text
    # Three QR cells (chat / EHR / device) plus the card title.
    assert "card-network" in html
    assert "Chat station" in html
    assert "EHR station"  in html
    assert "Device station" in html
    # The QR URLs encode the join code for the encounter.
    assert "/join?code=" in html
    assert "/ehr/join?code=" in html
    assert "/device/join?code=" in html
    assert join in html


# ── Part A — per-row Characters multi-select + Curriculum overrides ──

def test_wizard_exposes_modules_and_programs_to_js(client) -> None:
    """The wizard's window.MEDSIM2 carries modules + programs lists
    so the per-row pickers can render them."""
    r = client.get("/portal/control")
    assert r.status_code == 200
    html = r.text
    assert "modulesForRoom" in html
    assert "programsForRoom" in html
    # personasForRoom carries roleGroup + safetyClass so the row's
    # persona picker can mirror Step 4's filters in a future pass.
    assert "roleGroup" in html


def test_room_start_carries_per_row_personas_modules_program_week(client) -> None:
    """The /api/room/start route already accepted these fields; the
    M31 wizard now SUBMITS them per row. Verify the encounter ends
    up with the right per-bed personas + modules + program/week."""
    from portal import control_room

    r = client.post("/api/room/start", json={
        "label": "Per-row depth",
        "encounters": [
            {"scenario_name": "Bed 1 — ED sepsis",
             "persona_id": "P-014",   # primary patient
             "patient_persona_id": "P-014",
             "personas": ["P-014", "P-001", "P-004"],   # patient + MD + charge RN
             "ehr_id": "helix",
             "program_id": "ADN-RN", "week": 4,
             "modules": ["M32", "M08", "M02"]},
            {"scenario_name": "Bed 2 — Peds fever",
             "persona_id": "P-003",
             "patient_persona_id": "P-003",
             "personas": ["P-003", "P-015"],   # peds patient + anxious parent
             "ehr_id": "helix",
             "program_id": "BSN-RN", "week": 6,
             "modules": ["M07", "M06"]},
        ],
    })
    assert r.status_code == 200
    eids = [e["encounter_id"] for e in r.json()["encounters"]]
    room = control_room.get_active_room()
    sepsis = room.encounters[eids[0]]
    peds   = room.encounters[eids[1]]

    # Sepsis bed carries patient + MD + charge RN, all three modules.
    assert set(sepsis.selected_personas) == {"P-014", "P-001", "P-004"}
    assert set(sepsis.selected_modules)  == {"M32", "M08", "M02"}
    assert sepsis.program_id == "ADN-RN"
    assert sepsis.week       == 4

    # Peds bed carries patient + parent, two modules.
    assert set(peds.selected_personas) == {"P-003", "P-015"}
    assert set(peds.selected_modules)  == {"M07", "M06"}
    assert peds.program_id == "BSN-RN"
    assert peds.week       == 6
    # No bleed.
    assert "M32" not in peds.selected_modules
    assert "P-014" not in peds.selected_personas


def test_qr_svg_route_responds(client) -> None:
    """The /api/qr.svg endpoint that the QR card's <img> tags hit
    must return an SVG payload."""
    r = client.get("/api/qr.svg?data=hello+world")
    assert r.status_code == 200
    assert "image/svg" in r.headers.get("content-type", "").lower()
    body = r.text
    assert "<svg" in body.lower()
