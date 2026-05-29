"""V7 Phase 7 — Telemetry simulation engine (M23).

Derives a live snapshot of HR / BP / SpO2 / RR / Temp for an
encounter from its most recent ``vitals.record`` chart event,
plus optional small jitter so the displayed numbers look "alive"
rather than static.

No physiological model — when a scene fires ``vitals.drop``, the
chart_event log gets a new vitals.record row; this engine simply
reads the most recent row at snapshot time. The trajectory between
snapshots is interpolation + jitter, not predicted physiology.

Instructor overrides:
  - Per-metric force-set values stored in
    ``ehr_session.telemetry_overrides_json`` (schema v5 field added
    inline below — append-only). When a metric is overridden, the
    derivation ignores the chart-event value for that metric.
  - Use cases: "what if BP keeps dropping" demos; teaching
    deteriorating vitals without re-injecting scenes; covering for
    a delayed `vitals.drop` scene if the operator wants the
    metrics changed instantly.

Phase 7 M23 ships:
  - ``snapshot(encounter_id) -> dict`` — current values per metric.
  - ``set_override(encounter_id, key, value)`` — force-set one metric.
  - ``clear_override(encounter_id, key)`` — return that metric to
    derived mode.
  - HTTP routes added in server.py:
    GET  /api/encounter/{id}/telemetry          — snapshot
    POST /api/encounter/{id}/telemetry/override — set/clear

The next phase 7 module (M24) adds the ECG waveform library; M25
wires both into the Per-Patient Console UI.
"""
from __future__ import annotations

import json
import random
import time
from typing import Any

from . import ehr_db


# ── Default vitals (when no chart event has fired yet) ───────────────

_DEFAULTS = {
    "hr":      80,
    "sbp":     118,
    "dbp":     74,
    "spo2":    98,
    "rr":      16,
    "temp_f":  98.6,
}

# Small jitter ranges per metric — applied each snapshot to make the
# numbers feel live. Tight enough that a "stable" patient's strip
# looks stable; large enough that you can see the digit move.
_JITTER_RANGES = {
    "hr":     (-2, 2),
    "sbp":    (-2, 2),
    "dbp":    (-1, 1),
    "spo2":   (-1, 0),    # SpO2 trends down, not up (under 100%)
    "rr":     (-1, 1),
    "temp_f": (-0.1, 0.1),
}


_VALID_METRICS = frozenset(_DEFAULTS.keys())


def _latest_vitals_for(encounter_id: str) -> dict[str, Any]:
    """Walk the encounter's chart_event log newest-first and return
    the most recent ``vitals.record`` payload, or {} if none."""
    events = ehr_db.events(encounter_id) or []
    for ev in reversed(events):
        if ev.get("type") == "vitals.record":
            return dict(ev.get("payload") or {})
    return {}


def _get_encounter(encounter_id: str):
    """Resolve the encounter from the active room. Returns None if
    no room is active or the encounter id is unknown."""
    from . import control_room
    room = control_room.get_active_room()
    if room is None:
        return None
    return room.encounters.get(encounter_id)


def _load_overrides(encounter_id: str) -> dict[str, Any]:
    """Read the live overrides for an encounter from the in-memory
    ControlRoom. Telemetry overrides don't need restart-survival —
    the room itself dies with the server."""
    enc = _get_encounter(encounter_id)
    if enc is None:
        return {}
    return dict(enc.telemetry_overrides or {})


def _save_overrides(encounter_id: str, overrides: dict[str, Any]) -> None:
    enc = _get_encounter(encounter_id)
    if enc is None:
        return
    enc.telemetry_overrides = dict(overrides)


def snapshot(encounter_id: str, *,
              jitter: bool = True,
              now: float | None = None) -> dict[str, Any]:
    """Return the live telemetry snapshot for an encounter.

    Each metric resolves in priority order:
      1. Active operator override (if any).
      2. Most recent ``vitals.record`` payload value.
      3. Module default.

    ``jitter`` adds a small random offset to mimic continuous
    bedside monitoring. Pass ``jitter=False`` for deterministic
    test reads.
    """
    latest = _latest_vitals_for(encounter_id)
    overrides = _load_overrides(encounter_id)
    rnd = random.Random(int(time.time() * 1000) if now is None
                          else int(now * 1000))
    out: dict[str, Any] = {}
    for metric, default_val in _DEFAULTS.items():
        if metric in overrides:
            out[metric] = overrides[metric]
            continue
        val = latest.get(metric, default_val)
        if jitter:
            lo, hi = _JITTER_RANGES[metric]
            if isinstance(val, (int, float)):
                if metric == "temp_f":
                    val = round(val + rnd.uniform(lo, hi), 1)
                else:
                    val = max(0, int(val + rnd.randint(lo, hi)))
        out[metric] = val
    out["overrides_active"] = sorted(overrides.keys())
    out["from"] = {m: ("override" if m in overrides
                        else "vitals.record" if m in latest
                        else "default")
                    for m in _DEFAULTS}
    out["ts"] = now if now is not None else time.time()
    return out


def set_override(encounter_id: str, key: str, value: Any) -> dict[str, Any]:
    """Force-set one metric. Returns the updated override dict."""
    if key not in _VALID_METRICS:
        raise ValueError(f"unknown metric {key!r}; valid: "
                          f"{sorted(_VALID_METRICS)}")
    overrides = _load_overrides(encounter_id)
    overrides[key] = value
    _save_overrides(encounter_id, overrides)
    return overrides


def clear_override(encounter_id: str, key: str) -> dict[str, Any]:
    overrides = _load_overrides(encounter_id)
    overrides.pop(key, None)
    _save_overrides(encounter_id, overrides)
    return overrides


def clear_all_overrides(encounter_id: str) -> None:
    _save_overrides(encounter_id, {})


# ── Inline migration for schema v6 (telemetry_overrides_json) ────────
#
# Phase 7 M23 only — adds one column. Slots into the existing
# SCHEMA_MIGRATIONS list. Idempotent (the column is NULL until first
# override).
#
# We register the migration at import time so it lands the first time
# any caller imports ``portal.telemetry``. The migration runner picks
# it up on the next `_open_db()` cycle.

def _register_v6_migration() -> None:
    if any(v == 6 for v, _ in ehr_db.SCHEMA_MIGRATIONS):
        return
    ehr_db.SCHEMA_MIGRATIONS.append((6, """
    -- V7 Phase 7 M23 — telemetry overrides per encounter.
    ALTER TABLE ehr_session ADD COLUMN telemetry_overrides_json TEXT;
    """))
    # Bump the cached SCHEMA_VERSION.
    ehr_db.SCHEMA_VERSION = ehr_db.SCHEMA_MIGRATIONS[-1][0]


_register_v6_migration()
