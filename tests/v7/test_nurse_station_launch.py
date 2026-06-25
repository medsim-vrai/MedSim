"""M36 — Nursing Station QR + instructor launch button.

New route:
  GET /portal/control/launch_nurse_station  — auto-creates (or reuses)
       an instructor nurse-station student and 303s to
       /portal/students/nurse_station?sid={student.student_id}.

UI surface:
  - Multi-Patient Control dashboard (/portal/room): a "🩺 Nursing
    Station" launch panel with QR + button, rendered only when a
    room is active.
  - Per-Patient Console (/portal/room/encounter/{id}): a 4th cell
    in the QR-codes card with the nurse-station QR + "Open here"
    link.
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


def _start_room(client):
    r = client.post("/api/room/start", json={
        "label": "M36 nurse station",
        "encounters": [
            {"scenario_name": "Bed 1", "persona_id": "P-014",
             "patient_persona_id": "P-014", "ehr_id": "helix"},
            {"scenario_name": "Bed 2", "persona_id": "P-003",
             "patient_persona_id": "P-003", "ehr_id": "helix"},
        ],
    })
    assert r.status_code == 200, r.text
    return r.json()


# ── Backend route ───────────────────────────────────────────────────

def test_launch_nurse_station_creates_instructor_student_and_redirects(
    client,
) -> None:
    """First call: creates a nurse-station student named 'Instructor
    (Nursing Station)' and 303s to /portal/students/nurse_station?sid=…"""
    from portal import control_room as cr
    _start_room(client)
    r = client.get("/portal/control/launch_nurse_station",
                   follow_redirects=False)
    assert r.status_code == 303, r.text
    loc = r.headers["location"]
    assert loc.startswith("/portal/students/nurse_station?sid=")
    # Roster picked up the instructor seat.
    room = cr.get_active_room()
    nurse_students = [
        s for s in room.students.values() if s.role == "nurse_station"
    ]
    assert len(nurse_students) == 1
    assert nurse_students[0].display_name == "Instructor (Nursing Station)"


def test_launch_nurse_station_reuses_existing_instructor_seat(client) -> None:
    """Second call: returns the same sid — no duplicate students."""
    from portal import control_room as cr
    _start_room(client)
    a = client.get("/portal/control/launch_nurse_station",
                   follow_redirects=False)
    b = client.get("/portal/control/launch_nurse_station",
                   follow_redirects=False)
    sid_a = a.headers["location"].split("sid=", 1)[1]
    sid_b = b.headers["location"].split("sid=", 1)[1]
    assert sid_a == sid_b, "Repeat clicks must reuse the instructor seat."
    # Still only one nurse_station student in the roster.
    room = cr.get_active_room()
    nurse_students = [
        s for s in room.students.values() if s.role == "nurse_station"
    ]
    assert len(nurse_students) == 1


def test_launch_nurse_station_no_room_redirects_to_dashboard(client) -> None:
    """If no room is active, the launcher bounces to /portal/room
    instead of 500-ing or creating an orphan student."""
    # No room created.
    r = client.get("/portal/control/launch_nurse_station",
                   follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/portal/room"


def test_launch_nurse_station_redirect_target_actually_serves(client) -> None:
    """The sid URL the launcher redirects to must serve a 200 — i.e.
    we're not handing the instructor a dead link."""
    _start_room(client)
    r = client.get("/portal/control/launch_nurse_station",
                   follow_redirects=False)
    loc = r.headers["location"]
    # Hit the redirect target directly.
    r2 = client.get(loc)
    assert r2.status_code == 200, (
        f"Launcher pointed at {loc!r} but it returned {r2.status_code}.")


# ── Multi-Patient Control dashboard renders the panel ────────────────

def test_dashboard_renders_nurse_station_panel_when_room_active(client) -> None:
    """When a room is active, /portal/room carries the 🩺 Nursing
    Station card with QR + Open button."""
    body = _start_room(client)
    room_code = body["room_code"]
    r = client.get("/portal/room")
    assert r.status_code == 200
    html = r.text
    assert "nurse-station-launch" in html
    assert "Open Nursing Station" in html
    # QR encodes /portal/students/join?code=<ROOM_CODE>.
    assert "portal%2Fstudents%2Fjoin" in html or \
           "/portal/students/join?code=" + room_code in html
    # Plain-text URL is shown as a fallback.
    assert "/portal/students/join?code=" + room_code in html
    # Button hits the new launcher route in a new tab.
    assert '/portal/control/launch_nurse_station' in html
    assert 'target="_blank"' in html


def test_dashboard_omits_nurse_station_panel_when_no_room(client) -> None:
    """When there's no active room, the dashboard does not render
    the nursing-station panel — there's no room_code to embed in
    the QR."""
    r = client.get("/portal/room")
    assert r.status_code == 200
    # Check the SECTION element, not the bare class — the always-rendered
    # CARD_STRATEGY config lists ".nurse-station-launch" as a selector
    # regardless of room state.
    assert '<section class="nurse-station-launch"' not in r.text


# ── Per-Patient Console adds a 4th QR cell ──────────────────────────

def test_encounter_console_renders_nurse_station_qr_cell(client) -> None:
    """The QR card on each Per-Patient Console gets a 4th cell for
    the Nursing Station — encoded with the ROOM code (not the
    encounter's join code, since the Nursing Station supervises
    every bed)."""
    body = _start_room(client)
    eid = body["encounters"][0]["encounter_id"]
    room_code = body["room_code"]
    r = client.get(f"/portal/room/encounter/{eid}")
    assert r.status_code == 200
    html = r.text
    assert "qr-cell-nurse" in html
    assert "🩺 Nursing Station" in html
    assert "/portal/students/join?code=" + room_code in html
    # "Open here" inline link points at the launcher.
    assert "/portal/control/launch_nurse_station" in html


def test_encounter_console_help_text_clarifies_room_vs_join_code(client) -> None:
    """The QR card's footer copy now mentions that the Nursing
    Station scans the ROOM code (not the per-encounter join code)
    so the operator understands the scoping difference."""
    body = _start_room(client)
    eid = body["encounters"][0]["encounter_id"]
    room_code = body["room_code"]
    r = client.get(f"/portal/room/encounter/{eid}")
    html = r.text
    assert "Nursing Station uses the" in html
    assert "room code" in html
    assert room_code in html
