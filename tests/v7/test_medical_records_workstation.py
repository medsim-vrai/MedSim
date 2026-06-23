"""M62 — Medical Records workstation + admin entry surfaces.

Operator: "there needs to be a path to open the system in from the
multi-patient control screen with both a QR code and button to open
from the control screen. the entry screen should list the active
patients characters so that the student or instructor must select
the patient then enter the medical records system. This will support
setting up an independent work station that multiple students will
access to enter patient data and get information. The instructor
should also have a special access to all them to insert updates and
information likes labs that have been generated, or doctors notes or
other supporting character information into the selected patient
chart as they need to to support the simulation. Separately a
designated nursing supervisor student should be able access through
the nursing station a 'administrative portal' to enter labs and make
notes separate from students assigned to specific patient characters.
A button on the nursing station that allows the Student Nursing
supervisor to enter their 2 initials to enter the administrative
entry to have the medical records open up in new window to do their
work."
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
    # Test isolation: resume-on-boot persists session state into the shared
    # EHR SQLite on TestClient teardown, which the next test's boot would
    # restore — leaking a prior test's session. These tests want a clean
    # slate (and don't exercise resume), so disable resume-on-boot.
    monkeypatch.setenv("MEDSIM_RESUME", "0")
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
        "label": "M62",
        "encounters": [
            {"scenario_name": f"Bed {i+1}", "persona_id": pool[i],
             "patient_persona_id": pool[i],
             "personas": [pool[i]], "ehr_id": "helix"}
            for i in range(n)
        ],
    })
    assert r.status_code == 200, r.text
    return r.json()


# ── 1. Multi-Patient Control panel renders workstation launcher ────

def test_control_room_has_workstation_panel(client):
    """Multi-Patient Control gets a new panel with button + QR for
    the public Medical Records workstation."""
    body = _start_room(client, n=2)
    html = client.get("/portal/room").text
    assert "Medical Records Workstation" in html
    assert "mr-ws-launch-btn" in html
    assert "/students/medical_records?code=" in html
    # QR includes the URL.
    assert "/api/qr.svg" in html


def test_workstation_panel_hidden_without_room(client):
    """The {% if room %} guard keeps the panel off when no room is
    active."""
    html = client.get("/portal/room").text
    assert "Medical Records Workstation" not in html


# ── 2. Public workstation entry route ──────────────────────────────

def test_workstation_entry_lists_every_patient(client):
    body = _start_room(client, n=2)
    room_code = body["room_code"]
    # Drop auth cookie so the route runs as public.
    from portal import auth
    client.cookies.delete(auth.COOKIE_NAME)
    r = client.get(f"/students/medical_records?code={room_code}")
    assert r.status_code == 200
    html = r.text
    assert "Helix Health" in html          # branded records terminal
    # Patient cards for every encounter.
    assert html.count("mr-ws-patient-card") >= 2
    # Identity form fields.
    assert 'id="mr-ws-name"' in html
    assert 'id="mr-ws-initials"' in html


def test_workstation_entry_no_active_session_shows_empty(client):
    from portal import auth
    client.cookies.delete(auth.COOKIE_NAME)
    r = client.get("/students/medical_records?code=XYZ")
    assert r.status_code == 200
    assert "No active session" in r.text


def test_workstation_entry_carries_role_querystring(client):
    _start_room(client, n=1)
    from portal import auth
    client.cookies.delete(auth.COOKIE_NAME)
    r = client.get(
        "/students/medical_records?code=any&role=supervisor&initials=BJ")
    assert r.status_code == 200
    html = r.text
    # Supervisor badge surfaces.
    assert "Supervisor session" in html or "supervisor" in html.lower()


# ── 3. Public chart route ──────────────────────────────────────────

def test_workstation_chart_renders_for_student(client):
    body = _start_room(client, n=1)
    from portal import auth
    client.cookies.delete(auth.COOKIE_NAME)
    r = client.get(
        "/students/medical_records/P-014"
        "?code=&user=Alice&initials=AP&role=student")
    assert r.status_code == 200
    html = r.text
    # MAR rendered (same template family as the operator chart).
    assert "Medication Administration Record" in html
    # Author identity surfaced in the header.
    assert "Alice" in html
    # No add-to-chart form for plain students.
    assert "mr-add-form" not in html


def test_workstation_chart_supervisor_sees_add_form(client):
    _start_room(client, n=1)
    from portal import auth
    client.cookies.delete(auth.COOKIE_NAME)
    r = client.get(
        "/students/medical_records/P-014"
        "?code=&user=Supe&initials=BJ&role=supervisor")
    assert r.status_code == 200
    html = r.text
    # Admin form is present for supervisor role.
    assert "mr-add-form" in html
    assert "Add to chart" in html
    # Supervisor badge surfaces.
    assert "Supervisor" in html


def test_workstation_chart_404_for_unknown_persona(client):
    _start_room(client, n=1)
    from portal import auth
    client.cookies.delete(auth.COOKIE_NAME)
    r = client.get(
        "/students/medical_records/P-bogus"
        "?code=&user=Alice&initials=AP")
    assert r.status_code == 404


# ── 4. Chart inserts API ───────────────────────────────────────────

def test_insert_note_appends_to_encounter_chart_inserts(client):
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    r = client.post("/api/medical_records/P-014/insert", json={
        "kind": "note",
        "title": "Family visit",
        "body": "Spouse at bedside, anxious about discharge plan.",
        "author_name": "Alice Pham",
        "author_initials": "AP",
        "author_role": "student",
    })
    assert r.status_code == 200, r.text
    body_r = r.json()
    assert body_r["ok"] is True
    assert body_r["insert"]["title"] == "Family visit"
    # Encounter dataclass field has the new entry.
    from portal import control_room as _cr
    room = _cr.get_active_room()
    enc = room.encounters[eid]
    assert len(enc.chart_inserts) == 1
    assert enc.chart_inserts[0]["author_role"] == "student"


def test_insert_lab_requires_title(client):
    _start_room(client, n=1)
    r = client.post("/api/medical_records/P-014/insert", json={
        "kind": "lab", "title": "", "body": "WBC 12.3 K/µL",
        "author_role": "instructor",
    })
    assert r.status_code == 400


def test_insert_note_requires_body(client):
    _start_room(client, n=1)
    r = client.post("/api/medical_records/P-014/insert", json={
        "kind": "note", "title": "Title", "body": "",
        "author_role": "instructor",
    })
    assert r.status_code == 400


def test_insert_unknown_kind_400(client):
    _start_room(client, n=1)
    r = client.post("/api/medical_records/P-014/insert", json={
        "kind": "whatever", "title": "x", "body": "y",
        "author_role": "instructor",
    })
    assert r.status_code == 400


def test_insert_unknown_persona_404(client):
    _start_room(client, n=1)
    r = client.post("/api/medical_records/P-bogus/insert", json={
        "kind": "note", "title": "x", "body": "y",
        "author_role": "instructor",
    })
    assert r.status_code == 404


def test_inserts_render_on_chart_view(client):
    """A note added via the API appears on the workstation chart's
    Notes & Updates section."""
    _start_room(client, n=1)
    client.post("/api/medical_records/P-014/insert", json={
        "kind": "doctor_note",
        "title": "Cardiology consult",
        "body": "EF 35%. Add carvedilol 6.25 mg BID; titrate.",
        "author_name": "Dr. Lee",
        "author_initials": "DL",
        "author_role": "instructor",
    })
    from portal import auth
    client.cookies.delete(auth.COOKIE_NAME)
    html = client.get(
        "/students/medical_records/P-014?code=&user=A&initials=AP").text
    assert "Notes &amp; Updates" in html or "Notes & Updates" in html
    assert "Cardiology consult" in html
    assert "Dr. Lee" in html
    assert "DL" in html


def test_inserts_filter_by_persona(client):
    """Inserts attach to a SPECIFIC persona — adding a note to P-014
    must NOT surface on P-003's chart."""
    _start_room(client, n=2)
    client.post("/api/medical_records/P-014/insert", json={
        "kind": "note", "title": "For P-014 only",
        "body": "Patient-specific data",
        "author_role": "instructor",
    })
    from portal import auth
    client.cookies.delete(auth.COOKIE_NAME)
    html_other = client.get(
        "/students/medical_records/P-003?code=&user=A&initials=AP").text
    assert "For P-014 only" not in html_other


# ── 5. Instructor chart view has add-to-chart form ─────────────────

def test_instructor_chart_view_has_add_form(client):
    _start_room(client, n=1)
    html = client.get("/portal/medical_records/P-014").text
    # The operator chart now also has the inline Add-to-chart form.
    assert "Add to chart" in html
    assert "mr-add-form" in html


# ── 6. Nursing Station has Supervisor button ───────────────────────

def test_nurse_station_has_supervisor_button(client):
    _start_room(client, n=1)
    r = client.get("/portal/control/launch_nurse_station",
                   follow_redirects=False)
    assert r.status_code == 303
    nurse_url = r.headers["location"]
    html = client.get(nurse_url).text
    assert 'id="ns-supervisor-btn"' in html
    assert "Open Supervisor Records" in html
    # The prompt for 2 initials.
    assert "2 initials" in html
    # Opens the workstation in role=supervisor mode.
    assert "role=supervisor" in html
