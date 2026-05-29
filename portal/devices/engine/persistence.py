"""Persistence shim — every engine writes through here.

Centralizing the writes lets the WebSocket layer subscribe in one place
and lets tests stub a single function. All events go to ``device_event``
via ``ehr_db.append_device_event`` — never directly to SQLite.

Each appended event is decorated with the current character_id at write
time, so debrief replay can show which character was assigned when an
action happened — even if the device is later reassigned.
"""
from __future__ import annotations

from typing import Any

from portal import ehr_db


def record(session_id: str, station_id: str, *,
           type: str, surface: str,
           payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Append an event. Returns the persisted row (id, ts, etc.).

    ``surface`` is one of ``"instructor" | "device" | "system"`` — the
    debrief and comparison engines filter on this.
    """
    payload = dict(payload or {})
    # Stamp the currently-assigned character at write time. The
    # assignment is append-only, so re-reading later gives the same
    # answer; baking it into the payload makes debrief decoding O(1).
    assignment = ehr_db.current_assignment(station_id)
    if assignment and assignment.get("character_id"):
        payload.setdefault("character_id", assignment["character_id"])
    return ehr_db.append_device_event(
        session_id, station_id,
        type=type, surface=surface, payload=payload,
    )


def replay(station_id: str) -> list[dict[str, Any]]:
    return ehr_db.device_events(station_id=station_id)
