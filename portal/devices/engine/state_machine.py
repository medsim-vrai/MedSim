"""Base ``DeviceEngine`` — server-side state machine for one device station.

The contract every concrete engine (PumpIvEngine, PumpEnteralEngine,
CabinetEngine) follows:

- **State is a fold of the event log.** ``fold(events)`` rebuilds the
  current state from scratch by replaying every persisted event through
  ``apply(state, event)``. This is what makes pause/resume trivial — we
  just replay.
- **Every state-changing call goes through ``handle()``.** ``handle()``
  appends the event to the persistence layer, then folds the resulting
  log into the new state. The caller never mutates state directly.
- **Pause gates time, not input.** ``tick(now)`` short-circuits when the
  ControlSession is paused; ``handle()`` still works (the instructor can
  inspect, reassign, or end the session while paused) but events with
  ``surface == "device"`` are rejected — a paused device is read-only.

Subclasses implement:

    initial_state()   -> dict[str, Any]
    apply(state, ev)  -> dict[str, Any]   # pure reducer
    tick(state, dt)   -> tuple[state, events_to_emit]
"""
from __future__ import annotations

import time
from typing import Any

from portal import ehr_db
from portal.devices import registry
from portal.devices.engine import persistence


class DeviceEngine:
    """Concrete engines subclass this. Defaults are deliberately empty."""

    device_kind: str = ""

    def __init__(self, *, session_id: str, station_id: str,
                  device_model: str) -> None:
        self.session_id = session_id
        self.station_id = station_id
        self.device_model = device_model
        self.spec: dict[str, Any] = registry.load_spec(self.device_kind,
                                                       device_model)
        self._last_tick: float = time.time()

    # ── Reducer surface — subclasses override ─────────────────────────

    def initial_state(self) -> dict[str, Any]:
        return {"screen": "idle", "active_alarms": []}

    def apply(self, state: dict[str, Any],
              event: dict[str, Any]) -> dict[str, Any]:
        """Pure reducer. Returns a NEW dict — never mutate ``state``."""
        et = event["type"]
        payload = event.get("payload", {}) or {}
        if et == "alarm.injected":
            tone = payload.get("tone")
            if tone:
                alarms = list(state.get("active_alarms", []))
                if not any(a["tone"] == tone for a in alarms):
                    alarms.append({
                        "tone": tone,
                        "raised_at": event["ts"],
                        "silenced_until": 0.0,
                        "source": event.get("surface", "instructor"),
                    })
                return {**state, "active_alarms": alarms}
        elif et == "alarm.silenced":
            tone = payload.get("tone")
            until = float(payload.get("until", event["ts"] + 120))
            alarms = [
                {**a, "silenced_until": until} if a["tone"] == tone else a
                for a in state.get("active_alarms", [])
            ]
            return {**state, "active_alarms": alarms}
        elif et == "alarm.cleared":
            tone = payload.get("tone")
            alarms = [a for a in state.get("active_alarms", [])
                      if a["tone"] != tone]
            return {**state, "active_alarms": alarms}
        elif et == "device.assigned":
            return {**state, "character_id": payload.get("character_id")}
        return state

    def tick(self, state: dict[str, Any],
             dt: float) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Advance time-driven state. Default = no-op. Returns (new_state,
        events_to_persist).
        """
        return state, []

    # ── Fold + handle — the engine's outer API ────────────────────────

    def fold(self, events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Replay events into a complete current state."""
        events = events if events is not None else persistence.replay(self.station_id)
        state = self.initial_state()
        for ev in events:
            state = self.apply(state, ev)
        return state

    def handle(self, *, type: str, surface: str,
               payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Persist one event and return the resulting state. Pause gating
        is enforced by the WebSocket layer (which sees the live
        ControlSession), so ``handle`` itself does NOT branch on pause —
        callers are expected to drop ``surface=="device"`` events while
        paused. This keeps the engine pure and testable.
        """
        persistence.record(
            self.session_id, self.station_id,
            type=type, surface=surface, payload=payload or {},
        )
        ehr_db.touch_device_station(self.station_id)
        return self.fold()

    def run_tick(self, *, now: float) -> dict[str, Any]:
        """Advance time and emit any events the time-step produced.
        Returns the post-tick state. Idempotent if no time has passed."""
        dt = max(0.0, now - self._last_tick)
        self._last_tick = now
        if dt == 0.0:
            return self.fold()
        state = self.fold()
        new_state, emit = self.tick(state, dt)
        for ev in emit:
            persistence.record(
                self.session_id, self.station_id,
                type=ev["type"], surface=ev.get("surface", "system"),
                payload=ev.get("payload", {}),
            )
        # Re-fold AFTER emitting so the returned state includes them.
        return self.fold()


def make_engine(*, session_id: str, station_id: str,
                 device_kind: str, device_model: str) -> DeviceEngine:
    """Factory — picks the concrete engine class for this device_kind."""
    # Imports here to avoid circular imports at module load time.
    if device_kind == "pump_iv":
        from portal.devices.pumps.alaris.engine import PumpIvEngine
        return PumpIvEngine(session_id=session_id, station_id=station_id,
                            device_model=device_model)
    if device_kind == "pump_enteral":
        from portal.devices.pumps.kangaroo_omni.engine import PumpEnteralEngine
        return PumpEnteralEngine(session_id=session_id, station_id=station_id,
                                 device_model=device_model)
    if device_kind == "cabinet":
        from portal.devices.cabinets.pyxis.engine import CabinetEngine
        return CabinetEngine(session_id=session_id, station_id=station_id,
                             device_model=device_model)
    # M51 — Patient Integrated Alarm. The PIA does not need a custom
    # reducer (its button presses are routed to side-effects in
    # routes._handle_pia_button, not folded into per-station state),
    # so we return a thin DeviceEngine subclass that just sets
    # device_kind for spec lookup. The base reducer is enough — it
    # quietly returns unchanged state for unknown event types like
    # `pia.button` so the route can persist the event without error.
    if device_kind == "patient_integrated_alarm":
        return PiaEngine(session_id=session_id, station_id=station_id,
                          device_model=device_model)
    raise KeyError(f"no engine for device_kind={device_kind!r}")


class PiaEngine(DeviceEngine):
    """M51 — Minimal engine for Patient Integrated Alarm tablets."""
    device_kind = "patient_integrated_alarm"
