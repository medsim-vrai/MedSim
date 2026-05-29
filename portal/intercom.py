"""V7 Phase 7 — Intercom (M28).

Lets the in-sim Nursing Station (M27) page a specific bedside
encounter. The MVP cut (this module) writes a ``comm.intercom``
chart_event carrying the typed message text + voice selection. The
chart-station UI on the bedside picks the event up and plays
(or displays) it. M28 also fires a WS push on /ws/room/{room_code}
so the bedside reacts in real time.

Future v7.1 candidate: full WebRTC mic-to-mic. Out of scope here —
M28 ships a TEXT-driven path (the nurse types, the bedside hears
synthesized voice + sees text). The data contract is forward-
compatible: a future WebRTC upgrade just adds an audio_url to the
comm.intercom payload alongside the existing text.
"""
from __future__ import annotations

import time
from typing import Any

from . import ehr_db


def _staff_persona_for(enc: Any) -> str | None:
    """Pick a 'staff' persona id from the encounter's selected
    personas (non-patient roles like Charge Nurse Kim P-004). Returns
    None if no staff persona is bound — caller falls back to a
    generic Hospital Communications voice.

    Heuristic: the patient persona is enc.patient_persona_id;
    everyone else in selected_personas is staff/family.
    """
    if not enc.selected_personas:
        return None
    patient_id = enc.patient_persona_id
    for pid in enc.selected_personas:
        if pid != patient_id:
            return pid
    return None


def page_encounter(room: Any, encounter_id: str,
                    *, text: str, from_student_id: str | None = None,
                    voice_id: str | None = None) -> dict[str, Any]:
    """Page a bedside encounter from the Nursing Station.

    Writes a ``comm.intercom`` chart_event scoped to the encounter's
    session id. Returns a result dict the caller (the M28 route)
    serializes to JSON.

    The payload carries:
      - text — the message the nurse typed
      - from_student_id — the nurse-station student id (audit trail)
      - voice_id — ElevenLabs voice id used for synthesis. If None,
        the caller falls back to browser SpeechSynthesis.
      - persona_id — staff persona id when chosen automatically.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("intercom text required")
    enc = room.encounters.get(encounter_id)
    if enc is None:
        raise KeyError(f"unknown encounter {encounter_id!r}")

    persona_id = _staff_persona_for(enc)
    # Resolve voice: explicit voice_id wins; otherwise look up the
    # encounter's voice assignment for the chosen staff persona;
    # otherwise None (browser-TTS fallback).
    resolved_voice = voice_id or (
        enc.voice_assignments.get(persona_id) if persona_id else None
    )

    station_id = (next(iter(enc.ehr_stations.keys()))
                   if enc.ehr_stations
                   else f"intercom:{from_student_id or 'nurse_station'}")
    event_id = ehr_db.append_event(
        encounter_id, station_id,
        type="comm.intercom", surface="comms",
        payload={
            "text":             text,
            "from_student_id":  from_student_id,
            "persona_id":       persona_id,
            "voice_id":         resolved_voice,
            "source":           "nurse_station",
            "ts":               time.time(),
        },
    )
    return {
        "ok":             True,
        "event_id":       event_id,
        "encounter_id":   encounter_id,
        "persona_id":     persona_id,
        "voice_id":       resolved_voice,
        "text":           text,
    }
