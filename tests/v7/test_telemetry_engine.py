"""Phase 7 M23 — telemetry simulation tests.

Three acceptance bars:
  1. snapshot uses the latest vitals.record event when one exists.
  2. injecting a vitals.drop scene shifts the snapshot.
  3. overrides take precedence over derived values.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from portal import control_room, ehr_db, telemetry as telemetry_mod
from portal.control_session import ControlSession


def _isolated_db(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(tmp_path / "telem.db"), isolation_level=None)
    ehr_db._run_migrations(conn)
    return conn


@pytest.fixture(autouse=True)
def _reset():
    control_room._reset_for_tests()
    yield
    control_room._reset_for_tests()


def test_telemetry_snapshot_uses_latest_vitals(tmp_path: Path) -> None:
    conn = _isolated_db(tmp_path)
    try:
        with patch.object(ehr_db, "_conn", return_value=conn):
            room = control_room.create_room()
            enc = room.add_encounter(ControlSession(
                id="ENC-T", join_code="JCT0001",
                scenario_name="Telem", api_key=""))
            ehr_db.register_session(enc.id, enc.join_code, "helix",
                                      "P-001", {"patient": "test"})
            ehr_db.register_station(enc.id, "ES-A")
            ehr_db.append_event(enc.id, "ES-A",
                                  type="vitals.record", surface="vitals",
                                  payload={"hr": 110, "sbp": 92, "dbp": 60,
                                            "spo2": 94, "rr": 22, "temp_f": 99.4})
            snap = telemetry_mod.snapshot(enc.id, jitter=False)
            assert snap["hr"]   == 110
            assert snap["sbp"]  == 92
            assert snap["spo2"] == 94
            assert snap["temp_f"] == 99.4
            # `from` map says every metric is sourced from vitals.record.
            assert snap["from"]["hr"]      == "vitals.record"
            assert snap["from"]["sbp"]     == "vitals.record"
            # No override → empty list.
            assert snap["overrides_active"] == []
    finally:
        conn.close()


def test_telemetry_falls_back_to_defaults_when_no_vitals(tmp_path: Path) -> None:
    conn = _isolated_db(tmp_path)
    try:
        with patch.object(ehr_db, "_conn", return_value=conn):
            room = control_room.create_room()
            enc = room.add_encounter(ControlSession(
                id="ENC-D", join_code="JCD0001",
                scenario_name="Defaults", api_key=""))
            ehr_db.register_session(enc.id, enc.join_code, "helix",
                                      "P-001", {"patient": "test"})
            snap = telemetry_mod.snapshot(enc.id, jitter=False)
            # Module defaults — 80 / 118 / 74 / 98 / 16 / 98.6
            assert snap["hr"] == 80
            assert snap["sbp"] == 118
            assert snap["spo2"] == 98
            assert snap["temp_f"] == 98.6
            assert snap["from"]["hr"] == "default"
    finally:
        conn.close()


def test_telemetry_scene_injection_changes_snapshot(tmp_path: Path) -> None:
    """A scene that writes a new vitals.record updates the snapshot
    on the next read."""
    from portal import scenes
    conn = _isolated_db(tmp_path)
    try:
        with patch.object(ehr_db, "_conn", return_value=conn):
            room = control_room.create_room()
            enc = room.add_encounter(ControlSession(
                id="ENC-S", join_code="JCS0001",
                scenario_name="Scene", api_key=""))
            ehr_db.register_session(enc.id, enc.join_code, "helix",
                                      "P-001", {"patient": "test"})

            # Baseline.
            snap1 = telemetry_mod.snapshot(enc.id, jitter=False)
            assert snap1["sbp"] == 118  # default

            # Fire vitals.drop scene.
            scenes.apply(enc, {"kind": "vitals.drop"}, by="instructor")
            snap2 = telemetry_mod.snapshot(enc.id, jitter=False)
            # vitals.drop preset SBP is 78.
            assert snap2["sbp"] == 78
            assert snap2["from"]["sbp"] == "vitals.record"
    finally:
        conn.close()


def test_telemetry_overrides_take_precedence(tmp_path: Path) -> None:
    """An operator override beats the latest vitals.record. Overrides
    live in-memory on the active room's Encounter (M23 fix — they
    don't need to survive restart since the room itself doesn't)."""
    conn = _isolated_db(tmp_path)
    try:
        with patch.object(ehr_db, "_conn", return_value=conn):
            room = control_room.create_room()
            enc = room.add_encounter(ControlSession(
                id="ENC-O", join_code="JCO0001",
                scenario_name="Override", api_key=""))
            ehr_db.register_session(enc.id, enc.join_code, "helix",
                                      "P-001", {"patient": "test"})
            ehr_db.register_station(enc.id, "ES-A")
            ehr_db.append_event(enc.id, "ES-A",
                                  type="vitals.record", surface="vitals",
                                  payload={"sbp": 120, "hr": 80})

            # Override SBP. HR should still come from chart.
            telemetry_mod.set_override(enc.id, "sbp", 65)
            assert enc.telemetry_overrides == {"sbp": 65}
            snap = telemetry_mod.snapshot(enc.id, jitter=False)
            assert snap["sbp"] == 65          # overridden
            assert snap["hr"]  == 80          # derived
            assert snap["overrides_active"] == ["sbp"]
            assert snap["from"]["sbp"] == "override"
            assert snap["from"]["hr"]  == "vitals.record"

            # Clear override — back to derived.
            telemetry_mod.clear_override(enc.id, "sbp")
            assert enc.telemetry_overrides == {}
            snap2 = telemetry_mod.snapshot(enc.id, jitter=False)
            assert snap2["sbp"] == 120
            assert snap2["overrides_active"] == []
    finally:
        conn.close()


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    from portal import (
        auth, credentials, voices as _voices,
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


TEST_PASSWORD = "test_passwd_xyz_8chars"


def test_telemetry_routes_round_trip(client) -> None:
    r = client.post("/api/room/start", json={
        "label": "Telem route test",
        "encounters": [{"scenario_name": "Bed", "persona_id": "P-001",
                         "patient_persona_id": "P-001", "ehr_id": "helix"}],
    })
    assert r.status_code == 200
    eid = r.json()["encounters"][0]["encounter_id"]

    # GET snapshot — defaults at first.
    r = client.get(f"/api/encounter/{eid}/telemetry?jitter=false")
    assert r.status_code == 200
    body = r.json()
    assert body["hr"] == 80
    assert body["overrides_active"] == []

    # POST override.
    r = client.post(f"/api/encounter/{eid}/telemetry/override",
                     json={"hr": 132, "sbp": 70})
    assert r.status_code == 200
    overrides = r.json()["overrides"]
    assert overrides["hr"]  == 132
    assert overrides["sbp"] == 70

    # GET snapshot — sees overrides.
    body = client.get(f"/api/encounter/{eid}/telemetry?jitter=false").json()
    assert body["hr"] == 132
    assert body["sbp"] == 70
    assert set(body["overrides_active"]) == {"hr", "sbp"}

    # POST clear — one metric.
    r = client.post(f"/api/encounter/{eid}/telemetry/override",
                     json={"clear": "hr"})
    assert r.status_code == 200
    assert "hr" not in r.json()["overrides"]

    # POST clear_all.
    r = client.post(f"/api/encounter/{eid}/telemetry/override",
                     json={"clear_all": True})
    assert r.status_code == 200
    assert r.json()["overrides"] == {}
