"""M16 acceptance — scene injection broadcasts to subscribers fast.

A WS subscriber sees the scene event within 500 ms of the POST
finishing (in practice it's < 10 ms in the TestClient — the 500 ms
bar in the spec is the production target, not a tight test bound).
The payload carries the encounter_id, the scene dict, and the
ehr_db append result so the subscriber can update its in-memory
chart copy without a full re-fetch.
"""
from __future__ import annotations

import time
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


def test_ws_scene_event_appears_within_500ms_for_single_encounter(client) -> None:
    r = client.post("/api/room/start", json={
        "label": "WS scene test",
        "encounters": [{
            "scenario_name": "Bed 1", "persona_id": "P-001",
            "patient_persona_id": "P-001", "ehr_id": "helix",
        }],
    })
    assert r.status_code == 200
    state = client.get("/api/room/state").json()
    room_code = state["room_code"]
    eid = state["encounters"][0]["encounter_id"]

    with client.websocket_connect(f"/ws/room/{room_code}") as ws:
        t0 = time.monotonic()
        r = client.post(f"/api/encounter/{eid}/scene", json={
            "scene": {"kind": "vitals.drop", "params": {"sbp": 70}},
        })
        assert r.status_code == 200
        msg = ws.receive_json()
        elapsed_ms = (time.monotonic() - t0) * 1000

    assert msg["type"] == "scene"
    assert msg["encounter_id"] == eid
    assert msg["payload"]["scene"]["kind"] == "vitals.drop"
    # The append result carries the chart event id and category.
    assert msg["payload"]["result"]["category"] == "chart"
    # Latency bar — generous; spec is 500 ms production target.
    assert elapsed_ms < 500


def test_ws_scene_broadcast_pushes_one_event_per_target(client) -> None:
    """A room scene_broadcast to all encounters emits one WS event
    per targeted encounter (so each station knows it was hit)."""
    r = client.post("/api/room/start", json={
        "label": "Multi WS scene",
        "encounters": [
            {"scenario_name": f"Bed {i+1}", "persona_id": f"P-{i+1:03d}",
             "patient_persona_id": f"P-{i+1:03d}", "ehr_id": "helix"}
            for i in range(3)
        ],
    })
    assert r.status_code == 200
    state = client.get("/api/room/state").json()
    room_code = state["room_code"]
    eids = [e["encounter_id"] for e in state["encounters"]]

    with client.websocket_connect(f"/ws/room/{room_code}") as ws:
        r = client.post("/api/room/scene_broadcast", json={
            "scene": {"kind": "vitals.rise"},
            "targets": "all",
        })
        assert r.status_code == 200
        # Receive 3 scene events (one per encounter).
        seen_eids = set()
        for _ in range(3):
            msg = ws.receive_json()
            assert msg["type"] == "scene"
            assert msg["payload"]["scene"]["kind"] == "vitals.rise"
            seen_eids.add(msg["encounter_id"])
        assert seen_eids == set(eids)


def test_ws_disconnect_cleans_up_subscriber_state(client) -> None:
    """Closing the WS removes the subscriber from the manager so
    next broadcast doesn't try (and fail silently) to send to it."""
    from portal import ws_room as ws_room_mod

    r = client.post("/api/room/start", json={
        "label": "cleanup test",
        "encounters": [{"scenario_name": "Bed", "persona_id": "P-001",
                         "patient_persona_id": "P-001", "ehr_id": "helix"}],
    })
    room_code = client.get("/api/room/state").json()["room_code"]
    assert ws_room_mod.manager.subscriber_count(room_code) == 0
    with client.websocket_connect(f"/ws/room/{room_code}"):
        assert ws_room_mod.manager.subscriber_count(room_code) == 1
    # After the context manager exits, the subscription is dropped.
    # Give the event loop one tick to fire the disconnect handler.
    import time as _time
    _time.sleep(0.05)
    assert ws_room_mod.manager.subscriber_count(room_code) == 0
