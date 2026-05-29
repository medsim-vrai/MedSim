"""V7 — Scenes engine (M7).

A **Scene** is a templated event-injection an instructor fires at one
or many encounters during a live simulation. Each Scene resolves to
one or more typed events written through the existing ``ehr_db``
appenders:

  - ``vitals.drop``       → 1 ``vitals.record`` event (hypotension preset)
  - ``vitals.rise``       → 1 ``vitals.record`` event (hypertension / tachy preset)
  - ``lab.result``        → 1 ``result.acknowledge`` event with panel + values
  - ``order.new``         → 1 ``order.place`` event (instructor-authored order)
  - ``family.arrives``    → 1 ``note.save`` (communication note)
  - ``pump.alarm``        → 1 ``device.alarm.injected`` device event when a
                            pump is bound to the encounter; otherwise a
                            chart-side ``instructor.trigger`` fallback so the
                            scene still leaves a footprint in the chart.
  - ``code.blue``         → compound: ``vitals.record`` (crash) +
                            ``note.save`` (CODE BLUE) + ``instructor.trigger``
                            marker + optional pump alarm if bound.
  - ``note.instructor``   → 1 ``note.save`` (free-form instructor message).

Unknown kinds fall back to a single ``instructor.trigger`` event so
forward-compatibility holds — a future palette entry can be added
without server changes, and clients that already emit it will produce
a logged-but-otherwise-inert chart event.

Every event payload carries:
  ``{"source": "scene", "scene_kind": kind, "by": <who fired it>}``
so the cohort debrief (M14) can filter scene-driven events out of
the student-driven activity.

Reference: ``research/p6_v7_architecture.md`` §4.13.
"""
from __future__ import annotations

import time
from typing import Any, Callable

from . import ehr_db
from .control_room import Encounter

# ── Palette ──────────────────────────────────────────────────────────

PALETTE: list[dict[str, Any]] = [
    {
        "kind":            "vitals.drop",
        "label":           "Vitals drop — hypotensive crash",
        "category":        "chart",
        "default_params":  {"hr": 132, "sbp": 78, "dbp": 44,
                            "spo2": 88, "rr": 28, "temp_f": 99.1},
        "description":     "Append a vitals.record showing acute hypotension + tachycardia.",
    },
    {
        "kind":            "vitals.rise",
        "label":           "Vitals rise — sympathetic surge",
        "category":        "chart",
        "default_params":  {"hr": 142, "sbp": 188, "dbp": 102,
                            "spo2": 96, "rr": 26, "temp_f": 100.6},
        "description":     "Append a vitals.record showing hypertension + tachycardia.",
    },
    {
        "kind":            "lab.result",
        "label":           "Lab result returns",
        "category":        "chart",
        "default_params":  {"panel": "BMP",
                            "values": {"Na": 132, "K": 5.4, "Cl": 102,
                                        "CO2": 22, "BUN": 28, "Cr": 1.4,
                                        "Glu": 184}},
        "description":     "Append a result.acknowledge entry the student is expected to read.",
    },
    {
        "kind":            "order.new",
        "label":           "New order from MD",
        "category":        "chart",
        "default_params":  {"order_type": "med", "code": "FUROSEMIDE",
                            "label": "Furosemide 40 mg IV push x1",
                            "patient_id": ""},
        "description":     "Append an order.place authored by the instructor as MD.",
    },
    {
        "kind":            "family.arrives",
        "label":           "Family arrives at bedside",
        "category":        "chart",
        "default_params":  {"who": "daughter"},
        "description":     "Append a note.save documenting communication / consent need.",
    },
    {
        "kind":            "pump.alarm",
        "label":           "Pump alarm — occlusion",
        "category":        "device",
        "default_params":  {"tone": "occlusion"},
        "description":     "Emit a device.alarm.injected on a bound pump; falls back to a chart event if no pump is bound.",
    },
    {
        "kind":            "code.blue",
        "label":           "Code blue — full arrest (compound)",
        "category":        "compound",
        "default_params":  {},
        "description":     "Compound scene: vitals.crash + CODE BLUE note + instructor.trigger marker + pump alarm (if bound).",
    },
    {
        "kind":            "note.instructor",
        "label":           "Note — free-form instructor message",
        "category":        "chart",
        "default_params":  {"text": ""},
        "description":     "Append a note.save with arbitrary instructor text.",
    },
]


def palette() -> list[dict[str, Any]]:
    """Public read of the built-in scene palette. Returned verbatim —
    callers can present it to the operator UI / scene-injector dialog."""
    return [dict(entry) for entry in PALETTE]


# ── Internal helpers ─────────────────────────────────────────────────

def _station_id(enc: Encounter, *, prefix: str = "instructor") -> str:
    """Pick an EHR station id to attribute the scene's chart event to.

    Prefers an actually-joined EHR station so the cohort debrief
    correctly attributes the event source. If none exists yet (a fresh
    encounter with no student station yet), synthesize a deterministic
    instructor station id so the row still passes the NOT NULL
    `ehr_station_id` constraint. The fold() reader tolerates any string.
    """
    if enc.ehr_stations:
        return next(iter(enc.ehr_stations.keys()))
    return f"{prefix}:{enc.id}"


# Phase 7 1.4 — Scene kinds that the M26 alarm bus surfaces.
# When a payload carries level='alarm', the alarm bus picks it up.
# Currently: code.blue compound + pump.alarm (when bound). Future
# M29 future-device-stubs add fire.alarm scenes.
_ALARM_LEVEL_KINDS: frozenset[str] = frozenset({
    "code.blue", "pump.alarm",
})


def _scene_payload(kind: str, by: str, extra: dict[str, Any]) -> dict[str, Any]:
    """Tag every scene-driven event so M14 can filter scene events out
    of student-driven debrief stats. Phase 7 1.4 — alarm-class scenes
    also carry ``level='alarm'`` so the M26 alarm bus picks them up."""
    out = {**extra, "source": "scene", "scene_kind": kind, "by": by}
    if kind in _ALARM_LEVEL_KINDS:
        out.setdefault("level", "alarm")
    return out


def _find_pump_station(enc: Encounter) -> Any | None:
    """First IV or enteral pump device station on this encounter, if any.
    Cabinets are excluded — alarms are a pump-only feature."""
    for ds in enc.device_stations.values():
        if ds.device_kind in ("pump_iv", "pump_enteral"):
            return ds
    return None


# ── Per-kind handlers ────────────────────────────────────────────────

def _handle_vitals_drop(enc, kind, params, *, by):
    defaults = next(s for s in PALETTE if s["kind"] == kind)["default_params"]
    vitals = {**defaults, **params}
    sid = _station_id(enc)
    event_id = ehr_db.append_event(
        enc.id, sid,
        type="vitals.record", surface="vitals",
        payload=_scene_payload(kind, by, vitals),
    )
    return {"ok": True, "kind": kind, "encounter_id": enc.id,
            "category": "chart", "event_ids": [event_id]}


def _handle_vitals_rise(enc, kind, params, *, by):
    defaults = next(s for s in PALETTE if s["kind"] == kind)["default_params"]
    vitals = {**defaults, **params}
    sid = _station_id(enc)
    event_id = ehr_db.append_event(
        enc.id, sid,
        type="vitals.record", surface="vitals",
        payload=_scene_payload(kind, by, vitals),
    )
    return {"ok": True, "kind": kind, "encounter_id": enc.id,
            "category": "chart", "event_ids": [event_id]}


def _handle_lab_result(enc, kind, params, *, by):
    panel = params.get("panel", "BMP")
    values = params.get("values") or next(
        s for s in PALETTE if s["kind"] == "lab.result"
    )["default_params"]["values"]
    sid = _station_id(enc)
    event_id = ehr_db.append_event(
        enc.id, sid,
        type="result.acknowledge", surface="results",
        payload=_scene_payload(kind, by, {"panel": panel, "values": values,
                                            "result_id": f"scene-lab-{int(time.time() * 1000)}"}),
    )
    return {"ok": True, "kind": kind, "encounter_id": enc.id,
            "category": "chart", "event_ids": [event_id]}


def _handle_order_new(enc, kind, params, *, by):
    sid = _station_id(enc)
    order = {
        "order_id":   f"scene-ord-{int(time.time() * 1000)}",
        "order_type": params.get("order_type", "med"),
        "code":       params.get("code", "ORDER"),
        "label":      params.get("label", "Instructor-authored order"),
        **_scene_payload(kind, by, {"authored_by": "MD (instructor scene)"}),
    }
    patient_id = params.get("patient_id", "")
    event_id = ehr_db.append_order(enc.id, sid,
                                     patient_id=patient_id, order=order)
    return {"ok": True, "kind": kind, "encounter_id": enc.id,
            "category": "chart", "event_ids": [event_id]}


def _handle_family_arrives(enc, kind, params, *, by):
    who = params.get("who", "family member")
    body = params.get("note") or (
        f"Family member arrived at bedside ({who}). Communication and "
        "consent needs. Document interaction and any patient-stated wishes."
    )
    sid = _station_id(enc)
    event_id = ehr_db.append_event(
        enc.id, sid,
        type="note.save", surface="notes",
        payload=_scene_payload(kind, by, {
            "note_id": f"scene-fam-{int(time.time() * 1000)}",
            "body":    body,
            "who":     who,
        }),
    )
    return {"ok": True, "kind": kind, "encounter_id": enc.id,
            "category": "chart", "event_ids": [event_id]}


def _handle_pump_alarm(enc, kind, params, *, by):
    """Emit a device.alarm.injected event on a bound pump. Falls back to
    a chart instructor.trigger event when no pump is bound — keeps the
    scene's footprint visible in the chart even without a pump."""
    tone = params.get("tone", "occlusion")
    pump = _find_pump_station(enc)
    if pump is not None:
        device_event = ehr_db.append_device_event(
            enc.id, pump.station_id,
            type="alarm.injected", surface="instructor",
            payload=_scene_payload(kind, by, {"tone": tone}),
        )
        return {"ok": True, "kind": kind, "encounter_id": enc.id,
                "category": "device",
                "station_id": pump.station_id,
                "device_event_id": device_event.get("id")}
    # No pump bound — chart-side fallback so the event is still recorded.
    sid = _station_id(enc)
    event_id = ehr_db.append_event(
        enc.id, sid,
        type="instructor.trigger", surface="instructor",
        payload=_scene_payload(kind, by, {
            "fallback_reason": "no pump bound to this encounter",
            "tone":            tone,
            "scene":           {"kind": kind, "params": params},
        }),
    )
    return {"ok": True, "kind": kind, "encounter_id": enc.id,
            "category": "chart_fallback", "event_ids": [event_id]}


def _handle_code_blue(enc, kind, params, *, by):
    """Compound: vitals crash + CODE BLUE note + instructor.trigger
    marker + (optional) pump alarm if a pump is bound. Each child
    event carries its own source='scene' tag so the debrief can either
    treat them as one compound or as four separate signals."""
    sid = _station_id(enc)
    event_ids: list[int] = []
    crash = {"hr": 40, "sbp": 60, "dbp": 30, "spo2": 70, "rr": 4,
              "temp_f": 97.0}
    event_ids.append(ehr_db.append_event(
        enc.id, sid,
        type="vitals.record", surface="vitals",
        payload=_scene_payload(kind, by, {**crash, "compound_role": "crash_vitals"}),
    ))
    event_ids.append(ehr_db.append_event(
        enc.id, sid,
        type="note.save", surface="notes",
        payload=_scene_payload(kind, by, {
            "note_id":       f"code-blue-{int(time.time() * 1000)}",
            "body":          "CODE BLUE — patient unresponsive, no pulse. Initiate ACLS.",
            "compound_role": "code_announcement",
        }),
    ))
    event_ids.append(ehr_db.append_event(
        enc.id, sid,
        type="instructor.trigger", surface="instructor",
        payload=_scene_payload(kind, by, {
            "scene": {"kind": kind, "params": params},
            "compound_role": "marker",
        }),
    ))
    device_event_id = None
    pump = _find_pump_station(enc)
    if pump is not None:
        device_event = ehr_db.append_device_event(
            enc.id, pump.station_id,
            type="alarm.injected", surface="instructor",
            payload=_scene_payload(kind, by, {"tone": "high_priority",
                                                "compound_role": "pump_alarm"}),
        )
        device_event_id = device_event.get("id")
    return {"ok": True, "kind": kind, "encounter_id": enc.id,
            "category": "compound",
            "event_ids": event_ids,
            "device_event_id": device_event_id}


def _handle_note_instructor(enc, kind, params, *, by):
    text = params.get("text", "Instructor scene note.").strip()
    if not text:
        text = "Instructor scene note."
    sid = _station_id(enc)
    event_id = ehr_db.append_event(
        enc.id, sid,
        type="note.save", surface="notes",
        payload=_scene_payload(kind, by, {
            "note_id": f"scene-note-{int(time.time() * 1000)}",
            "body":    text,
        }),
    )
    return {"ok": True, "kind": kind, "encounter_id": enc.id,
            "category": "chart", "event_ids": [event_id]}


def _handle_default(enc, kind, params, *, by):
    """Unknown kind — record an instructor.trigger so the scene is
    still observable in the chart. Forward-compatibility hook."""
    sid = _station_id(enc)
    event_id = ehr_db.append_event(
        enc.id, sid,
        type="instructor.trigger", surface="instructor",
        payload=_scene_payload(kind, by, {
            "scene": {"kind": kind, "params": params},
            "note":  "Unknown scene kind — fell back to instructor.trigger.",
        }),
    )
    return {"ok": True, "kind": kind, "encounter_id": enc.id,
            "category": "chart_fallback", "event_ids": [event_id]}


_HANDLERS: dict[str, Callable[..., dict[str, Any]]] = {
    "vitals.drop":     _handle_vitals_drop,
    "vitals.rise":     _handle_vitals_rise,
    "lab.result":      _handle_lab_result,
    "order.new":       _handle_order_new,
    "family.arrives":  _handle_family_arrives,
    "pump.alarm":      _handle_pump_alarm,
    "code.blue":       _handle_code_blue,
    "note.instructor": _handle_note_instructor,
}


# ── Public entry point ───────────────────────────────────────────────

def apply(enc: Encounter, scene: dict[str, Any],
          *, by: str = "instructor") -> dict[str, Any]:
    """Apply a scene to one encounter. Returns a result dict with at
    minimum {ok, kind, encounter_id, category}. The exact shape of the
    rest depends on the kind — chart-category scenes return
    ``event_ids: list[int]``; the pump-alarm device-category returns
    ``device_event_id``; compound returns both.

    Scene shape from the wire: ``{"kind": "...", "params": {...}}``.
    Both keys are optional — defaults from PALETTE fill in the gaps.
    Unknown kinds route to the forward-compatibility handler.
    """
    kind   = scene.get("kind") or "note.instructor"
    params = scene.get("params") or {}
    handler = _HANDLERS.get(kind, _handle_default)
    return handler(enc, kind, params, by=by)
