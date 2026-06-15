"""portal/vent_faults.py — FR-012 D6: ventilator fault injection.

A curated, bounded catalog of common real-world ventilator problems the
instructor injects into a running scenario (the FR-008 arm-and-catch model, for
the ventilator). Each fault:
  * perturbs the EFFECTIVE vent state — abnormality flags (leak, secretions,
    overdistension) and/or patient-mechanics / setting overrides (resistance,
    compliance, rr, fio2) — so the airway waveforms + numerics show the
    signature and the matching EQUIPMENT alarm auto-fires (vent_state.evaluate);
  * imposes a bounded gas-exchange PENALTY (SpO2 down / EtCO2 up) and, where
    relevant, a direct HR/BP IMPACT, so it moves GLOBAL patient physiology
    (visible on the monitor + nurse station);
  * carries a RESOLUTION the student must perform.

Clearing a fault rebuilds the effective state from the remaining armed faults and
lets the ventilator coupling recover the patient. PHI-free (structured only).
"""
from __future__ import annotations

import logging
import time
from typing import Any

from . import physiology, vent_state

log = logging.getLogger(__name__)

# id -> definition. flags: abnormality drivers; overrides: effective-setting
# overrides layered over the student's settings; condition: physiology envelope;
# penalty: SpO2 down / EtCO2 up the settings alone can't express; impact: direct
# vitals delta (HR/BP); alarms: the equipment alarm(s) it should raise (doc);
# resolution: the corrective action; severity for the board.
FAULTS: dict[str, dict[str, Any]] = {
    "air_leak": {
        "label": "Air leak (cuff / circuit)", "severity": "high",
        "flags": {"leak_fraction": 0.6}, "penalty": {"spo2": 9, "etco2": 4},
        "alarms": ["low_tidal_volume", "low_minute_volume", "peep_loss"],
        "resolution": "Reseat / inflate the ET cuff and check every circuit connection.",
    },
    "circuit_disconnect": {
        "label": "Circuit disconnect", "severity": "critical",
        "flags": {"leak_fraction": 0.97}, "penalty": {"spo2": 22, "etco2": 8},
        "alarms": ["low_pressure", "low_minute_volume", "low_tidal_volume"],
        "resolution": "Reconnect the ventilator circuit to the airway.",
    },
    "et_obstruction": {
        "label": "ET tube obstruction (kink / bite / mucus plug)", "severity": "high",
        "overrides": {"resistance_cmh2o_l_s": 90}, "penalty": {"spo2": 8, "etco2": 6},
        "alarms": ["high_pressure"],
        "resolution": "Suction the airway; relieve the kink / bite (insert a bite block).",
    },
    "secretions": {
        "label": "Secretions", "severity": "medium",
        "flags": {"secretions": True}, "overrides": {"resistance_cmh2o_l_s": 70},
        "penalty": {"spo2": 5, "etco2": 5}, "alarms": ["high_pressure"],
        "resolution": "Suction the airway.",
    },
    "bronchospasm": {
        "label": "Bronchospasm", "severity": "high",
        "overrides": {"resistance_cmh2o_l_s": 80}, "penalty": {"spo2": 7, "etco2": 7},
        "alarms": ["high_pressure"],
        "resolution": "Administer a bronchodilator; reassess for wheeze.",
    },
    "patient_bucking": {
        "label": "Patient bucking / coughing (dyssynchrony)", "severity": "high",
        "flags": {"overdistension": True}, "overrides": {"resistance_cmh2o_l_s": 60},
        "penalty": {"spo2": 3}, "impact": {"hr": 18}, "alarms": ["high_pressure"],
        "resolution": "Improve synchrony — sedation / analgesia; reassess trigger + mode.",
    },
    "compliance_drop": {
        "label": "Decreased compliance (ARDS / edema / pneumothorax)", "severity": "high",
        "overrides": {"compliance_ml_cmh2o": 16}, "condition": "ards", "penalty": {"spo2": 6},
        "alarms": ["high_pressure"],
        "resolution": "Recruit (titrate PEEP / FiO2); treat the cause.",
    },
    "auto_peep": {
        "label": "Auto-PEEP / air-trapping", "severity": "medium",
        "overrides": {"resistance_cmh2o_l_s": 28}, "penalty": {"spo2": 4},
        "impact": {"sbp": -14, "dbp": -8}, "alarms": ["auto_peep"],
        "resolution": "Lengthen expiratory time — lower RR / shorten I:E; treat the obstruction.",
    },
    "apnea": {
        "label": "Apnea (oversedation / central)", "severity": "critical",
        "overrides": {"rr": 0}, "penalty": {"spo2": 8, "etco2": 12},
        "alarms": ["apnea", "low_minute_volume"],
        "resolution": "Restore backup ventilation / reduce sedation — the patient stopped triggering.",
    },
    "o2_supply": {
        "label": "O2 supply failure", "severity": "high",
        "overrides": {"fio2": 0.21}, "penalty": {"spo2": 5}, "alarms": ["o2_supply"],
        "resolution": "Restore the wall O2 / cylinder / blender supply.",
    },
    "exhalation_valve_leak": {
        "label": "Exhalation valve leak", "severity": "medium",
        "flags": {"leak_fraction": 0.2}, "penalty": {"spo2": 4}, "alarms": ["peep_loss"],
        "resolution": "Service or replace the exhalation valve.",
    },
}

_armed: dict[str, dict[str, dict]] = {}   # encounter_id -> {fault_id: record}


def catalog() -> list[dict[str, Any]]:
    return [{"id": k, "label": v["label"], "severity": v["severity"],
             "alarms": v.get("alarms", []), "resolution": v["resolution"]}
            for k, v in FAULTS.items()]


def active(encounter_id: str) -> list[dict[str, Any]]:
    return [{"id": fid, "label": FAULTS[fid]["label"], "severity": FAULTS[fid]["severity"],
             "resolution": FAULTS[fid]["resolution"], "armed_at": rec.get("armed_at")}
            for fid, rec in _armed.get(encounter_id, {}).items() if fid in FAULTS]


def _reapply(encounter_id: str) -> None:
    """Rebuild the effective fault state (flags + overrides + penalty + condition)
    from the currently-armed faults, then re-couple physiology + re-evaluate vent
    alarms (via vent_state.set_settings)."""
    armed = _armed.get(encounter_id, {})
    vent_state.clear_faults(encounter_id)
    flags: dict[str, Any] = {}
    overrides: dict[str, Any] = {}
    pen = {"spo2": 0.0, "etco2": 0.0}
    for fid in armed:
        f = FAULTS[fid]
        flags.update(f.get("flags", {}))
        overrides.update(f.get("overrides", {}))
        p = f.get("penalty", {})
        pen["spo2"] += p.get("spo2", 0)
        pen["etco2"] += p.get("etco2", 0)
        if f.get("condition"):
            try:
                physiology.set_condition(encounter_id, f["condition"])
            except Exception:  # noqa: BLE001
                pass
    vent_state.set_faults(encounter_id, flags)
    vent_state.set_fault_overrides(encounter_id, overrides)
    vent_state.set_fault_penalty(encounter_id, pen["spo2"], pen["etco2"])
    vent_state.set_settings(encounter_id, {})   # re-couple (with penalty) + re-evaluate


def arm(encounter_id: str, fault_id: str):
    """Inject a ventilator fault. Returns (active_faults, error)."""
    f = FAULTS.get(fault_id)
    if not f:
        return None, f"unknown ventilator fault {fault_id!r}"
    if fault_id in _armed.get(encounter_id, {}):
        return active(encounter_id), None       # idempotent — already armed
    impact = f.get("impact") or {}
    captured = {k: physiology.read(encounter_id)["vitals"].get(k) for k in impact}
    _armed.setdefault(encounter_id, {})[fault_id] = {
        "fault_id": fault_id, "armed_at": time.time(), "captured": captured}
    _reapply(encounter_id)
    if impact:
        physiology.apply_delta(encounter_id, impact, surface="device_fault",
                               cause="vent_fault:" + fault_id)
    return active(encounter_id), None


def clear(encounter_id: str, fault_id: str) -> list[dict[str, Any]]:
    rec = _armed.get(encounter_id, {}).pop(fault_id, None)
    if not rec:
        return active(encounter_id)
    _reapply(encounter_id)   # rebuild from remaining; coupling recovers SpO2/EtCO2
    captured = rec.get("captured") or {}
    restore = {k: v for k, v in captured.items() if v is not None}
    if restore:              # walk the direct-impact vitals (HR/BP) back toward baseline
        physiology.set_vitals(encounter_id, restore, surface="device_fault",
                              cause="vent_fault_cleared:" + fault_id)
    return active(encounter_id)


def clear_all(encounter_id: str) -> None:
    for fid in list(_armed.get(encounter_id, {})):
        clear(encounter_id, fid)


# ── Resumability (wired into session_state in D7) ────────────────────────────

def snapshot() -> dict[str, Any]:
    return {e: {fid: dict(rec) for fid, rec in faults.items()}
            for e, faults in _armed.items()}


def restore(blob: dict[str, Any] | None) -> None:
    _armed.clear()
    if not blob:
        return
    for e, faults in blob.items():
        if isinstance(faults, dict):
            _armed[e] = {fid: dict(rec) for fid, rec in faults.items() if fid in FAULTS}
