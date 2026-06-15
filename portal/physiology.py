"""portal/physiology.py — FR-012 D2: the physiology spine.

v8 has no physiology engine: vitals are the latest ``vitals.record`` chart event
read + jittered by ``portal/telemetry.py``. This module is the single read/write
SEAM the advanced devices (telemetry monitor, vent monitor, ventilator) sit on:

  * ``read(encounter_id)``      — the current physiologic snapshot devices show.
  * ``apply_delta`` / ``set_vitals`` — the ONLY way ventilator controls (D5) and
    faults (D6) move vitals, bounded to physiologic ranges + the patient's
    condition ceiling, written back as a ``vitals.record`` (so the existing
    console / nurse station / EHR see them too — same lever FR-008 impacts use).
  * a **PhysiologySource authority lease** — ONE writer per patient. The virtual
    baseline is the always-on floor; PhysioBridge / a manikin register later as
    higher-precedence sources and take the lease, with the virtual engine as a
    hot shadow (see docs/DESIGN-2026-06-14-physiology-source-authority.md). D2
    builds the seam; multi-source failover/reconcile activates when those
    sources exist.

Forward-compatible with PhysioBridge Shape-B: when it lands it registers as the
``physiobridge`` source (higher precedence), becomes the authority, and feeds
``vitals.record`` through ``set_vitals`` — the devices are unchanged.

PHI (ADR-0014): everything here is structured numbers + a condition label, never
trainee free-text.
"""
from __future__ import annotations

import logging
from typing import Any

from . import ehr_db

log = logging.getLogger(__name__)

# ── Respiratory-coupling envelopes (ported from PhysioBridge vent_coupling) ──
# spo2_ceiling = best achievable SpO2 for the condition (a sick lung can't be
# normalized by O2/PEEP alone); shunt informs D5's FiO2 response curve.
CONDITIONS: dict[str, dict[str, float]] = {
    "normal":    {"spo2_ceiling": 100.0, "shunt": 0.05},
    "ards":      {"spo2_ceiling": 99.0,  "shunt": 0.35},
    "copd":      {"spo2_ceiling": 96.0,  "shunt": 0.15},
    "pneumonia": {"spo2_ceiling": 98.0,  "shunt": 0.22},
    "sepsis":    {"spo2_ceiling": 99.0,  "shunt": 0.10},
}

# Hard physiologic clamps — a delta can never drive a metric outside these.
_RANGES: dict[str, tuple[float, float]] = {
    "hr": (0, 300), "sbp": (20, 300), "dbp": (10, 220), "spo2": (0, 100),
    "rr": (0, 80), "temp_f": (75.0, 113.0), "etco2": (0, 150),
}
_CORE = ("hr", "sbp", "dbp", "spo2", "rr", "temp_f")   # telemetry's metric set
_EXTRA = ("etco2",)                                    # physiology superset adds
_DEFAULT_ETCO2 = 38
_PHYS_STATION = "physiology"

# ── Source-authority lease (single writer per patient) ───────────────────────
# Higher precedence wins. "virtual" is the always-on floor and never registers
# explicitly — it is the default authority when nothing higher is healthy.
SOURCE_PRECEDENCE: dict[str, int] = {"virtual": 0, "physiobridge": 10, "manikin": 20}
_sources: dict[str, dict[str, bool]] = {}   # encounter_id -> {source: healthy}
_conditions: dict[str, str] = {}            # encounter_id -> condition key


# ── Internals ────────────────────────────────────────────────────────────────

def _encounter(encounter_id: str):
    from . import control_room
    room = control_room.get_active_room()
    return room.encounters.get(encounter_id) if room is not None else None


def _latest_record(encounter_id: str) -> dict[str, Any]:
    """Most recent ``vitals.record`` payload from the durable event log."""
    events = ehr_db.events(encounter_id) or []
    for ev in reversed(events):
        if ev.get("type") == "vitals.record":
            return dict(ev.get("payload") or {})
    return {}


def _add_map(vitals: dict[str, Any]) -> None:
    sbp, dbp = vitals.get("sbp"), vitals.get("dbp")
    if isinstance(sbp, (int, float)) and isinstance(dbp, (int, float)):
        vitals["map"] = round(dbp + (sbp - dbp) / 3)


def _bound(vitals: dict[str, Any], condition: str) -> dict[str, Any]:
    """Clamp to physiologic ranges + the condition's SpO2 ceiling."""
    out = dict(vitals)
    for key, (lo, hi) in _RANGES.items():
        v = out.get(key)
        if isinstance(v, (int, float)):
            out[key] = max(lo, min(hi, v))
    ceiling = CONDITIONS.get(condition, CONDITIONS["normal"])["spo2_ceiling"]
    if isinstance(out.get("spo2"), (int, float)):
        out["spo2"] = min(out["spo2"], ceiling)
    return out


def _write_vitals(encounter_id: str, vitals: dict[str, Any], *,
                  surface: str, cause: str | None, source: str) -> None:
    payload: dict[str, Any] = {"time": "now", "source": source}
    for key in (*_CORE, *_EXTRA):
        if isinstance(vitals.get(key), (int, float)):
            payload[key] = vitals[key]
    if cause:
        payload["cause"] = cause
    try:
        ehr_db.append_event(encounter_id, _PHYS_STATION, type="vitals.record",
                            surface=surface, payload=payload)
    except Exception:  # noqa: BLE001 — a write failure must not crash a device tick
        log.exception("physiology: failed to persist vitals.record for %s",
                      encounter_id)


# ── Authority lease ──────────────────────────────────────────────────────────

def register_source(encounter_id: str, source: str, *, healthy: bool = True) -> None:
    """Register a higher-fidelity source (physiobridge / manikin) for a patient."""
    _sources.setdefault(encounter_id, {})[source] = healthy


def release_source(encounter_id: str, source: str) -> None:
    _sources.get(encounter_id, {}).pop(source, None)


def set_source_health(encounter_id: str, source: str, healthy: bool) -> None:
    """Mark a source up/down (link loss/regain). Authority recomputes on read."""
    if source in _sources.get(encounter_id, {}):
        _sources[encounter_id][source] = healthy


def authority(encounter_id: str) -> str:
    """The single current writer = highest-precedence HEALTHY source. The virtual
    baseline is the always-on floor, so this is never empty."""
    healthy = {s for s, ok in _sources.get(encounter_id, {}).items() if ok}
    healthy.add("virtual")
    return max(healthy, key=lambda s: SOURCE_PRECEDENCE.get(s, 0))


def is_authority(source: str, encounter_id: str) -> bool:
    return authority(encounter_id) == source


# ── Condition ────────────────────────────────────────────────────────────────

def condition_for(encounter_id: str) -> str:
    return _conditions.get(encounter_id, "normal")


def set_condition(encounter_id: str, condition: str) -> str:
    if condition not in CONDITIONS:
        raise ValueError(f"unknown condition {condition!r}; "
                         f"valid: {sorted(CONDITIONS)}")
    _conditions[encounter_id] = condition
    return condition


# ── Read ─────────────────────────────────────────────────────────────────────

def read(encounter_id: str, *, jitter: bool = False) -> dict[str, Any]:
    """Current physiologic snapshot: vitals (telemetry's 6 + etCO2 + derived MAP),
    rhythm, condition, and the source that currently holds authority."""
    from . import telemetry
    snap = telemetry.snapshot(encounter_id, jitter=jitter)
    vitals: dict[str, Any] = {m: snap.get(m) for m in _CORE}
    vitals["etco2"] = _latest_record(encounter_id).get("etco2", _DEFAULT_ETCO2)
    _add_map(vitals)
    return {
        "vitals": vitals,
        "rhythm": rhythm_for(encounter_id),
        "condition": condition_for(encounter_id),
        "source": authority(encounter_id),
    }


# ── Write (authority-gated) ──────────────────────────────────────────────────

def apply_delta(encounter_id: str, deltas: dict[str, float], *,
                surface: str = "physiology", cause: str | None = None,
                source: str = "virtual") -> dict[str, Any]:
    """Add ``deltas`` to the current vitals, bounded, and persist. No-op (returns
    the current vitals) if ``source`` does not hold the authority lease."""
    if not is_authority(source, encounter_id):
        log.info("physiology: %s is not authority for %s (held by %s) — delta ignored",
                 source, encounter_id, authority(encounter_id))
        return read(encounter_id)["vitals"]
    current = read(encounter_id)["vitals"]
    new = dict(current)
    for key, dv in (deltas or {}).items():
        if key in _RANGES and isinstance(new.get(key), (int, float)) \
                and isinstance(dv, (int, float)):
            new[key] = new[key] + dv
    new = _bound(new, condition_for(encounter_id))
    _write_vitals(encounter_id, new, surface=surface, cause=cause, source=source)
    _add_map(new)
    return new


def set_vitals(encounter_id: str, values: dict[str, float], *,
               surface: str = "physiology", cause: str | None = None,
               source: str = "virtual") -> dict[str, Any]:
    """Set absolute vital values (only recognized metrics), bounded, and persist.
    Authority-gated like ``apply_delta``."""
    if not is_authority(source, encounter_id):
        log.info("physiology: %s is not authority for %s — set ignored",
                 source, encounter_id)
        return read(encounter_id)["vitals"]
    current = read(encounter_id)["vitals"]
    new = dict(current)
    for key, val in (values or {}).items():
        if key in _RANGES and isinstance(val, (int, float)):
            new[key] = val
    new = _bound(new, condition_for(encounter_id))
    _write_vitals(encounter_id, new, surface=surface, cause=cause, source=source)
    _add_map(new)
    return new


# ── Rhythm ───────────────────────────────────────────────────────────────────

def rhythm_for(encounter_id: str) -> str:
    enc = _encounter(encounter_id)
    return getattr(enc, "ecg_rhythm_id", "nsr") if enc is not None else "nsr"


def set_rhythm(encounter_id: str, rhythm_id: str, *, source: str = "virtual") -> str:
    """Set the ECG rhythm (validated against the rhythm catalog). Authority-gated."""
    from . import ecg
    if not ecg.is_valid_id(rhythm_id):
        raise ValueError(f"unknown rhythm_id {rhythm_id!r}")
    if not is_authority(source, encounter_id):
        return rhythm_for(encounter_id)
    enc = _encounter(encounter_id)
    if enc is not None:
        enc.ecg_rhythm_id = rhythm_id
    return rhythm_id


# ── Resumability (FR-011 G1 seam — wired into session_state in D7) ────────────

def snapshot() -> dict[str, Any]:
    """PHI-free structured state for restart survival: the source registry +
    per-patient conditions. (Vitals themselves already live in the durable
    event log.)"""
    return {
        "sources": {eid: dict(srcs) for eid, srcs in _sources.items()},
        "conditions": dict(_conditions),
    }


def restore(blob: dict[str, Any] | None) -> None:
    _sources.clear()
    _conditions.clear()
    if not blob:
        return
    for eid, srcs in (blob.get("sources") or {}).items():
        if isinstance(srcs, dict):
            _sources[eid] = {s: bool(h) for s, h in srcs.items()}
    for eid, cond in (blob.get("conditions") or {}).items():
        if cond in CONDITIONS:
            _conditions[eid] = cond
