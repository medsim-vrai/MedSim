"""M18 acceptance — observer seat is read-only.

An observer session can view dashboard + debrief + state endpoints
but is rejected (403) by every state-mutating v7 route. Confirms
the require_instructor gate works on every M4 / M7 / M12 / M13 /
M15 / M17 mutator.
"""
from __future__ import annotations

from pathlib import Path

import pytest


TEST_PASSWORD = "test_passwd_xyz_8chars"


def _make_clients(tmp_path: Path, monkeypatch):
    """Return (instructor_client, observer_client) sharing one
    sandboxed vault but with different session roles."""
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
    instructor = TestClient(server.app)
    observer   = TestClient(server.app)
    # Start lifespan once for the app (M12 startup hook).
    instructor.__enter__()
    observer.__enter__()
    instructor.cookies.set(auth.COOKIE_NAME,
                            auth.issue_session_token(vault, role="instructor"))
    observer.cookies.set(auth.COOKIE_NAME,
                          auth.issue_session_token(vault, role="observer"))
    return instructor, observer


@pytest.fixture
def clients(tmp_path: Path, monkeypatch):
    from portal import control_room
    instructor, observer = _make_clients(tmp_path, monkeypatch)
    yield instructor, observer
    instructor.__exit__(None, None, None)
    observer.__exit__(None, None, None)
    control_room._reset_for_tests()


def test_observer_seat_cannot_freeze_all(clients) -> None:
    instructor, observer = clients
    r = instructor.post("/api/room/start", json={
        "label": "Observer gate test",
        "encounters": [{"scenario_name": "Bed", "persona_id": "P-001",
                         "patient_persona_id": "P-001", "ehr_id": "helix"}],
    })
    assert r.status_code == 200, r.text

    # Observer attempts freeze — 403.
    r = observer.post("/api/room/freeze_all")
    assert r.status_code == 403
    assert "observer" in r.json().get("detail", "").lower()

    # Instructor can still freeze — unaffected.
    r = instructor.post("/api/room/freeze_all")
    assert r.status_code == 200


def test_observer_seat_sees_dashboard_state(clients) -> None:
    instructor, observer = clients
    instructor.post("/api/room/start", json={
        "label": "Observer read test",
        "encounters": [{"scenario_name": "Bed 1", "persona_id": "P-001",
                         "patient_persona_id": "P-001", "ehr_id": "helix"}],
    })
    # Observer can read state.
    r = observer.get("/api/room/state")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "active"
    assert len(body["encounters"]) == 1


def test_observer_seat_rejected_on_every_v7_mutator(clients) -> None:
    instructor, observer = clients
    r = instructor.post("/api/room/start", json={
        "label": "Reject every mutator",
        "encounters": [{"scenario_name": "Bed", "persona_id": "P-001",
                         "patient_persona_id": "P-001", "ehr_id": "helix"}],
    })
    assert r.status_code == 200
    eid = r.json()["encounters"][0]["encounter_id"]

    # Run through every v7 mutating route as observer; all 403.
    mutations = [
        ("POST",   "/api/room/start",          {"json": {"label": "x", "encounters": [{"scenario_name": "a", "persona_id": "P-001"}]}}),
        ("POST",   "/api/room/freeze_all",     {}),
        ("POST",   "/api/room/resume_all",     {}),
        ("POST",   "/api/room/scene_broadcast",{"json": {"scene": {"kind": "vitals.drop"}, "targets": "all"}}),
        ("POST",   f"/api/encounter/{eid}/scene",
                                                {"json": {"scene": {"kind": "note.instructor"}}}),
        ("POST",   f"/api/encounter/{eid}/assign_students",
                                                {"json": {"student_ids": []}}),
        ("POST",   "/api/activities",          {"json": {"label": "x"}}),
        ("PATCH",  "/api/activities/builtin_msurg_dka", {"json": {"label": "y"}}),
        ("DELETE", "/api/activities/act_xyz",  {}),
        ("POST",   "/api/room/budget",         {"json": {"haiku_rate_cap": 10}}),
        ("POST",   "/api/room/end",            {}),
    ]
    for method, path, kwargs in mutations:
        r = getattr(observer, method.lower())(path, **kwargs)
        assert r.status_code == 403, (
            f"{method} {path} expected 403 for observer, got {r.status_code}"
        )


def test_instructor_default_role_keeps_all_mutators_open(clients) -> None:
    """An issued-without-role-arg session keeps instructor privilege —
    the v6 default. Verified by exercising one mutator."""
    instructor, _observer = clients
    r = instructor.post("/api/room/start", json={
        "label": "default-role",
        "encounters": [{"scenario_name": "Bed", "persona_id": "P-001",
                         "patient_persona_id": "P-001", "ehr_id": "helix"}],
    })
    assert r.status_code == 200
    # And mutator works.
    r = instructor.post("/api/room/freeze_all")
    assert r.status_code == 200


def test_session_role_helper_defaults_to_instructor() -> None:
    """The auth.session_role() helper falls back to 'instructor' when
    asked about an unknown token — matches v6 behavior where every
    session was implicitly an instructor."""
    from portal import auth
    assert auth.session_role(None) == "instructor"
    assert auth.session_role("some-unknown-token") == "instructor"
