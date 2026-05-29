"""M17 acceptance — Haiku rate cap throttles turns.

The RoomBudgetTracker's check_haiku_turn returns
Decision(allow=False, fallback='refuse') once the sliding-60s
window reaches the cap. record_haiku_turn stamps a successful
turn; the window prunes events older than 60s automatically.

Also exercises the M17 routes for getting + setting the cap.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from portal.budgets import RoomBudgetTracker


TEST_PASSWORD = "test_passwd_xyz_8chars"


def test_haiku_rate_cap_allow_under_cap() -> None:
    t = RoomBudgetTracker(haiku_rate_cap=5)
    for _ in range(4):
        d = t.check_haiku_turn("enc-a")
        assert d.allow is True
        t.record_haiku_turn("enc-a")
    # 5th turn still ok (under the 5-turn cap).
    d = t.check_haiku_turn("enc-a")
    assert d.allow is True
    assert d.remaining == 1


def test_haiku_rate_cap_refuses_at_cap() -> None:
    t = RoomBudgetTracker(haiku_rate_cap=3)
    for _ in range(3):
        d = t.check_haiku_turn("enc-a")
        assert d.allow is True
        t.record_haiku_turn("enc-a")
    # 4th turn refused.
    d = t.check_haiku_turn("enc-a")
    assert d.allow is False
    assert d.fallback == "refuse"
    assert "rate cap" in d.reason.lower()


def test_haiku_rate_cap_resets_after_window_passes() -> None:
    """The sliding-60s window prunes events; older turns no longer
    count once they fall outside the window."""
    t = RoomBudgetTracker(haiku_rate_cap=2)
    # Record 2 turns at t=0, fill the cap.
    t.record_haiku_turn("enc-a", now=1000.0)
    t.record_haiku_turn("enc-a", now=1001.0)
    # Right after — at the cap.
    assert t.check_haiku_turn("enc-a", now=1002.0).allow is False
    # 65 seconds later — both prior turns aged out.
    assert t.check_haiku_turn("enc-a", now=1066.0).allow is True


def test_haiku_rate_cap_per_encounter_override() -> None:
    """per_encounter_haiku_rate_cap restricts each encounter; the
    room-wide cap stacks on top."""
    t = RoomBudgetTracker(haiku_rate_cap=10,
                           per_encounter_haiku_rate_cap=2)
    # Encounter A maxes out at 2 turns.
    t.record_haiku_turn("enc-a")
    t.record_haiku_turn("enc-a")
    assert t.check_haiku_turn("enc-a").allow is False
    # Encounter B has its own 2-turn budget.
    assert t.check_haiku_turn("enc-b").allow is True


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


def test_room_budget_route_round_trip(client) -> None:
    """/api/room/budget GET + POST round-trip — set caps, read them
    back, verify the tracker picks them up."""
    r = client.post("/api/room/start", json={
        "label": "Budget test",
        "encounters": [{"scenario_name": "Bed", "persona_id": "P-001",
                         "patient_persona_id": "P-001", "ehr_id": "helix"}],
    })
    assert r.status_code == 200

    # Initial usage: caps are None (no /api/room/start opts set).
    r = client.get("/api/room/budget")
    assert r.status_code == 200
    body = r.json()
    assert body["haiku_rate_cap"] is None
    assert body["voice_char_cap"] is None

    # Set both caps.
    r = client.post("/api/room/budget",
                     json={"haiku_rate_cap": 30, "voice_char_cap": 5000})
    assert r.status_code == 200
    body = r.json()
    assert body["haiku_rate_cap"] == 30
    assert body["voice_char_cap"] == 5000

    # Clear the voice cap (pass null).
    r = client.post("/api/room/budget", json={"voice_char_cap": None})
    assert r.status_code == 200
    body = r.json()
    assert body["voice_char_cap"] is None
    # haiku cap untouched.
    assert body["haiku_rate_cap"] == 30
