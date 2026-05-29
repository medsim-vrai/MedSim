"""M32 — In Room of N mode, the wizard skips the single-patient
steps (2 Scenario / 2b Records / 3 Curriculum) and lands directly
on Step 4r (per-encounter authoring). Each row's drawers carry
scenario / characters / curriculum authority for that bed.

These tests verify the markup carries the right per-step `data-*`
attributes (the JS reads `data-step-single` / `data-pane-single`
to hide those steps in room mode) and that the new "Room label"
input lives on Step 4r.
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


def test_step_strip_marks_single_only_steps(client) -> None:
    """The step strip's 2 / 2b / 3 / 4 entries carry `data-step-single`
    so the JS knows to hide them in room mode. Step 4r carries
    `data-step-room` (already there from M6)."""
    r = client.get("/portal/control")
    assert r.status_code == 200
    html = r.text
    # Each single-mode step indicator must carry the marker.
    for step_id in ('"2"', '"2b"', '"3"', '"4"'):
        # crude but specific — the markup is "data-step=<id>  data-step-single"
        # on the same div, and the values appear together within ~60 chars.
        idx = html.find(f'data-step={step_id}')
        assert idx >= 0, f"step {step_id} indicator not found in /portal/control"
        snippet = html[idx:idx + 120]
        assert "data-step-single" in snippet, (
            f"step {step_id} indicator is missing data-step-single — "
            "room mode will not hide it. Snippet: " + snippet)
    # Step 4r keeps data-step-room (room-only).
    idx = html.find('data-step="4r"')
    assert idx >= 0
    assert "data-step-room" in html[idx:idx + 120]


def test_single_only_panes_carry_data_pane_single(client) -> None:
    """The Scenario / Records-system / Curriculum panes (2, 2b, 3)
    must carry `data-pane-single` so applyMode() hides them in room
    mode. Step 4r still carries `data-pane-room`."""
    r = client.get("/portal/control")
    assert r.status_code == 200
    html = r.text
    for pane_id in ('"2"', '"2b"', '"3"'):
        idx = html.find(f'data-pane={pane_id}')
        assert idx >= 0, f"pane {pane_id} not found"
        snippet = html[idx:idx + 180]
        assert "data-pane-single" in snippet, (
            f"pane {pane_id} missing data-pane-single — room mode will "
            f"show it. Snippet: {snippet}")
    # 4r keeps room marker, 4 stays unmarked (the room mode pane category
    # only hides single-mode panes; pane 4 only renders when its parent
    # step is in the active sequence anyway).
    idx = html.find('data-pane="4r"')
    assert idx >= 0
    assert "data-pane-room" in html[idx:idx + 180]


def test_step_4r_has_dedicated_room_label_input(client) -> None:
    """In room mode the wizard skips Step 2 (Scenario name), so Step
    4r needs its own Room label input — otherwise there's nowhere
    to type the cohort label."""
    r = client.get("/portal/control")
    assert r.status_code == 200
    html = r.text
    assert 'id="room-label-input"' in html, (
        "Step 4r needs a #room-label-input now that wizard-wide "
        "Step 2 (Scenario) is hidden in room mode.")
    assert 'name="room_label"' in html
    # The room-label input lives on Step 4r — verify by checking the
    # section after the data-pane="4r" marker contains it.
    pane_idx = html.find('data-pane="4r"')
    next_pane_idx = html.find('data-pane=', pane_idx + 1)
    pane_4r = html[pane_idx:next_pane_idx if next_pane_idx > 0 else len(html)]
    assert 'id="room-label-input"' in pane_4r, (
        "room-label-input must live inside the Step 4r pane.")


def test_scenario_name_required_is_conditional(client) -> None:
    """The Step 2 `scenario_name` input keeps its `required` attribute
    for single mode, but is tagged `data-required-single` so the JS
    strips `required` in room mode (otherwise HTML5 validation blocks
    the submit before our JS handler runs)."""
    r = client.get("/portal/control")
    assert r.status_code == 200
    html = r.text
    # Find the scenario_name input and assert both markers are there.
    idx = html.find('name="scenario_name"')
    assert idx >= 0
    # Look in a window before + after the attribute to catch the
    # `required` and `data-required-single` tokens on the same <input>.
    window = html[max(0, idx - 60):idx + 240]
    assert "required" in window
    assert "data-required-single" in window, (
        "scenario_name needs data-required-single so room mode can "
        "strip the required attribute (HTML5 validation otherwise "
        "blocks the room submit).")
