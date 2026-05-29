"""M41 — Printable QR sheet for the instructor.

New route GET /portal/control/qr_print[?encounter_id=…] renders a
print-friendly HTML page with QR codes per encounter. Without
?encounter_id, every encounter in the active room gets its own
page (page-break-after). With it, only that encounter is rendered.

Each page header carries:
  - "Training Bridge MedSim-VRAI" title
  - The patient character display name + persona id
  - Room code + bed join code (sign-in codes printed at the top)

Per encounter: four QR blocks — Chat / EHR / Device / Nursing
Station — each clearly labeled with the URL beneath.
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
        "label": "M41 print sheet",
        "encounters": [
            {"scenario_name": "Bed 1 — ED sepsis", "persona_id": "P-014",
             "patient_persona_id": "P-014", "ehr_id": "helix"},
            {"scenario_name": "Bed 2 — Peds fever", "persona_id": "P-003",
             "patient_persona_id": "P-003", "ehr_id": "helix"},
        ],
    })
    assert r.status_code == 200, r.text
    return r.json()


# ── Route returns the print page with the expected header ───────────

def test_qr_print_route_returns_branded_print_page(client) -> None:
    _start_2enc_room(client)
    r = client.get("/portal/control/qr_print")
    assert r.status_code == 200, r.text
    html = r.text
    # Branded title appears in <title> + page header.
    # M52 — brand reflowed from "Training Bridge MedSim-VRAI" to
    # "Training Bridge VRAI- MedSim" per operator.
    assert "Training Bridge VRAI- MedSim" in html
    # Print action button + back link.
    assert "window.print()" in html
    assert 'href="/portal/room"' in html
    # Print-only CSS for page-break-after and @media print.
    assert "page-break-after" in html
    assert "@media print" in html


def test_qr_print_route_renders_all_encounters_by_default(client) -> None:
    """Without ?encounter_id the page prints every encounter in the
    room — one .qr-page section per bed."""
    body = _start_2enc_room(client)
    eids = [e["encounter_id"] for e in body["encounters"]]
    joins = [e["join_code"] for e in body["encounters"]]
    r = client.get("/portal/control/qr_print")
    html = r.text
    # Both encounters' join codes appear in the page (each bed's QR
    # uses its own join code).
    for j in joins:
        assert j in html, f"join {j} missing from sheet"
    # Scope label reflects "all N encounters".
    assert "all 2 encounters" in html


def test_qr_print_route_scoped_to_single_encounter(client) -> None:
    """With ?encounter_id, only that bed's section renders."""
    body = _start_2enc_room(client)
    eids = [e["encounter_id"] for e in body["encounters"]]
    joins = [e["join_code"] for e in body["encounters"]]
    r = client.get(f"/portal/control/qr_print?encounter_id={eids[0]}")
    html = r.text
    assert r.status_code == 200
    # Bed 1's join code is present; bed 2's is NOT.
    assert joins[0] in html
    assert joins[1] not in html
    assert "single encounter" in html


def test_qr_print_route_404_on_unknown_encounter(client) -> None:
    _start_2enc_room(client)
    r = client.get("/portal/control/qr_print?encounter_id=ENC-bogus")
    assert r.status_code == 404


def test_qr_print_route_handles_no_active_room(client) -> None:
    """No room → page still renders with an empty notice (no 500)."""
    r = client.get("/portal/control/qr_print")
    assert r.status_code == 200
    html = r.text
    assert "Training Bridge MedSim-VRAI" in html or \
           "No encounters to print" in html


# ── Patient character header + sign-in codes ────────────────────────

def test_qr_print_page_carries_patient_character_in_header(client) -> None:
    """Each encounter's page header must show the patient persona's
    display name AND id. The catalog's P-014 maps to 'Mr. Hayes'."""
    body = _start_2enc_room(client)
    r = client.get("/portal/control/qr_print")
    html = r.text
    # P-014 → Mr. Hayes (per library.get_persona).
    assert "Mr. Hayes" in html, (
        "Patient character display name must appear in the page header.")
    # P-003 → Mateo (or whatever the library has — the id is enough).
    assert "P-014" in html
    assert "P-003" in html
    # 'Patient character:' label appears in the banner.
    assert "Patient character" in html


def test_qr_print_page_carries_room_and_join_codes(client) -> None:
    """The page shows both the room code (Nursing Station entry) and
    the bed's join code (Chat/EHR/Device entry) at the top of each
    encounter's section — operators read these to type a code by
    hand when the QR can't be scanned."""
    body = _start_2enc_room(client)
    room_code = body["room_code"]
    join_code = body["encounters"][0]["join_code"]
    r = client.get("/portal/control/qr_print")
    html = r.text
    assert room_code in html
    assert join_code in html
    # Labels for clarity.
    assert "Room code" in html
    assert "Bed join code" in html


# ── All four QR blocks are present per encounter ────────────────────

def test_qr_print_page_renders_all_four_station_qrs_per_encounter(client) -> None:
    """Each encounter section has Chat / EHR / Device / Nursing
    QR blocks. The QRs are <img src="/api/qr.svg?data=…">."""
    body = _start_2enc_room(client)
    join = body["encounters"][0]["join_code"]
    room_code = body["room_code"]
    r = client.get("/portal/control/qr_print")
    html = r.text
    # Labels.
    assert "💬 Chat station" in html
    assert "📋 EHR station" in html
    assert "⚕ Device station" in html
    assert "🩺 Nursing Station" in html
    # Each station's URL is present in plain text under its QR.
    assert f"/join?code={join}" in html
    assert f"/ehr/join?code={join}" in html
    assert f"/device/join?code={join}" in html
    # Nursing Station uses the ROOM code, not the bed join code.
    assert f"/portal/students/join?code={room_code}" in html


def test_qr_print_page_qr_imgs_use_api_qr_svg_endpoint(client) -> None:
    """The four station QR <img> tags hit /api/qr.svg with the URL
    URL-encoded in the `data=` param. Verify the endpoint is what
    the template uses (not a stale /api/qr.png or similar)."""
    _start_2enc_room(client)
    r = client.get("/portal/control/qr_print")
    html = r.text
    assert "/api/qr.svg?data=" in html


# ── Print buttons on the two control surfaces ───────────────────────

def test_multi_patient_control_header_has_print_qr_button(client) -> None:
    _start_2enc_room(client)
    r = client.get("/portal/room")
    html = r.text
    assert 'id="btn-qr-print"' in html
    assert 'href="/portal/control/qr_print"' in html
    assert 'target="_blank"' in html


def test_encounter_console_has_per_encounter_print_link(client) -> None:
    body = _start_2enc_room(client)
    eid = body["encounters"][0]["encounter_id"]
    r = client.get(f"/portal/room/encounter/{eid}")
    html = r.text
    assert 'class="qr-print-link"' in html
    assert f"/portal/control/qr_print?encounter_id={eid}" in html
    assert "Print QR codes for this encounter" in html
