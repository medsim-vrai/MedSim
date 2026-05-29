"""M37 — Fix TTS audio cut-off on reused primed audio element.

Bug: when the instructor engages a character via the M35 Engage flow
and runs a turn, the filler audio plays through the primedAudio
element first, then the reply plays through the SAME element. On
Chrome/Safari, setting `audio.src` to a new URL on an element that
just finished playing doesn't fully reset internal state — `ended`,
`currentTime`, and buffered duration leak from the prior play, and
`ended` fires prematurely on the new stream. The instructor hears
the reply start and immediately cut off.

Fix: in `tts_client.js`'s `playElevenLabs`, before assigning the new
src to the audio element, pause it, remove the old src, call
`audio.load()` to wipe internal state, reset `currentTime` to 0,
then set the new src and call `load()` again to start a fresh load.

This is a client-side fix — we can't drive a real browser in pytest
(M20's Playwright test is the only acceptance-level browser test,
and it skips by default). So we assert here that the reset sequence
is present in the shipped JS. Future regressions that remove the
sequence will fail this test.
"""
from __future__ import annotations

from pathlib import Path


TTS_CLIENT = (
    Path(__file__).resolve().parents[2]
    / "portal" / "static" / "tts_client.js"
)


def _src() -> str:
    return TTS_CLIENT.read_text(encoding="utf-8")


def test_play_eleven_labs_resets_audio_state_before_new_src() -> None:
    """playElevenLabs must reset the audio element's state before
    assigning the new src — otherwise the second play through a reused
    primed element cuts off because Chrome/Safari fire `ended` early."""
    src = _src()
    # The reset sequence must appear BEFORE the new src assignment.
    # We look for the snippet that pauses + removeAttribute("src") +
    # load() + currentTime reset, and assert it precedes the actual
    # src= assignment to "/api/tts?".
    reset_pause     = src.find('audio.pause()')
    reset_remove    = src.find('audio.removeAttribute("src")')
    reset_load_pre  = src.find('audio.load()')
    reset_ct        = src.find('audio.currentTime = 0')
    src_assignment  = src.find('audio.src = "/api/tts?"')
    assert reset_pause   >= 0, "missing audio.pause() reset"
    assert reset_remove  >= 0, "missing audio.removeAttribute('src') reset"
    assert reset_load_pre >= 0, "missing audio.load() reset"
    assert reset_ct      >= 0, "missing audio.currentTime = 0 reset"
    assert src_assignment >= 0, "audio.src = '/api/tts?' anchor not found"
    # Ordering: every reset step must come before the src= assignment.
    assert reset_pause    < src_assignment
    assert reset_remove   < src_assignment
    assert reset_load_pre < src_assignment
    assert reset_ct       < src_assignment


def test_play_eleven_labs_calls_load_after_setting_new_src() -> None:
    """After assigning the new src, a second `audio.load()` is called
    to start a clean fresh load of the new audio. Without this, the
    element may stay in its prior idle state and the new stream never
    plays."""
    src = _src()
    src_assignment = src.find('audio.src = "/api/tts?"')
    # Find an audio.load() call AFTER the src assignment.
    post_src_segment = src[src_assignment:src_assignment + 600]
    assert 'audio.load()' in post_src_segment, (
        "playElevenLabs must call audio.load() after setting the new "
        "src to start a clean fresh stream load.")


def test_primed_audio_pattern_is_still_used() -> None:
    """We must not regress the Chrome autoplay-policy workaround —
    primedAudio is what lets async TTS playback bypass the autoplay
    block once the original user gesture has expired. The reset
    sequence preserves the workaround; this test guards against an
    accidental switch back to `new Audio()` per call."""
    src = _src()
    assert "primedAudio || new Audio()" in src, (
        "playElevenLabs must keep reusing the primed <audio> element "
        "as the autoplay-policy workaround (V6 design).")
    # And the prime() entry point is still defined + exported.
    assert "function prime()" in src
    assert "MedSimTTS = { speak, cancel, pickVoice, prime }" in src


def test_reset_calls_are_wrapped_in_try_catch() -> None:
    """Some browsers throw InvalidStateError when load() is called
    too early in the lifecycle. Each reset call must be wrapped so
    one transient throw doesn't blow up the whole playback path."""
    src = _src()
    # Locate the playElevenLabs body and the reset block within it.
    fn_idx = src.find("function playElevenLabs")
    assert fn_idx >= 0
    end_idx = src.find("function ", fn_idx + 1)
    body = src[fn_idx:end_idx if end_idx > 0 else len(src)]
    # Each of the four reset operations should be inside a try { … } catch.
    # We don't care about exact whitespace — just that each call shows up
    # at least once inside a try/catch pattern.
    for op in ("audio.pause()", 'audio.removeAttribute("src")',
               "audio.load()", "audio.currentTime = 0"):
        assert op in body, f"{op!r} not found in playElevenLabs body"
    # Count try { audio.pause() } catch — there should be at least one
    # try{} catch{} construct wrapping audio.pause().
    assert "try { audio.pause()" in body, (
        "audio.pause() reset must be wrapped in try/catch.")
    assert 'try { audio.removeAttribute("src")' in body
    assert "try { audio.load()" in body
