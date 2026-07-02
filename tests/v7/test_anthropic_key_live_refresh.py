"""M38 — Anthropic key live-refresh on station-turn + friendlier 401.

Three behaviors verified here:

1. /api/room/start fails fast (400) when the operator has no
   ANTHROPIC_API_KEY in vault. Prevents the "filler plays, then 401
   in chat" experience that prompted this fix.

2. /api/room/start seeds the process-wide `_anthropic_runtime_key`
   cache so station-turn routes can resolve the key without re-
   reading vault (stations carry no operator cookie).

3. The station-turn route's `_resolve_anthropic_key` prefers the
   cache over the snapshot stamped on the encounter — so a
   /portal/credentials update propagates to live encounters
   without a room restart.

4. Chat-side error messages from a 401 are friendly + actionable
   (point the operator at /portal/credentials).
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
    # M38 — reset the Anthropic runtime-key cache between tests so each
    # case starts clean.
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
        # admin seat — /portal/credentials is admin-gated as of task #94
        c.cookies.set(auth.COOKIE_NAME, auth.issue_session_token(vault, role="admin"))
        yield c
    control_room._reset_for_tests()


# ── Fail-fast at room start when no Anthropic key ───────────────────

def test_room_start_400s_when_no_anthropic_key_in_vault(client) -> None:
    """If the operator forgot to set ANTHROPIC_API_KEY, /api/room/start
    must fail fast with a 400 + clear message, rather than creating
    encounters that will 401 on every turn."""
    # Reach into auth._active_vaults to delete on the *exact* Vault
    # object the route's `require_vault` dependency will return. The
    # module-level _active_vaults map accumulates across tests, so
    # look up by THIS test's cookie token (not "first vault").
    from portal import auth as _auth
    token = client.cookies.get(_auth.COOKIE_NAME)
    assert token, "fixture should have set the session cookie"
    live_vault = _auth._active_vaults[token]
    live_vault.delete("ANTHROPIC_API_KEY")
    r = client.post("/api/room/start", json={
        "label": "M38 missing key",
        "encounters": [{"scenario_name": "Bed 1", "persona_id": "P-014",
                         "patient_persona_id": "P-014", "ehr_id": "helix"}],
    })
    assert r.status_code == 400, r.text
    # Message points the operator at /portal/credentials.
    assert "/portal/credentials" in r.text or "credentials" in r.text.lower()


def test_room_start_seeds_anthropic_runtime_cache(client) -> None:
    """When /api/room/start runs with a valid vault key, the process-
    wide cache is populated so station-turn routes can resolve it."""
    from portal import server as server_mod
    r = client.post("/api/room/start", json={
        "label": "M38 cache seed",
        "encounters": [{"scenario_name": "Bed 1", "persona_id": "P-014",
                         "patient_persona_id": "P-014", "ehr_id": "helix"}],
    })
    assert r.status_code == 200, r.text
    assert server_mod._anthropic_runtime_key == "sk-ant-dummy"


# ── Credentials update refreshes the cache live ─────────────────────

def test_credentials_post_refreshes_anthropic_runtime_cache(client) -> None:
    """Updating ANTHROPIC_API_KEY at /portal/credentials must refresh
    the cache so live rooms pick up the new key on the next station
    turn — no restart required."""
    from portal import server as server_mod
    # Initial state: fixture set sk-ant-dummy + we seed by starting a room.
    client.post("/api/room/start", json={
        "label": "M38",
        "encounters": [{"scenario_name": "Bed 1", "persona_id": "P-014",
                         "patient_persona_id": "P-014", "ehr_id": "helix"}],
    })
    assert server_mod._anthropic_runtime_key == "sk-ant-dummy"
    # Now post a new key via the credentials form.
    r = client.post("/portal/credentials", data={
        "key": "ANTHROPIC_API_KEY",
        "value": "sk-ant-NEW-rotated",
    }, follow_redirects=False)
    assert r.status_code in (200, 303)
    # Cache reflects the new key without a server restart.
    assert server_mod._anthropic_runtime_key == "sk-ant-NEW-rotated"


# ── _resolve_anthropic_key picks the cache over sess snapshot ───────

def test_resolve_anthropic_key_prefers_runtime_cache_over_snapshot(
    client,
) -> None:
    """The helper that station-turn routes use must prefer the cache
    over the encounter's snapshot — that's what makes a credentials
    update propagate to a live room."""
    from portal import server as server_mod, control_room as cr
    r = client.post("/api/room/start", json={
        "label": "M38 prefer cache",
        "encounters": [{"scenario_name": "Bed 1", "persona_id": "P-014",
                         "patient_persona_id": "P-014", "ehr_id": "helix"}],
    })
    eid = r.json()["encounters"][0]["encounter_id"]
    enc = cr.get_active_room().encounters[eid]
    # Encounter has the original (snapshot) key.
    assert enc.api_key == "sk-ant-dummy"
    # Rotate via cache update.
    server_mod._capture_anthropic_key("sk-ant-LIVE-rotated")
    # _resolve_anthropic_key now returns the cache value.
    assert server_mod._resolve_anthropic_key(enc) == "sk-ant-LIVE-rotated"


def test_resolve_anthropic_key_falls_back_to_session_snapshot(client) -> None:
    """When the cache is empty (e.g. fresh process, no operator route
    has touched the vault yet), the helper falls back to the
    encounter's snapshot. Prevents False from the cache becoming a
    hard-fail."""
    from portal import server as server_mod, control_room as cr
    r = client.post("/api/room/start", json={
        "label": "M38 fallback",
        "encounters": [{"scenario_name": "Bed 1", "persona_id": "P-014",
                         "patient_persona_id": "P-014", "ehr_id": "helix"}],
    })
    eid = r.json()["encounters"][0]["encounter_id"]
    enc = cr.get_active_room().encounters[eid]
    # Force the cache empty.
    server_mod._anthropic_runtime_key = ""
    # Helper returns the snapshot.
    assert server_mod._resolve_anthropic_key(enc) == "sk-ant-dummy"


def test_capture_does_not_overwrite_cache_with_empty(client) -> None:
    """`_capture_anthropic_key("")` must not wipe a previously-cached
    non-empty value — protects against accidental clears (e.g. a
    credentials POST that *deletes* the key shouldn't blank the
    cache used by live rooms)."""
    from portal import server as server_mod
    server_mod._capture_anthropic_key("sk-ant-keep")
    server_mod._capture_anthropic_key("")
    assert server_mod._anthropic_runtime_key == "sk-ant-keep"
    server_mod._capture_anthropic_key("   ")
    assert server_mod._anthropic_runtime_key == "sk-ant-keep"


# ── Station-turn route surfaces friendly 401 ────────────────────────

def test_station_turn_returns_friendly_message_when_no_key(
    client, monkeypatch,
) -> None:
    """If somehow the cache + snapshot are both empty when a station
    turn arrives, the response must point the operator at
    /portal/credentials — not raise."""
    from portal import server as server_mod, control_room as cr
    r = client.post("/api/room/start", json={
        "label": "M38 friendly 401",
        "encounters": [{"scenario_name": "Bed 1", "persona_id": "P-014",
                         "patient_persona_id": "P-014",
                         "personas": ["P-014"],  # M35 engage checks this list
                         "ehr_id": "helix"}],
    })
    encs = r.json()["encounters"]
    join = encs[0]["join_code"]
    # Use the M35 engage flow to register an INST- station.
    r = client.get(
        f"/portal/engage/{encs[0]['encounter_id']}/P-014",
        follow_redirects=False,
    )
    assert r.status_code == 303
    # Now scrub both the runtime cache AND the encounter snapshot.
    server_mod._anthropic_runtime_key = ""
    room = cr.get_active_room()
    room.encounters[encs[0]["encounter_id"]].api_key = ""
    # Station turn — must NOT raise, must return a friendly error.
    r = client.post(
        f"/api/station/{join}/INST-P-014/turn",
        data={"message": "Hello, how are you feeling?"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    assert "/portal/credentials" in body["error"]
