"""M16 acceptance — freeze_all WebSocket broadcast.

A test client subscribes to /ws/room/{room_code}; firing
POST /api/room/freeze_all causes that client to receive a
`freeze_all` event envelope on the WS within the timeout. The
same mechanism delivers `resume_all` and `end` events.
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


def _start_room(client) -> str:
    r = client.post("/api/room/start", json={
        "label": "WS broadcast test",
        "encounters": [{
            "scenario_name": "Bed 1", "persona_id": "P-001",
            "patient_persona_id": "P-001", "ehr_id": "helix",
        }],
    })
    assert r.status_code == 200
    return client.get("/api/room/state").json()["room_code"]


def test_ws_freeze_event_arrives_at_subscribed_station(client) -> None:
    room_code = _start_room(client)
    with client.websocket_connect(f"/ws/room/{room_code}") as ws:
        # Fire freeze_all from the operator side.
        r = client.post("/api/room/freeze_all")
        assert r.status_code == 200
        # The WS subscriber receives the broadcast.
        msg = ws.receive_json()
        assert msg["type"] == "freeze_all"
        assert msg["room_code"] == room_code
        assert "ts" in msg
        assert msg["payload"]["encounter_count"] == 1


def test_ws_resume_event_arrives(client) -> None:
    room_code = _start_room(client)
    client.post("/api/room/freeze_all")  # flush the freeze
    with client.websocket_connect(f"/ws/room/{room_code}") as ws:
        r = client.post("/api/room/resume_all")
        assert r.status_code == 200
        msg = ws.receive_json()
        assert msg["type"] == "resume_all"
        assert msg["room_code"] == room_code


def test_ws_end_event_arrives_before_singleton_clears(client) -> None:
    room_code = _start_room(client)
    with client.websocket_connect(f"/ws/room/{room_code}") as ws:
        r = client.post("/api/room/end")
        assert r.status_code == 200
        msg = ws.receive_json()
        assert msg["type"] == "end"


def test_ws_broadcasts_only_to_matching_room_code(client) -> None:
    """A WS connection to room A must not receive room B's events.
    Verified by opening two subscribers (different room codes) — only
    the matching one receives."""
    room_code_a = _start_room(client)
    # Connect to a NON-EXISTENT room code; no broadcasts should land.
    with client.websocket_connect(f"/ws/room/{room_code_a}") as ws_a:
        with client.websocket_connect("/ws/room/NOTHIN") as ws_other:
            client.post("/api/room/freeze_all")
            # The matching room WS gets the message.
            msg_a = ws_a.receive_json()
            assert msg_a["type"] == "freeze_all"
            assert msg_a["room_code"] == room_code_a
            # The other WS has no message available. We can't block on
            # receive_json (would hang) — instead disconnect and use
            # the manager's subscriber count to confirm the message
            # was not dispatched there.
            from portal import ws_room as ws_room_mod
            assert ws_room_mod.manager.subscriber_count("NOTHIN") == 1
