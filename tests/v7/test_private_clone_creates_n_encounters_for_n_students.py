"""M13 acceptance — private_clone mode spawns one clone per student.

A room finalized with a private_clone template encounter has ONE
encounter in the active room at start. When N students join via
the M9 student-join flow, the system spawns N clones (one per
student), each with its own join code and chart, leaving the
template intact. After N joins the room has 1 template + N clones
= N+1 encounters total.
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


def test_private_clone_creates_n_encounters_for_n_students(client) -> None:
    from portal import control_room

    # Start a room with one private_clone template.
    r = client.post("/api/room/start", json={
        "label": "M13 private clone test",
        "encounters": [{
            "scenario_name":      "Bed 1 — Diaz (template)",
            "persona_id":         "P-001",
            "patient_persona_id": "P-001",
            "ehr_id":             "helix",
            "chart_mode":         "private_clone",
        }],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    template_id = body["encounters"][0]["encounter_id"]

    room = control_room.get_active_room()
    assert len(room.encounters) == 1
    assert room.is_template(template_id) is True
    assert room.encounters[template_id].chart_mode == "private_clone"
    assert room.encounters[template_id].cloned_from_id is None

    # 3 students join — each should land on their own clone.
    redirects: list[str] = []
    clone_ids: list[str] = []
    for name in ("Alice", "Bob", "Cara"):
        r = client.post("/portal/students/register", data={
            "room_code":    room.room_code,
            "encounter_id": template_id,
            "display_name": name,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["is_clone"] is True
        assert body["cloned_from_id"] == template_id
        # The redirect URL points at the CLONE's join code, NOT the template's.
        assert body["encounter_id"] != template_id
        clone_ids.append(body["encounter_id"])
        redirects.append(body["redirect_url"])

    # Room now holds 1 template + 3 clones.
    assert len(room.encounters) == 4
    assert all(cid in room.encounters for cid in clone_ids)
    # Each clone has cloned_from_id pointing at the template.
    for cid in clone_ids:
        assert room.encounters[cid].cloned_from_id == template_id
        assert room.encounters[cid].chart_mode == "private_clone"
        # The clone inherits scenario content from the template.
        assert (room.encounters[cid].patient_persona_id ==
                room.encounters[template_id].patient_persona_id)

    # All 3 redirect URLs point at distinct clone join codes.
    join_codes = [r.split("/station/")[1].split("/")[0] for r in redirects]
    assert len(set(join_codes)) == 3

    # Each student is assigned to their own clone (not the template).
    for cid, name in zip(clone_ids, ("Alice", "Bob", "Cara")):
        students_on_clone = [s for s in room.students.values()
                              if s.assigned_encounter_id == cid]
        assert len(students_on_clone) == 1
        assert students_on_clone[0].display_name == name


def test_private_clone_template_is_filtered_from_join_picker_after_clones_exist(client) -> None:
    """The join page still shows the template (so the next student
    can pick the bed and get their own clone) — the clones themselves
    are hidden from the picker."""
    from portal import control_room

    r = client.post("/api/room/start", json={
        "label": "Picker visibility test",
        "encounters": [{
            "scenario_name":      "Bed 1 — Diaz (template)",
            "persona_id":         "P-001",
            "patient_persona_id": "P-001",
            "ehr_id":             "helix",
            "chart_mode":         "private_clone",
        }],
    })
    assert r.status_code == 200
    room = control_room.get_active_room()
    template_id = list(room.encounters.keys())[0]

    # First student joins — clone created.
    r = client.post("/portal/students/register", data={
        "room_code": room.room_code, "encounter_id": template_id,
        "display_name": "Alice",
    })
    assert r.status_code == 200

    # The join page should still list ONLY the template; the clone
    # for Alice must not appear in the picker.
    r = client.get(f"/portal/students/join?code={room.room_code}")
    assert r.status_code == 200
    html = r.text
    # The template's encounter id must be referenced (so the next
    # student can pick the bed and get their own clone).
    assert template_id in html
    # No clone of the template should be in the rendered picker
    # — but the template itself uses the SAME persona_id string. So
    # we check by counting `encounter-card` divs: still exactly 1.
    assert html.count('data-encounter-id="') == 1
