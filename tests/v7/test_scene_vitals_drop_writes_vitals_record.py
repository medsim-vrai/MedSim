"""M7 acceptance — the vitals.drop scene emits a vitals.record event.

The chart_event log after one vitals.drop fire must contain exactly
one ``vitals.record`` row scoped to the target encounter, carrying
the hypotension preset (or any operator-overridden params), tagged
with ``source: 'scene'`` so the M14 cohort debrief can distinguish
scene-driven from student-driven activity.

Also exercises the route layer: /api/encounter/{id}/scene must
dispatch to scenes.apply on the encounter and persist the row.
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


def _start_room(client, n: int = 2):
    entries = [
        {"scenario_name": f"Bed {i + 1}", "persona_id": f"P-{i + 1:03d}",
         "ehr_id": "helix"} for i in range(n)
    ]
    r = client.post("/api/room/start",
                     json={"label": "vitals-drop test", "encounters": entries})
    assert r.status_code == 200, r.text
    return r.json()


def test_scene_vitals_drop_writes_vitals_record(client) -> None:
    from portal import ehr_db

    body = _start_room(client, n=2)
    eid_a = body["encounters"][0]["encounter_id"]
    eid_b = body["encounters"][1]["encounter_id"]

    # Direct injection on encounter A.
    r = client.post(f"/api/encounter/{eid_a}/scene", json={
        "scene": {"kind": "vitals.drop"},
    })
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["ok"] is True
    assert result["kind"] == "vitals.drop"
    assert result["category"] == "chart"
    assert len(result["event_ids"]) == 1

    # The chart_event log for A has exactly one vitals.record row.
    events_a = ehr_db.events(eid_a)
    events_b = ehr_db.events(eid_b)
    assert len(events_a) == 1
    assert len(events_b) == 0  # encounter isolation holds

    ev = events_a[0]
    assert ev["type"] == "vitals.record"
    assert ev["surface"] == "vitals"
    payload = ev["payload"]
    # Default hypotensive preset values present.
    assert payload["source"] == "scene"
    assert payload["scene_kind"] == "vitals.drop"
    assert payload["sbp"] == 78
    assert payload["spo2"] == 88
    assert payload["hr"] == 132


def test_scene_vitals_drop_param_override_carries_through(client) -> None:
    from portal import ehr_db
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]

    r = client.post(f"/api/encounter/{eid}/scene", json={
        "scene": {"kind": "vitals.drop",
                  "params": {"sbp": 68, "hr": 148, "spo2": 82}},
    })
    assert r.status_code == 200, r.text
    events = ehr_db.events(eid)
    assert len(events) == 1
    payload = events[0]["payload"]
    # Overrides applied; defaults preserved for the keys we didn't override.
    assert payload["sbp"] == 68
    assert payload["hr"] == 148
    assert payload["spo2"] == 82
    assert payload["dbp"] == 44  # default preserved


def test_scene_vitals_rise_emits_distinct_preset(client) -> None:
    """Quick sanity check on the sister scene — vitals.rise (sympathetic
    surge) hits the same code path with the opposite default preset."""
    from portal import ehr_db
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]

    r = client.post(f"/api/encounter/{eid}/scene", json={
        "scene": {"kind": "vitals.rise"},
    })
    assert r.status_code == 200, r.text
    ev = ehr_db.events(eid)[0]
    assert ev["type"] == "vitals.record"
    assert ev["payload"]["scene_kind"] == "vitals.rise"
    assert ev["payload"]["sbp"] >= 180  # hypertension
    assert ev["payload"]["hr"] >= 130   # tachy
