"""FR-020 — *stage directions* are kept in the reply DATA but never SPOKEN.

The canonical strip lives in portal/voices.py (server synthesis boundary); the JS/TS
speak fallbacks mirror it (tts_client.js, encounter_console.js, speechConsumer.ts).
These tests pin the strip semantics + the _synthesize_voice behavior.
"""
from __future__ import annotations

import asyncio

import pytest

from portal import voices, vrai_faces


# ── the canonical strip ──────────────────────────────────────────────


def test_plain_dialog_untouched():
    assert voices.strip_stage_directions("It hurts when I breathe.") == \
        "It hurts when I breathe."


def test_leading_direction_removed():
    got = voices.strip_stage_directions("*coughs weakly* It hurts when I breathe.")
    assert got == "It hurts when I breathe."


def test_inline_and_multiple_directions_removed():
    got = voices.strip_stage_directions(
        "*winces* I told you already. *turns away* Please stop asking.")
    assert got == "I told you already. Please stop asking."


def test_direction_only_line_becomes_empty():
    assert voices.strip_stage_directions(
        "*eyes darting toward your voice, then away. fingers plucking at the blanket*") == ""


def test_unbalanced_stars_left_untouched():
    raw = "*mutters something. trails off and never closes the direction"
    assert voices.strip_stage_directions(raw) == raw


def test_orphan_punctuation_tidied():
    got = voices.strip_stage_directions("I can't *gasps* , it hurts.")
    assert got == "I can't, it hurts."


def test_error_reply_parentheses_still_spoken():
    err = "(the character could not respond: Anthropic API key was rejected)"
    assert voices.strip_stage_directions(err) == err


# ── the synthesis boundary (_synthesize_voice) ───────────────────────


class _FakeSess:
    elevenlabs_api_key = "test-key-not-real"
    voice_assignments = {"c1": "voice_x"}


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def captured(monkeypatch):
    """Capture what text reaches ElevenLabs; never hit the network."""
    calls: list[str] = []

    async def fake_stream(text, voice_id, api_key, **kw):
        calls.append(text)
        yield b"mp3bytes"

    monkeypatch.setattr(voices, "synthesize_stream", fake_stream)
    return calls


def test_synth_receives_stripped_text(captured):
    audio, fmt = _run(vrai_faces._synthesize_voice(
        _FakeSess(), "c1", "*coughs* It hurts when I breathe."))
    assert captured == ["It hurts when I breathe."]
    assert audio and fmt == "mp3"


def test_direction_only_returns_no_audio_and_never_calls_tts(captured, monkeypatch):
    monkeypatch.delenv("VRAI_DEV_TTS", raising=False)
    audio, fmt = _run(vrai_faces._synthesize_voice(
        _FakeSess(), "c1", "*shifts uncomfortably and stares at the ceiling*"))
    assert (audio, fmt) == (None, None)
    assert captured == []


def test_error_reply_is_still_voiced(captured):
    _run(vrai_faces._synthesize_voice(
        _FakeSess(), "c1", "(the character could not respond: key rejected)"))
    assert captured == ["(the character could not respond: key rejected)"]
