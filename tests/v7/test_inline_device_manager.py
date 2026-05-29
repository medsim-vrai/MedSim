"""M42 — Inline device manager in encounter console.

The v6 ops view (/portal/control/ops) is now usable in v7 multi-
patient mode via `?join=<code>` query param. The encounter console's
Devices card replaces its link-out with a "🔧 Manage devices"
button that opens the ops view in an iframe modal scoped to this
encounter, with the add-device patient persona pre-populated.

Three pieces verified:
1. The ops route accepts `?join=<code>` and resolves the encounter
   even when `control_session.get_active()` returns None (the v7
   multi-encounter contract).
2. The ops route's bootstrap JSON carries `default_device_patient_id`
   from `?patient_persona_id=` query param OR the session's
   patient_persona_id, so the add-device modal pre-fills.
3. The encounter console template/JS carries the modal + button
   hooks that open the iframe.
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
        "label": "M42 devices",
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


# ── Ops route works in multi-patient mode via ?join=… ───────────────

def test_ops_view_loads_via_join_code_in_multi_encounter_room(client) -> None:
    """In v7 multi-patient mode, control_session.get_active() returns
    None — so the OLD ops view redirected to the wizard. M42 wires
    the route to look up by `?join=<code>` first."""
    body = _start_2enc_room(client)
    join = body["encounters"][0]["join_code"]
    r = client.get(f"/portal/control/ops?join={join}",
                   follow_redirects=False)
    assert r.status_code == 200, r.text
    html = r.text
    # Bed 1's join code appears in the page (the ops view's invite QR
    # card uses session.join_code).
    assert join in html


def test_ops_view_with_unknown_join_falls_back_to_wizard(client) -> None:
    """Unknown join code → falls back to get_active() (which is None
    here) → wizard redirect. Same as the no-active-session case."""
    _start_2enc_room(client)
    r = client.get("/portal/control/ops?join=BOGUS-CODE",
                   follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/portal/control"


# ── Bootstrap JSON exposes default_device_patient_id ────────────────

def test_ops_view_bootstrap_pre_fills_patient_persona_from_query(client) -> None:
    """When ?patient_persona_id is passed, the bootstrap JSON carries
    it as `default_device_patient_id` so the add-device modal can
    pre-select that patient."""
    body = _start_2enc_room(client)
    join = body["encounters"][0]["join_code"]
    r = client.get(
        f"/portal/control/ops?join={join}&patient_persona_id=P-014"
    )
    assert r.status_code == 200
    html = r.text
    # The MEDSIM2_OPS bootstrap block exposes it (tojson-quoted).
    assert "default_device_patient_id" in html
    assert '"P-014"' in html


def test_ops_view_bootstrap_falls_back_to_session_primary(client) -> None:
    """Without ?patient_persona_id, the bootstrap defaults to the
    session/encounter's primary patient. So even an instructor who
    opens the ops view manually still gets sensible auto-fill."""
    body = _start_2enc_room(client)
    join = body["encounters"][1]["join_code"]   # Bed 2 → P-003
    r = client.get(f"/portal/control/ops?join={join}")
    assert r.status_code == 200
    html = r.text
    assert "default_device_patient_id" in html
    assert '"P-003"' in html


def test_ops_view_embed_mode_hides_top_header(client) -> None:
    """`?embed=1` injects CSS that hides the v6 ops-view header so
    when iframed inside the encounter console the operator doesn't
    see two stacked headers."""
    body = _start_2enc_room(client)
    join = body["encounters"][0]["join_code"]
    r = client.get(f"/portal/control/ops?join={join}&embed=1")
    html = r.text
    # The bootstrap reports embed_mode = true.
    assert "embed_mode" in html
    # The injected style block hides the topbar.
    assert ".topbar" in html
    assert "display: none" in html


# ── Device-manager JS reads default_device_patient_id ────────────────

def test_device_js_uses_default_patient_on_add_device() -> None:
    """control_ops_devices.js must read
    `window.MEDSIM2_OPS.default_device_patient_id` and pass it to
    `fillCharacterSelect` as the initial selection when opening the
    add-device modal."""
    js_path = (
        Path(__file__).resolve().parents[2]
        / "portal" / "static" / "control_ops_devices.js"
    )
    src = js_path.read_text(encoding="utf-8")
    # Locate openAddDevice.
    fn_idx = src.find("function openAddDevice")
    assert fn_idx >= 0
    body = src[fn_idx:fn_idx + 800]
    # The body must reference the new bootstrap field.
    assert "default_device_patient_id" in body
    # And pass it to fillCharacterSelect (not the hard-coded "").
    assert "fillCharacterSelect($('ad-char'), defaultPatient)" in body


# ── Encounter console: button + modal markup ────────────────────────

def test_encounter_console_renders_manage_devices_button(client) -> None:
    """The Devices card on the encounter console must have the
    'Managed devices' button, NOT the old 'Open v6 ops view' link-out.

    M43 renamed the button label from "Manage devices" →
    "Managed devices" per operator feedback (reads as a panel
    descriptor, not an imperative link-out)."""
    body = _start_2enc_room(client)
    eid = body["encounters"][0]["encounter_id"]
    r = client.get(f"/portal/room/encounter/{eid}")
    assert r.status_code == 200
    html = r.text
    assert 'id="btn-manage-devices"' in html
    assert "Managed devices" in html
    # The old link-out is gone.
    assert "Open v6 ops view" not in html


def test_encounter_console_devices_modal_present(client) -> None:
    """The devices modal markup (dialog + iframe + close + popout)
    is in the console template."""
    body = _start_2enc_room(client)
    eid = body["encounters"][0]["encounter_id"]
    html = client.get(f"/portal/room/encounter/{eid}").text
    assert 'id="devices-dialog"' in html
    assert 'id="devices-dialog-frame"' in html
    assert 'id="devices-dialog-close"' in html
    assert 'id="devices-dialog-popout"' in html
    # The iframe initially points at about:blank (no eager preload).
    idx = html.find('id="devices-dialog-frame"')
    snippet = html[idx:idx + 300]
    assert 'src="about:blank"' in snippet


def test_devices_dialog_popout_href_is_scoped_to_encounter(client) -> None:
    """Pop-out link is rendered server-side with the encounter's
    join code + patient persona ready, so the second-monitor
    workflow gets the same scope as the modal iframe."""
    body = _start_2enc_room(client)
    eid = body["encounters"][0]["encounter_id"]
    join = body["encounters"][0]["join_code"]
    html = client.get(f"/portal/room/encounter/{eid}").text
    # Popout anchor carries the join code + patient persona in the href.
    assert f"join={join}" in html
    assert "patient_persona_id=P-014" in html


def test_encounter_console_js_wires_manage_devices_button() -> None:
    """encounter_console.js binds the button to opening the modal
    with the ops-view iframe URL (join + embed=1)."""
    js_path = (
        Path(__file__).resolve().parents[2]
        / "portal" / "static" / "encounter_console.js"
    )
    src = js_path.read_text(encoding="utf-8")
    # The button id is wired.
    assert "btn-manage-devices" in src
    # The iframe src is built with join + embed=1.
    # We're loose here — any form that includes both tokens passes.
    assert "embed" in src and "join" in src
    # The frame is blanked on close (same audio/cleanup pattern as M39).
    fn_block = src[src.find("btn-manage-devices"):
                    src.find("btn-manage-devices") + 2000]
    assert "frame.src = 'about:blank'" in fn_block or \
           'frame.src = "about:blank"' in fn_block
    assert "showModal" in fn_block
