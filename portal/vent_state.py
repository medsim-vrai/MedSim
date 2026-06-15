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

_settings: dict[str, dict] = {}   # encounter_id -> STUDENT settings (mode/fio2/peep/...)
_faults:   dict[str, dict] = {}   # encounter_id -> abnormality flags (leak/secretions/...)
# FR-012 D6 — fault perturbations layered ON TOP of student settings (patient
# mechanics + rr/fio2 overrides) and the gas-exchange penalty active faults impose.
_fault_overrides: dict[str, dict] = {}   # encounter_id -> {key: value}
_fault_penalty:   dict[str, dict] = {}   # encounter_id -> {"spo2": x, "etco2": y}


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
        pen = fault_penalty_for(encounter_id)
        physiology.set_vitals(encounter_id,
                              {"spo2": tgt["spo2"] - pen.get("spo2", 0.0),
                               "etco2": tgt["etco2"] + pen.get("etco2", 0.0)},
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


# ── State presets — pick a clinical state, everything aligns ─────────────────
# The instructor selects a state and the ventilator settings + patient mechanics
# + physiology condition + vitals all snap to a coherent picture; per-parameter
# injects / control changes then fine-tune. Conditions match physiology.CONDITIONS.
STATE_PRESETS: dict[str, dict[str, Any]] = {
    "stable": {"label": "Stable / normal lungs", "condition": "normal",
               "settings": {"mode": "VC-CMV", "fio2": 0.40, "peep": 5, "tidal_volume_ml": 450,
                            "rr": 14, "ie_ratio": 2.0, "compliance_ml_cmh2o": 50, "resistance_cmh2o_l_s": 10}},
    "ards": {"label": "ARDS — lung-protective", "condition": "ards",
             "settings": {"mode": "PC-CMV", "fio2": 0.70, "peep": 12, "tidal_volume_ml": 360,
                          "rr": 22, "pip": 28, "compliance_ml_cmh2o": 28, "resistance_cmh2o_l_s": 12}},
    "copd": {"label": "COPD — obstructive", "condition": "copd",
             "settings": {"mode": "VC-CMV", "fio2": 0.40, "peep": 5, "tidal_volume_ml": 420,
                          "rr": 12, "ie_ratio": 3.0, "compliance_ml_cmh2o": 55, "resistance_cmh2o_l_s": 22}},
    "pneumonia": {"label": "Pneumonia", "condition": "pneumonia",
                  "settings": {"mode": "VC-CMV", "fio2": 0.55, "peep": 8, "tidal_volume_ml": 420,
                               "rr": 18, "ie_ratio": 2.0, "compliance_ml_cmh2o": 38, "resistance_cmh2o_l_s": 14}},
    "weaning": {"label": "Weaning / spontaneous (PSV)", "condition": "normal",
                "settings": {"mode": "PSV", "fio2": 0.35, "peep": 5, "psupport": 8,
                             "rr": 16, "compliance_ml_cmh2o": 50, "resistance_cmh2o_l_s": 10}},
}


def state_presets() -> list[dict[str, Any]]:
    return [{"id": k, "label": v["label"], "condition": v.get("condition")}
            for k, v in STATE_PRESETS.items()]


def apply_state(encounter_id: str, state_id: str):
    """Apply a clinical-state preset: set the physiology condition + the full
    ventilator settings, which couples aligned SpO2/EtCO2 + re-evaluates vent
    alarms. Returns (controls_view, error)."""
    preset = STATE_PRESETS.get(state_id)
    if not preset:
        return None, f"unknown ventilator state {state_id!r}"
    cond = preset.get("condition")
    if cond:
        try:
            from . import physiology
            physiology.set_condition(encounter_id, cond)
        except Exception:  # noqa: BLE001
            pass
    set_settings(encounter_id, preset.get("settings", {}))   # couples vitals + re-evaluates
    return controls_view(encounter_id), None


def faults_for(encounter_id: str) -> dict[str, Any]:
    return dict(_faults.get(encounter_id, {}))


def set_faults(encounter_id: str, flags: dict[str, Any]) -> dict[str, Any]:
    cur = dict(_faults.get(encounter_id, {}))
    cur.update({k: v for k, v in (flags or {}).items()})
    _faults[encounter_id] = cur
    return faults_for(encounter_id)


def clear_faults(encounter_id: str) -> None:
    _faults.pop(encounter_id, None)


def set_fault_overrides(encounter_id: str, overrides: dict[str, Any]) -> None:
    """Replace the fault-applied setting overrides (mechanics + rr/fio2)."""
    _fault_overrides[encounter_id] = dict(overrides or {})


def set_fault_penalty(encounter_id: str, spo2: float = 0.0, etco2: float = 0.0) -> None:
    """The aggregate gas-exchange penalty active faults impose (SpO2 down, EtCO2 up)
    on top of what the ventilator settings alone would achieve."""
    _fault_penalty[encounter_id] = {"spo2": float(spo2), "etco2": float(etco2)}


def fault_penalty_for(encounter_id: str) -> dict[str, float]:
    return dict(_fault_penalty.get(encounter_id, {"spo2": 0.0, "etco2": 0.0}))


def effective_settings(encounter_id: str) -> dict[str, Any]:
    """Student settings with active-fault overrides layered on top — the physics
    input for numerics/waveforms/coupling. The control view keeps showing the
    student's SET values, so set-vs-measured DIVERGES under a fault (e.g. set
    Vt 450 but a leak measures 180)."""
    return {**settings_for(encounter_id), **_fault_overrides.get(encounter_id, {})}


def _state(encounter_id: str) -> vent_model.VentState:
    return vent_model.state_from_settings(effective_settings(encounter_id),
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
    # FR-012 D6 — fault signatures the numerics alone don't capture:
    if state.leak_fraction >= 0.5:
        out.add("low_pressure")          # big leak / circuit disconnect
    if state.leak_fraction >= 0.15:
        out.add("peep_loss")             # PEEP not maintained
    if state.fio2 < 0.25:
        out.add("o2_supply")             # O2 supply / blender failure
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
            "faults": {e: dict(f) for e, f in _faults.items()},
            "fault_overrides": {e: dict(o) for e, o in _fault_overrides.items()},
            "fault_penalty": {e: dict(p) for e, p in _fault_penalty.items()}}


def restore(blob: dict[str, Any] | None) -> None:
    for d in (_settings, _faults, _fault_overrides, _fault_penalty):
        d.clear()
    if not blob:
        return
    for e, s in (blob.get("settings") or {}).items():
        if isinstance(s, dict):
            _settings[e] = dict(s)
    for e, f in (blob.get("faults") or {}).items():
        if isinstance(f, dict):
            _faults[e] = dict(f)
    for e, o in (blob.get("fault_overrides") or {}).items():
        if isinstance(o, dict):
            _fault_overrides[e] = dict(o)
    for e, p in (blob.get("fault_penalty") or {}).items():
        if isinstance(p, dict):
            _fault_penalty[e] = dict(p)
