"""Phase 7 M25 — Per-Patient Console rich features smoke.

The rich console UI is wired by `portal/static/encounter_console.js`
which fetches:
  - /api/ecg/catalog (M24)
  - /api/encounter/{id}/ecg (M24)
  - /api/encounter/{id}/telemetry (M23)
  - /api/room/state (M4 + M19 capacity block)
  - POST /api/encounter/{id}/scene (M7)

Acceptance is mostly visual; this test asserts the wire-up is in
place — the template references ecg_strip.js, and the underlying
poll sequence works end-to-end.
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


def test_encounter_console_template_includes_ecg_strip_renderer(client) -> None:
    r = client.post("/api/room/start", json={
        "label": "M25 smoke",
        "encounters": [{"scenario_name": "Bed", "persona_id": "P-001",
                         "patient_persona_id": "P-001", "ehr_id": "helix"}],
    })
    eid = r.json()["encounters"][0]["encounter_id"]
    r = client.get(f"/portal/room/encounter/{eid}")
    assert r.status_code == 200
    html = r.text
    assert "ecg_strip.js" in html
    assert "encounter_console.js" in html
    # The rich UI's anchor ids are present.
    for anchor in ("ecg-waveform-picker", "ecg-canvas", "t-hr",
                    "t-bp", "override-grid"):
        assert anchor in html


def test_encounter_console_telemetry_route_round_trip(client) -> None:
    """End-to-end the console JS would walk: start room → fetch ECG
    catalog → fetch ECG state → fetch telemetry → set override →
    re-fetch telemetry — all via the v7 routes."""
    r = client.post("/api/room/start", json={
        "label": "M25 e2e",
        "encounters": [{"scenario_name": "Bed", "persona_id": "P-001",
                         "patient_persona_id": "P-001", "ehr_id": "helix"}],
    })
    eid = r.json()["encounters"][0]["encounter_id"]

    # Step 1 — ECG catalog (11 entries).
    assert len(client.get("/api/ecg/catalog").json()["catalog"]) == 11

    # Step 2 — initial ECG state for this encounter.
    body = client.get(f"/api/encounter/{eid}/ecg").json()
    assert body["rhythm_id"] == "nsr"
    assert body["enabled"] is False

    # Step 3 — telemetry snapshot (defaults).
    body = client.get(f"/api/encounter/{eid}/telemetry?jitter=false").json()
    assert body["hr"] == 80

    # Step 4 — operator sets afib + enables.
    r = client.post(f"/api/encounter/{eid}/ecg",
                     json={"rhythm_id": "afib", "enabled": True})
    assert r.status_code == 200

    # Step 5 — override HR.
    r = client.post(f"/api/encounter/{eid}/telemetry/override",
                     json={"hr": 132})
    assert r.status_code == 200

    # Step 6 — confirm both stuck.
    body = client.get(f"/api/encounter/{eid}/ecg").json()
    assert body["rhythm_id"] == "afib"
    assert body["enabled"] is True
    body = client.get(f"/api/encounter/{eid}/telemetry?jitter=false").json()
    assert body["hr"] == 132
    assert "hr" in body["overrides_active"]
