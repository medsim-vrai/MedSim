"""M9 acceptance — unknown room codes are handled cleanly.

The student-join page is public, so it must tolerate:
  - missing ``?code=`` query string
  - typo'd or stale codes (operator ended the room already)
  - lower-case input (we upper it before lookup)

In every error case the page renders an error state with a re-entry
form rather than redirecting. The POST endpoint 404s on bad codes.
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
    )
    sandbox_vault_dir = fake_home / ".medsim"
    sandbox_vault_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(credentials, "VAULT_DIR", sandbox_vault_dir)
    monkeypatch.setattr(credentials, "VAULT_PATH",
                         sandbox_vault_dir / "vault.enc")
    monkeypatch.setattr(_voices, "KEYFILE", tmp_path / "no-such.key")
    monkeypatch.setattr(_voices, "_runtime_key", "")
    control_room._reset_for_tests()

    if not credentials.is_initialized():
        credentials.initialize(TEST_PASSWORD)
    vault = credentials.unlock(TEST_PASSWORD)
    vault.set("ANTHROPIC_API_KEY", "sk-ant-dummy")
    vault.set("ELEVENLABS_API_KEY", "")

    from portal import server
    from fastapi.testclient import TestClient
    c = TestClient(server.app)
    c.cookies.set(auth.COOKIE_NAME, auth.issue_session_token(vault))
    yield c
    control_room._reset_for_tests()


def test_join_page_with_no_code_renders_error_form(client) -> None:
    r = client.get("/portal/students/join")
    assert r.status_code == 200, r.text
    html = r.text
    assert "Room not found" in html or "Re-scan the QR" in html
    # The re-entry form should be present (so a student can type a code).
    assert 'action="/portal/students/join"' in html


def test_join_page_with_unknown_code_renders_error_form(client) -> None:
    """No active room → any code is unknown."""
    r = client.get("/portal/students/join?code=NOSUCH")
    assert r.status_code == 200, r.text
    assert "Room not found" in r.text
    # The page should NOT render encounter cards — there are none to show.
    assert "encounter-card" not in r.text


def test_join_page_with_stale_code_after_active_room_changes(client) -> None:
    """Operator starts room A, hands out its code, then ends A and
    starts room B. A scan of A's old code must error cleanly without
    leaking into room B."""
    from portal import control_room

    # Room A.
    r = client.post("/api/room/start", json={
        "label": "Room A", "encounters": [
            {"scenario_name": "Bed 1", "persona_id": "P-001", "ehr_id": "helix"},
        ],
    })
    assert r.status_code == 200
    old_code = control_room.get_active_room().room_code

    # End room A. Start room B with a different (likely) code.
    client.post("/api/room/end")
    r = client.post("/api/room/start", json={
        "label": "Room B", "encounters": [
            {"scenario_name": "Bed 1", "persona_id": "P-002", "ehr_id": "cyrus"},
        ],
    })
    assert r.status_code == 200
    new_code = control_room.get_active_room().room_code

    # Stale code → error page (NOT a redirect to room B).
    r = client.get(f"/portal/students/join?code={old_code}")
    assert r.status_code == 200
    if old_code == new_code:
        # 6-char alphabet collision (rare) — skip the test rather than
        # fail. The contract still holds because lookup is by exact
        # room_code match against the active room.
        pytest.skip("room_code collision between rooms — re-run to retry.")
    assert "Room not found" in r.text
    assert "Bed 1" not in r.text  # B's content is not leaked


def test_join_page_lowercase_code_is_uppercased(client) -> None:
    """QR codes upper-case the code but a user might type it in lower.
    Lookup should be case-insensitive (we upper it server-side)."""
    from portal import control_room
    r = client.post("/api/room/start", json={
        "label": "Case test", "encounters": [
            {"scenario_name": "Bed 1", "persona_id": "P-001", "ehr_id": "helix"},
        ],
    })
    assert r.status_code == 200
    code = control_room.get_active_room().room_code
    r = client.get(f"/portal/students/join?code={code.lower()}")
    assert r.status_code == 200
    assert "Room not found" not in r.text
    assert code in r.text


def test_register_post_404s_on_unknown_room_code(client) -> None:
    """The register POST must also reject unknown room codes, not just
    the GET page."""
    r = client.post("/portal/students/register", data={
        "room_code":    "NOSUCH",
        "encounter_id": "anything",
        "display_name": "Alice",
    })
    assert r.status_code == 404, r.text


def test_register_post_404s_when_no_active_room(client) -> None:
    """No active room at all — every register attempt 404s."""
    r = client.post("/portal/students/register", data={
        "room_code":    "ANYTHG",
        "encounter_id": "ENC-X",
        "display_name": "Alice",
    })
    assert r.status_code == 404
