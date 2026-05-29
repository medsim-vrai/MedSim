"""M13 acceptance — shared mode keeps the v6 contract.

When chart_mode='shared', multiple students all join the same
encounter. The room has exactly one encounter (not N + 1), the
encounter's `assigned_student_ids` list grows by one per join, and
every student's chat station points at the SAME chart_event log.
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


def test_shared_mode_single_encounter_for_all_students(client) -> None:
    from portal import control_room

    # Start a room with one shared-mode encounter.
    r = client.post("/api/room/start", json={
        "label": "M13 shared mode test",
        "encounters": [{
            "scenario_name":      "Bed 1 — Kowalski",
            "persona_id":         "P-013",
            "patient_persona_id": "P-013",
            "ehr_id":             "helix",
            "chart_mode":         "shared",
        }],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    enc_id = body["encounters"][0]["encounter_id"]

    room = control_room.get_active_room()
    assert len(room.encounters) == 1

    # 3 students join — each lands on the SAME encounter.
    redirected_to_eids: list[str] = []
    redirected_to_joins: list[str] = []
    for name in ("Alice", "Bob", "Cara"):
        r = client.post("/portal/students/register", data={
            "room_code":    room.room_code,
            "encounter_id": enc_id,
            "display_name": name,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["is_clone"] is False
        assert body["cloned_from_id"] is None
        assert body["encounter_id"] == enc_id
        redirected_to_eids.append(body["encounter_id"])
        redirected_to_joins.append(
            body["redirect_url"].split("/station/")[1].split("/")[0]
        )

    # All 3 redirected to the SAME encounter.
    assert set(redirected_to_eids) == {enc_id}
    # And the same join code (the shared encounter's join code).
    assert len(set(redirected_to_joins)) == 1

    # Still exactly 1 encounter in the room — no clones created.
    assert len(room.encounters) == 1

    # Encounter's assigned_student_ids list grew to 3.
    enc = room.encounters[enc_id]
    assert len(enc.assigned_student_ids) == 3
    assert len(enc.stations) == 3  # one chat station per student


def test_mixed_shared_and_private_in_one_room(client) -> None:
    """A room may mix shared-mode and private-clone encounters. The
    behavior must be per-encounter — shared keeps one encounter,
    private spawns clones."""
    from portal import control_room

    r = client.post("/api/room/start", json={
        "label": "Mixed mode",
        "encounters": [
            {"scenario_name": "Bed 1 — shared", "persona_id": "P-001",
             "patient_persona_id": "P-001", "ehr_id": "helix",
             "chart_mode": "shared"},
            {"scenario_name": "Bed 2 — private", "persona_id": "P-013",
             "patient_persona_id": "P-013", "ehr_id": "helix",
             "chart_mode": "private_clone"},
        ],
    })
    assert r.status_code == 200
    eids = [e["encounter_id"] for e in r.json()["encounters"]]
    eid_shared, eid_private = eids
    room = control_room.get_active_room()

    # 2 students each join shared bed; 2 students each join private bed.
    for n in ("S1", "S2"):
        r = client.post("/portal/students/register", data={
            "room_code": room.room_code, "encounter_id": eid_shared,
            "display_name": n,
        })
        assert r.status_code == 200
        assert r.json()["is_clone"] is False
    for n in ("P1", "P2"):
        r = client.post("/portal/students/register", data={
            "room_code": room.room_code, "encounter_id": eid_private,
            "display_name": n,
        })
        assert r.status_code == 200
        assert r.json()["is_clone"] is True

    # Final room state: shared bed = 1 encounter with 2 students,
    # private template = 1 encounter, + 2 clones = 3 encounters
    # downstream of the private template, total = 4 encounters in
    # the room (1 shared + 1 template + 2 clones).
    assert len(room.encounters) == 4
    assert len(room.encounters[eid_shared].assigned_student_ids) == 2
    assert len(room.encounters[eid_private].assigned_student_ids) == 0
    clones = [e for e in room.encounters.values()
               if e.cloned_from_id == eid_private]
    assert len(clones) == 2
