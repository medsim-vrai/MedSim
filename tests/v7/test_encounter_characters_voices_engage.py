"""M33 — Per-Patient Console: persona display names + voice test
button + engage button.

Backend changes verified here:
  - GET /api/encounter/{id}/voices now returns a `personas` array of
    {id, name, role} triples so the JS can label rows by name.
  - The same response includes `join_code` so per-row Engage buttons
    can deep-link to the chat join page.

Front-end changes verified here (by inspecting the template +
encounter_console.js source on disk):
  - The voice card's <h2> is renamed to "Characters · voices · engage".
  - encounter_console.js builds row HTML with the new char-test +
    char-engage controls and the testVoiceForRow() preview path.
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


# ── Backend: API contract for character names + join code ────────────

def test_voices_endpoint_returns_personas_with_name_and_role(client) -> None:
    """GET /api/encounter/{id}/voices must include a `personas`
    array of {id, name, role} so the UI can label rows by name."""
    r = client.post("/api/room/start", json={
        "label": "M33 names",
        "encounters": [{
            "scenario_name": "ED sepsis bed",
            "persona_id": "P-014",
            "patient_persona_id": "P-014",
            "personas": ["P-014", "P-001"],   # patient + one staff
            "ehr_id": "helix",
        }],
    })
    assert r.status_code == 200
    eid = r.json()["encounters"][0]["encounter_id"]

    r = client.get(f"/api/encounter/{eid}/voices")
    assert r.status_code == 200
    body = r.json()
    # Backward-compat keys still present.
    assert body["encounter_id"] == eid
    assert set(body["selected_personas"]) == {"P-014", "P-001"}
    assert body["patient_persona_id"] == "P-014"
    # M33: new `personas` array with id + name + role.
    assert "personas" in body
    by_id = {p["id"]: p for p in body["personas"]}
    assert set(by_id) == {"P-014", "P-001"}
    for p in body["personas"]:
        assert "name" in p and p["name"], (
            f"persona {p['id']} missing display name (got {p!r}). "
            "JS row labels need the name field.")
        assert "role" in p, f"persona {p['id']} missing role field"
    # M33: `join_code` is echoed so the Engage links can deep-link.
    assert "join_code" in body
    assert body["join_code"]


def test_voices_endpoint_defensive_when_persona_missing_from_library(client) -> None:
    """If a persona id sneaks through that isn't in the canonical
    24-persona library, the route echoes the id back as `name` so
    the UI still has something to render — instead of 500-ing."""
    r = client.post("/api/room/start", json={
        "label": "M33 defensive",
        "encounters": [{
            "scenario_name": "Edge case bed",
            "persona_id": "P-014",
            "patient_persona_id": "P-014",
            "personas": ["P-014", "P-99-unknown"],
            "ehr_id": "helix",
        }],
    })
    assert r.status_code == 200
    eid = r.json()["encounters"][0]["encounter_id"]
    r = client.get(f"/api/encounter/{eid}/voices")
    assert r.status_code == 200
    by_id = {p["id"]: p for p in r.json()["personas"]}
    assert by_id["P-99-unknown"]["name"] == "P-99-unknown", (
        "Unknown persona should echo id as name — never 500.")


# ── Frontend: template + JS markers ──────────────────────────────────

def test_voice_card_h2_renamed_to_characters_voices_engage(client) -> None:
    """The voice card heading is now 'Characters · voices · engage'
    — it serves three jobs (list characters, pick voice, engage)."""
    r = client.post("/api/room/start", json={
        "label": "M33 card title",
        "encounters": [{"scenario_name": "Bed 1", "persona_id": "P-014",
                         "patient_persona_id": "P-014", "ehr_id": "helix"}],
    })
    eid = r.json()["encounters"][0]["encounter_id"]
    r = client.get(f"/portal/room/encounter/{eid}")
    assert r.status_code == 200
    html = r.text
    # The new title text must appear in the rendered console.
    assert "Characters · voices · engage" in html, (
        "Voice card <h2> should be renamed to "
        "'Characters · voices · engage' (M33).")


def test_encounter_console_js_renders_name_test_and_engage(client) -> None:
    """The encounter_console.js bundle on disk carries the new render
    paths (char-name span, ▶ Test button, 💬 Engage anchor, and the
    testVoiceForRow() preview function)."""
    js_path = (
        Path(__file__).resolve().parents[2]
        / "portal" / "static" / "encounter_console.js"
    )
    src = js_path.read_text(encoding="utf-8")
    # Row label uses the display name, not the raw persona id alone.
    assert "char-name" in src
    # Per-row buttons.
    assert "char-test" in src and "▶ Test" in src
    assert "char-engage" in src and "💬 Engage" in src
    # Preview function is wired.
    assert "testVoiceForRow" in src
    # Falls back to browser SpeechSynthesis when no voice picked.
    assert "speechSynthesis" in src
    # Calls /api/tts for ElevenLabs preview.
    assert "/api/tts" in src
    # M35: the engage link now targets /portal/engage/{eid}/{pid}
    # (deep-link to the instructor station, bypassing /join).
    assert "/portal/engage/" in src


def test_engage_link_url_serves_join_page(client) -> None:
    """The Engage link points at /join?code={join_code}; verify that
    URL serves a 200 (the public chat join page) so the link doesn't
    dead-end."""
    r = client.post("/api/room/start", json={
        "label": "M33 engage URL",
        "encounters": [{"scenario_name": "Bed 1", "persona_id": "P-014",
                         "patient_persona_id": "P-014", "ehr_id": "helix"}],
    })
    join = r.json()["encounters"][0]["join_code"]
    r = client.get(f"/join?code={join}", follow_redirects=False)
    # Should NOT be a 404; either 200 (page renders) or a redirect to
    # the join flow.
    assert r.status_code in (200, 302, 303, 307, 308), (
        f"/join?code={join} returned {r.status_code}; "
        "the Engage link would dead-end.")
