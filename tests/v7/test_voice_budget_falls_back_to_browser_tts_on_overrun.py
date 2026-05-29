"""M17 acceptance — voice char budget overrun → browser-TTS fallback.

The RoomBudgetTracker is the load-bearing data layer for the M17
contract. Once room-wide voice_chars_used would exceed voice_char_cap,
check_voice_chars returns Decision(allow=False, fallback='browser_tts').
The voices.py integration (later wire-up) reads that decision and
emits a 503 + {"fallback": true} response so the browser switches
to SpeechSynthesis.
"""
from __future__ import annotations

from portal.budgets import RoomBudgetTracker


def test_voice_budget_allow_under_cap() -> None:
    t = RoomBudgetTracker(voice_char_cap=1000)
    d = t.check_voice_chars("enc-a", 500)
    assert d.allow is True
    t.record_voice_chars("enc-a", 500)
    d2 = t.check_voice_chars("enc-a", 400)
    assert d2.allow is True
    assert d2.remaining == 100


def test_voice_budget_falls_back_at_cap() -> None:
    t = RoomBudgetTracker(voice_char_cap=1000)
    t.record_voice_chars("enc-a", 900)
    # 200 more would overshoot; refuse with browser_tts fallback.
    d = t.check_voice_chars("enc-a", 200)
    assert d.allow is False
    assert d.fallback == "browser_tts"
    assert "voice char cap" in d.reason.lower()
    assert d.remaining == 100   # 100 chars still under cap


def test_voice_budget_no_cap_means_unlimited() -> None:
    t = RoomBudgetTracker(voice_char_cap=None)
    d = t.check_voice_chars("enc-a", 1_000_000)
    assert d.allow is True


def test_voice_budget_per_encounter_cap_overrides_room() -> None:
    """When per_encounter_voice_char_cap is set, it takes precedence
    over the room-wide cap on a per-encounter basis."""
    t = RoomBudgetTracker(voice_char_cap=10_000,
                           per_encounter_voice_char_cap=500)
    # Encounter A: room has 10k budget but encounter A capped at 500.
    t.record_voice_chars("enc-a", 480)
    d = t.check_voice_chars("enc-a", 50)
    assert d.allow is False
    assert d.fallback == "browser_tts"
    # Encounter B (independent) — still has its own 500-char budget.
    d2 = t.check_voice_chars("enc-b", 400)
    assert d2.allow is True


def test_voice_budget_usage_snapshot_reports_per_encounter() -> None:
    t = RoomBudgetTracker(voice_char_cap=1000)
    t.record_voice_chars("enc-a", 200)
    t.record_voice_chars("enc-b", 300)
    snap = t.usage()
    assert snap["voice_char_cap"] == 1000
    assert snap["voice_chars_used"] == 500
    assert snap["voice_chars_remaining"] == 500
    assert snap["per_encounter"]["enc-a"]["voice_chars_used"] == 200
    assert snap["per_encounter"]["enc-b"]["voice_chars_used"] == 300
