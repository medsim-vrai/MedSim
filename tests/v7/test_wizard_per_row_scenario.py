"""Bugfix tests — per-row scenario authoring + wizard 500.

Two operator-reported issues:

  1. /portal/control 500'd when a multi-encounter room was active
     because v6's `get_active()` raised on >1 encounter. Fixed by
     changing the contract — `get_active` now returns None and a
     new `get_active_strict` is available for callers that want the
     loud failure.

  2. The Room-of-N wizard should let each bed have its own scenario
     text. The Step 4r row now exposes a per-row scenario textarea
     (collapsible drawer); the submit handler prefers the row's
     textarea value over the activity-derived stash AND over
     Step 3's wizard-wide scenario_text.
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


# ── Bug 1: /portal/control no longer 500s during room mode ──────────

def test_portal_control_renders_when_multi_encounter_room_is_active(client) -> None:
    """Reproduces the operator's reported 500. With a 2-encounter
    room active, /portal/control must render (not crash). The wizard
    should show "no single-patient session active" and let the
    operator either inspect the existing room or start a new one."""
    r = client.post("/api/room/start", json={
        "label": "Repro room",
        "encounters": [
            {"scenario_name": "Bed 1", "persona_id": "P-001",
             "patient_persona_id": "P-001", "ehr_id": "helix"},
            {"scenario_name": "Bed 2", "persona_id": "P-013",
             "patient_persona_id": "P-013", "ehr_id": "helix"},
        ],
    })
    assert r.status_code == 200
    r = client.get("/portal/control")
    assert r.status_code == 200, (
        "Wizard 500'd in room mode — get_active() should return None, "
        "not raise."
    )
    # The wizard page itself renders.
    assert "Control room" in r.text


def test_get_active_returns_none_on_multi_encounter_room(client) -> None:
    """Direct data-layer check on the new contract."""
    from portal import control_session, control_room
    r = client.post("/api/room/start", json={
        "label": "Soft get_active",
        "encounters": [
            {"scenario_name": f"Bed {i+1}", "persona_id": f"P-{i+1:03d}",
             "patient_persona_id": f"P-{i+1:03d}", "ehr_id": "helix"}
            for i in range(3)
        ],
    })
    assert r.status_code == 200
    # Old behavior: would raise. New behavior: returns None.
    assert control_session.get_active() is None
    assert control_room.get_active() is None
    # Strict helper still raises for callers that opt in.
    with pytest.raises(RuntimeError):
        control_room.get_active_strict()


# ── Bug 2: per-row scenario authoring ────────────────────────────────

def test_per_row_scenario_text_wins_over_wizard_wide(client) -> None:
    """Each encounter row carries its own scenario_text in the
    `/api/room/start` body. The wizard's submit handler builds the
    body so that the row's textarea value takes precedence over both
    the activity-derived stash and Step 3's wizard-wide scenario."""
    from portal import control_room

    r = client.post("/api/room/start", json={
        "label": "Per-row scenarios",
        "encounters": [
            {"scenario_name": "Bed 1 — sepsis",
             "persona_id": "P-001", "patient_persona_id": "P-001",
             "ehr_id": "helix", "chart_mode": "shared",
             "scenario_text": "POD#2 sigmoid resection. Sepsis 1-hour bundle."},
            {"scenario_name": "Bed 2 — DKA",
             "persona_id": "P-005", "patient_persona_id": "P-005",
             "ehr_id": "helix", "chart_mode": "shared",
             "scenario_text": "23yo M T1DM. Glucose 524, anion gap 22."},
            {"scenario_name": "Bed 3 — postop pain",
             "persona_id": "P-012", "patient_persona_id": "P-012",
             "ehr_id": "helix", "chart_mode": "shared",
             "scenario_text": "POD#1 lap chole. Pain 7/10. PCA management."},
        ],
    })
    assert r.status_code == 200
    eids = [e["encounter_id"] for e in r.json()["encounters"]]
    room = control_room.get_active_room()
    sepsis = room.encounters[eids[0]]
    dka    = room.encounters[eids[1]]
    pain   = room.encounters[eids[2]]
    # Each encounter carries its OWN scenario_text, not the wizard-wide
    # one or another row's.
    assert "Sepsis 1-hour bundle" in sepsis.scenario_text
    assert "T1DM"                in dka.scenario_text
    assert "PCA management"      in pain.scenario_text
    # No bleed.
    assert "Sepsis" not in dka.scenario_text
    assert "T1DM"   not in pain.scenario_text


def test_wizard_template_includes_per_row_scenario_textarea(client) -> None:
    """The Step 4r template renders the per-row scenario drawer
    + textarea hooks the JS reads/writes."""
    r = client.get("/portal/control")
    assert r.status_code == 200
    html = r.text
    # The Step 4r pane is in the markup.
    assert 'data-pane="4r"' in html
    # The new per-row controls land via JS at render time, so the
    # static HTML just carries the container + the help text that
    # says scenarios are per-row. M32 rephrased this copy from
    # "Each bed can have its own scenario" to "each bed is its own
    # scenario" when the wizard-wide Scenario step (2) was hidden in
    # room mode — both phrasings carry the same intent.
    assert "each bed is its own scenario" in html.lower()


def test_per_row_scenario_persists_through_round_trip_with_clones(client) -> None:
    """When the row's chart_mode='private_clone' creates clones at
    join time, every clone inherits the template's scenario_text —
    so the per-row authoring carries through to the per-student
    clone the bedside student lands on."""
    from portal import control_room
    r = client.post("/api/room/start", json={
        "label": "Per-row + private clones",
        "encounters": [
            {"scenario_name": "Bed 1 — private",
             "persona_id": "P-001", "patient_persona_id": "P-001",
             "ehr_id": "helix", "chart_mode": "private_clone",
             "scenario_text": "Unique scenario for Bed 1 clones."},
        ],
    })
    assert r.status_code == 200
    template_id = r.json()["encounters"][0]["encounter_id"]
    room = control_room.get_active_room()
    # Student joins → spawns a clone.
    r = client.post("/portal/students/register", data={
        "room_code": room.room_code, "encounter_id": template_id,
        "display_name": "Alice",
    })
    assert r.status_code == 200
    clone_id = r.json()["encounter_id"]
    clone = room.encounters[clone_id]
    assert "Unique scenario for Bed 1 clones" in clone.scenario_text
