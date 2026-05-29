"""M60 — Med cart patient picker.

Operator: "For the med cart patient pull up tab, should list all the
patient characters in the sim, then select from that to pull up the
med list in the cart for the patient character."

Pre-M60 the cart's MAR panel only ever rendered for the SINGLE
instructor-assigned patient (`ASSIGNED_CHAR_ID`, set via WS assign
event). Without an assignment the panel stayed empty even when the
cart was linked to multiple patients. M60 introduces a local
`SELECTED_CHAR_ID` state and a patient picker step:

  - Open 👤 PATIENT LIST → picker showing every linked patient.
  - Tap a patient → drill into THAT patient's MAR.
  - ← Patients button → back to the picker.

Tests cover (a) the bootstrap data path delivers all linked patients
to the cart (M47+M59-bugfix#2 invariants still hold), and (b) the
device JS source carries the new code paths.
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


# ── 1. Data path — cart bootstrap delivers all linked patients ─────

def test_cart_bootstrap_delivers_every_linked_patient(client) -> None:
    """The cart's `characters[]` payload (consumed by the device JS
    as the patient picker's data) must contain one entry per linked
    encounter's patient — same shape that the M58 patient-only
    filter guarantees."""
    body = _start_room(client, n=2)
    eids = [e["encounter_id"] for e in body["encounters"]]
    r = client.post("/api/room/med_cart/register",
                     json={"label": "M60 cart",
                           "encounter_ids": eids})
    cart_sid = r.json()["station_id"]
    boot = client.get(f"/api/device/{cart_sid}/bootstrap").json()
    chars = boot.get("characters") or []
    assert len(chars) == 2
    # Each entry carries the fields the picker render uses.
    for c in chars:
        assert c.get("character_id")
        assert c.get("name")
        assert "medications" in c
        # M59 bugfix #2 tags every character with its source
        # encounter id + label.
        assert c.get("encounter_id") in eids
        assert c.get("encounter_label")


# ── 2. Device JS source has the picker code path ───────────────────

def test_device_js_has_selected_char_id_local_state() -> None:
    """Pre-M60 only ASSIGNED_CHAR_ID existed. M60 adds a separate
    SELECTED_CHAR_ID for local picker state so the cart can override
    the instructor's assignment."""
    src = (Path(__file__).resolve().parents[2]
           / "portal" / "static" / "devices" / "device_app.js"
          ).read_text("utf-8")
    assert "SELECTED_CHAR_ID" in src
    # Both states must still be in play — assigned is the default,
    # selected overrides locally.
    assert "ASSIGNED_CHAR_ID" in src


def test_device_js_has_patient_picker_render() -> None:
    """Picker render function + per-patient button class so the JS
    can identify tap targets."""
    src = (Path(__file__).resolve().parents[2]
           / "portal" / "static" / "devices" / "device_app.js"
          ).read_text("utf-8")
    assert "_renderCabinetPicker" in src
    assert "cabinet-pick-patient" in src
    # Pick a patient title text.
    assert "Pick a patient" in src


def test_device_js_has_mar_render_extracted() -> None:
    """Pre-M60 the MAR render was inline inside renderCabinetChecklist;
    M60 extracts it so the picker can share the panel chrome."""
    src = (Path(__file__).resolve().parents[2]
           / "portal" / "static" / "devices" / "device_app.js"
          ).read_text("utf-8")
    assert "_renderCabinetMar" in src


def test_device_js_has_back_to_picker_button() -> None:
    """← Patients button in the MAR header drops back to the picker
    by clearing SELECTED_CHAR_ID."""
    src = (Path(__file__).resolve().parents[2]
           / "portal" / "static" / "devices" / "device_app.js"
          ).read_text("utf-8")
    assert "cabinet-checklist-back" in src
    assert "← Patients" in src
    # The handler clears the local selection.
    idx = src.find("backBtnEl.addEventListener")
    assert idx > 0
    handler = src[idx:idx + 200]
    assert "SELECTED_CHAR_ID = null" in handler


def test_device_js_floating_button_opens_picker(_=None) -> None:
    """The bottom-left 👤 PATIENT LIST button resets
    SELECTED_CHAR_ID so opening lands on the picker, not on the
    last-viewed MAR."""
    src = (Path(__file__).resolve().parents[2]
           / "portal" / "static" / "devices" / "device_app.js"
          ).read_text("utf-8")
    idx = src.find("cabinet-checklist-open")
    assert idx > 0
    # The click handler near this id should clear SELECTED_CHAR_ID.
    window = src[idx:idx + 1200]
    assert "SELECTED_CHAR_ID = null" in window
    assert "PATIENT LIST" in window


def test_device_js_picker_falls_back_to_assigned() -> None:
    """When the instructor pushes an assign event (ASSIGNED_CHAR_ID
    becomes truthy), the cart should drill straight into THAT
    patient's MAR — keeping the pre-M60 behaviour for the assign-
    driven workflow. Achieved by defaulting SELECTED_CHAR_ID to
    ASSIGNED_CHAR_ID on first render."""
    src = (Path(__file__).resolve().parents[2]
           / "portal" / "static" / "devices" / "device_app.js"
          ).read_text("utf-8")
    fn_idx = src.find("function renderCabinetChecklist")
    assert fn_idx > 0
    body = src[fn_idx:fn_idx + 1500]
    # Defaulting branch — set selected = assigned if null AND
    # assigned is set.
    assert "SELECTED_CHAR_ID == null && ASSIGNED_CHAR_ID" in body
    assert "SELECTED_CHAR_ID = ASSIGNED_CHAR_ID" in body


def test_device_js_picker_hidden_when_no_patients(_=None) -> None:
    """An unlinked cart (no characters) shows nothing — picker stays
    hidden."""
    src = (Path(__file__).resolve().parents[2]
           / "portal" / "static" / "devices" / "device_app.js"
          ).read_text("utf-8")
    fn_idx = src.find("function renderCabinetChecklist")
    assert fn_idx > 0
    body = src[fn_idx:fn_idx + 1500]
    assert "haveAnyChars" in body
    # Hide the panel + the open button when no patients.
    assert "existing.remove" in body


def test_device_js_back_button_only_shows_for_multi_patient() -> None:
    """A single-patient cart doesn't need a "← Patients" back button
    (there's nothing to go back to). M60 hides it when CHARACTERS
    has only one entry."""
    src = (Path(__file__).resolve().parents[2]
           / "portal" / "static" / "devices" / "device_app.js"
          ).read_text("utf-8")
    fn_idx = src.find("function _renderCabinetMar")
    assert fn_idx > 0
    body = src[fn_idx:fn_idx + 2000]
    assert "CHARACTERS.length > 1" in body
    # Guards the back-btn HTML render.
    assert "showBackBtn" in body or "cabinet-checklist-back" in body
