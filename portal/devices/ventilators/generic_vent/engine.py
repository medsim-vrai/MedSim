"""VentilatorEngine — ventilator with control interface (FR-012).

D1 scaffold: establishes the surface, holds the current ventilator settings,
and accepts a thin ``vent.set`` event so the controls round-trip. D5 replaces
the thin setter with the full mode-aware ``control_settings`` model (per-mode
control availability + ranges + step-snapping, ported from PhysioBridge VC0),
set-vs-measured, and maneuvers — and couples control changes into patient
physiology (``portal/physiology.py``, ported from PhysioBridge VC1). D6 adds
ventilator fault injection.
"""
from __future__ import annotations

from typing import Any

from portal.devices.engine.state_machine import DeviceEngine


class VentilatorEngine(DeviceEngine):
    device_kind = "ventilator"

    def initial_state(self) -> dict[str, Any]:
        return {
            "screen": "standby",
            "active_alarms": [],
            "settings": dict(self.spec.get("default_settings", {})),
            "measured": {},   # D5: derived from the engine (set-vs-measured)
            "alarm_limits": dict(self.spec.get("default_alarm_limits", {})),
        }

    def apply(self, state: dict[str, Any],
              event: dict[str, Any]) -> dict[str, Any]:
        state = super().apply(state, event)
        if event["type"] == "vent.set":
            payload = event.get("payload", {}) or {}
            settings = dict(state.get("settings", {}))
            # D1: thin store of recognized keys. D5 validates against
            # per-mode ranges and snaps to step before applying.
            for key, value in payload.items():
                if key in settings or key == "mode":
                    settings[key] = value
            screen = "running" if settings.get("mode") not in (None, "standby") else state.get("screen")
            return {**state, "settings": settings, "screen": screen}
        return state
