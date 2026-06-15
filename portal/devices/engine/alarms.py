"""Shared alarm + alert catalogue.

The audio assets live under ``portal/static/devices/audio/{alarms,alerts}/``.
This module names them and tags each with a default tier — devices map
their own condition codes to these tone IDs in their ``spec.json``.

Pumps use the 16-tone alarm library; cabinets use the 13-tone alert
library. Both share the same data shape so the device front-end has
exactly one playback path.
"""
from __future__ import annotations

from typing import Any

# Tier semantics (IEC 60601-1-8 inspired):
#   high     immediate action, looping
#   medium   prompt action, looping
#   low      awareness, sparse looping
#   advisory near-end / info, one-shot or slow loop
#   feedback transactional confirmation, one-shot
# Looping is the *default* — overridable per-device via spec.json.

PUMP_ALARMS: dict[str, dict[str, Any]] = {
    "alarm_high_priority":    {"tier": "high",     "loop": True,  "label": "High-priority alarm"},
    "alarm_medium_priority":  {"tier": "medium",   "loop": True,  "label": "Medium-priority alarm"},
    "alarm_low_priority":     {"tier": "low",      "loop": True,  "label": "Low-priority alarm"},
    "air_in_line":            {"tier": "high",     "loop": True,  "label": "Air in line"},
    "occlusion_downstream":   {"tier": "high",     "loop": True,  "label": "Downstream occlusion"},
    "occlusion_upstream":     {"tier": "medium",   "loop": True,  "label": "Upstream occlusion / empty"},
    "door_open":              {"tier": "high",     "loop": True,  "label": "Door / set"},
    "infusion_complete":      {"tier": "advisory", "loop": False, "label": "Infusion complete"},
    "feed_complete":          {"tier": "advisory", "loop": False, "label": "Feed / therapy complete"},
    "near_end_prealarm":      {"tier": "advisory", "loop": False, "label": "Near-end pre-alarm"},
    "low_battery":            {"tier": "medium",   "loop": True,  "label": "Low battery"},
    "depleted_battery":       {"tier": "high",     "loop": True,  "label": "Depleted battery"},
    "system_error":           {"tier": "high",     "loop": True,  "label": "System error"},
    "callback_reminder":      {"tier": "advisory", "loop": True,  "label": "Programmed-not-started"},
    "excess_flow_flofast":    {"tier": "high",     "loop": True,  "label": "Excess flow / FLO FAST"},
    "dose_done":              {"tier": "advisory", "loop": False, "label": "Dose done"},
}

CABINET_ALERTS: dict[str, dict[str, Any]] = {
    "scan_success":           {"tier": "feedback", "loop": False, "label": "Scan match"},
    "scan_mismatch":          {"tier": "feedback", "loop": False, "label": "Scan mismatch"},
    "transaction_complete":   {"tier": "feedback", "loop": False, "label": "Transaction complete"},
    "login_success":          {"tier": "feedback", "loop": False, "label": "Login OK"},
    "login_failed":           {"tier": "feedback", "loop": False, "label": "Login failed"},
    "discrepancy_alert":      {"tier": "medium",   "loop": True,  "label": "Discrepancy unresolved"},
    "witness_required":       {"tier": "medium",   "loop": True,  "label": "Witness required"},
    "inventory_low":          {"tier": "low",      "loop": True,  "label": "Inventory low"},
    "ekit_expiration":        {"tier": "low",      "loop": True,  "label": "E-kit at/near expiration"},
    "drawer_open":            {"tier": "high",     "loop": True,  "label": "Drawer left open"},
    "drawer_failure":         {"tier": "high",     "loop": True,  "label": "Drawer failure"},
    "network_offline":        {"tier": "high",     "loop": True,  "label": "Pharmacy link lost"},
    "security_alert":         {"tier": "high",     "loop": True,  "label": "Security event"},
}


# FR-012 — telemetry-monitor alarm catalogue (nursing-station standard).
# Tiers follow IEC 60601-1-8: life-threatening rhythms + desat/apnea = high.
MONITOR_ALARMS: dict[str, dict[str, Any]] = {
    "asystole":     {"tier": "high",   "loop": True, "label": "Asystole"},
    "vfib":         {"tier": "high",   "loop": True, "label": "Ventricular fibrillation"},
    "vtach":        {"tier": "high",   "loop": True, "label": "Ventricular tachycardia"},
    "brady_severe": {"tier": "high",   "loop": True, "label": "Extreme bradycardia"},
    "tachy_severe": {"tier": "high",   "loop": True, "label": "Extreme tachycardia"},
    "spo2_low":     {"tier": "high",   "loop": True, "label": "SpO2 low / desaturation"},
    "apnea":        {"tier": "high",   "loop": True, "label": "Apnea"},
    "brady":        {"tier": "medium", "loop": True, "label": "Bradycardia"},
    "tachy":        {"tier": "medium", "loop": True, "label": "Tachycardia"},
    "rr_high":      {"tier": "medium", "loop": True, "label": "Respiratory rate high"},
    "nibp_high":    {"tier": "medium", "loop": True, "label": "NIBP high"},
    "nibp_low":     {"tier": "medium", "loop": True, "label": "NIBP low"},
    "pvc_frequent": {"tier": "low",    "loop": True, "label": "Frequent PVCs"},
    "afib":         {"tier": "low",    "loop": True, "label": "Atrial fibrillation"},
    "leads_off":    {"tier": "low",    "loop": True, "label": "Leads off / artifact"},
}

# FR-012 — ventilator alarm catalogue (shared by vent_monitor + ventilator).
VENT_ALARMS: dict[str, dict[str, Any]] = {
    "high_pressure":      {"tier": "high",   "loop": True, "label": "High airway pressure"},
    "low_pressure":       {"tier": "high",   "loop": True, "label": "Low pressure / disconnect"},
    "low_minute_volume":  {"tier": "high",   "loop": True, "label": "Low minute volume"},
    "apnea":              {"tier": "high",   "loop": True, "label": "Apnea / no breath"},
    "o2_supply":          {"tier": "high",   "loop": True, "label": "O2 supply failure"},
    "vent_inop":          {"tier": "high",   "loop": True, "label": "Ventilator inoperative"},
    "power_fail":         {"tier": "high",   "loop": True, "label": "Power / battery"},
    "low_tidal_volume":   {"tier": "medium", "loop": True, "label": "Low tidal volume"},
    "high_rr":            {"tier": "medium", "loop": True, "label": "Respiratory rate high"},
    "high_minute_volume": {"tier": "medium", "loop": True, "label": "High minute volume"},
    "peep_loss":          {"tier": "medium", "loop": True, "label": "PEEP not maintained"},
    "auto_peep":          {"tier": "medium", "loop": True, "label": "Auto-PEEP / air trapping"},
    "fio2_deviation":     {"tier": "medium", "loop": True, "label": "FiO2 deviation"},
    "exhalation_valve":   {"tier": "medium", "loop": True, "label": "Exhalation valve leak"},
}

# Until bespoke monitor/vent WAVs are recorded (D3/D4), advanced-device tones
# play the existing IEC priority tones, mapped by tier.
_TIER_TO_GENERIC = {
    "high":   "alarm_high_priority",
    "medium": "alarm_medium_priority",
    "low":    "alarm_low_priority",
}
_ADVANCED_KINDS = ("telemetry_monitor", "vent_monitor", "ventilator")


def catalog_for(device_kind: str) -> dict[str, dict[str, Any]]:
    """All tones a device of this kind can play."""
    if device_kind in ("pump_iv", "pump_enteral"):
        return dict(PUMP_ALARMS)
    if device_kind == "cabinet":
        return dict(CABINET_ALERTS)
    if device_kind == "telemetry_monitor":
        return dict(MONITOR_ALARMS)
    if device_kind in ("vent_monitor", "ventilator"):
        return dict(VENT_ALARMS)
    return {}


def audio_url(device_kind: str, tone_id: str) -> str:
    """URL the device front-end uses to fetch the WAV file."""
    if device_kind == "cabinet":
        return f"/static/devices/audio/alerts/{tone_id}.wav"
    if device_kind in _ADVANCED_KINDS:
        tier = (catalog_for(device_kind).get(tone_id) or {}).get("tier", "high")
        return f"/static/devices/audio/alarms/{_TIER_TO_GENERIC.get(tier, 'alarm_high_priority')}.wav"
    return f"/static/devices/audio/alarms/{tone_id}.wav"
