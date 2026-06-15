"""portal/vent_model.py — FR-012 D4: ventilator breath model (pressure / flow /
volume + bedside numerics) from a lumped resistance-compliance model.

A reimplementation in v8 of the PhysioBridge ventilator synthesis model
(`physiobridge/waveform/vent/scalars.py`, read-only reference). Pure + dependency
free: a breath is parametrized by mode (VC/PC), rate, tidal volume, PEEP,
compliance, resistance, and I:E. Inspiration is constant-flow (VC) or
decelerating (PC); expiration is passive exponential decay with time constant
tau = R*C. Pressure P = PEEP + flow*R + volume/C. Abnormality drivers (leak,
overdistension/beaking, flow starvation, secretions, air-trapping via short Te)
shape the SAME equations so a trace only shows an abnormality when the physiology
warrants it — these are the levers FR-012 D6 (vent fault injection) pulls.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# v8 device/UI use Chatburn mode names; the breath model only cares whether the
# inspiratory flow is constant (volume targeted) or decelerating (pressure
# targeted). Map one to the other.
_PRESSURE_MODES = {"PC-CMV", "PRVC", "PSV", "CPAP", "PC"}


def model_mode(chatburn_mode: str | None) -> str:
    """Chatburn mode name -> breath-model mode ('VC' | 'PC')."""
    return "PC" if (chatburn_mode or "").upper() in _PRESSURE_MODES else "VC"


@dataclass
class VentState:
    mode: str = "VC"                       # breath-model mode: 'VC' | 'PC'
    rr: float = 14.0                       # set respiratory rate (breaths/min)
    tidal_volume_ml: float = 450.0
    peep: float = 5.0                      # cmH2O
    pip: float = 20.0                      # cmH2O (PC target)
    compliance_ml_cmh2o: float = 50.0
    resistance_cmh2o_l_s: float = 10.0
    ie_ratio: float = 2.0                  # E:I, i.e. I:E = 1:ie_ratio
    inspiratory_time_s: float | None = None
    fio2: float = 0.40
    psupport: float = 10.0
    trigger_sensitivity: float = 2.0
    rise_time_ms: float = 100.0
    cycle_pct: float = 25.0
    apnea_time_s: float = 20.0
    high_pressure_limit: float = 35.0      # cmH2O alarm/relief
    # abnormality drivers (FR-012 D6)
    leak_fraction: float = 0.0             # fraction of Vt not exhaled past the sensor
    overdistension: bool = False           # beaking at end-inspiration
    flow_starvation: bool = False          # scooped (concave) inspiratory pressure
    secretions: bool = False               # sawtooth expiratory flow

    @property
    def breath_period_s(self) -> float:
        return 60.0 / max(1.0, self.rr)

    @property
    def time_constant_s(self) -> float:
        return max(0.05, self.resistance_cmh2o_l_s * (self.compliance_ml_cmh2o / 1000.0))

    @property
    def ti_s(self) -> float:
        if self.inspiratory_time_s:
            return self.inspiratory_time_s
        return self.breath_period_s / (1.0 + self.ie_ratio)

    @property
    def te_s(self) -> float:
        return self.breath_period_s - self.ti_s


@dataclass
class VentWaveforms:
    t: list[float]
    pressure: list[float]     # cmH2O
    flow: list[float]         # L/s (insp +, exp -)
    volume: list[float]       # mL (resets to baseline each breath)
    sample_rate_hz: float
    state: VentState = field(repr=False)


_SETTINGS_FIELDS = (
    "mode", "rr", "tidal_volume_ml", "peep", "pip", "fio2", "ie_ratio",
    "compliance_ml_cmh2o", "resistance_cmh2o_l_s", "psupport",
    "trigger_sensitivity", "rise_time_ms", "cycle_pct", "apnea_time_s",
    "high_pressure_limit", "inspiratory_time_s",
)
_FAULT_FIELDS = ("leak_fraction", "overdistension", "flow_starvation", "secretions")


def state_from_settings(settings: dict, faults: dict | None = None) -> VentState:
    """Build a VentState from a settings dict (Chatburn mode is mapped) plus
    optional abnormality flags. Unknown keys are ignored."""
    kw = {k: settings[k] for k in _SETTINGS_FIELDS if k in settings and k != "mode"}
    kw["mode"] = model_mode(settings.get("mode"))
    for k in _FAULT_FIELDS:
        if faults and k in faults:
            kw[k] = faults[k]
    return VentState(**kw)


def _breath_point(s: VentState, tb: float, ti: float, tau: float,
                  vt: float, insp_flow: float):
    peep, r, c = s.peep, s.resistance_cmh2o_l_s, s.compliance_ml_cmh2o
    leak_resid = s.leak_fraction * vt
    if tb <= ti:                                   # inspiration
        frac = tb / ti if ti > 0 else 1.0
        if s.mode == "PC":
            rise = max(0.05, 0.5 * tau)
            v = vt * (1.0 - math.exp(-tb / rise))
            f = (vt / 1000.0) / rise * math.exp(-tb / rise)
            p = peep + (s.pip - peep)
        else:                                      # VC — constant inspiratory flow
            v = vt * frac
            f = insp_flow
            p = peep + f * r + v / c
            if s.flow_starvation:
                p -= 4.0 * math.sin(math.pi * frac)     # concave "scoop"
        if s.overdistension and frac > 0.7:
            p += 80.0 * (frac - 0.7) ** 2               # beaking near end-inspiration
        return p, f, v
    te = tb - ti                                   # expiration — passive decay
    decay = math.exp(-te / tau)
    v = leak_resid + (vt - leak_resid) * decay
    f = -((vt - leak_resid) / 1000.0) / tau * decay
    p = peep + (vt / c) * decay
    if s.secretions:
        f += 0.06 * math.sin(2.0 * math.pi * 8.0 * te) * decay   # sawtooth serration
    return p, f, v


def synthesize(state: VentState, *, breaths: int = 2,
               sample_rate_hz: float = 100.0) -> VentWaveforms:
    t_period, ti, tau = state.breath_period_s, state.ti_s, state.time_constant_s
    vt = state.tidal_volume_ml
    insp_flow = (vt / 1000.0) / ti if ti > 0 else 0.0
    n = int(round(breaths * t_period * sample_rate_hz))
    ts, ps, fs, vs = [], [], [], []
    for i in range(n):
        t = i / sample_rate_hz
        p, f, v = _breath_point(state, t % t_period, ti, tau, vt, insp_flow)
        ts.append(t)
        ps.append(p)
        fs.append(f)
        vs.append(v)
    return VentWaveforms(ts, ps, fs, vs, float(sample_rate_hz), state)


def ventilator_numerics(state: VentState) -> dict:
    """The bedside numeric set: Ppeak, Pplateau, Pmean, Cdyn/Cstat, Raw, MV …"""
    wf = synthesize(state, breaths=1, sample_rate_hz=100.0)
    insp_flow = (state.tidal_volume_ml / 1000.0) / state.ti_s if state.ti_s > 0 else 0.0
    ppeak = max(wf.pressure)
    pplateau = state.peep + state.tidal_volume_ml / state.compliance_ml_cmh2o
    pmean = sum(wf.pressure) / len(wf.pressure)
    cdyn = state.tidal_volume_ml / max(0.1, ppeak - state.peep)
    cstat = state.tidal_volume_ml / max(0.1, pplateau - state.peep)
    raw = (ppeak - pplateau) / max(0.01, insp_flow)
    # Exhaled tidal volume drops with a leak — the measured Vt a monitor shows.
    vt_exhaled = state.tidal_volume_ml * (1.0 - state.leak_fraction)
    return {
        "mode": state.mode,
        "vt_ml": round(state.tidal_volume_ml),
        "vt_exhaled_ml": round(vt_exhaled),
        "rr": round(state.rr),
        "peep": round(state.peep, 1),
        "fio2": round(state.fio2, 2),
        "ppeak": round(ppeak, 1),
        "pplateau": round(pplateau, 1),
        "pmean": round(pmean, 1),
        "ie": f"1:{state.ie_ratio:g}",
        "minute_vent_l": round(vt_exhaled * state.rr / 1000.0, 1),
        "cdyn": round(cdyn, 1),
        "cstat": round(cstat, 1),
        "raw": round(raw, 1),
    }


# ── VC0: control surface — mode-aware ranges + validation + set-vs-measured ──
# Ported from PhysioBridge waveform/vent/control_settings.py. Modes keyed by the
# Chatburn concept so one vocabulary feeds the UI, the breath model, and coupling.

@dataclass(frozen=True)
class ControlSpec:
    name: str
    label: str
    unit: str
    lo: float
    hi: float
    step: float
    default: float


RANGES: dict[str, ControlSpec] = {
    "fio2": ControlSpec("fio2", "FiO2", "", 0.21, 1.0, 0.01, 0.40),
    "peep": ControlSpec("peep", "PEEP", "cmH2O", 0, 24, 1, 5),
    "tidal_volume_ml": ControlSpec("tidal_volume_ml", "Vt", "mL", 200, 800, 10, 450),
    "pip": ControlSpec("pip", "Pinsp", "cmH2O", 5, 50, 1, 18),
    "rr": ControlSpec("rr", "RR", "/min", 4, 40, 1, 14),
    "ie_ratio": ControlSpec("ie_ratio", "I:E (1:n)", "", 1.0, 4.0, 0.5, 2.0),
    "psupport": ControlSpec("psupport", "P-support", "cmH2O", 0, 30, 1, 10),
    "trigger_sensitivity": ControlSpec("trigger_sensitivity", "Trigger", "L/min", 0.5, 10, 0.5, 2.0),
    "rise_time_ms": ControlSpec("rise_time_ms", "Rise", "ms", 0, 400, 50, 100),
    "cycle_pct": ControlSpec("cycle_pct", "Cycle", "%", 10, 60, 5, 25),
    "apnea_time_s": ControlSpec("apnea_time_s", "Apnea", "s", 10, 60, 5, 20),
    "high_pressure_limit": ControlSpec("high_pressure_limit", "Phigh limit", "cmH2O", 10, 60, 1, 35),
}

MODES = ["VC-CMV", "PC-CMV", "PRVC", "SIMV", "PSV", "CPAP"]

_MODE_CONTROLS: dict[str, list[str]] = {
    "VC-CMV": ["fio2", "peep", "tidal_volume_ml", "rr", "ie_ratio",
               "trigger_sensitivity", "high_pressure_limit", "apnea_time_s"],
    "PC-CMV": ["fio2", "peep", "pip", "rr", "ie_ratio", "trigger_sensitivity",
               "rise_time_ms", "high_pressure_limit", "apnea_time_s"],
    "PRVC": ["fio2", "peep", "tidal_volume_ml", "rr", "ie_ratio",
             "trigger_sensitivity", "high_pressure_limit", "apnea_time_s"],
    "SIMV": ["fio2", "peep", "tidal_volume_ml", "rr", "psupport",
             "trigger_sensitivity", "cycle_pct", "high_pressure_limit", "apnea_time_s"],
    "PSV": ["fio2", "peep", "psupport", "trigger_sensitivity", "rise_time_ms",
            "cycle_pct", "high_pressure_limit", "apnea_time_s"],
    "CPAP": ["fio2", "peep", "trigger_sensitivity", "high_pressure_limit", "apnea_time_s"],
}


def controls_for(mode: str) -> list[str]:
    """Ordered control names available in a Chatburn mode."""
    return list(_MODE_CONTROLS.get(mode if mode in _MODE_CONTROLS else "VC-CMV"))


def validate(param: str, value, *, mode: str | None = None):
    """Validate + step-snap a control value. Returns (snapped_value, error)."""
    if param == "mode":
        return (None, None) if str(value) in _MODE_CONTROLS else (None, f"unknown mode {value!r}")
    spec = RANGES.get(param)
    if spec is None:
        return None, f"unknown control {param!r}"
    if mode is not None and param not in controls_for(mode):
        return None, f"{param} is not available in {mode}"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None, f"{param} must be numeric"
    if v < spec.lo or v > spec.hi:
        return None, f"{param}={v} out of range [{spec.lo}, {spec.hi}] {spec.unit}".strip()
    snapped = round(round((v - spec.lo) / spec.step) * spec.step + spec.lo, 4)
    return snapped, None


def set_vs_measured(settings: dict, numerics: dict) -> list[dict]:
    """Pair commanded (set) values with engine-measured values for the screen."""
    rows = [
        {"label": "Ppeak", "set": None, "measured": numerics.get("ppeak"), "unit": "cmH2O"},
        {"label": "Pplateau", "set": None, "measured": numerics.get("pplateau"), "unit": "cmH2O"},
    ]
    for label, set_key, meas_key, unit in (
        ("Vt", "tidal_volume_ml", "vt_exhaled_ml", "mL"),
        ("RR", "rr", "rr", "/min"),
        ("PEEP", "peep", "peep", "cmH2O"),
        ("FiO2", "fio2", "fio2", ""),
    ):
        rows.append({"label": label, "set": settings.get(set_key),
                     "measured": numerics.get(meas_key), "unit": unit})
    return rows


# ── VC1: ventilator → physiology coupling (closed-loop targets) ──────────────
# Ported from PhysioBridge engine/vent_coupling.py. Monotonic + bounded: FiO2
# raises oxygenation toward a shunt/condition-limited ceiling; PEEP recruits to
# an optimum then overdistends; minute ventilation clears CO2; condition caps it.
PEEP_OPTIMUM = 10.0
OVERDISTENSION_PEEP = 16.0
_COUPLING_ENV: dict[str, dict] = {
    "normal":    {"spo2_ceiling": 100.0, "shunt": 0.05, "co2_production": 1.0},
    "ards":      {"spo2_ceiling": 99.0,  "shunt": 0.35, "co2_production": 1.1},
    "copd":      {"spo2_ceiling": 96.0,  "shunt": 0.15, "co2_production": 1.0},
    "pneumonia": {"spo2_ceiling": 98.0,  "shunt": 0.22, "co2_production": 1.05},
    "sepsis":    {"spo2_ceiling": 99.0,  "shunt": 0.10, "co2_production": 1.3},
}


def minute_ventilation(state: VentState) -> float:
    if state.mode == "PC":
        vt = max(50.0, (state.pip - state.peep) * state.compliance_ml_cmh2o)
    else:
        vt = state.tidal_volume_ml
    return max(0.5, vt * state.rr / 1000.0)


def ventilator_targets(state: VentState, condition: str = "normal") -> dict:
    """The gas-exchange targets the current settings drive the patient toward."""
    env = _COUPLING_ENV.get(condition, _COUPLING_ENV["normal"])
    fio2_norm = max(0.0, (state.fio2 - 0.21) / 0.79)
    peep_recruit = max(0.0, 1.0 - abs(state.peep - PEEP_OPTIMUM) / PEEP_OPTIMUM)
    support = 0.6 * fio2_norm + 0.4 * peep_recruit
    overdist = max(0.0, state.peep - OVERDISTENSION_PEEP) * 1.2
    shunt_relief = min(0.7, 0.5 * fio2_norm + 0.4 * peep_recruit)
    achievable = env["spo2_ceiling"] - env["shunt"] * 25.0 * (1.0 - shunt_relief) - overdist
    spo2 = max(60.0, min(achievable, 96.0 + support * 4.0))
    mv = minute_ventilation(state)
    etco2 = max(15.0, min(90.0, 40.0 * env["co2_production"] * (5.5 / mv)))
    return {
        "spo2": round(spo2, 1),
        "etco2": round(etco2, 1),
        "minute_ventilation": round(mv, 1),
        "overdistension": (state.peep > OVERDISTENSION_PEEP
                           or (state.mode == "PC" and state.pip > 35.0)
                           or (state.mode == "VC" and state.tidal_volume_ml > 560.0)),
        "hyperoxia": state.fio2 > 0.6,
    }
