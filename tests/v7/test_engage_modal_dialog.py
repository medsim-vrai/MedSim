"""M39 — Engage opens in-encounter modal, not a new tab.

The instructor's complaint: clicking Engage on the encounter
console used to spawn a new browser tab (M33+M35 design with
target="_blank"). They want the conversation to happen IN the
encounter window so they don't lose console context.

Fix: replace the `<a target="_blank">` engage anchor with a
`<button>` that opens a modal `<dialog>` containing an iframe
pointed at /portal/engage/{eid}/{pid}. The chat UI renders inside
the dialog; closing the dialog blanks the iframe (stops audio).

These are JS+template guards. The actual modal behavior is best
verified manually in a browser, but we can assert here that the
markup carries the right hooks.
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


def _start_room(client):
    r = client.post("/api/room/start", json={
        "label": "M39 engage modal",
        "encounters": [{
            "scenario_name": "Bed 1",
            "persona_id": "P-014",
            "patient_persona_id": "P-014",
            "personas": ["P-014", "P-001"],
            "ehr_id": "helix",
        }],
    })
    assert r.status_code == 200, r.text
    return r.json()


# ── Template markup ─────────────────────────────────────────────────

def test_encounter_console_includes_engage_dialog_markup(client) -> None:
    """The console must carry the modal <dialog> + iframe + close
    button so the JS can render the chat inside the encounter
    window."""
    encs = _start_room(client)
    eid = encs["encounters"][0]["encounter_id"]
    r = client.get(f"/portal/room/encounter/{eid}")
    assert r.status_code == 200
    html = r.text
    assert 'id="engage-dialog"' in html
    assert 'id="engage-dialog-frame"' in html
    assert 'id="engage-dialog-close"' in html
    assert 'id="engage-dialog-popout"' in html
    # The iframe carries the right allow attributes so mic + audio
    # autoplay work inside it (the chat needs both).
    assert "allow=\"microphone; autoplay\"" in html or \
           "allow='microphone; autoplay'" in html


def test_engage_dialog_starts_with_blank_iframe_src(client) -> None:
    """The iframe must start at about:blank — we set the real src on
    Engage click. Important so the console doesn't try to mount a
    chat session before the operator asks for one (would pre-create
    INST- stations on lazy load, polluting the roster)."""
    encs = _start_room(client)
    eid = encs["encounters"][0]["encounter_id"]
    html = client.get(f"/portal/room/encounter/{eid}").text
    # Locate the iframe and assert its initial src is about:blank.
    idx = html.find('id="engage-dialog-frame"')
    assert idx >= 0
    snippet = html[idx:idx + 400]
    assert 'src="about:blank"' in snippet


# ── JS markers ──────────────────────────────────────────────────────

def test_engage_js_uses_button_and_opens_dialog_not_new_tab() -> None:
    """The Engage element in the voice grid is now a <button>, not
    an <a target="_blank">. The handler calls openEngageDialog()
    which sets the iframe src and shows the modal."""
    js_path = (
        Path(__file__).resolve().parents[2]
        / "portal" / "static" / "encounter_console.js"
    )
    src = js_path.read_text(encoding="utf-8")
    # No more target="_blank" on the engage element.
    # (Find the engageHref usage and assert no target=_blank near it.)
    engage_block = src[src.find("data-engage-href="):
                       src.find("data-engage-href=") + 600]
    assert engage_block, "engage button block not found"
    assert "target=\"_blank\"" not in engage_block, (
        "Engage element must NOT use target=\"_blank\" — M39 design "
        "is in-encounter modal.")
    # The handler function exists.
    assert "function openEngageDialog" in src
    # Click handler is wired.
    assert "openEngageDialog(btn)" in src
    # Dialog show/close uses native <dialog> API with fallback.
    assert "showModal" in src
    assert "dlg.close" in src
    # On close, the iframe src is blanked so audio inside it stops.
    assert "frame.src = 'about:blank'" in src or \
           'frame.src = "about:blank"' in src


def test_engage_dialog_popout_link_uses_engage_href() -> None:
    """The dialog still offers a "↗ Pop out" affordance for instructors
    who do want a separate window. That link's href is set from the
    button's data-engage-href when the dialog opens."""
    js_path = (
        Path(__file__).resolve().parents[2]
        / "portal" / "static" / "encounter_console.js"
    )
    src = js_path.read_text(encoding="utf-8")
    # The popout href is wired to btn.dataset.engageHref inside
    # openEngageDialog.
    fn_idx = src.find("function openEngageDialog")
    assert fn_idx >= 0
    fn_body = src[fn_idx:fn_idx + 800]
    assert "popout.href" in fn_body
    assert "engageHref" in fn_body or "dataset.engageHref" in fn_body


def test_engage_button_carries_required_data_attributes(client) -> None:
    """The rendered button (built client-side by bootVoices) needs
    `data-persona`, `data-persona-name`, and `data-engage-href` so
    the click handler can construct the modal title + iframe src.
    The JS source must show that the row HTML carries these attrs."""
    js_path = (
        Path(__file__).resolve().parents[2]
        / "portal" / "static" / "encounter_console.js"
    )
    src = js_path.read_text(encoding="utf-8")
    # All three attrs are present in the engage button template literal.
    button_block = src[src.find("button type=\"button\" class=\"char-engage\""):
                       src.find("button type=\"button\" class=\"char-engage\"") + 500]
    assert "data-persona=" in button_block
    assert "data-persona-name=" in button_block
    assert "data-engage-href=" in button_block
