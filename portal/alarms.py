"""V7 Phase 7 — Alarm bus (M26).

Unified active-alarm list across every encounter in a room. Reads
from three sources:

  1. **Device events** — ``device_event`` rows of type
     ``alarm.injected`` (v6 pump + cabinet subsystem). Cleared by
     a subsequent ``alarm.cleared`` row with the same tone (or
     ``all``).
  2. **Scene events** — ``chart_event`` rows whose payload carries
     ``level='alarm'``. M7's compound scenes (code.blue,
     pump.alarm fallback) get this tag via Phase 7 1.4. Cleared
     when the operator hits POST /api/alarm/{alarm_id}/clear.
  3. **Future-device buttons** — M29 will add new device kinds
     (call bell, bed alarm, code blue button, fire alarm). Their
     button-press emits an ``alarm.injected`` device_event so they
     surface here automatically.

The returned dict shape:
  {
    "alarm_id":      "<deterministic id; stable per event row>",
    "source":        "device" | "scene" | "bedside_button",
    "kind":          "<device_kind or scene_kind>",
    "encounter_id":  "<encounter scope>",
    "encounter_label": "<bed label for the dashboard>",
    "ts":            <float>,
    "severity":      "info" | "warning" | "critical",
    "cleared":       false,
    "payload":       {<original event payload>},
  }

The bus does not persist a separate ``alarm`` table — every active
alarm is derivable on demand from the chart_event + device_event
logs. The operator's "Clear" action writes a synthetic clear-event
row (chart-side ``alarm.cleared`` or device-side ``alarm.cleared``)
which the next aggregator read filters out.
"""
from __future__ import annotations

import time
from typing import Any

from . import ehr_db


# ── Severity classification ──────────────────────────────────────────

_SEVERITY_BY_KIND = {
    # Device tones (v6 pump/cabinet)
    "occlusion":        "warning",
    "air_in_line":      "critical",
    "battery_low":      "warning",
    "door_left_open":   "warning",
    "wrong_med":        "critical",
    "scan_required":    "info",
    "high_priority":    "critical",
    # Scene kinds (M7).  M54 — code.blue is promoted to "danger"
    # (rank 4, above critical) so it sorts to the TOP of the alarm
    # board and triggers the near-continuous audio cadence on the
    # nurse station. Same WAV (_SPECIAL_FILES['code_blue']) — only
    # the cadence + sort position change.
    "code.blue":        "danger",
    "pump.alarm":       "warning",
    # Future-device stubs (M29).  M54 — code_blue_button also
    # promoted to danger for consistency with the scene kind.
    "call_bell":        "info",
    "bed_alarm":        "warning",
    "code_blue_button": "danger",
    "fire_alarm":       "critical",
    # FR-012 telemetry-monitor alarms (lethal rhythms sort to the top = danger)
    "asystole":         "danger",
    "vfib":             "danger",
    "vtach":            "danger",
    "brady_severe":     "critical",
    "tachy_severe":     "critical",
    "spo2_low":         "critical",
    "apnea":            "critical",
    "brady":            "warning",
    "tachy":            "warning",
    "rr_high":          "warning",
    "nibp_high":        "warning",
    "nibp_low":         "warning",
    "pvc_frequent":     "info",
    "afib":             "info",
    "leads_off":        "info",
    # FR-012 ventilator alarms
    "high_pressure":      "critical",
    "low_pressure":       "critical",
    "low_minute_volume":  "critical",
    "o2_supply":          "critical",
    "vent_inop":          "critical",
    "power_fail":         "critical",
    "low_tidal_volume":   "warning",
    "high_rr":            "warning",
    "high_minute_volume": "warning",
    "peep_loss":          "warning",
    "auto_peep":          "warning",
    "fio2_deviation":     "warning",
    "exhalation_valve":   "warning",
}


def _classify(kind: str | None) -> str:
    if not kind:
        return "info"
    return _SEVERITY_BY_KIND.get(kind, "info")


def _alarm_id(source: str, ev_id: int | str, encounter_id: str) -> str:
    """Deterministic alarm id so the clear action references the
    original event row. Form: ``<source>:<encounter>:<event_id>``."""
    return f"{source}:{encounter_id}:{ev_id}"


# ── Source 1: device events ─────────────────────────────────────────

def _device_alarms_for(encounter_id: str) -> list[dict[str, Any]]:
    """Walk the device_event log for one encounter, pair each
    alarm.injected with any subsequent alarm.cleared, return the
    unpaired (active) ones."""
    rows = ehr_db.device_events(session_id=encounter_id) or []
    # Build a tone → last-cleared-ts index so we know which injected
    # rows are still active.
    cleared_at: dict[str, float] = {}
    for ev in rows:
        if ev.get("type") == "alarm.cleared":
            payload = ev.get("payload") or {}
            tone = payload.get("tone")
            if payload.get("all"):
                # Clear-all sets cleared_at for every tone at this ts.
                # We approximate by stamping a wildcard key.
                cleared_at["__all__"] = ev.get("ts", 0)
            elif tone:
                # Latest clear timestamp wins per tone.
                cleared_at[tone] = max(cleared_at.get(tone, 0),
                                         ev.get("ts", 0))
    out: list[dict[str, Any]] = []
    all_cleared_after = cleared_at.get("__all__", 0)
    for ev in rows:
        if ev.get("type") != "alarm.injected":
            continue
        payload = ev.get("payload") or {}
        tone = payload.get("tone")
        ev_ts = ev.get("ts", 0)
        if ev_ts <= all_cleared_after:
            continue
        if tone and ev_ts <= cleared_at.get(tone, 0):
            continue
        kind = tone or "device"
        out.append({
            "alarm_id":        _alarm_id("device", ev.get("id"), encounter_id),
            "source":          "device",
            "kind":            kind,
            "encounter_id":    encounter_id,
            "ts":              ev_ts,
            "severity":        _classify(kind),
            "cleared":         False,
            "payload":         payload,
            "station_id":      ev.get("station_id"),
        })
    return out


# ── Source 2: scene events with level='alarm' ───────────────────────

def _scene_alarms_for(encounter_id: str) -> list[dict[str, Any]]:
    """Walk chart_event for `level: alarm` payloads. Operator's
    clear writes a chart-side `alarm.cleared` row stamped with the
    alarm_id; the next read filters cleared ones out."""
    events = ehr_db.events(encounter_id) or []
    # Build cleared-alarm-id set from chart-side alarm.cleared events.
    cleared_ids: set[str] = set()
    for ev in events:
        if ev.get("type") == "alarm.cleared":
            payload = ev.get("payload") or {}
            if payload.get("alarm_id"):
                cleared_ids.add(str(payload["alarm_id"]))
            elif payload.get("all"):
                # 'all' clear takes effect after this ts — handled
                # below per-row.
                pass
    # Find the max all-clear ts.
    all_cleared_after = max(
        (ev.get("ts", 0) for ev in events
          if ev.get("type") == "alarm.cleared"
          and (ev.get("payload") or {}).get("all")),
        default=0,
    )
    out: list[dict[str, Any]] = []
    for ev in events:
        payload = ev.get("payload") or {}
        if payload.get("level") != "alarm":
            continue
        ev_ts = ev.get("ts", 0)
        if ev_ts <= all_cleared_after:
            continue
        alarm_id = _alarm_id("scene", ev.get("id"), encounter_id)
        if alarm_id in cleared_ids:
            continue
        kind = payload.get("scene_kind") or ev.get("type") or "scene"
        out.append({
            "alarm_id":     alarm_id,
            "source":       "scene",
            "kind":         kind,
            "encounter_id": encounter_id,
            "ts":           ev_ts,
            "severity":     _classify(kind),
            "cleared":      False,
            "payload":      payload,
        })
    return out


# ── Public API ─────────────────────────────────────────────────────

def active_alarms(room: Any) -> list[dict[str, Any]]:
    """Aggregate every active alarm across the room. Sort: danger
    first, then critical, then newest first within each tier."""
    out: list[dict[str, Any]] = []
    # M50 — `danger` outranks `critical` so dangerous-waveform alarms
    # (v-fib, asystole) sort to the TOP of the alarm board. Real
    # bedside monitors give arrhythmia detection the highest weight.
    severity_rank = {"danger": 4, "critical": 3, "warning": 2, "info": 1}
    for enc in room.encounters.values():
        encounter_label = (enc.encounter_label or enc.scenario_name)
        device_alarms = _device_alarms_for(enc.id)
        scene_alarms  = _scene_alarms_for(enc.id)
        # M48 — threshold-breach alarms (vitals out of operator-set
        # range + dangerous ECG waveforms).
        threshold_alarms = _threshold_alarms_for(room, enc)
        for a in device_alarms + scene_alarms + threshold_alarms:
            a["encounter_label"] = encounter_label
            out.append(a)
    # M50 — Apply silence / clear from room.silenced_alarms. Cleared
    # alarms are filtered out entirely; silenced alarms stay visible
    # with `silenced=True` + `silenced_until` so the UI shows the
    # badge but the JS audio dispatcher skips them. Auto-expire when
    # `until` timestamp has passed.
    out = _apply_silenced(room, out)
    out.sort(key=lambda a: (-severity_rank.get(a["severity"], 0),
                              -a["ts"]))
    # M49 — annotate each alarm with its `audio_url` (or None when no
    # curated WAV exists). The Nursing Station JS reads this to play
    # the right clinical-alarm sound on new alarms.
    from portal import alarm_sounds as _alarm_sounds
    _alarm_sounds.annotate(out)
    return out


def _apply_silenced(room: Any, alarms: list[dict[str, Any]],
                     ) -> list[dict[str, Any]]:
    """M50 — filter/annotate alarms based on room.silenced_alarms."""
    sil = getattr(room, "silenced_alarms", None) or {}
    if not sil:
        return alarms
    now = time.time()
    # First clean up expired entries so the map doesn't grow forever.
    expired = [aid for aid, info in sil.items()
                if (info.get("until") or 0) <= now]
    for aid in expired:
        sil.pop(aid, None)
    if not sil:
        return alarms
    kept: list[dict[str, Any]] = []
    for a in alarms:
        info = sil.get(a.get("alarm_id"))
        if info is None:
            kept.append(a)
            continue
        if info.get("cleared"):
            # Cleared — drop from the active feed entirely.
            continue
        # Silenced — keep visible with metadata so UI can grey it out
        # and the JS audio dispatcher skips it.
        a["silenced"] = True
        a["silenced_until"] = info.get("until") or 0
        kept.append(a)
    return kept


# M48 — Threshold-breach alarms.
#
# Reads the room-level `alarm_thresholds` (set on the Nursing Station)
# and the per-encounter telemetry. Returns a list of alarm dicts in
# the same shape as device/scene alarms so they merge cleanly into
# the unified room alarm feed.

def _threshold_alarms_for(room: Any, enc: Any) -> list[dict[str, Any]]:
    thresholds = (room.alarm_thresholds if hasattr(room, "alarm_thresholds")
                  else None) or {}
    if not thresholds:
        return []
    # Lazy import to avoid a circular dep with telemetry/server.
    from portal import telemetry as _telemetry
    try:
        # `jitter=False` so threshold checks are deterministic — without
        # this a jittered reading might oscillate across the boundary.
        snap = _telemetry.snapshot(enc.id, jitter=False)
    except Exception:  # noqa: BLE001
        return []
    out: list[dict[str, Any]] = []
    # Threshold alarms use a fixed sort-key timestamp (0) so they
    # always sort to the END of their severity bucket — actual
    # device/scene alarms (with a real timestamp) win the top of
    # the list. This preserves the M26 alarm-bus existing-test
    # invariants while still surfacing threshold breaches.
    now = 0.0
    metric_breaches = [
        # (threshold_key, snapshot field, friendly label)
        ("hr",            "hr",   "Heart rate"),
        ("spo2",          "spo2", "SpO₂"),
        ("rr",            "rr",   "Respiratory rate"),
        # M50 — Blood pressure (both sides). The snapshot returns
        # `sbp` + `dbp`; thresholds key on `bp_systolic` + `bp_diastolic`.
        ("bp_systolic",   "sbp",  "BP systolic"),
        ("bp_diastolic",  "dbp",  "BP diastolic"),
    ]
    for metric_key, snap_key, label in metric_breaches:
        value = snap.get(snap_key) if isinstance(snap, dict) else None
        # Numeric coercion — snapshot values may arrive as int/float.
        try:
            v = float(value) if value is not None else None
        except (TypeError, ValueError):
            v = None
        if v is None:
            continue
        bounds = thresholds.get(metric_key) or {}
        low  = bounds.get("low")
        high = bounds.get("high")
        breach: str | None = None
        deviation_pct: float = 0.0
        if low is not None and v < float(low):
            breach = f"low ({v:g} < {low})"
            # Percent past the lower bound, relative to the bound.
            deviation_pct = (float(low) - v) / abs(float(low)) * 100.0 if low else 0.0
        elif high is not None and v > float(high):
            breach = f"high ({v:g} > {high})"
            deviation_pct = (v - float(high)) / abs(float(high)) * 100.0 if high else 0.0
        if breach:
            # M54 — Severity scales with the MAGNITUDE of the breach
            # relative to the threshold bound. Operator: "Low level
            # alarms sound when parameters are 10% below lower
            # threshold or 10% Higher than upper threshold. Medium is
            # between 10% and 20% of threshold limits and high if
            # above 20% of the threshold limits."
            #
            # Mapping (deviation_pct = how far past the bound, as
            # percent of the bound itself):
            #   0%  ≤ d < 10%   → "info"     (LOW — just crossed)
            #   10% ≤ d < 20%   → "warning"  (MEDIUM)
            #   d ≥ 20%         → "critical" (HIGH)
            #
            # Pre-M54 the severity was a fixed per-metric value
            # (SpO2 always critical, others warning). M54 makes it
            # responsive to how DEEP the breach is — a 1-point SpO2
            # dip below threshold is now low, a deep drop stays
            # critical, matching real bedside monitor behaviour.
            if deviation_pct >= 20.0:
                severity = "critical"
            elif deviation_pct >= 10.0:
                severity = "warning"
            else:
                severity = "info"
            out.append({
                "alarm_id":       f"threshold:{enc.id}:{metric_key}",
                "source":         "threshold",
                "encounter_id":   enc.id,
                "kind":           f"vitals.{metric_key}.breach",
                "label":          f"{label} {breach}",
                "severity":       severity,
                "ts":             now,
                "raised_at":      now,
                "cleared":        False,
                "metric":         metric_key,
                "value":          v,
                # M54 — surface the computed magnitude so the UI can
                # show a "+15% past upper" badge if it ever wants to.
                "deviation_pct":  round(deviation_pct, 1),
            })
    # Dangerous ECG rhythm — check the encounter's `ecg_rhythm_id` field
    # against the operator's danger list. `ecg_enabled=False` means the
    # operator turned off the strip; treat that as no-alarm.
    danger_rhythms = set(thresholds.get("dangerous_rhythms") or [])
    if danger_rhythms and getattr(enc, "ecg_enabled", False):
        rhythm = getattr(enc, "ecg_rhythm_id", "") or ""
        if rhythm in danger_rhythms:
            # M50 — dangerous waveforms get severity="danger" (rank 4)
            # so they sort ABOVE other critical alarms. Real bedside
            # monitors give arrhythmia detection the highest priority.
            out.append({
                "alarm_id":     f"threshold:{enc.id}:rhythm",
                "source":       "threshold",
                "encounter_id": enc.id,
                "kind":         "vitals.rhythm.dangerous",
                "label":        f"ECG rhythm: {rhythm}",
                "severity":     "danger",
                "ts":           now,
                "raised_at":    now,
                "cleared":      False,
                "metric":       "rhythm",
                "value":        rhythm,
            })
    return out


def clear_alarm(room: Any, alarm_id: str) -> dict[str, Any] | None:
    """Mark one alarm cleared. Returns the cleared alarm dict (with
    ``cleared=True``) or None if the id is unknown. The clear writes
    a synthetic alarm.cleared event to the appropriate log so the
    next ``active_alarms`` read filters it out."""
    # Parse the deterministic id.
    try:
        source, encounter_id, ev_id = alarm_id.split(":", 2)
    except ValueError:
        return None
    enc = room.encounters.get(encounter_id)
    if enc is None:
        return None
    if source == "device":
        # Write a device_event of type alarm.cleared. We need a
        # station_id; reuse the first device station bound to the
        # encounter or fall back to a synthetic one.
        station_id = (next(iter(enc.device_stations.keys()))
                       if enc.device_stations
                       else "instructor:clear")
        ehr_db.append_device_event(
            encounter_id, station_id,
            type="alarm.cleared", surface="instructor",
            payload={"alarm_id": alarm_id, "by": "instructor"},
        )
        return {"alarm_id": alarm_id, "cleared": True, "source": "device"}
    if source == "scene":
        # Chart-side clear. Re-use any existing ehr_station id; else
        # synthesize one.
        station_id = (next(iter(enc.ehr_stations.keys()))
                       if enc.ehr_stations
                       else f"instructor:clear:{enc.id}")
        ehr_db.append_event(
            encounter_id, station_id,
            type="alarm.cleared", surface="instructor",
            payload={"alarm_id": alarm_id, "by": "instructor"},
        )
        return {"alarm_id": alarm_id, "cleared": True, "source": "scene"}
    # M50 — Threshold alarms have no event log to write into. The
    # Clear button records them in `room.silenced_alarms` with
    # cleared=True so they're filtered out of the active feed.
    # When the underlying value comes back into range, the threshold
    # alarm naturally stops being emitted from _threshold_alarms_for
    # and the silenced-map entry expires harmlessly. If the breach
    # is still active, the cleared flag keeps it hidden until
    # `until` ticks past — at which point the breach re-emerges and
    # the operator can clear/silence it again.
    if source == "threshold":
        sil = getattr(room, "silenced_alarms", None)
        if sil is None:
            return None
        # Far-future expiry — "cleared" stays in effect until either
        # the underlying breach resolves or the operator restarts.
        sil[alarm_id] = {"until": time.time() + 86400, "cleared": True}
        return {"alarm_id": alarm_id, "cleared": True, "source": "threshold"}
    return None


def silence_alarm(room: Any, alarm_id: str, *,
                   duration_s: int = 45) -> dict[str, Any] | None:
    """M50 — Silence an alarm for `duration_s` seconds. Unlike Clear,
    the alarm stays visible on the alarm board (with a silenced badge)
    so the supervisor can see it's still active — but no audio fires
    during the silence window. Works on any alarm source (device,
    scene, threshold). Returns the silenced metadata or None if the
    alarm_id is malformed.

    M52 — Default dropped from 120 s to 45 s per operator: "silence of
    an alarm last 45 seconds then it goes active if the condition is
    not resolved or cleared". The alarm bus's `_apply_silenced` auto-
    expires entries past `until`, so a still-active breach surfaces
    its audio again the moment the 45 s window lapses."""
    if not alarm_id:
        return None
    sil = getattr(room, "silenced_alarms", None)
    if sil is None:
        return None
    until = time.time() + max(1, int(duration_s))
    sil[alarm_id] = {"until": until, "cleared": False}
    return {"alarm_id": alarm_id, "silenced": True,
            "silenced_until": until, "duration_s": duration_s}
