"""M53 — Lead student / group / list assignment from Multi-Patient
Control.

Operator: "Lead student needs to be able to add the name of the lead
student, the name of a group, a list of students or the name of a
single student to assign to a specific encounter or in several
encounters. this may be more effective to locate in the Multi-patient
control and then list the lead in the encounter or encounters as a
reference for the instructor."

Delivered:
  1. New `Encounter.lead_label: str` free-text field (default "").
  2. POST /api/encounter/{eid}/lead_label — set one bed.
  3. POST /api/room/lead_assignments — bulk apply one label to N beds.
  4. GET  /api/room/lead_assignments — read every bed's current label.
  5. /api/room/state surfaces `lead_label` + `effective_lead_display`
     on each encounter row.
  6. Multi-Patient Control template pre-renders one row per encounter
     with checkbox + free-text input + Apply/Clear buttons + a bulk
     "Apply to checked encounters" action.
  7. Encounter console renders the label as a read-only reference
     banner (no edit there — the operator types it on the dashboard).
  8. M30 roster-picked lead is preserved — both fields can coexist;
     M53 label wins for display when set.
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


def _start_room(client, n: int = 3):
    r = client.post("/api/room/start", json={
        "label": "M53",
        "encounters": [
            {"scenario_name": f"Bed {i+1}", "persona_id": f"P-{i+1:03d}",
             "patient_persona_id": f"P-{i+1:03d}", "ehr_id": "helix"}
            for i in range(n)
        ],
    })
    assert r.status_code == 200
    return r.json()


# ── 1. Dataclass field default ─────────────────────────────────────

def test_encounter_lead_label_defaults_empty() -> None:
    """A fresh Encounter dataclass starts with lead_label=''."""
    from portal.control_session import ControlSession
    enc = ControlSession(
        id="enc_x", join_code="ABC123",
        scenario_name="Test", api_key="",
    )
    assert hasattr(enc, "lead_label")
    assert enc.lead_label == ""


# ── 2. Single-encounter POST ───────────────────────────────────────

def test_set_lead_label_for_one_encounter(client) -> None:
    body = _start_room(client, n=2)
    eid = body["encounters"][0]["encounter_id"]
    r = client.post(
        f"/api/encounter/{eid}/lead_label",
        json={"lead_label": "Alice Pham"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["lead_label"] == "Alice Pham"
    # State poll surfaces it.
    state = client.get("/api/room/state").json()
    bed = next(e for e in state["encounters"] if e["encounter_id"] == eid)
    assert bed["lead_label"] == "Alice Pham"
    assert bed["effective_lead_display"] == "Alice Pham"


def test_set_lead_label_trims_whitespace(client) -> None:
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    r = client.post(
        f"/api/encounter/{eid}/lead_label",
        json={"lead_label": "  Team Alpha  "},
    )
    assert r.status_code == 200
    assert r.json()["lead_label"] == "Team Alpha"


def test_clear_lead_label_with_empty_string(client) -> None:
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    client.post(f"/api/encounter/{eid}/lead_label",
                 json={"lead_label": "Bob"})
    r = client.post(f"/api/encounter/{eid}/lead_label",
                     json={"lead_label": ""})
    assert r.status_code == 200
    assert r.json()["lead_label"] == ""


def test_set_lead_label_unknown_encounter_404(client) -> None:
    _start_room(client, n=1)
    r = client.post("/api/encounter/enc_bogus/lead_label",
                     json={"lead_label": "Alice"})
    assert r.status_code == 404


# ── 3. Bulk multi-encounter POST ───────────────────────────────────

def test_bulk_assign_label_to_multiple_encounters(client) -> None:
    """The headline operator ask — type 'Team Alpha' once, apply to
    three beds at once."""
    body = _start_room(client, n=3)
    eids = [e["encounter_id"] for e in body["encounters"]]
    r = client.post(
        "/api/room/lead_assignments",
        json={"assignments": [
            {"encounter_ids": eids, "lead_label": "Team Alpha"},
        ]},
    )
    assert r.status_code == 200, r.text
    body_r = r.json()
    assert body_r["ok"] is True
    assert len(body_r["applied"]) == 3
    # Each encounter's row now carries the label.
    state = client.get("/api/room/state").json()
    for bed in state["encounters"]:
        assert bed["lead_label"] == "Team Alpha"


def test_bulk_assign_different_labels_per_group(client) -> None:
    """One bulk POST can carry multiple assignments — 'Team Alpha' to
    bed 1, 'Team Bravo' to bed 2."""
    body = _start_room(client, n=2)
    e1 = body["encounters"][0]["encounter_id"]
    e2 = body["encounters"][1]["encounter_id"]
    r = client.post(
        "/api/room/lead_assignments",
        json={"assignments": [
            {"encounter_ids": [e1], "lead_label": "Team Alpha"},
            {"encounter_ids": [e2], "lead_label": "Team Bravo"},
        ]},
    )
    assert r.status_code == 200
    rows = client.get("/api/room/lead_assignments").json()["encounters"]
    by_id = {r["encounter_id"]: r for r in rows}
    assert by_id[e1]["lead_label"] == "Team Alpha"
    assert by_id[e2]["lead_label"] == "Team Bravo"


def test_bulk_assign_list_of_students(client) -> None:
    """A comma-separated student list is just a string — no parsing,
    no validation. Operator's words land verbatim."""
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    r = client.post(
        "/api/room/lead_assignments",
        json={"assignments": [
            {"encounter_ids": [eid],
             "lead_label": "Alice Pham, Bob Chen, Charlie Davis"},
        ]},
    )
    assert r.status_code == 200
    rows = client.get("/api/room/lead_assignments").json()["encounters"]
    assert rows[0]["lead_label"] == "Alice Pham, Bob Chen, Charlie Davis"


def test_bulk_assign_unknown_ids_are_reported_not_500(client) -> None:
    """Mixing a known and unknown encounter id should NOT 500 — the
    known one applies, the unknown one shows up in `unknown` so the
    UI can warn."""
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    r = client.post(
        "/api/room/lead_assignments",
        json={"assignments": [
            {"encounter_ids": [eid, "enc_bogus"], "lead_label": "X"},
        ]},
    )
    assert r.status_code == 200
    body_r = r.json()
    assert len(body_r["applied"]) == 1
    assert "enc_bogus" in body_r["unknown"]


def test_bulk_assign_empty_string_clears(client) -> None:
    """Empty label in a bulk apply clears every listed bed's label."""
    body = _start_room(client, n=2)
    eids = [e["encounter_id"] for e in body["encounters"]]
    client.post("/api/room/lead_assignments",
                 json={"assignments": [
                     {"encounter_ids": eids, "lead_label": "Team"},
                 ]})
    r = client.post("/api/room/lead_assignments",
                     json={"assignments": [
                         {"encounter_ids": eids, "lead_label": ""},
                     ]})
    assert r.status_code == 200
    rows = client.get("/api/room/lead_assignments").json()["encounters"]
    for row in rows:
        assert row["lead_label"] == ""


# ── 4. GET endpoint shape ──────────────────────────────────────────

def test_get_lead_assignments_lists_every_encounter(client) -> None:
    body = _start_room(client, n=3)
    eids = sorted(e["encounter_id"] for e in body["encounters"])
    rows = client.get("/api/room/lead_assignments").json()["encounters"]
    assert sorted(r["encounter_id"] for r in rows) == eids
    # Every row has the required shape.
    for row in rows:
        assert "lead_label" in row
        assert "effective_lead_display" in row
        assert "encounter_label" in row
        assert "lead_student_id" in row


# ── 5. M30 roster lead + M53 label can coexist ─────────────────────

def test_lead_label_takes_priority_over_roster_pick(client) -> None:
    """Both set: M53 free-text wins for `effective_lead_display`."""
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    # Register a student so we have a roster-picked lead to use.
    from portal import control_room as _cr
    room = _cr.get_active_room()
    student = room.add_student("Roster Bob", role="bedside")
    # Set M30 lead.
    r = client.post(f"/api/encounter/{eid}/lead_student",
                     json={"lead_student_id": student.student_id})
    assert r.status_code == 200, r.text
    # Set M53 label.
    client.post(f"/api/encounter/{eid}/lead_label",
                 json={"lead_label": "Team Alpha"})
    state = client.get("/api/room/state").json()
    bed = next(e for e in state["encounters"] if e["encounter_id"] == eid)
    assert bed["lead_student_name"] == "Roster Bob"
    assert bed["lead_label"] == "Team Alpha"
    # M53 wins for display.
    assert bed["effective_lead_display"] == "Team Alpha"


def test_effective_display_falls_back_to_roster_when_label_blank(client) -> None:
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    from portal import control_room as _cr
    room = _cr.get_active_room()
    student = room.add_student("Roster Bob", role="bedside")
    client.post(f"/api/encounter/{eid}/lead_student",
                 json={"lead_student_id": student.student_id})
    # No M53 label set.
    state = client.get("/api/room/state").json()
    bed = next(e for e in state["encounters"] if e["encounter_id"] == eid)
    assert bed["effective_lead_display"] == "Roster Bob"


# ── 6. Multi-Patient Control template renders the panel ────────────

def test_control_room_renders_lead_assign_panel(client) -> None:
    """When a room is active the dashboard pre-renders one
    `.lead-assign-row` per encounter so the inputs are visible on
    first paint."""
    body = _start_room(client, n=3)
    r = client.get("/portal/room")
    assert r.status_code == 200
    html = r.text
    assert 'id="lead-assign-panel"' in html
    assert "👤 Lead assignments" in html
    # One row per encounter.
    for enc in body["encounters"]:
        eid = enc["encounter_id"]
        assert f'data-encounter-id="{eid}"' in html
    assert html.count("lead-assign-row") >= 3
    # Bulk apply controls present.
    assert 'id="lead-bulk-input"' in html
    assert 'id="lead-bulk-apply"' in html


def test_control_room_panel_prefills_existing_labels(client) -> None:
    body = _start_room(client, n=2)
    e1 = body["encounters"][0]["encounter_id"]
    client.post(f"/api/encounter/{e1}/lead_label",
                 json={"lead_label": "Team Alpha"})
    html = client.get("/portal/room").text
    # The input for e1 should be pre-filled with the label.
    # Search for the input element that carries e1 and check value=.
    idx = html.find(f'class="lead-assign-input"\n             data-encounter-id="{e1}"')
    assert idx >= 0
    window = html[idx:idx + 500]
    assert 'value="Team Alpha"' in window


def test_control_room_panel_hidden_when_no_room(client) -> None:
    """If no room is active the panel doesn't render — the operator
    needs encounters before they can pick leads."""
    html = client.get("/portal/room").text
    assert 'id="lead-assign-panel"' not in html


# ── 7. Encounter console — read-only reference banner ──────────────

def test_encounter_console_carries_lead_label_ref_markup() -> None:
    """The per-encounter Lead-student card hosts a hidden banner that
    shows the M53 label when set."""
    p = (Path(__file__).resolve().parents[2]
         / "portal" / "templates" / "encounter_console.html")
    src = p.read_text(encoding="utf-8")
    assert 'id="lead-label-ref"' in src
    assert 'id="lead-label-ref-text"' in src
    assert "set from Multi-Patient Control" in src


def test_encounter_console_js_consumes_lead_label() -> None:
    """The JS state-poll reads `enc.lead_label` and calls a helper to
    show/hide the banner."""
    p = (Path(__file__).resolve().parents[2]
         / "portal" / "static" / "encounter_console.js")
    src = p.read_text(encoding="utf-8")
    assert "lead_label" in src
    assert "_updateLeadLabelRef" in src
    # The helper must hide the banner when the label is empty.
    fn_idx = src.find("function _updateLeadLabelRef")
    assert fn_idx > 0
    body = src[fn_idx:fn_idx + 600]
    assert "ref.hidden" in body


def test_control_room_js_has_lead_assignments_handlers() -> None:
    p = (Path(__file__).resolve().parents[2]
         / "portal" / "static" / "control_room.js")
    src = p.read_text(encoding="utf-8")
    assert "wireLeadAssignments" in src
    # Single-encounter Apply route + bulk route.
    assert "/lead_label" in src
    assert "/api/room/lead_assignments" in src
    # Check-all toggle.
    assert "lead-bulk-checkall" in src


# ── 8. M53 bugfix — header pill + SSR ──────────────────────────────

def test_encounter_page_renders_lead_label_in_header_ssr(client) -> None:
    """Operator-reported bug: "The assigned Leads are not showing on
    the encounter". Root cause: the M53 label only populated via JS
    state poll (~2 s lag) and lived in a buried card. Fix: render
    server-side in the prominent header pill so the lead is visible
    on first paint without waiting for the poll."""
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    # Apply a label on Multi-Patient Control.
    client.post(f"/api/encounter/{eid}/lead_label",
                 json={"lead_label": "Team Alpha"})
    # Load the encounter page — label must appear in the SSR HTML.
    r = client.get(f"/portal/room/encounter/{eid}")
    assert r.status_code == 200
    html = r.text
    # Header pill (next to encounter title) must NOT be hidden and
    # must carry the label.
    idx = html.find('id="lead-student-banner"')
    assert idx > 0
    window = html[idx:idx + 200]
    assert "hidden" not in window
    assert "Team Alpha" in window


def test_encounter_page_renders_lead_label_in_card_ssr(client) -> None:
    """Same fix on the lead-student card banner."""
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    client.post(f"/api/encounter/{eid}/lead_label",
                 json={"lead_label": "Alice, Bob, Charlie"})
    html = client.get(f"/portal/room/encounter/{eid}").text
    # M57 — bound the window to just the banner's own attributes so
    # the empty-state hint (which lives in the same card and IS
    # hidden when a label is set) doesn't get scooped into the
    # `"hidden" not in window` check.
    idx = html.find('id="lead-label-ref"')
    end = html.find('>', idx)
    assert idx > 0 and end > idx
    banner_open = html[idx:end + 1]
    assert "hidden" not in banner_open
    # Label text is rendered inside the banner.
    span_idx = html.find('id="lead-label-ref-text"', idx)
    span_end = html.find('</span>', span_idx)
    assert span_idx > 0 and span_end > span_idx
    assert "Alice, Bob, Charlie" in html[span_idx:span_end]


def test_encounter_page_hides_header_pill_when_no_lead(client) -> None:
    """No lead set → header pill stays hidden so it doesn't show a
    confusing empty "Lead: " label."""
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    html = client.get(f"/portal/room/encounter/{eid}").text
    idx = html.find('id="lead-student-banner"')
    assert idx > 0
    window = html[idx:idx + 200]
    assert "hidden" in window


def test_encounter_js_updates_header_pill_on_state_poll() -> None:
    """The JS `_updateLeadLabelRef` helper must update BOTH the card
    banner AND the header pill so live label changes propagate
    everywhere. M57 — the empty-state hint is also toggled."""
    p = (Path(__file__).resolve().parents[2]
         / "portal" / "static" / "encounter_console.js")
    src = p.read_text(encoding="utf-8")
    fn_idx = src.find("function _updateLeadLabelRef")
    assert fn_idx > 0
    body = src[fn_idx:fn_idx + 2000]
    # Touches the card banner, the header pill, AND the new empty-
    # state hint added in M57.
    assert "lead-label-ref-text" in body
    assert "lead-student-banner" in body
    assert "lead-student-name"   in body
    assert "lead-empty-hint"     in body
    # M57 — the dataset.rosterName fallback path was removed along
    # with the M30 picker. Make sure it really is gone (so we don't
    # quietly regress when someone touches this function later).
    assert "rosterName" not in body


# ── 9. M53 bugfix #2 — Bulk Apply smart fallback + per-row auto-save

def test_bulk_assign_with_empty_label_unset_skips_unknown_personas(
    client) -> None:
    """The bulk-apply route accepts multiple assignment entries with
    different labels — that's what the JS smart-fallback POSTs when
    the operator typed different labels into multiple rows."""
    body = _start_room(client, n=3)
    e1, e2, e3 = [e["encounter_id"] for e in body["encounters"]]
    # Mimic the JS smart-fallback shape: per-row labels grouped by
    # label, multiple assignments in one POST.
    r = client.post(
        "/api/room/lead_assignments",
        json={"assignments": [
            {"encounter_ids": [e1], "lead_label": "Alice"},
            {"encounter_ids": [e2], "lead_label": "Bob"},
            {"encounter_ids": [e3], "lead_label": "Carol"},
        ]},
    )
    assert r.status_code == 200
    rows = client.get("/api/room/lead_assignments").json()["encounters"]
    by_id = {r["encounter_id"]: r for r in rows}
    assert by_id[e1]["lead_label"] == "Alice"
    assert by_id[e2]["lead_label"] == "Bob"
    assert by_id[e3]["lead_label"] == "Carol"


def test_control_room_js_bulk_apply_has_smart_fallback() -> None:
    """The bulk-apply handler must (a) skip rows with empty inputs
    when bulk input is empty, (b) NOT auto-clear the bulk input on
    success."""
    p = (Path(__file__).resolve().parents[2]
         / "portal" / "static" / "control_room.js")
    src = p.read_text(encoding="utf-8")
    # The smart-fallback branch is the one that groups by label.
    assert "byLabel" in src
    # Helpful empty-state error message instead of silently wiping.
    assert "nothing to apply" in src
    # The pre-fix bug was: blindly write bulkLabel to every checked
    # row. The fix keeps that behaviour ONLY when bulkLabel has text.
    assert "if (bulkLabel)" in src
    # After success the bulk input is NOT cleared — operator may want
    # to re-apply.
    assert "Intentionally NOT clearing the bulk input" in src


def test_control_room_js_per_row_auto_save() -> None:
    """Per-row inputs auto-save on Enter and on blur so the operator
    doesn't have to find the tiny per-row Apply button."""
    p = (Path(__file__).resolve().parents[2]
         / "portal" / "static" / "control_room.js")
    src = p.read_text(encoding="utf-8")
    # Helper extracted so per-row Apply + Enter + blur all share it.
    assert "_saveRowLabel" in src
    # The auto-save listeners.
    assert "input.addEventListener('keydown'" in src
    assert "input.addEventListener('blur'" in src
    # And the no-op guard via dataset.saved so blur after page load
    # doesn't re-POST the unchanged value.
    assert "dataset.saved" in src


def test_control_room_panel_hint_mentions_both_workflows(client) -> None:
    """The panel's helper text must explain the per-row Enter / blur
    auto-save AND the bulk-apply workflow so the operator doesn't
    mix them up the way the bug report did."""
    _start_room(client, n=1)
    html = client.get("/portal/room").text
    # Two workflows called out by name.
    assert "Per row:" in html
    assert "Bulk:" in html
    # The Enter keyboard hint is explicit.
    assert "Enter" in html


# ── 10. M57 — Strip dead M30 lead-picker UI ────────────────────────

def test_encounter_console_has_no_lead_picker(client) -> None:
    """Operator: "remove the other parts in the leads area since
    they add no value … Lead (roster) and the listing pull down."
    The roster `<select>` + the explanatory paragraph + the status
    `<p>` are gone from the lead-student card."""
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    html = client.get(f"/portal/room/encounter/{eid}").text
    assert 'id="lead-student-picker"' not in html
    assert 'id="lead-student-status"' not in html
    # The "Lead (roster)" label is gone.
    assert "Lead (roster)" not in html
    # The long paragraph that started with "Assign one bedside
    # student…" is gone.
    assert "Assign one bedside student" not in html
    assert "Surfaces in the cohort debrief" not in html


def test_encounter_console_renders_empty_state_hint_when_no_lead(client) -> None:
    """With no lead label set, an empty-state hint pointing the
    operator at Multi-Patient Control is shown so the card isn't
    visually empty after the picker removal."""
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    html = client.get(f"/portal/room/encounter/{eid}").text
    idx = html.find('id="lead-empty-hint"')
    assert idx > 0
    end = html.find('>', idx)
    hint_open = html[idx:end + 1]
    assert "hidden" not in hint_open   # visible because no label set


def test_encounter_console_hides_empty_state_hint_when_lead_set(client) -> None:
    """Conversely, setting a label hides the empty-state hint at
    SSR time."""
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    client.post(f"/api/encounter/{eid}/lead_label",
                 json={"lead_label": "Team Alpha"})
    html = client.get(f"/portal/room/encounter/{eid}").text
    idx = html.find('id="lead-empty-hint"')
    assert idx > 0
    end = html.find('>', idx)
    hint_open = html[idx:end + 1]
    assert "hidden" in hint_open


def test_encounter_console_js_bootleadstudent_is_a_no_op() -> None:
    """The boot call is preserved (still wired in DOMContentLoaded)
    but the body should be a stub. No `lead-student-picker` DOM
    touches, no fetch to /lead_student."""
    src = (Path(__file__).resolve().parents[2]
           / "portal" / "static" / "encounter_console.js").read_text("utf-8")
    fn_idx = src.find("async function bootLeadStudent")
    assert fn_idx > 0
    body = src[fn_idx:fn_idx + 300]
    # No DOM touches on the now-removed picker.
    assert "lead-student-picker" not in body
    assert "lead-student-status" not in body
    # The roster fetch is gone too.
    assert "/lead_student" not in body
    # `updateLeadBanner` helper is also gone module-wide.
    assert "function updateLeadBanner" not in src
