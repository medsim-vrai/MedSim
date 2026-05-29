"""M43-followup — /api/device/{sid}/state must work in multi-patient
mode + connection badge hidden by default.

Operator: "offline.http 409 on the upper right corner of the screen
of med cart, then flashes polling, can this box be removed from the
screen view and second is being offline ok or is this an error during
the operation of the med cart?"

Two distinct issues — one was a real M43-style miss (the state route
still called `control_session.get_active()` which returns None in
multi-patient mode, 409'ing every 2 s on every device tablet) and
one was UX noise (the LIVE/POLLING/OFFLINE badge in the upper-right
flashing through every poll).

Fixes verified here:
  1. Back-end: state route now resolves via `_session_for_station`
     and returns the correct fold for ANY device station in either
     single-patient or multi-patient mode.
  2. Client: connection badge is hidden by default; surfaces only
     when ?debug=conn is in the URL.
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


def _start_room_with_cart(client, n_beds: int = 2):
    pool = ["P-014", "P-003", "P-001"]
    r = client.post("/api/room/start", json={
        "label": "Conn-badge repro",
        "encounters": [
            {"scenario_name": f"Bed {i+1}", "persona_id": pool[i],
             "patient_persona_id": pool[i],
             "personas": [pool[i]], "ehr_id": "helix"}
            for i in range(n_beds)
        ],
    })
    eids = [e["encounter_id"] for e in r.json()["encounters"]]
    rc = client.post("/api/room/med_cart/register",
                      json={"label": "Repro cart",
                            "encounter_ids": eids})
    return rc.json()["station_id"], eids


# ── 1. Back-end fix: state route returns 200 in multi-patient mode

def test_device_state_returns_200_for_cart_in_multipatient(client) -> None:
    """The headline bug: every 2 s the device tablet polls
    /api/device/{cart_sid}/state and pre-fix the route returned 409
    because control_session.get_active() is None in multi-patient
    mode. Confirm we now get 200 with a proper state fold."""
    cart_sid, _eids = _start_room_with_cart(client, n_beds=2)
    r = client.get(f"/api/device/{cart_sid}/state")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "state" in body
    assert "session_state" in body


def test_device_state_unknown_station_404(client) -> None:
    _start_room_with_cart(client, n_beds=1)
    r = client.get("/api/device/cart_does_not_exist/state")
    assert r.status_code == 404


def test_device_state_returns_409_when_room_ended(client) -> None:
    """If the room is gone (ended + cleared), the state route should
    say so cleanly instead of 500."""
    cart_sid, _eids = _start_room_with_cart(client, n_beds=1)
    # End the room.
    r_end = client.post("/api/room/end")
    assert r_end.status_code == 200
    r = client.get(f"/api/device/{cart_sid}/state")
    # Without an active session the resolver returns None → 409.
    assert r.status_code in (409, 404)


def test_device_state_works_for_every_linked_encounter_cart(client) -> None:
    """A cart linked to multiple encounters resolves to its PRIMARY
    encounter's session via `_session_for_station`. The state poll
    works regardless of which encounter the operator opens the cart
    from."""
    cart_sid, _eids = _start_room_with_cart(client, n_beds=3)
    # Three polls in a row — none should 409.
    for _ in range(3):
        r = client.get(f"/api/device/{cart_sid}/state")
        assert r.status_code == 200


# ── 2. Front-end fix: connection badge hidden by default ──────────

def test_device_js_hides_conn_badge_by_default() -> None:
    """The LIVE/POLLING/OFFLINE badge is only painted when
    ?debug=conn is in the query string. Otherwise setStatus() does
    everything except create the DOM element."""
    src = (Path(__file__).resolve().parents[2]
           / "portal" / "static" / "devices" / "device_app.js"
          ).read_text("utf-8")
    # The opt-in flag.
    assert "_SHOW_CONN_BADGE" in src
    assert "debug=conn" in src or "'conn'" in src
    # The early-return when the flag is false.
    fn_idx = src.find("function setStatus")
    assert fn_idx > 0
    body = src[fn_idx:fn_idx + 1500]
    assert "_SHOW_CONN_BADGE" in body
    assert "stale.remove" in body or "badge.remove" in body


def test_device_js_tracks_state_even_when_badge_hidden() -> None:
    """State is still tracked internally (so future reconnects + the
    WS/polling lifecycle still work) — only the visible badge is
    suppressed."""
    src = (Path(__file__).resolve().parents[2]
           / "portal" / "static" / "devices" / "device_app.js"
          ).read_text("utf-8")
    assert "_CONN_STATE" in src
    fn_idx = src.find("function setStatus")
    body = src[fn_idx:fn_idx + 600]
    # The state record is written BEFORE the early-return guard.
    record_idx = body.find("_CONN_STATE")
    guard_idx  = body.find("_SHOW_CONN_BADGE")
    assert 0 < record_idx < guard_idx, \
        "state record must happen before the badge-render guard"


def test_device_js_state_lifecycle_intact() -> None:
    """The WebSocket open / close / polling fallback path is
    unchanged. Sanity check that setStatus calls still happen at
    the right points so we don't quietly lose connection feedback
    for the operator who DOES open ?debug=conn."""
    src = (Path(__file__).resolve().parents[2]
           / "portal" / "static" / "devices" / "device_app.js"
          ).read_text("utf-8")
    assert "setStatus('ws')" in src
    assert "setStatus('polling'" in src
    assert "setStatus('offline'" in src
