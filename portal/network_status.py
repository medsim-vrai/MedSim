"""FR-019 — assemble a live NetworkSnapshot of the running simulation for the
instructor "Network & device status" tool.

Pure read of control_room + ehr_db + library state into the contract in
docs/FR-019-network-status/schema.ts. The UI is a pure render of this snapshot —
truth lives here. Enums are closed; unknown classes/roles degrade to neutral.

v1 derives device link-state from station heartbeats (recent beat → active, stale →
fault). The richer active/idle/available split via instructor-managed links
(FR-019 decision 2) and the unified student-roster-with-roles (decision 1) refine
this later; the snapshot shape stays the same.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from . import control_room as _cr
from . import ehr_db as _db
from . import library as _lib

# device_kind → (snapshot class, slot)   slot: manikin | tablet | supporting | common
_KIND_MAP: dict[str, tuple[str, str]] = {
    "telemetry_monitor": ("physio", "manikin"),
    "vent_monitor":      ("physio", "manikin"),
    "ventilator":        ("supporting", "supporting"),
    "pump_iv":           ("supporting", "supporting"),
    "pump_enteral":      ("supporting", "supporting"),
    "patient_integrated_alarm": ("supporting", "supporting"),
    "cabinet":           ("operational", "common"),
}
_HEARTBEAT_FRESH = 45.0   # seconds — matches DeviceStation.online

# MedSim role strings → the closed Role enum (else None).
_ROLE_MAP = {
    "doctor": "doctor", "physician": "doctor", "md": "doctor",
    "charge_nurse": "charge_nurse", "charge nurse": "charge_nurse",
    "supervisor": "supervising_nurse", "supervising_nurse": "supervising_nurse",
    "supervising nurse": "supervising_nurse",
    "respiratory_therapist": "respiratory_therapist", "respiratory therapist": "respiratory_therapist",
    "rt": "respiratory_therapist",
    "pharmacist": "pharmacist", "pharmacy": "pharmacist",
}


# N4 (FR-019 decision 2) — instructor-managed link state. v1 derives every
# device state from heartbeats; an instructor can OVERRIDE a node to
# "available" (planned/unplugged) or "fault" (known-bad) from the network view.
# Session-scoped by design: cleared on restart, never persisted (the derived
# heartbeat truth always returns).
_state_overrides: dict[str, str] = {}


def set_state_override(node_id: str, state: str) -> bool:
    """state ∈ {'available','fault'} sets; 'auto' clears. False on bad input."""
    node_id = (node_id or "").strip()
    if not node_id:
        return False
    if state == "auto":
        _state_overrides.pop(node_id, None)
        return True
    if state in ("available", "fault"):
        _state_overrides[node_id] = state
        return True
    return False


def _apply_overrides(snap: dict) -> None:
    if not _state_overrides:
        return
    seen: set = set()

    def _mark(node):
        if not isinstance(node, dict):
            return
        nid = node.get("id")
        if nid is None:
            return
        seen.add(nid)
        if nid in _state_overrides:
            node["state"] = _state_overrides[nid]
            node["managed"] = True

    for n in snap.get("commonDevices") or []:
        _mark(n)
    for unit in snap.get("units") or []:
        for rm in unit.get("rooms") or []:
            for pt in rm.get("patients") or []:
                _mark(pt.get("manikin"))
                _mark(pt.get("tablet"))
                for d in pt.get("supporting") or []:
                    _mark(d)
    # Self-cleaning: drop overrides for nodes that no longer exist (a typo'd id,
    # a device that left the session) so a stale override can never become an
    # invisible, unclearable ghost.
    for gone in [k for k in _state_overrides if k not in seen]:
        _state_overrides.pop(gone, None)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_role(role: str | None) -> str | None:
    return _ROLE_MAP.get((role or "").strip().lower())


def _dev_state(last_seen: float | None) -> str:
    if not last_seen:
        return "idle"            # registered, no recent beat we can read
    return "active" if (time.time() - last_seen) < _HEARTBEAT_FRESH else "fault"


def _device_node(d: dict[str, Any], cls: str) -> dict[str, Any]:
    return {
        "id": d.get("id"),
        "tag": str(d.get("label") or d.get("device_kind") or "DEV")[:18],
        "name": d.get("label") or d.get("device_model") or d.get("device_kind") or "Device",
        "cls": cls,
        "state": _dev_state(d.get("last_seen")),
    }


def _persona(pid: str) -> tuple[str, str | None]:
    p = _lib.get_persona(pid) or {}
    return (p.get("name") or pid, _norm_role(p.get("role")))


def build_snapshot() -> dict[str, Any]:
    """Assemble the NetworkSnapshot from the active room. Returns a valid (empty)
    snapshot when nothing is running."""
    room = _cr.get_active_room()
    snap: dict[str, Any] = {
        "sessionId": (getattr(room, "room_id", "") if room else "") or "",
        "timestamp": _iso_now(),
        "control": {"id": "ctrl", "tag": "CTRL-01", "name": "Instructor Control",
                    "state": "active" if room else "fault"},
        "commonDevices": [],
        "units": [],
        "students": [],
    }
    if room is None:
        _state_overrides.clear()   # no live session → managed-link overrides reset
        return snap

    encs = list(room.encounters.values())
    shared = set(getattr(room, "shared_personas", []) or [])
    common: list[dict[str, Any]] = []

    # ── Shared operational surfaces (med cart · medical records · nurses station) ──
    # Mirror the Operate cockpit so the map shows the SAME shared assets. Each poll
    # re-reads live state, so connect/drop flips state within the poll + heartbeat
    # window.
    # Med cart(s) — real device stations; state from their heartbeat.
    for cart_id, label in (getattr(room, "cart_labels", {}) or {}).items():
        try:
            st = _db.get_device_station(cart_id)
        except Exception:  # noqa: BLE001
            st = None
        common.append({"id": cart_id, "tag": str(label or "CART")[:18],
                       "name": label or "Med cart", "cls": "operational",
                       "state": _dev_state((st or {}).get("last_seen")),
                       "area": "nurses_station"})
    # Medical records — one shared, session-wide chart surface; active when any
    # records/EHR station is online across the beds, else idle (present + ready).
    _rec_online = any(getattr(s, "online", False)
                      for enc in encs
                      for s in (getattr(enc, "ehr_stations", {}) or {}).values())
    common.append({"id": "records", "tag": "REC-01", "name": "Medical records",
                   "cls": "operational", "state": "active" if _rec_online else "idle",
                   "area": "nurses_station"})
    # Nurses station — shared monitor for a multi-bed room (Operate shows it only
    # then); active when a student is seated at it (role nurse_station).
    if len(encs) > 1:
        _ns_active = any(getattr(st, "role", "") == "nurse_station"
                         for st in (getattr(room, "students", {}) or {}).values())
        common.append({"id": "nursing", "tag": "STN-01", "name": "Nurses station",
                       "cls": "operational", "state": "active" if _ns_active else "idle",
                       "area": "nurses_station"})

    # Shared character roles (room-level).
    for pid in (getattr(room, "shared_personas", []) or []):
        name, role = _persona(pid)
        node = {"id": pid, "tag": str(pid)[:18], "name": name, "cls": "character", "state": "idle"}
        if role:
            node["role"] = role
        common.append(node)

    # Patients (one per bed) + their devices + per-bed characters.
    patients: list[dict[str, Any]] = []
    for i, enc in enumerate(encs, 1):
        try:
            devs = _db.device_stations(enc.id) or []
        except Exception:  # noqa: BLE001
            devs = []
        manikin = None
        supporting: list[dict[str, Any]] = []
        for d in devs:
            cls, slot = _KIND_MAP.get(d.get("device_kind") or "", ("supporting", "supporting"))
            if slot == "common":
                continue                                   # carts handled above
            node = _device_node(d, cls)
            if slot == "manikin" and manikin is None:
                manikin = node
            else:
                supporting.append(node)
        ppid = enc.patient_persona_id
        tablet = ({"id": f"{enc.id}:tablet", "tag": "TAB", "name": "Patient tablet",
                   "cls": "vrai", "state": "idle"} if ppid else None)
        patients.append({"id": enc.id, "tag": f"PT-{i:02d}", "bed": i,
                         "manikin": manikin, "tablet": tablet, "supporting": supporting})
        # Per-bed (non-shared) characters → character nodes assigned to this patient.
        for pid in (enc.selected_personas or []):
            if pid in shared or pid == ppid:
                continue
            name, role = _persona(pid)
            node = {"id": f"{enc.id}:{pid}", "tag": str(pid)[:18], "name": name,
                    "cls": "character", "state": "idle", "assignedToPatientId": enc.id}
            if role:
                node["role"] = role
            common.append(node)

    snap["commonDevices"] = common
    snap["units"] = [{
        "id": getattr(room, "room_id", "") or "unit",
        "name": room.label or "Unit A", "focus": "",
        "rooms": [{"id": getattr(room, "room_id", "") or "room",
                   "label": room.label or "Room 1",
                   "capacity": max(8, len(encs)), "patients": patients}],
    }]

    # Students — the staff roster (assignments = encounter ids = patient ids).
    students: list[dict[str, Any]] = []
    for sid, sm in (getattr(room, "staff", {}) or {}).items():
        # Effective coverage, not just the explicit list: charge nurse / supervisor
        # / instructor (and an unassigned nurse in open mode) cover ALL patients.
        # Use the SAME scoping the med cart + records terminal enforce.
        try:
            assigns = list(room.accessible_encounter_ids(sid))
        except Exception:  # noqa: BLE001
            assigns = [eid for eid in (getattr(sm, "assignments", []) or []) if eid in room.encounters]
        students.append({
            "id": sid,
            "tag": str(getattr(sm, "initials", "") or sid)[:10],
            "name": getattr(sm, "display_name", "") or sid,
            "patientIds": assigns,
            "role": _norm_role(getattr(sm, "role", "")),
        })
    snap["students"] = students

    # N0 (FR-019 decision 1): the extended roster is the SOURCE OF TRUTH for the
    # student tier — a student rostered into a character ROLE (doctor / charge
    # nurse / supervising nurse / RT / pharmacist) FILLS that seat: the matching
    # character node is marked student-filled, so the view shows the student
    # replacing the AI character rather than two disconnected nodes. First
    # unfilled node with the role wins; a signed-in (recently seen) student
    # shows the seat as active, a rostered-but-absent one leaves it idle.
    by_role: dict[str, list[dict[str, Any]]] = {}
    for node in common:
        if node.get("cls") == "character" and node.get("role"):
            by_role.setdefault(node["role"], []).append(node)
    now = time.time()
    for sid, sm in (getattr(room, "staff", {}) or {}).items():
        role = _norm_role(getattr(sm, "role", ""))
        for node in by_role.get(role or "", []):
            if "studentId" in node:
                continue
            node["studentId"] = sid
            node["filledBy"] = getattr(sm, "display_name", "") or sid
            # ACTIVE only with evidence of an actual sign-in: register_staff seeds
            # last_seen == created_at, so a just-rostered (never-joined) student
            # would otherwise read "active" for 30 min. touch() bumps last_seen on
            # real cabinet/records activity, so a live seat has last_seen well past
            # created_at AND recent; everyone else is rostered-but-idle.
            seen = getattr(sm, "last_seen", None)
            created = getattr(sm, "created_at", None)
            active = bool(seen and now - seen < 1800
                          and (not created or seen - created > 2))
            node["state"] = "active" if active else "idle"
            break
    _apply_overrides(snap)
    return snap
