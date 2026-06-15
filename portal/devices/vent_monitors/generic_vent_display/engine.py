"""VentMonitorEngine — ventilator display / graphics monitor (FR-012).

D1 scaffold: establishes the surface + alarm folding. D4 wires the airway
pressure/flow/volume scalars, P-V & F-V loops, and the live numerics
(Ppeak/Pplat/Pmean/PEEP/Vt/RR/MV/I:E/Cdyn/FiO2) from the vent-state contract
(read off the paired ``ventilator`` device or the physiology spine).
"""
from __future__ import annotations

from typing import Any

from portal.devices.engine.state_machine import DeviceEngine


class VentMonitorEngine(DeviceEngine):
    device_kind = "vent_monitor"

    def initial_state(self) -> dict[str, Any]:
        # Representative numerics for a stable VC breath; D4 makes these live.
        return {
            "screen": "monitoring",
            "active_alarms": [],
            "numerics": {"ppeak": 18, "pplat": 14, "peep": 5, "vt": 450,
                          "rr": 14, "mv": 6.3, "fio2": 0.40, "ie": "1:2"},
            "alarm_limits": dict(self.spec.get("default_alarm_limits", {})),
        }
