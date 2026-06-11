"""Phase 4.3 acceptance — the VRAI Faces ⇄ portal integration surface.

Exercises portal/vrai_faces.py:

  GET  /api/face/characters              launchable-character list (auth)
  GET  /api/face/{id}/binding            bind payload + portrait attach (no auth)
  POST /api/face/{id}/speak              push a VRAISpeechFrame (auth)
  WS   /ws/face/{scenario}/{id}          avatar speech transport

Each test stands up an isolated TestClient with a sandbox vault + HOME and
monkeypatched scenarios/characters/portraits dirs, so the operator's real
machine state is untouched and the YAML inputs are deterministic.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

TEST_PASSWORD = "test_passwd_xyz_8chars"

# A minimal-but-real MedSim card (schemas/character.json shape).
CARD: dict[str, Any] = {
    "id": "patel_attending",
    "name": "Dr. Anjali Patel",
    "role": "Hospitalist attending",
    "voice": {
        "register": "Dry, occasionally wry.",
        "sentence_length": "short",
        "examples": ["What's your read?", "Walk me through it.", "Confirm the dose."],
    },
    "knowledge_boundary": "Knows the sepsis protocol cold.",
    "teaching_stance": "Socratic.",
    "scene_contract": ["Never disclose the diagnosis first."],
    "voice_profile": {"gender": "female", "language": "en-US",
                      "voice_hints": ["Samantha", "Karen"]},
}
SCENARIO: dict[str, Any] = {
    "id": "sepsis_floor",
    "name": "Sepsis on the floor",
    "characters": ["patel_attending"],
    "ghost_color": "#cfe8ff",
}


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    """Sandboxed TestClient: tmp HOME/vault, tmp scenarios/characters/portraits,
    authenticated as an instructor."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)

    from portal import auth, control_room, credentials, scenarios, vrai_faces
    from portal import voices as _voices

    # Redirect the encrypted vault to the sandbox.
    sandbox_vault_dir = fake_home / ".medsim"
    sandbox_vault_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(credentials, "VAULT_DIR", sandbox_vault_dir)
    monkeypatch.setattr(credentials, "VAULT_PATH", sandbox_vault_dir / "vault.enc")
    monkeypatch.setattr(_voices, "KEYFILE", tmp_path / "no-such.key")
    monkeypatch.setattr(_voices, "_runtime_key", "")
    control_room._reset_for_tests()

    # Deterministic YAML inputs.
    scen_dir = tmp_path / "scenarios"
    char_dir = tmp_path / "characters"
    portrait_dir = tmp_path / "face_portraits"
    scen_dir.mkdir()
    char_dir.mkdir()
    portrait_dir.mkdir()
    (char_dir / "patel_attending.yaml").write_text(yaml.safe_dump(CARD))
    (scen_dir / "sepsis_floor.yaml").write_text(yaml.safe_dump(SCENARIO))
    monkeypatch.setattr(scenarios, "SCENARIOS_DIR", scen_dir)
    monkeypatch.setattr(scenarios, "CHARACTERS_DIR", char_dir)
    monkeypatch.setattr(vrai_faces, "PORTRAITS_DIR", portrait_dir)

    if not credentials.is_initialized():
        credentials.initialize(TEST_PASSWORD)
    vault = credentials.unlock(TEST_PASSWORD)
    vault.set("ANTHROPIC_API_KEY", "sk-ant-dummy")
    vault.set("ELEVENLABS_API_KEY", "")

    from fastapi.testclient import TestClient
    from portal import server
    c = TestClient(server.app)
    c.cookies.set(auth.COOKIE_NAME, auth.issue_session_token(vault))
    yield c
    control_room._reset_for_tests()


# ── Launchable-character list ─────────────────────────────────────────

def test_characters_list_marks_referenced_characters_launchable(client) -> None:
    r = client.get("/api/face/characters")
    assert r.status_code == 200, r.text
    chars = r.json()["characters"]
    patel = next(c for c in chars if c["id"] == "patel_attending")
    assert patel["launchable"] is True
    assert patel["scenarios"] == ["sepsis_floor"]
    assert patel["scenario"] == "sepsis_floor"
    assert "/api/face/patel_attending/binding" in patel["bind_url"]
    assert patel["speech_ws_url"].endswith("/ws/face/sepsis_floor/patel_attending")
    assert patel["qr_url"].startswith("/qr/face/patel_attending.svg")


# ── Bind payload + portrait attach ────────────────────────────────────

def test_binding_attaches_placeholder_portrait_and_maps_voice(client) -> None:
    r = client.get("/api/face/patel_attending/binding?scenario=sepsis_floor")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["characterId"] == "patel_attending"
    # Portrait attached here — the card carries none. Placeholder when no file.
    # PNG by design: createImageBitmap() cannot decode SVG in Chromium.
    assert b["sourcePhoto"].startswith("data:image/png;base64,")
    assert b["portraitSource"] == "placeholder"
    # voice_profile → gender-encoded id (matches medsim_adapter).
    assert b["voiceProfile"] == "female:Samantha"
    assert b["speechWsUrl"].endswith("/ws/face/sepsis_floor/patel_attending")
    assert b["opacityLevel"] == pytest.approx(0.66)
    assert b["ghostColor"] == "#cfe8ff"  # per-scenario tint (Phase 0 decision 4)
    # The real card fields ride along so the adapter's parseCharacterCard passes.
    assert b["voice"]["examples"]


def test_binding_uses_a_consented_file_portrait_when_present(client, tmp_path) -> None:
    # A 1x1 PNG dropped in by the facilitator.
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108020000009077"
        "53de0000000a49444154789c6360000002000154a24f9f0000000049454e44ae426082"
    )
    (tmp_path / "face_portraits" / "patel_attending.png").write_bytes(png)
    r = client.get("/api/face/patel_attending/binding?scenario=sepsis_floor")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["portraitSource"] == "file"
    assert b["sourcePhoto"].startswith("data:image/png;base64,")


def test_binding_unknown_character_is_404(client) -> None:
    r = client.get("/api/face/nobody/binding?scenario=sepsis_floor")
    assert r.status_code == 404


def test_binding_needs_no_auth(client) -> None:
    # The avatar tablet fetches this with no session — same trust as /qr/face.
    from fastapi.testclient import TestClient
    from portal import server
    bare = TestClient(server.app)  # no cookie
    r = bare.get("/api/face/patel_attending/binding?scenario=sepsis_floor")
    assert r.status_code == 200, r.text


# ── Speak path + speech WebSocket ─────────────────────────────────────

def test_speak_delivers_a_frame_over_the_websocket_and_increments_seq(client) -> None:
    with client.websocket_connect("/ws/face/sepsis_floor/patel_attending") as ws:
        r1 = client.post("/api/face/patel_attending/speak",
                         json={"scenario": "sepsis_floor", "text": "What's your read?"})
        assert r1.status_code == 200, r1.text
        body1 = r1.json()
        assert body1["ok"] is True
        assert body1["delivered"] == 1
        f1 = ws.receive_json()
        assert f1["v"] == 1
        assert f1["characterId"] == "patel_attending"
        assert f1["text"] == "What's your read?"
        assert f1["endOfUtterance"] is True
        assert f1["seq"] == body1["seq"]

        r2 = client.post("/api/face/patel_attending/speak",
                         json={"scenario": "sepsis_floor", "text": "Confirm the dose."})
        f2 = ws.receive_json()
        assert f2["seq"] > f1["seq"]  # strictly increasing


def test_speak_carries_emotion_when_provided(client) -> None:
    with client.websocket_connect("/ws/face/sepsis_floor/patel_attending") as ws:
        client.post("/api/face/patel_attending/speak", json={
            "scenario": "sepsis_floor",
            "text": "Lactate of 4?",
            "emotion": {"label": "concern", "weights": {"browInnerUp": 0.4}},
        })
        f = ws.receive_json()
        assert f["emotion"]["label"] == "concern"
        assert f["emotion"]["weights"]["browInnerUp"] == pytest.approx(0.4)


def test_speak_without_text_is_400(client) -> None:
    r = client.post("/api/face/patel_attending/speak",
                    json={"scenario": "sepsis_floor", "text": "  "})
    assert r.status_code == 400


def test_speak_requires_auth(client) -> None:
    from fastapi.testclient import TestClient
    from portal import server
    bare = TestClient(server.app)  # no cookie
    r = bare.post("/api/face/patel_attending/speak",
                  json={"scenario": "sepsis_floor", "text": "hi"})
    assert r.status_code in (401, 403)


# ── OPT-008 Cut 1: the pipelined-TTS reply splitter ──────────────────────────

def test_split_reply_splits_at_first_sentence_boundary() -> None:
    from portal.vrai_faces import _split_reply
    first, rest = _split_reply(
        "I have been feeling dizzy since this morning. It comes and goes in waves, "
        "and standing up makes everything spin.")
    assert first == "I have been feeling dizzy since this morning."
    assert rest.startswith("It comes and goes")


def test_split_reply_short_reply_is_single_chunk() -> None:
    from portal.vrai_faces import _split_reply
    first, rest = _split_reply("Yes. Fine.")
    assert first == "Yes. Fine."
    assert rest == ""


def test_split_reply_never_splits_inside_a_stage_direction() -> None:
    from portal.vrai_faces import _split_reply
    reply = ("*eyes darting toward your voice, then away. fingers plucking at the blanket* "
             "Yeah, I heard you fine. Where did my daughter go just now?")
    first, rest = _split_reply(reply)
    # The boundary must be AFTER the starred direction — the '.' inside it doesn't count.
    assert first.endswith("Yeah, I heard you fine.")
    assert rest == "Where did my daughter go just now?"


def test_split_reply_unbalanced_stars_fall_back_to_single_chunk() -> None:
    from portal.vrai_faces import _split_reply
    reply = "*mutters something. trails off and never closes the direction so no boundary"
    first, rest = _split_reply(reply)
    assert first == reply
    assert rest == ""


# ── OPT-008 Cut 2: the incremental first-sentence boundary finder ────────────

def test_first_sentence_cut_incremental_streaming() -> None:
    from portal.vrai_faces import _first_sentence_cut
    # Simulates deltas growing the buffer: no boundary until the sentence completes.
    partial = "I have been feeling dizzy and weak all"
    assert _first_sentence_cut(partial) is None          # mid-stream: no boundary yet
    full = partial + " morning. It comes and goes in waves."
    cut = _first_sentence_cut(full)
    assert cut is not None
    assert full[:cut].strip() == "I have been feeling dizzy and weak all morning."


def test_first_sentence_cut_ignores_stage_direction_periods() -> None:
    from portal.vrai_faces import _first_sentence_cut
    buf = "*looks around. confused, plucking at lines* Where is everyone? They said lunch."
    cut = _first_sentence_cut(buf)
    assert cut is not None
    assert buf[:cut].strip().endswith("Where is everyone?")


# ── FR-003: instructor speaks through the character (/speak upgrade) ─────────

def test_speak_verbatim_reports_mode_and_reply(client) -> None:
    r = client.post("/api/face/patel_attending/speak",
                    json={"scenario": "sepsis_floor", "text": "The labs are back."})
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert j["mode"] == "verbatim"
    assert j["reply"] == "The labs are back."
    assert "streamed" in j


def test_speak_in_character_without_session_is_409(client) -> None:
    r = client.post("/api/face/patel_attending/speak",
                    json={"scenario": "sepsis_floor", "text": "ask about pain",
                          "mode": "in_character"})
    assert r.status_code == 409
    assert "running scenario" in r.json()["error"]
