"""V7 Phase 7 — Future-device stubs (M29).

Four new in-sim device kinds that students press to raise an alarm.
The alarms surface immediately on the M26 alarm bus, visible to
the Nursing Station (M27) supervisor and the operator dashboard
(future M5 follow-up).

  - **call_bell**        — Patient pages the nurse (info severity).
  - **bed_alarm**        — Patient out of bed (warning).
  - **code_blue_button** — Code blue trigger (critical).
  - **fire_alarm**       — Fire alarm pulled (critical).

The M v6 device subsystem owns the heavyweight pump / cabinet
hardware. M29's "future devices" are intentionally lightweight —
they don't need spec.json / engine.py / skin.svg bundles like a
pump does. Each is just a button. The POST handler emits an
``alarm.injected`` device_event into the chart, which the M26
alarm bus picks up. No physical / SVG skin is required for the
MVP cut; a v7.1 enhancement could add tap-target SVGs for
deployment on physical tablets.

Each kind classifies into M26's severity ladder via the
``_SEVERITY_BY_KIND`` map in ``portal/alarms.py``.
"""
from __future__ import annotations

import secrets
import time
from typing import Any

from . import ehr_db


# Kind → human label for the operator dashboard + nurse station.
KINDS: dict[str, str] = {
    "call_bell":         "Call bell",
    "bed_alarm":         "Bed alarm",
    "code_blue_button":  "Code blue button",
    "fire_alarm":        "Fire alarm",
}


def is_valid_kind(kind: str) -> bool:
    return kind in KINDS


def label_for(kind: str) -> str:
    return KINDS.get(kind, kind)


def press(room: Any, encounter_id: str, kind: str,
          *, by: str = "bedside") -> dict[str, Any]:
    """Record a button-press as an alarm.injected device_event.
    Returns the persisted device_event dict. Raises:
      - ``KeyError`` for unknown encounter_id
      - ``ValueError`` for unknown kind
    """
    if not is_valid_kind(kind):
        raise ValueError(f"unknown future-device kind {kind!r}")
    enc = room.encounters.get(encounter_id)
    if enc is None:
        raise KeyError(f"unknown encounter {encounter_id!r}")
    # Synthetic station id keyed on the kind + a short suffix so
    # repeated presses don't all collapse into one station row.
    station_id = f"{kind}:{encounter_id[:8]}"
    return ehr_db.append_device_event(
        encounter_id, station_id,
        type="alarm.injected", surface="bedside",
        payload={
            "tone":         kind,
            "label":        label_for(kind),
            "source":       "future_device",
            "device_kind":  kind,
            "by":           by,
            "press_id":     secrets.token_urlsafe(6),
            "ts":           time.time(),
        },
    )
