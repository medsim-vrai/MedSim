"""M47 — Room-level med carts.

A single cabinet/med cart can be created on the Multi-Patient
Control page and linked to multiple encounters in the same room.
The cabinet bootstrap renders ALL linked encounters' patients
grouped per-patient. Dispense events on the cart write a transcript
entry to whichever encounter owns the named patient.

Tests cover:
  1. Cart registration via POST /api/room/med_cart/register.
  2. Linking + unlinking additional encounters.
  3. Listing carts via GET /api/room/med_carts.
  4. The cabinet bootstrap returns characters from ALL linked
     encounters when the cart_links map has multiple entries.
  5. A med.dispensed event on a cart writes a transcript entry to
     the encounter owning the named patient.
  6. UI markers on the Multi-Patient Control dashboard.
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


def _start_2enc_room(client):
    r = client.post("/api/room/start", json={
        "label": "M47 med carts",
        "encounters": [
            {"scenario_name": "Bed 1", "persona_id": "P-014",
             "patient_persona_id": "P-014",
             "personas": ["P-014"], "ehr_id": "helix"},
            {"scenario_name": "Bed 2", "persona_id": "P-003",
             "patient_persona_id": "P-003",
             "personas": ["P-003"], "ehr_id": "helix"},
        ],
    })
    assert r.status_code == 200, r.text
    return r.json()


# ── Cart registration + listing ──────────────────────────────────────

def test_med_cart_register_creates_room_level_cart(client) -> None:
    body = _start_2enc_room(client)
    eid_a = body["encounters"][0]["encounter_id"]
    r = client.post("/api/room/med_cart/register",
                     json={"label": "ICU Cart A"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["ok"] is True
    assert out["label"] == "ICU Cart A"
    assert out["station_id"].startswith("cart_")
    # Primary encounter is the first one in the room (default when no
    # explicit encounter_ids passed).
    assert out["primary_encounter_id"] == eid_a
    # Cart's link list starts with just the primary.
    assert out["linked_encounter_ids"] == [eid_a]
    # QR encodes a working device-join URL.
    assert "/device/join?code=" in out["join_url"]
    assert "<svg" in out["qr_svg"]


def test_med_cart_register_with_explicit_encounter_ids(client) -> None:
    """Operator can specify which encounters to link at creation."""
    body = _start_2enc_room(client)
    eids = [e["encounter_id"] for e in body["encounters"]]
    r = client.post("/api/room/med_cart/register",
                     json={"label": "Shared cart", "encounter_ids": eids})
    assert r.status_code == 200
    out = r.json()
    assert out["linked_encounter_ids"] == eids
    assert out["primary_encounter_id"] == eids[0]


def test_med_cart_register_rejects_unknown_encounter(client) -> None:
    _start_2enc_room(client)
    r = client.post("/api/room/med_cart/register",
                     json={"label": "X", "encounter_ids": ["bogus-id"]})
    assert r.status_code == 400


def test_med_cart_register_requires_active_room(client) -> None:
    r = client.post("/api/room/med_cart/register", json={"label": "X"})
    # No active room → 404 from _require_active_room (the helper
    # surfaces a 404 with "No active room. Start one via …").
    assert r.status_code == 404


# ── Linking + unlinking encounters ──────────────────────────────────

def test_med_cart_link_encounter_adds_to_list(client) -> None:
    body = _start_2enc_room(client)
    eid_a, eid_b = (e["encounter_id"] for e in body["encounters"])
    sid = client.post("/api/room/med_cart/register",
                       json={"label": "Cart A"}).json()["station_id"]
    # Cart starts with just encounter A (the primary).
    r = client.post(
        f"/api/room/med_cart/{sid}/link_encounter",
        json={"encounter_id": eid_b},
    )
    assert r.status_code == 200
    assert set(r.json()["linked_encounter_ids"]) == {eid_a, eid_b}


def test_med_cart_link_encounter_is_idempotent(client) -> None:
    body = _start_2enc_room(client)
    eid_b = body["encounters"][1]["encounter_id"]
    sid = client.post("/api/room/med_cart/register",
                       json={"label": "Cart A"}).json()["station_id"]
    client.post(f"/api/room/med_cart/{sid}/link_encounter",
                 json={"encounter_id": eid_b})
    # Same link again — still 200, still 2 entries.
    r = client.post(f"/api/room/med_cart/{sid}/link_encounter",
                     json={"encounter_id": eid_b})
    assert r.status_code == 200
    assert len(r.json()["linked_encounter_ids"]) == 2


def test_med_cart_unlink_removes_non_primary(client) -> None:
    body = _start_2enc_room(client)
    eid_a, eid_b = (e["encounter_id"] for e in body["encounters"])
    sid = client.post("/api/room/med_cart/register",
                       json={"label": "Cart A",
                             "encounter_ids": [eid_a, eid_b]}).json()["station_id"]
    r = client.delete(f"/api/room/med_cart/{sid}/link_encounter/{eid_b}")
    assert r.status_code == 200
    assert r.json()["linked_encounter_ids"] == [eid_a]


def test_med_cart_unlink_primary_is_409(client) -> None:
    """The primary encounter (the cart's DB session_id) can't be
    unlinked — operator must delete + recreate. Without this guard
    the per-station device routes would lose their session reference."""
    body = _start_2enc_room(client)
    eid_a = body["encounters"][0]["encounter_id"]
    sid = client.post("/api/room/med_cart/register",
                       json={"label": "Cart A"}).json()["station_id"]
    r = client.delete(f"/api/room/med_cart/{sid}/link_encounter/{eid_a}")
    assert r.status_code == 409
    assert "primary" in r.text.lower() or "Delete" in r.text


def test_med_cart_link_unknown_cart_404(client) -> None:
    body = _start_2enc_room(client)
    eid = body["encounters"][0]["encounter_id"]
    r = client.post("/api/room/med_cart/cart_bogus/link_encounter",
                     json={"encounter_id": eid})
    assert r.status_code == 404


# ── /api/room/med_carts listing ─────────────────────────────────────

def test_med_carts_list_returns_carts_with_links(client) -> None:
    body = _start_2enc_room(client)
    eids = [e["encounter_id"] for e in body["encounters"]]
    a = client.post("/api/room/med_cart/register",
                     json={"label": "Cart A"}).json()
    b = client.post("/api/room/med_cart/register",
                     json={"label": "Cart B",
                           "encounter_ids": eids}).json()
    r = client.get("/api/room/med_carts")
    assert r.status_code == 200
    carts = r.json()["carts"]
    assert len(carts) == 2
    by_sid = {c["station_id"]: c for c in carts}
    assert by_sid[a["station_id"]]["label"] == "Cart A"
    assert by_sid[b["station_id"]]["label"] == "Cart B"
    assert by_sid[b["station_id"]]["linked_encounter_ids"] == eids
    # Each cart has a join URL with its station id.
    for c in carts:
        assert "/device/join?code=" in c["join_url"]
        assert c["station_id"] in c["join_url"]


# ── Cabinet bootstrap merges MARs across linked encounters ──────────

def test_cabinet_bootstrap_returns_characters_from_all_linked_encs(
    client,
) -> None:
    """The pre-M47 bootstrap returned only the cart's own session's
    MAR. With M47's room-level link list, the bootstrap must return
    characters from EVERY linked encounter so the cart UI can render
    a per-patient grouped MAR."""
    body = _start_2enc_room(client)
    eids = [e["encounter_id"] for e in body["encounters"]]
    out = client.post("/api/room/med_cart/register",
                       json={"label": "Shared cart",
                             "encounter_ids": eids}).json()
    sid = out["station_id"]
    r = client.get(f"/api/device/{sid}/bootstrap")
    assert r.status_code == 200, r.text
    body_b = r.json()
    chars = body_b.get("characters", [])
    # Each linked encounter contributes its own selected_personas.
    eids_in_chars = {c.get("encounter_id") for c in chars}
    assert eids[0] in eids_in_chars
    assert eids[1] in eids_in_chars
    # `seeds_for_all_personas` keys persona ids on `character_id`,
    # not `id`. Both encounters' patient personas appear.
    pids = {c.get("character_id") for c in chars}
    assert "P-014" in pids
    assert "P-003" in pids


# ── Med dispense event writes to the right encounter transcript ─────

def test_dispense_event_writes_transcript_to_owning_encounter(
    client,
) -> None:
    """When a `med.dispensed` event fires on a cart linked to two
    encounters, the transcript entry lands on the encounter that
    owns the named patient — NOT on every linked encounter."""
    from portal import control_room
    body = _start_2enc_room(client)
    eid_a, eid_b = (e["encounter_id"] for e in body["encounters"])
    sid = client.post(
        "/api/room/med_cart/register",
        json={"label": "ICU Cart",
              "encounter_ids": [eid_a, eid_b]},
    ).json()["station_id"]
    # Fire a med.dispensed event naming the bed-2 patient (P-003).
    r = client.post(f"/api/device/{sid}/event", json={
        "type": "med.dispensed",
        "payload": {
            "character_id": "P-003",
            "medication": "lorazepam",
            "amount": "2",
            "unit": "mg",
            "wasted": "1",
            "wasted_witness": "RN Jane Doe",
            "dispensed_by": "Student Bob",
        },
    })
    assert r.status_code == 200, r.text
    # Bed B's transcript got the line. log_turn writes two entries
    # (student + empty character); the cart-dispense text lives on
    # the student-direction entry (the second-from-last).
    room = control_room.get_active_room()
    enc_b = room.encounters[eid_b]
    assert len(enc_b.transcript) >= 2
    # Combine all text in the latest pair so we can assert on any
    # of the substrings without worrying about ordering.
    line = " ".join(t.text for t in enc_b.transcript[-2:])
    assert "ICU Cart" in line
    assert "lorazepam" in line
    assert "2 mg" in line
    assert "by Student Bob" in line
    assert "wasted 1" in line
    assert "RN Jane Doe" in line
    # Bed A's transcript did NOT get a duplicate.
    enc_a = room.encounters[eid_a]
    assert all("lorazepam" not in t.text for t in enc_a.transcript)


def test_dispense_event_non_dispense_types_skip_transcript(client) -> None:
    """Only `med.dispensed` triggers the transcript hook; other
    device events (alarm.injected, etc.) go through the engine
    handler but don't write a transcript line."""
    from portal import control_room
    body = _start_2enc_room(client)
    eid_a = body["encounters"][0]["encounter_id"]
    sid = client.post(
        "/api/room/med_cart/register",
        json={"label": "Cart A"},
    ).json()["station_id"]
    # discrepancy_alert is a real cabinet tone.
    client.post(f"/api/device/{sid}/event", json={
        "type": "alarm.injected",
        "payload": {"tone": "discrepancy_alert"},
    })
    room = control_room.get_active_room()
    enc = room.encounters[eid_a]
    # No "💊" cart marker should appear in the transcript.
    assert all("💊" not in t.text for t in enc.transcript)


# ── Multi-Patient Control dashboard markers ──────────────────────────

def test_control_room_dashboard_includes_med_carts_panel(client) -> None:
    _start_2enc_room(client)
    r = client.get("/portal/room")
    assert r.status_code == 200
    html = r.text
    assert "med-carts-panel" in html
    assert "🛒 Med carts" in html
    assert 'id="med-cart-create-form"' in html
    assert 'id="med-carts-list"' in html


def test_control_room_dashboard_omits_panel_when_no_room(client) -> None:
    r = client.get("/portal/room")
    assert r.status_code == 200
    # The panel SECTION sits under `{% if room %}` — no active room → no panel.
    # (Check the element, not the bare class: the always-rendered CARD_STRATEGY
    # config lists ".med-carts-panel" as a selector regardless of room state.)
    assert '<section class="med-carts-panel"' not in r.text
