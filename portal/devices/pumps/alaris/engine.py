"""PumpIvEngine — IV-pump-family state machine, used by Alaris in v6.0
and the four IV re-skins (Spectrum IQ, Infusomat Space, Plum 360, Plum
Solo) in later versions. Per-model differences (drug library, key
layout, channel count) live in ``spec.json``; the engine itself is
device-model-agnostic.

Event types handled:

  pump.power             {state: 'on'|'off'}
  pump.program           {channel, drug_code, rate_ml_hr, vtbi_ml, dose, dose_unit,
                          library_used: bool, soft_override: bool}
  pump.start             {channel}
  pump.pause             {channel}
  pump.stop              {channel}
  pump.rate_change       {channel, rate_ml_hr, soft_override: bool}
  pump.battery_changed   {minutes_remaining}
  alarm.injected         {tone}          (inherited)
  alarm.silenced         {tone, until}   (inherited)
  alarm.cleared          {tone}          (inherited)
"""
from __future__ import annotations

import time
from typing import Any

from portal.devices.engine.state_machine import DeviceEngine


class PumpIvEngine(DeviceEngine):
    device_kind = "pump_iv"

    def initial_state(self) -> dict[str, Any]:
        # V6 — defensive defaults. If the loaded spec is the wrong shape
        # (e.g. the registry was mis-filtered and handed us an enteral
        # spec) we still produce a working channels dict so bootstrap
        # never 500s. Same for battery thresholds.
        channels_list = self.spec.get("channels") or ["A"]
        bat = self.spec.get("battery") or {}
        return {
            "screen": "off",
            "power": False,
            "channels": {ch: self._empty_channel() for ch in channels_list},
            "active_alarms": [],
            "battery_minutes": bat.get("capacity_minutes", 360),
            "battery_warning": None,    # 'low' | 'depleted' | None
            "library_overrides": 0,
        }

    @staticmethod
    def _empty_channel() -> dict[str, Any]:
        return {
            "drug_code": None, "drug_label": None,
            "rate_ml_hr": 0.0, "vtbi_ml": 0.0, "infused_ml": 0.0,
            "dose": None, "dose_unit": None,
            "library_used": False, "soft_override": False,
            "running": False, "paused": False,
            # V6.1.2 — anchor_ts is the epoch at which the current "running"
            # window began (set by pump.start, refreshed by pump.tick).
            # While running, fold() projects infused_ml = base + rate *
            # (now - anchor_ts). When pause/stop fires, we snapshot the
            # live infused into infused_ml and clear anchor_ts. This makes
            # the on-screen volume/time advance in real time without any
            # client-side timer, and survives stale-cache JS on tablets.
            "anchor_ts": None,
        }

    # ── Live infusion projection ─────────────────────────────────────────
    # Helper used by both apply(pump.pause/stop) and fold() to compute the
    # mL infused at an arbitrary point in time, given the channel's
    # current base infused_ml + rate + anchor_ts.
    @staticmethod
    def _project_infused(channel: dict[str, Any], at_ts: float) -> float:
        if not channel.get("running") or not channel.get("anchor_ts"):
            return float(channel.get("infused_ml") or 0)
        rate = float(channel.get("rate_ml_hr") or 0)
        base = float(channel.get("infused_ml") or 0)
        anchor = float(channel["anchor_ts"])
        dt_h = max(0.0, (at_ts - anchor) / 3600.0)
        live = base + rate * dt_h
        vtbi = float(channel.get("vtbi_ml") or 0)
        return min(vtbi, live) if vtbi > 0 else live

    def fold(self, events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Project live infused_ml for every running channel at read time.
        The base reducer (apply) only updates infused_ml on pump.tick,
        pump.pause, pump.stop, pump.program. Between those, fold extrapolates
        from anchor_ts + rate, so polling clients see seconds-accurate volumes
        without any client-side interpolation. Setting infused_ml here does
        NOT modify the persisted event log."""
        state = super().fold(events)
        channels = state.get("channels") or {}
        if not channels:
            return state
        now = time.time()
        projected = {}
        for ch_id, c in channels.items():
            projected[ch_id] = {**c, "infused_ml": PumpIvEngine._project_infused(c, now)}
        return {**state, "channels": projected}

    def apply(self, state: dict[str, Any],
              event: dict[str, Any]) -> dict[str, Any]:
        return PumpIvEngine._apply_pump_specific(self, state, event)

    def tick(self, state: dict[str, Any],
             dt: float) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if not state.get("power"):
            return state, []
        emit: list[dict[str, Any]] = []
        channels = dict(state.get("channels") or {})
        if not channels:
            channels = {ch: PumpIvEngine._empty_channel()
                        for ch in self.spec.get("channels", ["A"])}
        battery = float(state.get("battery_minutes", 0))
        running = any(c["running"] for c in channels.values())
        drain = (dt / 60.0) * (1.5 if running else 1.0)
        battery = max(0.0, battery - drain)
        new_channel_volumes: dict[str, float] = {}
        infusion_completed: list[str] = []
        for ch, c in channels.items():
            if not c["running"] or c["vtbi_ml"] <= 0:
                continue
            inc = (c["rate_ml_hr"] / 3600.0) * dt
            new_inf = min(c["vtbi_ml"], c["infused_ml"] + inc)
            new_channel_volumes[ch] = new_inf
            if new_inf >= c["vtbi_ml"]:
                infusion_completed.append(ch)
        # One snapshot event captures all derived advances at once. Folding
        # this event re-applies the same numbers, so pause/resume is exact.
        if drain > 0 or new_channel_volumes:
            emit.append({
                "type": "pump.tick", "surface": "system",
                "payload": {
                    "battery_minutes": battery,
                    "channel_volumes": new_channel_volumes,
                    "completed_channels": infusion_completed,
                },
            })
        # Battery-warning crossings — alarm event once per threshold.
        warn = state.get("battery_warning")
        thresh = self.spec["battery"]
        if warn is None and battery <= thresh["low_threshold_minutes"]:
            emit.append({"type": "alarm.injected", "surface": "system",
                         "payload": {"tone": "low_battery", "auto": True}})
        if warn != "depleted" and battery <= thresh["depleted_threshold_minutes"]:
            emit.append({"type": "alarm.injected", "surface": "system",
                         "payload": {"tone": "depleted_battery", "auto": True}})
        # Infusion-complete alarms once per channel crossing.
        for ch in infusion_completed:
            emit.append({
                "type": "alarm.injected", "surface": "system",
                "payload": {"tone": "infusion_complete", "channel": ch, "auto": True},
            })
        return state, emit

    @staticmethod
    def _apply_pump_specific(self_, state: dict[str, Any],
                              event: dict[str, Any]) -> dict[str, Any]:
        state = DeviceEngine.apply(self_, state, event)
        # V6 — defensive guard. The engine's initial_state populates
        # `channels`, but a corrupt fold (e.g. an event log surviving a
        # subclass change) could land here without it. Self-heal so a
        # KeyError never crashes the bootstrap. The repaired state is
        # built from the spec's declared channel list.
        # V8 — heal MISSING channels too, not just an absent dict: a state
        # carrying only {'A'} (e.g. a single-channel pump switched to a
        # dual-channel model via the in-control picker) would otherwise make
        # pump.program for 'B' a silent no-op (ch not in channels_in below).
        spec_channels = self_.spec.get("channels") or ["A"]
        chans = state.get("channels")
        if not isinstance(chans, dict):
            chans = {}
        missing = {ch: PumpIvEngine._empty_channel()
                   for ch in spec_channels if ch not in chans}
        if missing or not isinstance(state.get("channels"), dict):
            state = {**state, "channels": {**chans, **missing}}
        et = event["type"]
        payload = event.get("payload", {}) or {}
        channels_in = state.get("channels", {})

        if et == "pump.power":
            on = payload.get("state") == "on"
            return {**state, "power": on,
                    "screen": "home" if on else "off"}
        if et == "pump.program":
            ch = payload.get("channel")
            if ch not in channels_in:
                return state
            new_ch = {
                **channels_in[ch],
                "drug_code":     payload.get("drug_code"),
                "drug_label":    payload.get("drug_label"),
                "rate_ml_hr":    float(payload.get("rate_ml_hr") or 0),
                "vtbi_ml":       float(payload.get("vtbi_ml") or 0),
                "infused_ml":    0.0,
                "dose":          payload.get("dose"),
                "dose_unit":     payload.get("dose_unit"),
                "library_used":  bool(payload.get("library_used")),
                "soft_override": bool(payload.get("soft_override")),
                "running": False, "paused": False,
                "anchor_ts":     None,    # programming resets the live clock
            }
            channels = {**channels_in, ch: new_ch}
            overrides = state.get("library_overrides", 0)
            if new_ch["soft_override"]:
                overrides += 1
            return {**state, "channels": channels, "screen": "program",
                    "library_overrides": overrides}
        if et == "pump.start":
            ch = payload.get("channel")
            channels = dict(channels_in)
            if ch in channels:
                # V6.1.2 — anchor the live-projection clock at this event's ts
                channels[ch] = {**channels[ch], "running": True, "paused": False,
                                "anchor_ts": event["ts"]}
            return {**state, "channels": channels, "screen": "running"}
        if et == "pump.pause":
            ch = payload.get("channel")
            channels = dict(channels_in)
            if ch in channels:
                c = channels[ch]
                # Snapshot live infused at the moment of pause, then drop
                # the anchor so fold() stops projecting.
                snap = PumpIvEngine._project_infused(c, event["ts"])
                channels[ch] = {**c, "infused_ml": snap,
                                 "running": False, "paused": True,
                                 "anchor_ts": None}
            return {**state, "channels": channels}
        if et == "pump.stop":
            ch = payload.get("channel")
            channels = dict(channels_in)
            if ch in channels:
                c = channels[ch]
                snap = PumpIvEngine._project_infused(c, event["ts"])
                channels[ch] = {**c, "infused_ml": snap,
                                 "running": False, "paused": False,
                                 "anchor_ts": None}
            return {**state, "channels": channels}
        if et == "pump.rate_change":
            ch = payload.get("channel")
            channels = dict(channels_in)
            if ch in channels:
                channels[ch] = {
                    **channels[ch],
                    "rate_ml_hr": float(payload.get("rate_ml_hr") or 0),
                    "soft_override": bool(payload.get("soft_override")),
                }
            return {**state, "channels": channels}
        if et == "pump.battery_changed":
            mins = float(payload.get("minutes_remaining",
                                       self_.spec["battery"]["capacity_minutes"]))
            return {**state, "battery_minutes": mins, "battery_warning": None}
        if et == "pump.tick":
            channels = dict(channels_in)
            for ch, vol in (payload.get("channel_volumes") or {}).items():
                if ch in channels:
                    # Reset the live-projection anchor: post-tick, the
                    # stored infused_ml is the new base, and the clock
                    # re-starts counting from this event's ts.
                    channels[ch] = {**channels[ch], "infused_ml": float(vol),
                                     "anchor_ts": event["ts"]
                                     if channels[ch].get("running") else None}
            for ch in (payload.get("completed_channels") or []):
                if ch in channels:
                    channels[ch] = {**channels[ch], "running": False,
                                     "anchor_ts": None}
            battery = float(payload.get("battery_minutes",
                                          state.get("battery_minutes", 0)))
            warn = state.get("battery_warning")
            thresh = self_.spec["battery"]
            if warn is None and battery <= thresh["low_threshold_minutes"]:
                warn = "low"
            if warn != "depleted" and battery <= thresh["depleted_threshold_minutes"]:
                warn = "depleted"
            return {**state, "channels": channels,
                    "battery_minutes": battery, "battery_warning": warn}
        return state
