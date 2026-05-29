"""PumpEnteralEngine — enteral-feed-pump state machine.

Used by Kangaroo OMNI in v6.0; later versions reuse the same engine for
Kangaroo Joey, EnteraLite Infinity, Compat Ella, and Sentinel by varying
``spec.json``.

Differs from the IV engine in three ways:

1. **Single-channel** — feed pumps run one program at a time.
2. **State-color screen** — the OMNI's most visible feature; ``screen``
   field doubles as the running-state indicator.
3. **Modes** — continuous, intermittent, flush. Intermittent and flush
   schedules don't ship in v6.0 (they need a calendar/clock model);
   continuous works fully.

Event types:

  feed.power            {state: 'on'|'off'}
  feed.program          {mode, rate_ml_hr, volume_ml, flush_volume_ml}
  feed.start            {}
  feed.pause            {}
  feed.stop             {}
  feed.flush            {volume_ml}
  feed.tick             {battery_minutes, fed_ml, completed: bool}
  alarm.* (inherited)
"""
from __future__ import annotations

import time
from typing import Any

from portal.devices.engine.state_machine import DeviceEngine


class PumpEnteralEngine(DeviceEngine):
    device_kind = "pump_enteral"

    def initial_state(self) -> dict[str, Any]:
        # V6 — defensive against a wrong spec being handed in (registry
        # mis-filter); fall back to sensible Kangaroo OMNI defaults so
        # bootstrap doesn't 500.
        defaults = self.spec.get("default_program") or {
            "mode": "continuous", "rate_ml_hr": 0, "volume_ml": 0,
            "flush_volume_ml": 0,
        }
        # V6 — seed initial state from default_program so a freshly-loaded
        # pump shows realistic last-program values (mirrors real OMNI
        # behavior — most pumps come with the prior program retained).
        # Student still has to press Start to begin infusion.
        return {
            "screen": "off",
            "power": False,
            "mode":           defaults.get("mode", "continuous"),
            "rate_ml_hr":     float(defaults.get("rate_ml_hr", 0) or 0),
            "volume_ml":      float(defaults.get("volume_ml", 0) or 0),
            "fed_ml":         0.0,
            "flush_volume_ml": float(defaults.get("flush_volume_ml", 0) or 0),
            "running": False,
            "paused":  False,
            "active_alarms": [],
            "battery_minutes": self.spec["battery"]["capacity_minutes"],
            "battery_warning": None,
            "completed": False,
            # V6.1.2 — live-projection anchor (set by feed.start/feed.tick,
            # cleared by pause/stop/program). fold() extrapolates fed_ml
            # forward from this timestamp so the display advances in real
            # time without any client-side timer.
            "anchor_ts": None,
        }

    @staticmethod
    def _project_fed(state: dict[str, Any], at_ts: float) -> float:
        if not state.get("running") or not state.get("anchor_ts"):
            return float(state.get("fed_ml") or 0)
        rate = float(state.get("rate_ml_hr") or 0)
        base = float(state.get("fed_ml") or 0)
        anchor = float(state["anchor_ts"])
        dt_h = max(0.0, (at_ts - anchor) / 3600.0)
        live = base + rate * dt_h
        vol = float(state.get("volume_ml") or 0)
        return min(vol, live) if vol > 0 else live

    def fold(self, events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Project live fed_ml at read time (V6.1.2)."""
        state = super().fold(events)
        return {**state, "fed_ml": PumpEnteralEngine._project_fed(state, time.time())}

    def apply(self, state: dict[str, Any],
              event: dict[str, Any]) -> dict[str, Any]:
        state = super().apply(state, event)
        et = event["type"]
        payload = event.get("payload", {}) or {}
        if et == "feed.power":
            on = payload.get("state") == "on"
            return {**state, "power": on,
                    "screen": "home" if on else "off"}
        if et == "feed.program":
            return {
                **state,
                "mode":            payload.get("mode", state["mode"]),
                "rate_ml_hr":      float(payload.get("rate_ml_hr") or 0),
                "volume_ml":       float(payload.get("volume_ml") or 0),
                "fed_ml":          0.0,
                "flush_volume_ml": float(payload.get("flush_volume_ml") or 0),
                "running": False, "paused": False, "completed": False,
                "screen": "program",
                "anchor_ts": None,
            }
        if et == "feed.start":
            return {**state, "running": True, "paused": False,
                    "completed": False, "screen": "running",
                    "anchor_ts": event["ts"]}
        if et == "feed.pause":
            snap = PumpEnteralEngine._project_fed(state, event["ts"])
            return {**state, "fed_ml": snap, "running": False, "paused": True,
                    "screen": "paused", "anchor_ts": None}
        if et == "feed.stop":
            snap = PumpEnteralEngine._project_fed(state, event["ts"])
            return {**state, "fed_ml": snap, "running": False, "paused": False,
                    "screen": "home", "anchor_ts": None}
        if et == "feed.flush":
            return state   # flush is a transient action, no state change
        if et == "feed.tick":
            fed = float(payload.get("fed_ml", state["fed_ml"]))
            battery = float(payload.get("battery_minutes",
                                          state["battery_minutes"]))
            completed = bool(payload.get("completed", state.get("completed")))
            screen = state["screen"]
            running = state["running"]
            if completed and not state.get("completed"):
                running = False
                screen = "feed_complete"
            warn = state.get("battery_warning")
            thresh = self.spec["battery"]
            if warn is None and battery <= thresh["low_threshold_minutes"]:
                warn = "low"
            if warn != "depleted" and battery <= thresh["depleted_threshold_minutes"]:
                warn = "depleted"
            return {**state, "fed_ml": fed, "battery_minutes": battery,
                    "completed": completed, "running": running,
                    "screen": screen, "battery_warning": warn,
                    # Reset projection anchor: stored fed_ml is now the new
                    # base; if still running, restart the clock from this ts.
                    "anchor_ts": event["ts"] if running else None}
        return state

    def tick(self, state: dict[str, Any],
             dt: float) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if not state.get("power"):
            return state, []
        emit: list[dict[str, Any]] = []
        battery = float(state.get("battery_minutes", 0))
        drain = (dt / 60.0) * (1.4 if state["running"] else 1.0)
        battery = max(0.0, battery - drain)
        fed = float(state.get("fed_ml", 0))
        completed = False
        if state["running"] and state["volume_ml"] > 0:
            inc = (state["rate_ml_hr"] / 3600.0) * dt
            fed = min(state["volume_ml"], fed + inc)
            if fed >= state["volume_ml"]:
                completed = True
        if drain > 0 or fed != state.get("fed_ml"):
            emit.append({
                "type": "feed.tick", "surface": "system",
                "payload": {"battery_minutes": battery, "fed_ml": fed,
                            "completed": completed},
            })
        thresh = self.spec["battery"]
        warn = state.get("battery_warning")
        if warn is None and battery <= thresh["low_threshold_minutes"]:
            emit.append({"type": "alarm.injected", "surface": "system",
                         "payload": {"tone": "low_battery", "auto": True}})
        if warn != "depleted" and battery <= thresh["depleted_threshold_minutes"]:
            emit.append({"type": "alarm.injected", "surface": "system",
                         "payload": {"tone": "depleted_battery", "auto": True}})
        if completed and not state.get("completed"):
            emit.append({"type": "alarm.injected", "surface": "system",
                         "payload": {"tone": "feed_complete", "auto": True}})
        return state, emit
