"""portal/vent_state.py — FR-012 D4: per-encounter ventilator state.

The single source of truth for a patient's ventilator: settings (written by the
ventilator device in D5), abnormality faults (injected in D6), and the derived
numerics the vent monitor (D4) displays. Vent alarms AUTO-fire on the
vent-display + ventilator devices when the numerics breach limits — high
pressure, low tidal volume, low minute volume, apnea, auto-PEEP — through the
existing alarm bus, exactly like the telemetry monitor (portal/telemetry_monitor).

Like portal/physiology, this is the seam a richer vent engine (PhysioBridge) can
feed later. PHI-free: structured numbers + an enum mode only.
"""
from __future__ import annotations

import logging
from typing import Any

from . import ehr_db, vent_model

log = logging.getLogger(__name__)

AUTO_SURFACE = "auto"
_VENT_KINDS = ("vent_monitor", "ventilator")

# A stable adult VC-CMV breath — the default a ventilated patient shows before
# the ventilator device (D5) writes its own settings.
DEFAULT_SETTINGS: dict[str, Any] = {
    "mode": "VC-CMV", "rr": 14, "tidal_volume_ml": 450, "peep": 5.0,
    "pip": 20.0, "fio2": 0.40, "ie_ratio": 2.0,
    "compliance_ml_cmh2o": 50.0, "resistance_cmh2o_l_s": 10.0,
    "high_pressure_limit": 35.0,
}
# vent-alarm thresholds
_LOW_VT_ML = 300
_LOW_MV_L = 3.0
_AUTOPEEP_TAU_FACTOR = 2.5      # Te < factor*tau => incomplete exhalation (air-trapping)

_settings: dict[str, dict] = {}   # encounter_id -> settings
_faults:   dict[str, dict] = {}   # encounter_id -> abnormality flags


# ── State ────────────────────────────────────────────────────────────────────

def settings_for(encounter_id: str) -> dict[str, Any]:
    return {**DEFAULT_SETTINGS, **_settings.get(encounter_id, {})}


def set_settings(encounter_id: str, values: dict[str, Any]) -> dict[str, Any]:
    cur = dict(_settings.get(encounter_id, {}))
    cur.update({k: v for k, v in (values or {}).items()})
    _settings[encounter_id] = cur
    return settings_for(encounter_id)


def faults_for(encounter_id: str) -> dict[str, Any]:
    return dict(_faults.get(encounter_id, {}))


def set_faults(encounter_id: str, flags: dict[str, Any]) -> dict[str, Any]:
    cur = dict(_faults.get(encounter_id, {}))
    cur.update({k: v for k, v in (flags or {}).items()})
    _faults[encounter_id] = cur
    return faults_for(encounter_id)


def clear_faults(encounter_id: str) -> None:
    _faults.pop(encounter_id, None)


def _state(encounter_id: str) -> vent_model.VentState:
    return vent_model.state_from_settings(settings_for(encounter_id),
                                          faults_for(encounter_id))


def numerics(encounter_id: str) -> dict[str, Any]:
    return vent_model.ventilator_numerics(_state(encounter_id))


def waveforms(encounter_id: str, *, breaths: int = 2,
              sample_rate_hz: float = 50.0) -> dict[str, Any]:
    wf = vent_model.synthesize(_state(encounter_id), breaths=breaths,
                               sample_rate_hz=sample_rate_hz)
    return {"t": wf.t, "pressure": wf.pressure, "flow": wf.flow,
            "volume": wf.volume, "sample_rate_hz": wf.sample_rate_hz}


def view(encounter_id: str) -> dict[str, Any]:
    """Compact payload the vent monitor / ventilator client renders: numerics +
    the settings + fault flags it synthesizes the waveforms from."""
    return {"numerics": numerics(encounter_id),
            "settings": settings_for(encounter_id),
            "faults": faults_for(encounter_id)}


# ── Alarms ───────────────────────────────────────────────────────────────────

def expected_alarms(num: dict[str, Any], state: vent_model.VentState) -> set[str]:
    """PURE: the vent alarm tones a numerics + state warrant."""
    out: set[str] = set()
    if num["ppeak"] > state.high_pressure_limit:
        out.add("high_pressure")
    if num["vt_exhaled_ml"] < _LOW_VT_ML:
        out.add("low_tidal_volume")
    if num["minute_vent_l"] < _LOW_MV_L:
        out.add("low_minute_volume")
    if state.rr <= 0:
        out.add("apnea")
    if state.te_s < _AUTOPEEP_TAU_FACTOR * state.time_constant_s:
        out.add("auto_peep")
    return out


def evaluate(encounter_id: str, *, surface: str = AUTO_SURFACE) -> dict[str, Any]:
    """Re-evaluate vent alarms for every vent_monitor/ventilator on this
    encounter: fire newly-breached tones, clear AUTO tones that no longer apply.
    Idempotent; leaves instructor-armed alarms untouched."""
    from .devices.engine.state_machine import make_engine

    summary: dict[str, list[Any]] = {"fired": [], "cleared": []}
    try:
        state = _state(encounter_id)
        want = expected_alarms(numerics(encounter_id), state)
    except Exception:  # noqa: BLE001
        log.debug("vent_state: numerics failed for %s", encounter_id, exc_info=True)
        return summary

    stations = [s for s in (ehr_db.device_stations(encounter_id) or [])
                if s.get("device_kind") in _VENT_KINDS]
    for st in stations:
        try:
            eng = make_engine(session_id=encounter_id, station_id=st["id"],
                              device_kind=st["device_kind"],
                              device_model=st["device_model"])
            active = {a["tone"]: a for a in eng.fold().get("active_alarms", [])}
            for tone in want:
                if tone not in active:
                    eng.handle(type="alarm.injected", surface=surface,
                               payload={"tone": tone, "auto": True})
                    summary["fired"].append((st["id"], tone))
            for tone, a in active.items():
                if tone not in want and a.get("source") == surface:
                    eng.handle(type="alarm.cleared", surface=surface,
                               payload={"tone": tone})
                    summary["cleared"].append((st["id"], tone))
        except Exception:  # noqa: BLE001
            log.exception("vent_state: evaluate failed for station %s", st.get("id"))
    return summary


# ── Resumability (wired into session_state in D7) ────────────────────────────

def snapshot() -> dict[str, Any]:
    return {"settings": {e: dict(s) for e, s in _settings.items()},
            "faults": {e: dict(f) for e, f in _faults.items()}}


def restore(blob: dict[str, Any] | None) -> None:
    _settings.clear()
    _faults.clear()
    if not blob:
        return
    for e, s in (blob.get("settings") or {}).items():
        if isinstance(s, dict):
            _settings[e] = dict(s)
    for e, f in (blob.get("faults") or {}).items():
        if isinstance(f, dict):
            _faults[e] = dict(f)
