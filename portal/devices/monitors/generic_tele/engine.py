"""TelemetryMonitorEngine — bedside patient monitor (FR-012).

D1 (this scaffold) establishes the device-framework surface so the monitor
appears in the Advanced-devices picker, mints a QR, and renders. The base
``DeviceEngine`` already folds ``alarm.injected``/``silenced``/``cleared``, so an
instructor can fire the nursing-station alarm tones (asystole, VF/VT, desat,
apnea, …) at it today.

D3 wires it to the physiology spine (``portal/physiology.py``) for live
HR/ECG/SpO2/RR/NIBP/etCO2 and auto-fire-on-threshold against the per-device
alarm limits in ``spec.json``.
"""
from __future__ import annotations

from typing import Any

from portal.devices.engine.state_machine import DeviceEngine


class TelemetryMonitorEngine(DeviceEngine):
    device_kind = "telemetry_monitor"

    def initial_state(self) -> dict[str, Any]:
        # Representative resting vitals so the scaffold renders a believable
        # monitor; D3 replaces these with portal.physiology.read(encounter_id).
        return {
            "screen": "monitoring",
            "active_alarms": [],
            "vitals": {"hr": 78, "spo2": 98, "rr": 16,
                        "sbp": 118, "dbp": 74, "etco2": 38},
            "rhythm": "nsr",
            "alarm_limits": dict(self.spec.get("default_alarm_limits", {})),
        }
