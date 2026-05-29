"""V7 — Per-encounter cost caps (M17).

Two caps, configurable per-room (and overridable per-encounter):

  - ``haiku_rate_cap``  — max LLM turns per minute, across the room
                           or per encounter. Default: unlimited.
  - ``voice_char_cap``  — max ElevenLabs characters per room, across
                           the room's lifetime. Default: unlimited.

When a cap would be exceeded:
  - **Haiku rate cap exceeded** → ``check_haiku_turn(enc)`` returns
    ``Decision(allow=False, fallback='refuse', reason=...)`` and the
    caller refuses the turn with operator notice. No retry; the
    student sees a "(rate-limited)" notice on their station.
  - **Voice char budget exceeded** → ``check_voice_chars(enc, n)``
    returns ``Decision(allow=False, fallback='browser_tts', ...)``
    and the caller emits a 503 with ``{"fallback": true}`` so the
    browser switches to SpeechSynthesis. Subsequent turns continue
    in browser-TTS mode until the budget is reset.

State lives in-process on the ControlRoom — durable persistence
across restarts is intentionally NOT a goal. Operator restarts the
server → budgets reset. (Compatible with the v6 in-memory model.)
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field


# ── Sliding-window rate tracker ──────────────────────────────────────

class _RateWindow:
    """Tracks event timestamps in a sliding window so we can check
    whether the rate over the past ``window_s`` exceeds ``cap_per_window``.
    Memory bounded by the cap × window (typically ~tens of events)."""

    def __init__(self, window_s: float = 60.0) -> None:
        self.window_s = window_s
        self._events: deque[float] = deque()

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_s
        while self._events and self._events[0] < cutoff:
            self._events.popleft()

    def record(self, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        self._prune(now)
        self._events.append(now)

    def count_in_window(self, now: float | None = None) -> int:
        now = now if now is not None else time.time()
        self._prune(now)
        return len(self._events)


@dataclass
class Decision:
    allow:    bool
    fallback: str = ""   # 'refuse' | 'browser_tts' | ''
    reason:   str = ""
    remaining: int = -1  # advisory — chars left (voice) or turns left (haiku)


@dataclass
class _EncounterBudget:
    haiku_window: _RateWindow = field(default_factory=_RateWindow)
    voice_chars_used: int = 0


@dataclass
class RoomBudgetTracker:
    """One instance per ControlRoom. Tracks per-encounter usage AND
    a room-level rollup so a per-room cap can be enforced."""

    haiku_rate_cap: int | None = None        # turns/minute room-wide
    voice_char_cap: int | None = None        # total chars room-wide
    per_encounter_haiku_rate_cap: int | None = None  # optional per-encounter override
    per_encounter_voice_char_cap: int | None = None
    _encounters: dict[str, _EncounterBudget] = field(default_factory=dict)
    _room_haiku_window: _RateWindow = field(default_factory=_RateWindow)
    _room_voice_chars_used: int = 0

    # ── Internal ──────────────────────────────────────────────────

    def _bucket(self, encounter_id: str) -> _EncounterBudget:
        b = self._encounters.get(encounter_id)
        if b is None:
            b = _EncounterBudget()
            self._encounters[encounter_id] = b
        return b

    # ── Haiku rate cap ────────────────────────────────────────────

    def check_haiku_turn(self, encounter_id: str,
                          *, now: float | None = None) -> Decision:
        """Should this encounter be allowed to fire one Haiku turn?
        Returns a Decision. Does NOT record the turn — call
        ``record_haiku_turn`` after the LLM call succeeds."""
        now = now if now is not None else time.time()
        # Per-encounter cap (when set)
        if self.per_encounter_haiku_rate_cap is not None:
            cnt = self._bucket(encounter_id).haiku_window.count_in_window(now)
            if cnt >= self.per_encounter_haiku_rate_cap:
                return Decision(
                    allow=False, fallback="refuse",
                    reason=(f"Per-encounter Haiku rate cap reached "
                            f"({cnt}/{self.per_encounter_haiku_rate_cap} "
                            f"in the last 60 s)."),
                    remaining=0,
                )
        # Room-wide cap
        if self.haiku_rate_cap is not None:
            room_cnt = self._room_haiku_window.count_in_window(now)
            if room_cnt >= self.haiku_rate_cap:
                return Decision(
                    allow=False, fallback="refuse",
                    reason=(f"Room-wide Haiku rate cap reached "
                            f"({room_cnt}/{self.haiku_rate_cap} in the last 60 s)."),
                    remaining=0,
                )
            remaining = max(0, self.haiku_rate_cap - room_cnt)
            return Decision(allow=True, remaining=remaining)
        return Decision(allow=True)

    def record_haiku_turn(self, encounter_id: str,
                           *, now: float | None = None) -> None:
        """Stamp a successful turn. Must be called after the LLM call
        completes so refused-then-retried sequences aren't counted twice."""
        now = now if now is not None else time.time()
        self._bucket(encounter_id).haiku_window.record(now)
        self._room_haiku_window.record(now)

    # ── ElevenLabs voice char budget ───────────────────────────────

    def check_voice_chars(self, encounter_id: str,
                           char_count: int) -> Decision:
        """Can this encounter synthesize ``char_count`` more
        characters? Does NOT charge them — call ``record_voice_chars``
        after the synth call succeeds. The cap is a TOTAL budget for
        the room's lifetime; once exceeded, the room falls back to
        browser TTS until the operator resets."""
        if char_count <= 0:
            return Decision(allow=True)
        # Per-encounter cap (when set)
        if self.per_encounter_voice_char_cap is not None:
            used = self._bucket(encounter_id).voice_chars_used
            if used + char_count > self.per_encounter_voice_char_cap:
                return Decision(
                    allow=False, fallback="browser_tts",
                    reason=(f"Per-encounter voice char cap exceeded "
                            f"({used + char_count}/"
                            f"{self.per_encounter_voice_char_cap}). "
                            "Falling back to browser TTS."),
                    remaining=max(0, self.per_encounter_voice_char_cap - used),
                )
        # Room-wide cap
        if self.voice_char_cap is not None:
            if self._room_voice_chars_used + char_count > self.voice_char_cap:
                remaining = max(0, self.voice_char_cap -
                                 self._room_voice_chars_used)
                return Decision(
                    allow=False, fallback="browser_tts",
                    reason=(f"Room-wide voice char cap exceeded "
                            f"({self._room_voice_chars_used + char_count}/"
                            f"{self.voice_char_cap}). "
                            "Falling back to browser TTS."),
                    remaining=remaining,
                )
            return Decision(allow=True,
                            remaining=self.voice_char_cap -
                                      self._room_voice_chars_used - char_count)
        return Decision(allow=True)

    def record_voice_chars(self, encounter_id: str, char_count: int) -> None:
        """Charge ``char_count`` against the encounter + room budgets.
        Call after the synth call returns audio."""
        if char_count <= 0:
            return
        self._bucket(encounter_id).voice_chars_used += char_count
        self._room_voice_chars_used += char_count

    # ── Reporting ─────────────────────────────────────────────────

    def usage(self) -> dict:
        """Operator-facing snapshot of room + per-encounter usage.
        Used by the M5 dashboard's eventual "Budget" widget."""
        now = time.time()
        return {
            "haiku_rate_cap":            self.haiku_rate_cap,
            "haiku_turns_last_60s":      self._room_haiku_window.count_in_window(now),
            "voice_char_cap":            self.voice_char_cap,
            "voice_chars_used":          self._room_voice_chars_used,
            "voice_chars_remaining": (
                max(0, self.voice_char_cap - self._room_voice_chars_used)
                if self.voice_char_cap is not None else None
            ),
            "per_encounter": {
                eid: {
                    "haiku_turns_last_60s":
                        b.haiku_window.count_in_window(now),
                    "voice_chars_used": b.voice_chars_used,
                }
                for eid, b in self._encounters.items()
            },
        }
