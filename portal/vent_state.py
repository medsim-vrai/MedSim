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
    _couple_to_physiology(encounter_id)   # VC1 — settings drive SpO2/EtCO2
    evaluate(encounter_id)                # vent alarms re-evaluate on the new numerics
    return settings_for(encounter_id)


def _couple_to_physiology(encounter_id: str) -> None:
    """VC1 — push the gas-exchange targets the current settings produce into the
    physiology spine, so the monitor + nurse station show the response and the
    telemetry alarms re-evaluate. Bounded by the patient's condition ceiling."""
    try:
        from . import physiology, vent_model
        cond = physiology.condition_for(encounter_id)
        tgt = vent_model.ventilator_targets(_state(encounter_id), cond)
        physiology.set_vitals(encounter_id,
                              {"spo2": tgt["spo2"], "etco2": tgt["etco2"]},
                              cause="ventilator")
    except Exception:  # noqa: BLE001 — coupling is best-effort, never blocks a setting change
        log.debug("vent_state: physiology coupling failed for %s", encounter_id, exc_info=True)


def controls_view(encounter_id: str) -> dict[str, Any]:
    """The control surface the ventilator UI renders: mode, available controls,
    per-control ranges, current settings, live numerics, and set-vs-measured."""
    from . import vent_model
    s = settings_for(encounter_id)
    mode = s.get("mode", "VC-CMV")
    num = numerics(encounter_id)
    return {
        "mode": mode,
        "modes": vent_model.MODES,
        "available": vent_model.controls_for(mode),
        "ranges": {k: {"label": v.label, "unit": v.unit, "lo": v.lo, "hi": v.hi,
                       "step": v.step, "default": v.default}
                   for k, v in vent_model.RANGES.items()},
        "settings": s,
        "numerics": num,
        "set_vs_measured": vent_model.set_vs_measured(s, num),
    }


def apply_control(encounter_id: str, param: str, value: Any):
    """Validate (VC0) + apply one control change, couple to physiology (VC1), and
    re-evaluate vent alarms. Returns (controls_view, error)."""
    from . import vent_model
    if param == "mode":
        _snapped, err = vent_model.validate("mode", value)
        if err:
            return None, err
        set_settings(encounter_id, {"mode": str(value)})
        return controls_view(encounter_id), None
    mode = settings_for(encounter_id).get("mode", "VC-CMV")
    snapped, err = vent_model.validate(param, value, mode=mode)
    if err:
        return None, err
    set_settings(encounter_id, {param: snapped})
    return controls_view(encounter_id), None


def maneuver(encounter_id: str, kind: str) -> dict[str, Any]:
    """Diagnostic maneuvers: inspiratory hold → Pplateau; expiratory hold →
    auto-PEEP estimate; 100% O2 → bump FiO2 to 1.0."""
    state = _state(encounter_id)
    num = numerics(encounter_id)
    if kind == "insp_hold":
        return {"maneuver": kind, "pplateau": num["pplateau"]}
    if kind == "exp_hold":
        tau = state.time_constant_s
        ratio = (state.te_s / (2.5 * tau)) if tau else 9.0
        auto = round(max(0.0, (1.0 - min(1.0, ratio)) * 8.0), 1)   # up to ~8 cmH2O
        return {"maneuver": kind, "auto_peep": auto,
                "total_peep": round(state.peep + auto, 1)}
    if kind == "o2_100":
        set_settings(encounter_id, {"fio2": 1.0})
        return {"maneuver": kind, "fio2": 1.0}
    return {"maneuver": kind, "error": "unknown maneuver"}


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
