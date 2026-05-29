"""M35 — Start / Pause / End controls + instructor auto-stations.

Five new routes:
  POST /api/room/start_all                        — master Start
  POST /api/encounter/{id}/start                  — per-encounter Start
  POST /api/encounter/{id}/pause                  — per-encounter Pause
  POST /api/encounter/{id}/end                    — per-encounter End (NO debrief)
  GET  /portal/engage/{eid}/{persona_id}          — instructor engage deep-link

Master Start auto-registers an instructor chat station with id
`INST-<persona_id>` for every persona on every encounter — that's
the station the Engage button deep-links into, bypassing the
public /join landing.
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


def _start_2enc_room(client):
    r = client.post("/api/room/start", json={
        "label": "M35 controls",
        "encounters": [
            {"scenario_name": "Bed 1", "persona_id": "P-014",
             "patient_persona_id": "P-014",
             "personas": ["P-014", "P-001"],
             "ehr_id": "helix"},
            {"scenario_name": "Bed 2", "persona_id": "P-003",
             "patient_persona_id": "P-003",
             "personas": ["P-003", "P-015"],
             "ehr_id": "helix"},
        ],
    })
    assert r.status_code == 200, r.text
    return r.json()["encounters"]


# ── Master Start / Pause / End ────────────────────────────────────────

def test_master_start_all_transitions_every_encounter_to_running(client) -> None:
    """POST /api/room/start_all sets state='running' on every
    encounter and creates instructor stations for every persona."""
    from portal import control_room as cr
    encs = _start_2enc_room(client)
    r = client.post("/api/room/start_all")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["encounter_count"] == 2
    # 4 instructor stations created total: 2 personas × 2 encounters.
    assert body["instructor_stations_created"] == 4
    room = cr.get_active_room()
    for e in encs:
        enc = room.encounters[e["encounter_id"]]
        assert enc.state == "running"
        # Each persona has an INST-<pid> chat station.
        for pid in enc.selected_personas:
            sid = f"INST-{pid}"
            assert sid in enc.stations, (
                f"Master Start should auto-register {sid} on {enc.id}.")
            assert enc.stations[sid].persona_id == pid


def test_master_start_all_is_idempotent(client) -> None:
    _start_2enc_room(client)
    client.post("/api/room/start_all")
    r = client.post("/api/room/start_all")
    body = r.json()
    # Second call creates zero new instructor stations.
    assert body["instructor_stations_created"] == 0


def test_pause_all_after_start_all_marks_every_encounter_paused(client) -> None:
    """The existing /api/room/freeze_all still does the work; the
    UI just relabels it 'Pause all'. Confirm round-trip."""
    from portal import control_room as cr
    encs = _start_2enc_room(client)
    client.post("/api/room/start_all")
    client.post("/api/room/freeze_all")
    room = cr.get_active_room()
    for e in encs:
        assert room.encounters[e["encounter_id"]].state == "paused"


def test_master_end_saves_cohort_debrief_and_clears_singleton(client) -> None:
    """The master End route is unchanged — fires cohort debrief save,
    clears the singleton. Tested elsewhere but verify the contract
    still holds after M35 lands."""
    from portal import control_room as cr
    _start_2enc_room(client)
    client.post("/api/room/start_all")
    r = client.post("/api/room/end")
    body = r.json()
    assert body["ok"] is True
    assert body["cohort_debrief_saved"] is True
    assert body["cohort_debrief_url"].startswith("/portal/debrief/cohort/")
    assert cr.get_active_room() is None


# ── Per-encounter Start / Pause / End (no debrief on End) ────────────

def test_per_encounter_start_sets_running_and_creates_instructor_stations(
    client,
) -> None:
    from portal import control_room as cr
    encs = _start_2enc_room(client)
    e0, e1 = encs[0]["encounter_id"], encs[1]["encounter_id"]
    r = client.post(f"/api/encounter/{e0}/start")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "running"
    assert body["instructor_stations_created"] == 2  # 2 personas on bed 1
    room = cr.get_active_room()
    # Bed 1 has stations; bed 2 still doesn't.
    assert "INST-P-014" in room.encounters[e0].stations
    assert "INST-P-001" in room.encounters[e0].stations
    assert "INST-P-003" not in room.encounters[e1].stations
    assert room.encounters[e1].state != "running"


def test_per_encounter_pause_sets_paused(client) -> None:
    from portal import control_room as cr
    encs = _start_2enc_room(client)
    e0 = encs[0]["encounter_id"]
    client.post(f"/api/encounter/{e0}/start")
    r = client.post(f"/api/encounter/{e0}/pause")
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "paused"
    assert cr.get_active_room().encounters[e0].state == "paused"


def test_per_encounter_end_marks_ended_but_NO_cohort_debrief(client) -> None:
    """The crucial M35 contract — per-encounter End does NOT save the
    cohort debrief and does NOT clear the singleton. Cohort debrief
    only fires on master /api/room/end."""
    from portal import control_room as cr, debrief as debrief_mod
    encs = _start_2enc_room(client)
    e0 = encs[0]["encounter_id"]
    client.post("/api/room/start_all")
    r = client.post(f"/api/encounter/{e0}/end")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "ended"
    assert body["cohort_debrief_saved"] is False
    # Singleton still alive — only this encounter ended.
    assert cr.get_active_room() is not None
    # No cohort file saved for this room id yet.
    room = cr.get_active_room()
    saved = debrief_mod.load_cohort(room.room_id)
    assert saved is None, (
        "Per-encounter End must NOT have written a cohort debrief — "
        "that only happens on master End.")


def test_per_encounter_routes_404_unknown_encounter(client) -> None:
    _start_2enc_room(client)
    for action in ("start", "pause", "end"):
        r = client.post(f"/api/encounter/ENC-bogus/{action}")
        assert r.status_code == 404, action


# ── Engage deep-link bypasses /join ─────────────────────────────────

def test_engage_redirects_to_instructor_station_after_master_start(client) -> None:
    """After master Start, the engage URL 303s straight into the chat
    station — no /join landing, no name typed."""
    encs = _start_2enc_room(client)
    e0 = encs[0]["encounter_id"]
    join = encs[0]["join_code"]
    client.post("/api/room/start_all")
    r = client.get(f"/portal/engage/{e0}/P-014", follow_redirects=False)
    assert r.status_code == 303, r.text
    assert r.headers["location"] == f"/station/{join}/INST-P-014"


def test_engage_lazy_creates_station_before_master_start(client) -> None:
    """Engage works pre-start too — the route lazy-registers the
    instructor station so an instructor who clicks Engage before
    pressing master Start still lands on the chat. This is the
    safety net behind master Start's bulk creation."""
    from portal import control_room as cr
    encs = _start_2enc_room(client)
    e0 = encs[0]["encounter_id"]
    join = encs[0]["join_code"]
    # No master Start yet.
    assert cr.get_active_room().encounters[e0].state == "configured"
    r = client.get(f"/portal/engage/{e0}/P-014", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == f"/station/{join}/INST-P-014"
    # Station was lazy-created.
    assert "INST-P-014" in cr.get_active_room().encounters[e0].stations


def test_engage_rejects_persona_not_on_encounter(client) -> None:
    encs = _start_2enc_room(client)
    e0 = encs[0]["encounter_id"]
    # P-003 is on bed 2, not bed 1 → 404.
    r = client.get(f"/portal/engage/{e0}/P-003", follow_redirects=False)
    assert r.status_code == 404


# ── UI: header buttons present ───────────────────────────────────────

def test_multi_patient_control_header_has_start_pause_end_buttons(client) -> None:
    r = client.get("/portal/room")
    assert r.status_code == 200
    html = r.text
    assert 'id="btn-start-all"' in html
    assert 'id="btn-freeze"' in html       # repurposed visually as "Pause all"
    assert 'id="btn-end"' in html
    # Visible labels reflect the new naming.
    assert "Start all scenarios" in html
    assert "Pause all" in html
    assert "End all (debrief)" in html


def test_per_patient_console_header_has_start_pause_end_buttons(client) -> None:
    encs = _start_2enc_room(client)
    eid = encs[0]["encounter_id"]
    r = client.get(f"/portal/room/encounter/{eid}")
    assert r.status_code == 200
    html = r.text
    for bid in ("btn-enc-start", "btn-enc-pause", "btn-enc-end"):
        assert f'id="{bid}"' in html, f"missing {bid}"
    # Per-encounter End's confirm message clarifies that the cohort
    # debrief only fires on master End.
    assert "NOT saved until you press" in html


def test_encounter_console_js_uses_portal_engage_url_not_join(client) -> None:
    """The Engage button in the voice card now points at
    /portal/engage/{eid}/{pid}, not the public /join page."""
    js_path = (
        Path(__file__).resolve().parents[2]
        / "portal" / "static" / "encounter_console.js"
    )
    src = js_path.read_text(encoding="utf-8")
    assert "/portal/engage/" in src
    # And the old /join?code= construction inside the engage href is
    # gone (other references elsewhere in the file are fine, but the
    # Engage anchor's href specifically must not use it).
    # We grep for the engageHref variable assignment to be precise.
    snip_idx = src.find("const engageHref")
    assert snip_idx >= 0
    snippet = src[snip_idx:snip_idx + 300]
    assert "/portal/engage/" in snippet
    assert "/join?code=" not in snippet
