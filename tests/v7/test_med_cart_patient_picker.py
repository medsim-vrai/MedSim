"""M60 — Med cart patient picker (data path).

The cart's bootstrap must deliver one entry per linked patient — that
data contract still holds and is exercised here.

NOTE: the cart's device-side picker UI was REPLACED by the med-cart v2
shared-terminal flow (#76: sign-in → scoped patient picker → center-anchored
MAR). The old M60 DOM ids (`cabinet-pick-patient`, `cabinet-checklist-back`,
"← Patients", the `cabinet-checklist-open` floating button, the
`ASSIGNED_CHAR_ID` default) no longer exist, so those source-grep tests were
removed. The new behaviour (sign-in, open vs restrict scoping, server-side
enforcement) is covered behaviourally in tests/v8/test_med_cart_roster.py.
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
        debrief as debrief_mod, server as server_mod,
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
    monkeypatch.setattr(server_mod, "_anthropic_runtime_key", "")
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


def _start_room(client, n: int = 2):
    pool = ["P-014", "P-003", "P-001"]
    r = client.post("/api/room/start", json={
        "label": "M60",
        "encounters": [
            {"scenario_name": f"Bed {i+1}", "persona_id": pool[i],
             "patient_persona_id": pool[i],
             "personas": [pool[i]], "ehr_id": "helix"}
            for i in range(n)
        ],
    })
    assert r.status_code == 200, r.text
    return r.json()


# ── Data path — cart bootstrap delivers all linked patients ────────

def test_cart_bootstrap_delivers_every_linked_patient(client) -> None:
    """The cart's `characters[]` payload (consumed by the device JS
    as the patient picker's data) must contain one entry per linked
    encounter's patient — same shape the M58 patient-only filter
    guarantees."""
    body = _start_room(client, n=2)
    eids = [e["encounter_id"] for e in body["encounters"]]
    r = client.post("/api/room/med_cart/register",
                     json={"label": "M60 cart",
                           "encounter_ids": eids})
    cart_sid = r.json()["station_id"]
    boot = client.get(f"/api/device/{cart_sid}/bootstrap").json()
    chars = boot.get("characters") or []
    assert len(chars) == 2
    for c in chars:
        assert c.get("character_id")
        assert c.get("name")
        assert "medications" in c
        # M59 bugfix #2 tags every character with its source encounter.
        assert c.get("encounter_id") in eids
        assert c.get("encounter_label")


# ── Device JS still exposes the per-patient MAR render ─────────────

def test_device_js_has_mar_render_extracted() -> None:
    """The cart device JS renders a per-patient MAR via _renderCabinetMar
    (shared by the v2 sign-in/picker flow)."""
    src = (Path(__file__).resolve().parents[2]
           / "portal" / "static" / "devices" / "device_app.js"
          ).read_text("utf-8")
    assert "_renderCabinetMar" in src
    # The v2 selected-patient state the picker drives.
    assert "SELECTED_CHAR_ID" in src
