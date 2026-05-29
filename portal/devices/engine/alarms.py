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


def catalog_for(device_kind: str) -> dict[str, dict[str, Any]]:
    """All tones a device of this kind can play."""
    if device_kind in ("pump_iv", "pump_enteral"):
        return dict(PUMP_ALARMS)
    if device_kind == "cabinet":
        return dict(CABINET_ALERTS)
    return {}


def audio_url(device_kind: str, tone_id: str) -> str:
    """URL the device front-end uses to fetch the WAV file."""
    if device_kind == "cabinet":
        return f"/static/devices/audio/alerts/{tone_id}.wav"
    return f"/static/devices/audio/alarms/{tone_id}.wav"
