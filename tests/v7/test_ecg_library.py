"""Phase 7 M24 — ECG waveform library tests.

Two acceptance bars from the spec:
  1. The catalog lists 11 built-in waveforms with the expected ids.
  2. Per-encounter ECG selection persists (in-memory on the Encounter).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from portal import control_room, ecg as ecg_mod
from portal.control_session import ControlSession


@pytest.fixture(autouse=True)
def _reset():
    control_room._reset_for_tests()
    yield
    control_room._reset_for_tests()


TEST_PASSWORD = "test_passwd_xyz_8chars"


def test_catalog_lists_eleven_built_in_waveforms() -> None:
    cat = ecg_mod.catalog()
    assert len(cat) == 11
    ids = {e["id"] for e in cat}
    assert ids == {
        "nsr", "sinus_tachy", "sinus_brady", "afib", "aflutter",
        "vtach_mono", "vtach_poly", "vfib", "asystole", "pea", "paced",
    }
    # Every entry has the required fields the client renderer reads.
    for entry in cat:
        for key in ("id", "label", "default_rate", "rate_range",
                     "regular", "noise", "complex", "class"):
            assert key in entry
        # complex points are sortable + within [0,1] for t.
        ts = [pt[0] for pt in entry["complex"]]
        assert ts == sorted(ts)
        assert ts[0] == 0.0
        assert ts[-1] == 1.0


def test_get_returns_one_or_none() -> None:
    assert ecg_mod.get("nsr")["label"].startswith("Normal")
    assert ecg_mod.get("does_not_exist") is None


def test_is_valid_id_helper() -> None:
    assert ecg_mod.is_valid_id("vfib") is True
    assert ecg_mod.is_valid_id("not_a_rhythm") is False


def test_encounter_ecg_defaults() -> None:
    enc = ControlSession(id="e", join_code="J", scenario_name="x", api_key="")
    assert enc.ecg_rhythm_id == "nsr"
    assert enc.ecg_enabled is False


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


def test_ecg_catalog_route_returns_eleven(client) -> None:
    r = client.get("/api/ecg/catalog")
    assert r.status_code == 200
    body = r.json()
    assert len(body["catalog"]) == 11


def test_ecg_set_per_encounter_persists(client) -> None:
    r = client.post("/api/room/start", json={
        "label": "ECG persist test",
        "encounters": [{"scenario_name": "Bed", "persona_id": "P-001",
                         "patient_persona_id": "P-001", "ehr_id": "helix"}],
    })
    assert r.status_code == 200
    eid = r.json()["encounters"][0]["encounter_id"]

    # GET — default is nsr, disabled.
    r = client.get(f"/api/encounter/{eid}/ecg")
    body = r.json()
    assert body["rhythm_id"] == "nsr"
    assert body["enabled"] is False

    # POST — switch to afib + enable.
    r = client.post(f"/api/encounter/{eid}/ecg",
                     json={"rhythm_id": "afib", "enabled": True})
    assert r.status_code == 200
    body = r.json()
    assert body["rhythm_id"] == "afib"
    assert body["enabled"] is True
    assert body["rhythm"]["label"].startswith("Atrial fibrillation")

    # GET — confirm persistence.
    body = client.get(f"/api/encounter/{eid}/ecg").json()
    assert body["rhythm_id"] == "afib"
    assert body["enabled"] is True


def test_ecg_set_rejects_unknown_rhythm(client) -> None:
    r = client.post("/api/room/start", json={
        "label": "ECG unknown",
        "encounters": [{"scenario_name": "Bed", "persona_id": "P-001",
                         "patient_persona_id": "P-001", "ehr_id": "helix"}],
    })
    eid = r.json()["encounters"][0]["encounter_id"]
    r = client.post(f"/api/encounter/{eid}/ecg",
                     json={"rhythm_id": "definitely_not_a_rhythm"})
    assert r.status_code == 400


def test_ecg_observer_cannot_set(client, monkeypatch) -> None:
    """Observer seat cannot mutate ECG (M18 + M24)."""
    from portal import auth, credentials
    r = client.post("/api/room/start", json={
        "label": "Observer ECG",
        "encounters": [{"scenario_name": "Bed", "persona_id": "P-001",
                         "patient_persona_id": "P-001", "ehr_id": "helix"}],
    })
    eid = r.json()["encounters"][0]["encounter_id"]
    # Re-cookie as observer.
    vault = credentials.unlock(TEST_PASSWORD)
    client.cookies.set(auth.COOKIE_NAME,
                        auth.issue_session_token(vault, role="observer"))
    r = client.post(f"/api/encounter/{eid}/ecg",
                     json={"rhythm_id": "vfib"})
    assert r.status_code == 403
