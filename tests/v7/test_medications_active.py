"""M55 — Medications card on the Per-Patient Console + active-at-
start toggle + med-cart filter.

Operator: "Medication section needs to be added to the encounters.
Click on the header to have it open up of the assigned medications
for the scenario and allow the instructor to click on the medication
to be present or in use at the start of the scenario. These
medication will show up in the med cart under the name of the
patient character in the encounter."

Delivered:
  1. `Encounter.active_medications: dict[persona_id, list[str]]`
     default empty.
  2. GET /api/encounter/{eid}/medications — returns every persona's
     seed-derived MAR plus an `active` flag per med + an
     `explicit_active_list` flag per persona (default-all vs.
     operator-set subset).
  3. POST /api/encounter/{eid}/medications/active — replace ONE
     persona's active-list. Body `{persona_id, active_med_names}`.
  4. DELETE /api/encounter/{eid}/medications/active/{persona_id}
     — reset to default (every med back on the cart).
  5. M47 cart bootstrap filters per persona — if explicit list is
     set, the cart only sees the listed meds; otherwise, every med
     (back-compat).
  6. Encounter console template renders a collapsible 💊
     Medications card.
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


def _start_room(client, personas: list[str] | None = None):
    personas = personas or ["P-014"]
    r = client.post("/api/room/start", json={
        "label": "M55",
        "encounters": [{
            "scenario_name": "Bed 1",
            "persona_id": personas[0],
            "patient_persona_id": personas[0],
            "personas": personas,
            "ehr_id": "helix",
        }],
    })
    assert r.status_code == 200, r.text
    return r.json()


# ── 1. Dataclass field default ─────────────────────────────────────

def test_encounter_active_medications_defaults_empty_dict() -> None:
    from portal.control_session import ControlSession
    enc = ControlSession(
        id="enc_x", join_code="ABC123",
        scenario_name="Test", api_key="",
    )
    assert hasattr(enc, "active_medications")
    assert enc.active_medications == {}


# ── 2. GET medications surfaces per-persona MAR ────────────────────

def test_get_medications_returns_personas_and_meds(client) -> None:
    body = _start_room(client)
    eid = body["encounters"][0]["encounter_id"]
    r = client.get(f"/api/encounter/{eid}/medications")
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["encounter_id"] == eid
    personas = payload["personas"]
    assert personas, "expected at least one persona"
    p = personas[0]
    assert "character_id" in p
    assert "name" in p
    assert "explicit_active_list" in p
    # Default state: no operator interaction → all meds active.
    assert p["explicit_active_list"] is False
    for m in p["medications"]:
        assert m["active"] is True
        assert "name" in m


def test_get_medications_unknown_encounter_404(client) -> None:
    _start_room(client)
    r = client.get("/api/encounter/enc_bogus/medications")
    assert r.status_code == 404


# ── 3. POST replaces the active list ───────────────────────────────

def test_post_active_meds_sets_explicit_list(client) -> None:
    body = _start_room(client)
    eid = body["encounters"][0]["encounter_id"]
    # Discover the first persona + a med name.
    payload = client.get(f"/api/encounter/{eid}/medications").json()
    p = payload["personas"][0]
    if not p["medications"]:
        pytest.skip("persona has no seed meds; engine cold path.")
    target_name = p["medications"][0]["name"]
    pid = p["character_id"]
    r = client.post(f"/api/encounter/{eid}/medications/active",
                     json={"persona_id": pid,
                           "active_med_names": [target_name]})
    assert r.status_code == 200, r.text
    assert r.json()["active_count"] == 1
    # GET back — explicit list now True, only target is active.
    payload2 = client.get(f"/api/encounter/{eid}/medications").json()
    p2 = next(pp for pp in payload2["personas"]
              if pp["character_id"] == pid)
    assert p2["explicit_active_list"] is True
    active_meds = [m for m in p2["medications"] if m["active"]]
    inactive_meds = [m for m in p2["medications"] if not m["active"]]
    assert any(m["name"] == target_name for m in active_meds)
    # If the persona had more than one seed med, the others go
    # inactive.
    if len(p["medications"]) > 1:
        assert inactive_meds


def test_post_active_meds_empty_list_clears_all(client) -> None:
    """Empty list explicitly means "no meds active for this patient"
    — different from default-all."""
    body = _start_room(client)
    eid = body["encounters"][0]["encounter_id"]
    payload = client.get(f"/api/encounter/{eid}/medications").json()
    pid = payload["personas"][0]["character_id"]
    r = client.post(f"/api/encounter/{eid}/medications/active",
                     json={"persona_id": pid, "active_med_names": []})
    assert r.status_code == 200
    assert r.json()["active_count"] == 0
    payload2 = client.get(f"/api/encounter/{eid}/medications").json()
    p2 = next(pp for pp in payload2["personas"]
              if pp["character_id"] == pid)
    assert p2["explicit_active_list"] is True
    assert all(not m["active"] for m in p2["medications"])


def test_post_missing_persona_id_400(client) -> None:
    body = _start_room(client)
    eid = body["encounters"][0]["encounter_id"]
    r = client.post(f"/api/encounter/{eid}/medications/active",
                     json={"active_med_names": ["whatever"]})
    assert r.status_code == 400


def test_post_unknown_encounter_404(client) -> None:
    _start_room(client)
    r = client.post("/api/encounter/enc_bogus/medications/active",
                     json={"persona_id": "X", "active_med_names": []})
    assert r.status_code == 404


# ── 4. DELETE resets persona to default ────────────────────────────

def test_delete_resets_persona_to_default(client) -> None:
    body = _start_room(client)
    eid = body["encounters"][0]["encounter_id"]
    payload = client.get(f"/api/encounter/{eid}/medications").json()
    pid = payload["personas"][0]["character_id"]
    client.post(f"/api/encounter/{eid}/medications/active",
                 json={"persona_id": pid, "active_med_names": []})
    # Now reset.
    r = client.delete(
        f"/api/encounter/{eid}/medications/active/{pid}")
    assert r.status_code == 200
    payload2 = client.get(f"/api/encounter/{eid}/medications").json()
    p2 = next(pp for pp in payload2["personas"]
              if pp["character_id"] == pid)
    assert p2["explicit_active_list"] is False
    assert all(m["active"] for m in p2["medications"])


# ── 5. Cart bootstrap filters by active list ───────────────────────

def test_cart_bootstrap_filters_to_active_meds(client) -> None:
    """Register a med cart linked to the encounter, set an explicit
    active list, then bootstrap the cart — only the listed med
    should appear under that patient."""
    body = _start_room(client)
    eid = body["encounters"][0]["encounter_id"]
    join_code = body["encounters"][0]["join_code"]
    # Set persona's active list to a single med.
    payload = client.get(f"/api/encounter/{eid}/medications").json()
    p = payload["personas"][0]
    if not p["medications"]:
        pytest.skip("persona has no seed meds.")
    target = p["medications"][0]["name"]
    pid = p["character_id"]
    client.post(f"/api/encounter/{eid}/medications/active",
                 json={"persona_id": pid, "active_med_names": [target]})
    # Register a cart via the room-level med-cart route (M47). With
    # only one encounter in the room, that encounter becomes the
    # cart's primary + only link automatically.
    r = client.post("/api/room/med_cart/register",
                     json={"label": "M55 Cart"})
    assert r.status_code == 200, r.text
    cart_sid = r.json()["station_id"]
    assert eid in r.json()["linked_encounter_ids"]
    # Bootstrap the cart.
    boot = client.get(f"/api/device/{cart_sid}/bootstrap").json()
    chars = boot.get("characters") or []
    me = next(c for c in chars if c["character_id"] == pid)
    names = {(m.get("name") or "").lower() for m in me["medications"]}
    assert target.lower() in names
    # Anything NOT in the active list should be filtered out.
    if len(p["medications"]) > 1:
        other = p["medications"][1]["name"]
        assert other.lower() not in names


def test_cart_bootstrap_shows_all_when_no_active_list(client) -> None:
    """Back-compat: a persona with NO explicit active list still
    surfaces every med on the cart (pre-M55 behaviour)."""
    body = _start_room(client)
    eid = body["encounters"][0]["encounter_id"]
    r = client.post("/api/room/med_cart/register",
                     json={"label": "M55 Default Cart"})
    cart_sid = r.json()["station_id"]
    boot = client.get(f"/api/device/{cart_sid}/bootstrap").json()
    # Compare cart's per-patient med list against the encounter's
    # full med list — should match (filter is a no-op).
    payload = client.get(f"/api/encounter/{eid}/medications").json()
    p = payload["personas"][0]
    me = next(c for c in boot["characters"]
              if c["character_id"] == p["character_id"])
    expected_names = {(m["name"] or "").lower() for m in p["medications"]}
    cart_names = {(m["name"] or "").lower() for m in me["medications"]}
    assert cart_names == expected_names


# ── 6. UI markers ──────────────────────────────────────────────────

def test_encounter_console_renders_meds_card(client) -> None:
    body = _start_room(client)
    eid = body["encounters"][0]["encounter_id"]
    r = client.get(f"/portal/room/encounter/{eid}")
    assert r.status_code == 200
    html = r.text
    assert 'id="card-medications"' in html
    assert "💊 Medications" in html
    # Default state is collapsed (matches M54 threshold pattern).
    assert 'meds-collapsed' in html
    # Header is a real toggle with ARIA.
    assert 'id="meds-toggle"' in html
    assert 'aria-expanded="false"' in html
    assert 'aria-controls="meds-body"' in html
    # Caret marker for the visual cue.
    assert "meds-caret" in html


def test_encounter_console_js_wires_meds_handlers() -> None:
    src = (Path(__file__).resolve().parents[2]
           / "portal" / "static" / "encounter_console.js").read_text("utf-8")
    assert "wireMedsToggle" in src
    assert "bootMedications" in src
    assert "renderMedications" in src
    assert "onMedToggle" in src
    assert "onMedReset" in src
    # Hits the right routes.
    assert "/medications/active" in src
    assert "/medications" in src
    # Keyboard-accessible toggle.
    assert "'Enter'" in src or '"Enter"' in src


def test_encounter_console_css_styles_meds_card() -> None:
    src = (Path(__file__).resolve().parents[2]
           / "portal" / "static" / "encounter_console.css").read_text("utf-8")
    assert ".meds-card" in src
    # Hide body when collapsed.
    assert ".meds-card.meds-collapsed .meds-body" in src
    # Per-persona section + checkbox row.
    assert ".meds-persona" in src
    assert ".meds-row" in src
    # High-alert marker styling.
    assert ".meds-high-alert" in src


# ── 7. M58 — Patient-only filter ───────────────────────────────────

def test_get_medications_only_returns_patient_persona(client) -> None:
    """Operator: "Med list should only populate with Patient
    character medications no other character." When an encounter
    has the patient + a family member persona in selected_personas,
    only the patient's MAR should surface in the Medications card.
    """
    # Build an encounter explicitly carrying TWO personas — one of
    # them flagged as the patient via patient_persona_id.
    patient = "P-014"
    family  = "P-003"
    r = client.post("/api/room/start", json={
        "label": "M58",
        "encounters": [{
            "scenario_name": "Bed 1",
            "persona_id": patient,
            "patient_persona_id": patient,
            "personas": [patient, family],
            "ehr_id": "helix",
        }],
    })
    assert r.status_code == 200, r.text
    eid = r.json()["encounters"][0]["encounter_id"]
    payload = client.get(f"/api/encounter/{eid}/medications").json()
    personas = payload["personas"]
    # Only the patient persona shows up.
    assert len(personas) == 1
    assert personas[0]["character_id"] == patient


def test_cart_bootstrap_only_returns_patient_persona_per_encounter(client) -> None:
    """Same filter on the M47 med-cart bootstrap. Two personas on
    the encounter, one of them the patient → cart bootstrap returns
    exactly one character entry for that encounter (the patient)."""
    patient = "P-014"
    family  = "P-003"
    r = client.post("/api/room/start", json={
        "label": "M58 cart",
        "encounters": [{
            "scenario_name": "Bed 1",
            "persona_id": patient,
            "patient_persona_id": patient,
            "personas": [patient, family],
            "ehr_id": "helix",
        }],
    })
    eid = r.json()["encounters"][0]["encounter_id"]
    # Register a cart against the encounter.
    r2 = client.post("/api/room/med_cart/register",
                      json={"label": "M58 Cart",
                            "encounter_ids": [eid]})
    cart_sid = r2.json()["station_id"]
    boot = client.get(f"/api/device/{cart_sid}/bootstrap").json()
    chars = [c for c in (boot.get("characters") or [])
             if c.get("encounter_id") == eid]
    assert len(chars) == 1
    assert chars[0]["character_id"] == patient
    # And the family persona is nowhere in the cart's character list.
    assert all(c.get("character_id") != family
               for c in (boot.get("characters") or []))


def test_patient_persona_id_helper_falls_back_to_selected_personas() -> None:
    """Legacy v6 sessions don't set patient_persona_id; the helper
    falls back to selected_personas[0] (the v6 convention)."""
    from portal.ehr_seed import patient_persona_id
    from portal.control_session import ControlSession
    enc = ControlSession(
        id="enc_x", join_code="ABC123",
        scenario_name="Legacy", api_key="",
        selected_personas=["P-014", "P-003"],
        patient_persona_id=None,
    )
    assert patient_persona_id(enc) == "P-014"


def test_patient_persona_id_helper_prefers_explicit_field() -> None:
    """When patient_persona_id is set, it wins over
    selected_personas[0]."""
    from portal.ehr_seed import patient_persona_id
    from portal.control_session import ControlSession
    enc = ControlSession(
        id="enc_x", join_code="ABC123",
        scenario_name="V7", api_key="",
        selected_personas=["P-003", "P-014"],   # P-003 first
        patient_persona_id="P-014",              # but P-014 is the patient
    )
    assert patient_persona_id(enc) == "P-014"


def test_patient_persona_id_helper_returns_none_when_unset() -> None:
    from portal.ehr_seed import patient_persona_id
    from portal.control_session import ControlSession
    enc = ControlSession(
        id="enc_x", join_code="ABC123",
        scenario_name="Empty", api_key="",
    )
    assert patient_persona_id(enc) is None


def test_seeds_for_patient_only_skips_non_patient_personas() -> None:
    """The helper iterates seeds_for_all_personas and filters to
    just the patient's character_id."""
    from portal import ehr_seed as _ehr_seed
    from portal.control_session import ControlSession
    enc = ControlSession(
        id="enc_x", join_code="ABC123",
        scenario_name="Multi", api_key="",
        selected_personas=["P-014", "P-003"],
        patient_persona_id="P-014",
    )
    out = _ehr_seed.seeds_for_patient_only(enc, ehr_id="helix")
    # At most one entry, and if present it's the patient.
    assert len(out) <= 1
    if out:
        assert out[0]["character_id"] == "P-014"
