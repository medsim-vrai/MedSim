"""portal/telemetry_monitor.py — FR-012 D3: telemetry-monitor alarm engine.

Turns live physiology (``portal.physiology.read``) into the nursing-station
alarm set (plan §4) on a ``telemetry_monitor`` device: AUTO-fires
``alarm.injected`` when a vital crosses a limit (or a lethal rhythm appears) and
auto-clears when it resolves, flowing through the existing alarm bus
(``portal/alarms.py``) + device audio + the control-room board. Instructor
arm/silence/clear still work via the device inject/clear/silence routes — auto
and manual alarms share one model, distinguished by the event ``surface``.

v8 has no background ticker, so evaluation is CHANGE-DRIVEN: ``physiology`` calls
``evaluate()`` right after it writes vitals/rhythm (faults D6, vent controls D5,
scenes), and the monitor bootstrap evaluates once so a freshly-opened monitor
reflects current breaches.
"""
from __future__ import annotations

import logging
from typing import Any

from . import ehr_db, physiology

log = logging.getLogger(__name__)

AUTO_SURFACE = "auto"   # marks an alarm raised by threshold logic (vs instructor)

# Default per-metric limits [low, high]; a value strictly outside fires the
# matching alarm. Instructor-tunable per device is a later refinement; these
# mirror the bundle's spec.json default_alarm_limits.
DEFAULT_LIMITS: dict[str, tuple[float, float]] = {
    "hr":   (50, 120),
    "spo2": (90, 100),
    "rr":   (8, 30),
    "sbp":  (90, 180),
    "etco2": (25, 60),
}
# Red (high-priority) severe thresholds.
_HR_BRADY_SEVERE = 40
_HR_TACHY_SEVERE = 150
_RR_APNEA = 6
# Lethal-rhythm id (v8 ECG catalog, portal/ecg.py) → alarm tone.
_RHYTHM_ALARM = {
    "asystole": "asystole", "asys": "asystole", "pea": "asystole",
    "vfib": "vfib", "vf": "vfib", "v_fib": "vfib",
    "vtach": "vtach", "vt": "vtach", "v_tach": "vtach",
    "vtach_mono": "vtach", "vtach_poly": "vtach",
}


def expected_alarms(vitals: dict[str, Any], rhythm: str | None,
                    limits: dict[str, tuple[float, float]] | None = None) -> set[str]:
    """PURE: the set of catalog tones a physiology state warrants."""
    lim = {**DEFAULT_LIMITS, **(limits or {})}
    out: set[str] = set()

    lethal = (rhythm or "").lower() in _RHYTHM_ALARM
    if lethal:
        out.add(_RHYTHM_ALARM[(rhythm or "").lower()])

    hr = vitals.get("hr")
    if not lethal and isinstance(hr, (int, float)):   # HR is meaningless in VF/asystole
        if hr <= _HR_BRADY_SEVERE:
            out.add("brady_severe")
        elif hr < lim["hr"][0]:
            out.add("brady")
        if hr >= _HR_TACHY_SEVERE:
            out.add("tachy_severe")
        elif hr > lim["hr"][1]:
            out.add("tachy")

    spo2 = vitals.get("spo2")
    if isinstance(spo2, (int, float)) and spo2 < lim["spo2"][0]:
        out.add("spo2_low")

    rr = vitals.get("rr")
    if isinstance(rr, (int, float)):
        if rr <= _RR_APNEA:
            out.add("apnea")
        elif rr > lim["rr"][1]:
            out.add("rr_high")

    sbp = vitals.get("sbp")
    if isinstance(sbp, (int, float)):
        if sbp > lim["sbp"][1]:
            out.add("nibp_high")
        elif sbp < lim["sbp"][0]:
            out.add("nibp_low")
    return out


def _limits_for(station: dict[str, Any]) -> dict[str, tuple[float, float]]:
    # D3: bundle defaults. Per-device instructor-tunable limits are a later add.
    return DEFAULT_LIMITS


def evaluate(encounter_id: str, *, surface: str = AUTO_SURFACE) -> dict[str, Any]:
    """Re-evaluate auto alarms for every telemetry_monitor on this encounter:
    fire alarm.injected for newly-breached tones, clear AUTO alarms that no
    longer apply. Instructor-armed alarms are left untouched. Idempotent."""
    from .devices.engine.state_machine import make_engine

    summary: dict[str, list[Any]] = {"fired": [], "cleared": []}
    try:
        snap = physiology.read(encounter_id)
    except Exception:  # noqa: BLE001 — never let a monitor eval break a vitals write
        log.debug("telemetry_monitor: physiology.read failed for %s", encounter_id,
                  exc_info=True)
        return summary

    stations = [s for s in (ehr_db.device_stations(encounter_id) or [])
                if s.get("device_kind") == "telemetry_monitor"]
    for st in stations:
        want = expected_alarms(snap["vitals"], snap["rhythm"], _limits_for(st))
        try:
            eng = make_engine(session_id=encounter_id, station_id=st["id"],
                              device_kind="telemetry_monitor",
                              device_model=st["device_model"])
            active = {a["tone"]: a for a in eng.fold().get("active_alarms", [])}
            for tone in want:
                if tone not in active:
                    eng.handle(type="alarm.injected", surface=surface,
                               payload={"tone": tone, "auto": True})
                    summary["fired"].append((st["id"], tone))
            for tone, a in active.items():
                # Only auto-clear alarms WE raised; leave instructor-armed ones.
                if tone not in want and a.get("source") == surface:
                    eng.handle(type="alarm.cleared", surface=surface,
                               payload={"tone": tone})
                    summary["cleared"].append((st["id"], tone))
        except Exception:  # noqa: BLE001 — one bad station never blocks the rest
            log.exception("telemetry_monitor: evaluate failed for station %s",
                          st.get("id"))
    return summary


# Instructor "inject this condition" -> the PHYSIOLOGY that produces it, so the
# monitor's HR / ECG / SpO2 actually change and the matching alarm AUTO-fires
# (coherent). Rhythm ids are v8 ECG catalog ids (portal/ecg.py).
CLINICAL_EFFECTS: dict[str, dict[str, Any]] = {
    "brady_severe": {"rhythm": "sinus_brady", "vitals": {"hr": 35}},
    "brady":        {"rhythm": "sinus_brady", "vitals": {"hr": 46}},
    "tachy_severe": {"rhythm": "sinus_tachy", "vitals": {"hr": 165}},
    "tachy":        {"rhythm": "sinus_tachy", "vitals": {"hr": 130}},
    "spo2_low":     {"vitals": {"spo2": 82}},
    "apnea":        {"vitals": {"rr": 4}},
    "rr_high":      {"vitals": {"rr": 34}},
    "nibp_high":    {"vitals": {"sbp": 196, "dbp": 112}},
    "nibp_low":     {"vitals": {"sbp": 78, "dbp": 44}},
    "asystole":     {"rhythm": "asystole",   "vitals": {"hr": 0, "spo2": 60}},
    "vfib":         {"rhythm": "vfib",       "vitals": {"hr": 0, "spo2": 55}},
    "vtach":        {"rhythm": "vtach_mono", "vitals": {"hr": 180}},
}


def inject_clinical(encounter_id: str, tone: str) -> bool:
    """Apply the physiology that PRODUCES a condition so HR/ECG/SpO2 change and
    the alarm auto-fires. Returns False for tones with no physiology mapping
    (equipment/advisory alarms — leads_off, pvc_frequent, afib) so the caller
    falls back to sounding a plain tone."""
    effect = CLINICAL_EFFECTS.get(tone)
    if not effect:
        return False
    from . import physiology
    rhythm = effect.get("rhythm")
    if rhythm:
        try:
            physiology.set_rhythm(encounter_id, rhythm)
        except Exception:  # noqa: BLE001 — a rhythm-catalog miss never blocks the vitals
            log.debug("inject_clinical: set_rhythm(%s) failed", rhythm, exc_info=True)
    vitals = effect.get("vitals")
    if vitals:
        physiology.set_vitals(encounter_id, vitals)   # the hook auto-evaluates -> alarm
    else:
        evaluate(encounter_id)
    return True
