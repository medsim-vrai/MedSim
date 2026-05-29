"""M44 — Devices modal shows ONLY the device manager + cabinets are
room-level (not encounter-level).

Two parts:

1. The M42 embed-mode CSS used class names that don't actually exist
   in `control_ops.html` (e.g. `.operator-ptt-card` vs the actual
   `.op-ptt-card`). So the modal's iframe still rendered invite-
   stations, connected-stations, session-context, PTT, transcript,
   voices, and EHR-stations cards — making it look like a full
   control room page. M44 rewrites the embed-mode CSS to show only
   the simulated-devices card (`#devices-card`).

2. Med carts (cabinet kind) are a room-level resource. When the
   ops view is opened in embed mode (i.e. from an encounter
   console), the add-device kind dropdown excludes `cabinet`, AND
   the server-side route rejects encounter-scoped POSTs that try
   to mint a cabinet with 409.
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
        "label": "M44 device scope",
        "encounters": [
            {"scenario_name": "Bed 1", "persona_id": "P-014",
             "patient_persona_id": "P-014", "personas": ["P-014"],
             "ehr_id": "helix"},
            {"scenario_name": "Bed 2", "persona_id": "P-003",
             "patient_persona_id": "P-003", "personas": ["P-003"],
             "ehr_id": "helix"},
        ],
    })
    assert r.status_code == 200, r.text
    return r.json()


# ── Embed-mode CSS hides everything except the devices card ─────────

def test_embed_mode_css_hides_all_other_cards(client) -> None:
    """When ?embed=1 is set, the page injects CSS that hides every
    .check-card sibling and only shows #devices-card. Pre-M44 the
    hide list used invented class names so most cards stayed
    visible — the modal looked like the full control room page."""
    body = _start_2enc_room(client)
    join = body["encounters"][0]["join_code"]
    r = client.get(f"/portal/control/ops?join={join}&embed=1")
    assert r.status_code == 200
    html = r.text
    # The devices card now has a stable id.
    assert 'id="devices-card"' in html
    # The embed CSS block hides every .check-card and re-shows only
    # #devices-card. Look for the two key declarations.
    assert "body .check-card { display: none !important; }" in html
    assert "body #devices-card { display: block !important; }" in html
    # And it kills the body padding / max-widths so the card uses
    # the full iframe height/width.
    assert "padding: 0 !important" in html


def test_embed_mode_does_not_apply_in_v6_single_patient_path(client) -> None:
    """`?embed=1` is opt-in. Without it (v6 single-patient ops view),
    the page renders with all cards visible — the CSS injection
    block is conditional on embed_mode."""
    body = _start_2enc_room(client)
    join = body["encounters"][0]["join_code"]
    # Without ?embed=1 the conditional block doesn't render.
    r = client.get(f"/portal/control/ops?join={join}")
    html = r.text
    assert 'id="devices-card"' in html
    assert "body .check-card { display: none !important; }" not in html


# ── Cabinet (med cart) blocked from encounter-scoped register ───────

def test_register_cabinet_rejected_when_encounter_scoped(client) -> None:
    """In multi-patient mode (?join=<encounter join>), the route must
    reject `device_kind=cabinet` with a 409 — med carts live at the
    room level (M45). Test that the bypass-the-dropdown attack is
    rejected server-side."""
    body = _start_2enc_room(client)
    join = body["encounters"][0]["join_code"]
    r = client.post(
        f"/api/device/register?join={join}",
        json={"device_kind": "cabinet", "device_model": "pyxis",
              "label": "Bedside cart"},
    )
    assert r.status_code == 409, r.text
    # Friendly message hints at the room-level alternative.
    assert "Multi-Patient Control" in r.text or "room-level" in r.text


def test_register_pump_iv_still_works_when_encounter_scoped(client) -> None:
    """Pumps + future-device kinds remain creatable per encounter.
    Only `cabinet` is blocked in encounter scope."""
    body = _start_2enc_room(client)
    join = body["encounters"][0]["join_code"]
    r = client.post(
        f"/api/device/register?join={join}",
        json={"device_kind": "pump_iv", "device_model": "alaris",
              "label": "Bed 1 IV"},
    )
    assert r.status_code == 200, r.text


def test_cabinet_block_only_fires_when_join_targets_an_encounter(client) -> None:
    """The cabinet-block branch in `/api/device/register` requires
    BOTH `?join=<code>` AND `sess.id in room.encounters`. So the
    legacy v6 single-patient path (no `?join`) AND the no-active-
    session-at-all path are unaffected by M44.

    We can't easily stand up a v6 singleton inside this fixture
    (the fixture only initializes the v7 vault state). But we CAN
    verify the bounded scope of the new guard: it does NOT fire on
    a missing join, only on a v7-encounter-scoped join. So:

      - With a non-cabinet kind + ?join → 200 (M43 path works).
      - With cabinet + ?join → 409 (the new block).
      - With cabinet + no ?join + no v6 singleton → 409 "no active
        session" (NOT the cabinet block — the session-resolution
        block from M43 fires first).
    """
    _start_2enc_room(client)
    # No `?join`, no v6 singleton (get_active returns None in v7
    # multi-patient) → the route's session-resolution check fires
    # BEFORE the cabinet block. Operator sees the friendly "open
    # from a Per-Patient Console" hint, NOT the cabinet-specific
    # message — confirming the cabinet block is bounded.
    r = client.post(
        "/api/device/register",
        json={"device_kind": "cabinet", "device_model": "pyxis",
              "label": "Bypass attempt"},
    )
    assert r.status_code == 409
    # The session-resolution branch fires; cabinet branch is unreached.
    assert "Per-Patient Console" in r.text or "?join=" in r.text
    # NOT the cabinet-specific message.
    assert "Multi-Patient Control" not in r.text


# ── JS dropdown filters cabinet in embed mode ───────────────────────

def test_devices_js_filters_cabinet_kind_in_embed_mode() -> None:
    """`fillKindSelect` reads `window.MEDSIM2_OPS.embed_mode` and
    excludes the `cabinet` kind from the dropdown when set. Verify
    the source carries the filter."""
    js_path = (
        Path(__file__).resolve().parents[2]
        / "portal" / "static" / "control_ops_devices.js"
    )
    src = js_path.read_text(encoding="utf-8")
    fn_idx = src.find("function fillKindSelect")
    assert fn_idx >= 0
    body = src[fn_idx:fn_idx + 1200]
    # Reads embed_mode flag from bootstrap.
    assert "embed_mode" in body
    # Filters out the cabinet kind.
    assert "'cabinet'" in body or '"cabinet"' in body
    assert "filter" in body
    # Re-labels the help text in embed mode.
    assert "devices-card-kinds-note" in body
    assert "room level" in body or "Multi-Patient Control" in body
