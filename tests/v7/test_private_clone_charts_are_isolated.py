"""M13 acceptance — private-clone charts are independent.

Two students each get their own clone of the same template. A
chart_event written to one clone's session_id must not appear when
reading the other clone's chart. The template itself accumulates
no chart events from the student-driven flow (no student joins
the template directly).
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

    from portal import auth, control_room, credentials, voices as _voices
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


def test_private_clone_charts_are_isolated(client) -> None:
    from portal import control_room, ehr_db

    # Start a room with one private_clone template.
    r = client.post("/api/room/start", json={
        "label": "M13 chart isolation test",
        "encounters": [{
            "scenario_name":      "Bed 1 — private template",
            "persona_id":         "P-001",
            "patient_persona_id": "P-001",
            "ehr_id":             "helix",
            "chart_mode":         "private_clone",
        }],
    })
    assert r.status_code == 200
    template_id = r.json()["encounters"][0]["encounter_id"]
    room = control_room.get_active_room()

    # 2 students join — each gets a clone.
    for name in ("Alice", "Bob"):
        r = client.post("/portal/students/register", data={
            "room_code":    room.room_code,
            "encounter_id": template_id,
            "display_name": name,
        })
        assert r.status_code == 200

    clones = [e for e in room.encounters.values()
               if e.cloned_from_id == template_id]
    assert len(clones) == 2
    clone_alice = next(c for c in clones
                        if any(s.display_name == "Alice"
                                and s.assigned_encounter_id == c.id
                                for s in room.students.values()))
    clone_bob = next(c for c in clones
                      if any(s.display_name == "Bob"
                              and s.assigned_encounter_id == c.id
                              for s in room.students.values()))
    assert clone_alice.id != clone_bob.id

    # Inject a scene at Alice's clone — should write to her clone's
    # chart_event log only.
    r = client.post(f"/api/encounter/{clone_alice.id}/scene", json={
        "scene": {"kind": "vitals.drop", "params": {"sbp": 70}},
    })
    assert r.status_code == 200, r.text

    # Inject a different scene at Bob's clone.
    r = client.post(f"/api/encounter/{clone_bob.id}/scene", json={
        "scene": {"kind": "note.instructor",
                  "params": {"text": "Bob-only instructor note."}},
    })
    assert r.status_code == 200, r.text

    # Alice's chart has the vitals row only; Bob's has the note only;
    # the template has neither.
    events_alice = ehr_db.events(clone_alice.id)
    events_bob   = ehr_db.events(clone_bob.id)
    events_tpl   = ehr_db.events(template_id)

    assert len(events_alice) == 1
    assert events_alice[0]["type"] == "vitals.record"
    assert events_alice[0]["payload"]["sbp"] == 70

    assert len(events_bob) == 1
    assert events_bob[0]["type"] == "note.save"
    assert "Bob-only" in events_bob[0]["payload"]["body"]

    # Template chart_event log has no rows from the student-driven
    # path (the per-clone scenes don't bleed back to the template).
    assert events_tpl == []


def test_clone_inherits_template_scenario_content(client) -> None:
    """A clone must inherit the template's scenario_text, modules,
    persona, and ehr — only the encounter id, join code, and chart
    diverge per clone."""
    from portal import control_room

    r = client.post("/api/room/start", json={
        "label": "Clone inheritance",
        "encounters": [{
            "scenario_name":      "Bed 1 — Inheritance test",
            "scenario_text":      "Patient POD#3 from open chole. Vitals stable.",
            "persona_id":         "P-005",
            "patient_persona_id": "P-005",
            "ehr_id":             "cyrus",
            "chart_mode":         "private_clone",
            "modules":            ["M22", "M02"],
        }],
    })
    assert r.status_code == 200
    template_id = r.json()["encounters"][0]["encounter_id"]
    room = control_room.get_active_room()

    r = client.post("/portal/students/register", data={
        "room_code": room.room_code, "encounter_id": template_id,
        "display_name": "Cara",
    })
    assert r.status_code == 200
    clone_id = r.json()["encounter_id"]

    template = room.encounters[template_id]
    clone    = room.encounters[clone_id]

    # Diverging fields.
    assert clone.id != template.id
    assert clone.join_code != template.join_code
    assert clone.cloned_from_id == template.id

    # Inherited content.
    assert clone.scenario_text  == template.scenario_text
    assert clone.patient_persona_id == "P-005"
    assert clone.ehr_id          == template.ehr_id
    assert clone.chart_mode      == "private_clone"
    assert clone.selected_modules == template.selected_modules
    assert clone.activity_id     == template.activity_id


def test_dashboard_state_lists_clones_alongside_templates(client) -> None:
    """The instructor dashboard's /api/room/state returns BOTH the
    template and the clones — the operator wants to see what each
    student is working on. The student-join page hides clones (M13
    contract); the instructor dashboard surfaces them."""
    from portal import control_room

    r = client.post("/api/room/start", json={
        "label": "Dashboard view",
        "encounters": [{
            "scenario_name":      "Bed 1 — private template",
            "persona_id":         "P-001",
            "patient_persona_id": "P-001",
            "ehr_id":             "helix",
            "chart_mode":         "private_clone",
        }],
    })
    assert r.status_code == 200
    template_id = r.json()["encounters"][0]["encounter_id"]
    room = control_room.get_active_room()
    for name in ("A", "B", "C"):
        r = client.post("/portal/students/register", data={
            "room_code": room.room_code,
            "encounter_id": template_id,
            "display_name": name,
        })
        assert r.status_code == 200

    state = client.get("/api/room/state").json()
    # 1 template + 3 clones = 4 encounters surfaced to the instructor.
    assert len(state["encounters"]) == 4
