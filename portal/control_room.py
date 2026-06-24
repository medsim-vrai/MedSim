"""Control-room state for MEDSIM V7 — multi-patient extension.

A ControlRoom is the unit of instructor governance in v7. It contains
N Encounters (each is a v6 ControlSession promoted in place — see
``control_session.ControlSession``), an optional roster of Students, and
optional per-encounter cost caps.

Single-patient mode is just a room of 1: when the wizard's
``Single Patient`` branch finalizes, ``create_room_with_single_encounter``
builds a ControlRoom holding one Encounter and the v6-compat helpers
(``get_active``, ``get_by_join_code``) keep returning that one
Encounter, so every v6 code path resolves identically.

Held in memory only — single-instructor, single-active-room model.
The DB is the system of record for chart content (see ``ehr_db``);
this module is the in-process index over it.

Cross-references:
  - Schema lives in ``ehr_db.SCHEMA_MIGRATIONS`` migration 4 (M1).
  - Design rationale is in
    ``Multipatient multi student simualtion/research/p6_v7_architecture.md``.
"""
from __future__ import annotations

import secrets
import string
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from .control_session import ControlSession

# An Encounter IS a ControlSession in v7 — the v6 class has been extended
# in place with the new v7 fields (room_id, chart_mode, etc.) so the rich
# v6 behavior (stations, transcript, EHR, devices) carries forward without
# a rewrite. Code reads better when it uses ``Encounter`` in v7 contexts.
Encounter = ControlSession


# M19 — Capacity caps. Hard limits at the data layer, surfaced on
# /api/room/state for the dashboard banner. The values match P6
# §"Capacity caps": 10 concurrent encounters per room, 24 student
# stations per room. Tuned to one instructor + one classroom shift.
MAX_ENCOUNTERS_PER_ROOM = 10
MAX_STUDENT_STATIONS_PER_ROOM = 24


class CapacityExceeded(Exception):
    """Raised when an add_encounter / add_student would exceed the
    M19 caps. Route handlers translate this to a 409 with a clear
    message."""


def _count_student_stations(room: "ControlRoom") -> int:
    """Total chat stations across every encounter in the room. The
    cap is on student STATIONS (one per student device), not on the
    student roster — students may be on the roster without an active
    station yet."""
    return sum(len(e.stations) for e in room.encounters.values())


def _new_room_code() -> str:
    """Six-character room code, visually disambiguated. Distinct from
    encounter join codes so QR scans don't collide."""
    alphabet = string.ascii_uppercase + string.digits
    alphabet = (alphabet
                .replace("0", "").replace("O", "")
                .replace("1", "").replace("I", "").replace("L", ""))
    return "".join(secrets.choice(alphabet) for _ in range(6))


@dataclass
class Student:
    """A learner registered to a ControlRoom and optionally assigned to
    one Encounter. Persisted in the ``student`` table (M1 schema v4 +
    Phase 7 schema v5) so rostering survives server restarts.

    ``role`` (Phase 7 1.2) distinguishes M9 bedside students from M27
    Nursing Station supervisor students. Bedside students assign to
    an encounter; nurse_station students are room-scoped — they
    monitor every encounter remotely and don't bind to a single bed.
    """
    student_id: str
    display_name: str
    room_id: str
    assigned_encounter_id: str | None = None
    registered_at: float = field(default_factory=time.time)
    last_seen: float | None = None
    role: str = "bedside"   # 'bedside' | 'nurse_station'

    def touch(self) -> None:
        self.last_seen = time.time()


@dataclass
class StaffMember:
    """A cabinet user on the room's staff roster (med cart v2) — distinct
    from the learner ``Student`` table so cart-only people (instructors)
    never surface in the student-join / debrief flows. Persisted in the
    ``staff_member`` table (schema v8).

    ``role`` is 'nurse' | 'charge_nurse' | 'supervisor' | 'instructor'.
    ``assignments`` is the list of encounter_ids a NURSE is scoped to for
    med pulls — empty means "all of the cart's patients" (the
    no-assignments-show-all rule). charge_nurse / supervisor / instructor
    always see every patient regardless of ``assignments``.
    """
    staff_id: str
    room_id: str
    display_name: str
    initials: str = ""
    role: str = "nurse"
    assignments: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_seen: float | None = None

    @property
    def sees_all_patients(self) -> bool:
        """Charge nurse / supervisor / instructor have unit-wide access; a
        nurse with no explicit assignments also sees all (graceful
        default). Only a nurse WITH assignments is scoped down."""
        if self.role in ("charge_nurse", "supervisor", "instructor"):
            return True
        return not self.assignments

    def touch(self) -> None:
        self.last_seen = time.time()


@dataclass
class ControlRoom:
    """A roomful of Encounters under one instructor.

    Capacity caps are advisory at the dataclass level — the
    capacity-hardening module (M19) enforces them at the route layer.
    """
    room_id: str
    room_code: str
    label: str = ""
    status: str = "active"  # active | frozen | ended
    created_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    haiku_rate_cap: int | None = None     # M17 — turns/minute across the room
    voice_char_cap: int | None = None     # M17 — ElevenLabs char budget
    encounters: dict[str, Encounter] = field(default_factory=dict)   # keyed by Encounter.id
    students: dict[str, Student] = field(default_factory=dict)       # keyed by student_id
    # Med cart v2 — the room's STAFF roster (cabinet users: nurse /
    # charge_nurse / supervisor / instructor), keyed by staff_id. Persisted
    # in the `staff_member` table and rehydrated on boot like students; NOT
    # in the session_state snapshot (operator roster, not sim config).
    staff: dict[str, "StaffMember"] = field(default_factory=dict)
    # Med cart v2 — access mode for the shared terminals (cart + records). When
    # True (the default) access is OPEN: any student signs in with name/initials
    # and can reach every patient. When False it is RESTRICTED to each student's
    # assigned patients (the staff roster above); charge_nurse / supervisor /
    # instructor still see all. The instructor sets this in the room dashboard.
    open_med_access: bool = True
    # M17 — lazy-attached budget tracker. Built on first access to
    # avoid an import cycle; values mirror haiku_rate_cap +
    # voice_char_cap and are updated whenever the operator changes
    # the caps via the M17 routes.
    _budget_tracker: object | None = None
    # M47 — room-level med-cart linkage. A single med cart
    # (DeviceStation kind=cabinet) can serve multiple encounters in
    # the same room. The DB-side `device_station.session_id` still
    # references ONE encounter (the cart's primary owner — kept for
    # v6 compat + per-station route resolution), but this dict maps
    # the cart's station_id to the full list of encounters it serves.
    # The cabinet bootstrap reads it to render grouped per-patient
    # MAR sections; the dispense event handler reads it to find which
    # encounter's transcript a med dispense should land on.
    cart_links: dict[str, list[str]] = field(default_factory=dict)
    # M47 — friendly labels for room-level carts ("Cart A", "ED cart")
    # keyed by station_id so the dashboard + encounter console can
    # display them without round-tripping through ehr_db.
    cart_labels: dict[str, str] = field(default_factory=dict)
    # FR-007 — the universal/shared cast (common doctor, allied-health team)
    # available at every bed. Each encounter's selected_personas already
    # includes these; this room-level list lets surfaces (e.g. the QR sheet)
    # separate "common characters" from per-bed scenario cast.
    shared_personas: list[str] = field(default_factory=list)
    # FR-007 v2 — "one tablet, many patients": a single room-level chat station
    # per shared persona (NOT bound to a bed), with one transcript (Station.history)
    # that spans the room. Not snapshotted (transcript is trainee PHI, ADR-0014).
    room_stations: dict = field(default_factory=dict)   # persona_id -> Station
    # M48 — Operator-settable alarm thresholds. Room-level (applies to
    # every encounter in the room) — operators rarely need per-bed
    # thresholds in a teaching scenario, and the simpler UX is one
    # screen of settings on the Nursing Station.  Defaults below are
    # adult-norm sentinel values; operator overrides them per
    # scenario. The alarm bus (portal/alarms.py) reads these on every
    # /api/room/alarms tick.
    #
    # Schema:
    #   {"hr": {"low": 50, "high": 120},
    #    "spo2": {"low": 90, "high": null},     # null = no upper bound
    #    "rr":  {"low": 8,  "high": 30},
    #    "dangerous_rhythms": ["vfib", "asystole", "vtach"]}
    alarm_thresholds: dict[str, Any] = field(default_factory=lambda: {
        "hr":   {"low": 50,  "high": 120},
        "spo2": {"low": 90,  "high": None},
        "rr":   {"low": 8,   "high": 30},
        # M50 — Blood pressure thresholds. Both systolic + diastolic
        # are tracked because real bedside monitors alarm on both.
        # Adult-norm defaults (NHANES adult BP range; tighten per scenario).
        "bp_systolic":  {"low": 90, "high": 160},
        "bp_diastolic": {"low": 60, "high": 100},
        "dangerous_rhythms": ["vfib", "asystole", "vtach"],
    })
    # M50 — Per-alarm silence / clear state. Map from alarm_id →
    # {"until": expiry_ts, "cleared": bool}. Threshold alarms can't be
    # "cleared" the M26 way (no event log to write), so the supervisor
    # uses Silence (cleared=False, until=now+N) to mute audio while
    # the breach continues, or Clear (cleared=True, until=inf-ish)
    # which hides the alarm from the active feed entirely. Auto-
    # expires at the `until` timestamp.
    silenced_alarms: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def budget(self):  # type: ignore[override]
        """Lazy access to the M17 RoomBudgetTracker. Constructed on
        first use; haiku_rate_cap + voice_char_cap re-applied each
        time so cap changes take effect immediately."""
        from . import budgets
        bt = self._budget_tracker
        if bt is None or not isinstance(bt, budgets.RoomBudgetTracker):
            bt = budgets.RoomBudgetTracker(
                haiku_rate_cap=self.haiku_rate_cap,
                voice_char_cap=self.voice_char_cap,
            )
            self._budget_tracker = bt
        else:
            # Keep the tracker's caps in sync with the room's.
            bt.haiku_rate_cap = self.haiku_rate_cap
            bt.voice_char_cap = self.voice_char_cap
        return bt

    # ── Encounter management ───────────────────────────────────────────

    def add_encounter(self, encounter: Encounter) -> Encounter:
        """Attach an Encounter to this room and stamp its room_id.

        M19 — raises ``CapacityExceeded`` if the room already has
        ``MAX_ENCOUNTERS_PER_ROOM`` encounters. Includes private-clone
        children in the count.
        """
        if len(self.encounters) >= MAX_ENCOUNTERS_PER_ROOM:
            raise CapacityExceeded(
                f"Room capacity reached "
                f"({MAX_ENCOUNTERS_PER_ROOM} encounters max). "
                f"End the room or remove an encounter before adding "
                f"more."
            )
        encounter.room_id = self.room_id
        self.encounters[encounter.id] = encounter
        return encounter

    def get_encounter_by_join_code(self, code: str) -> Encounter | None:
        target = code.upper()
        for enc in self.encounters.values():
            if enc.join_code.upper() == target:
                return enc
        return None

    def shared_station(self, persona_id: str):
        """FR-007 v2 — the single room-level chat station for a shared persona
        (created on demand, one transcript spanning the room)."""
        st = self.room_stations.get(persona_id)
        if st is None:
            import secrets
            from .control_session import Station
            st = Station(station_id="rs_" + secrets.token_urlsafe(6), persona_id=persona_id)
            self.room_stations[persona_id] = st
        return st

    def clone_encounter(self, template_id: str,
                         *, label_suffix: str = "") -> Encounter:
        """M13 — Clone a template encounter into a fresh per-student copy.

        The clone inherits the template's scenario_name, scenario_text,
        modules, persona, ehr, chart_mode, activity_id, AND
        chart_mode='private_clone'. It gets a NEW encounter id and join
        code. Its ``cloned_from_id`` points at the template so the
        dashboard can group clones under their template.

        The clone has its own empty stations / ehr_stations /
        device_stations / transcript — they are independent encounters
        on the persistence layer (every chart_event row is scoped by
        the clone's own session_id).

        Use cases:
          - Student joins a private_clone-mode bed → M9 calls this and
            assigns the student to the clone (not to the template).
          - Future operator UI "Duplicate this bed" affordance.
        """
        from . import control_session as _cs
        template = self.encounters.get(template_id)
        if template is None:
            raise KeyError(f"unknown template encounter {template_id!r}")
        clone = _cs.ControlSession(
            id=secrets.token_urlsafe(8),
            join_code=_cs._new_join_code(),
            scenario_name=(template.scenario_name +
                            (f" ({label_suffix})" if label_suffix else "")),
            scenario_notes=template.scenario_notes,
            program_id=template.program_id,
            week=template.week,
            selected_modules=list(template.selected_modules),
            scenario_text=template.scenario_text,
            selected_personas=list(template.selected_personas),
            api_key=template.api_key,
            ehr_id=template.ehr_id,
            elevenlabs_api_key=template.elevenlabs_api_key,
            voice_assignments=dict(template.voice_assignments),
            encounter_label=(template.encounter_label +
                              (f" — {label_suffix}" if label_suffix else "")),
            activity_id=template.activity_id,
            chart_mode="private_clone",
            patient_persona_id=template.patient_persona_id,
            cloned_from_id=template.id,
        )
        return self.add_encounter(clone)

    def is_template(self, encounter_id: str) -> bool:
        """A template is a private_clone encounter that itself was not
        cloned from another. Templates are surfaced to the student
        join page; clones are hidden from it (a clone belongs to one
        student already)."""
        enc = self.encounters.get(encounter_id)
        if enc is None:
            return False
        return (enc.chart_mode == "private_clone"
                and enc.cloned_from_id is None)

    def encounters_for_join_picker(self) -> list[Encounter]:
        """Encounters a student should see on the M9 join page.
        Includes shared encounters (any chart_mode='shared') and
        private_clone TEMPLATES (chart_mode='private_clone' with
        no cloned_from_id). Hides clones (each clone belongs to one
        student already)."""
        out: list[Encounter] = []
        for enc in self.encounters.values():
            if enc.chart_mode == "private_clone" and enc.cloned_from_id:
                continue   # this is a clone — hide
            out.append(enc)
        return out

    def freeze_all(self) -> None:
        """Pause every encounter. The on-the-wire state change happens
        through ``state='paused'`` on each encounter; the WebSocket push
        (M16) is what actually notifies stations."""
        for enc in self.encounters.values():
            enc.state = "paused"
        self.status = "frozen"

    def resume_all(self) -> None:
        for enc in self.encounters.values():
            if enc.state == "paused":
                enc.state = "running"
        self.status = "active"

    def end(self) -> None:
        for enc in self.encounters.values():
            enc.state = "ended"
        self.status = "ended"
        self.ended_at = time.time()

    # ── Student management ────────────────────────────────────────────

    def add_student(self, display_name: str,
                    *, assigned_encounter_id: str | None = None,
                    role: str = "bedside") -> Student:
        """Register a student to this room. Writes a row to the
        ``student`` table so the roster survives server restarts.
        Phase 7 1.2 — ``role`` is 'bedside' (default) or
        'nurse_station' (M27 supervisor seat)."""
        from . import ehr_db  # local import — avoids module load cycle
        row = ehr_db.register_student(
            self.room_id,
            display_name=display_name,
            assigned_encounter_id=assigned_encounter_id,
            role=role,
        )
        student = Student(
            student_id=row["student_id"],
            display_name=row["display_name"],
            room_id=row["room_id"],
            assigned_encounter_id=row["assigned_encounter_id"],
            registered_at=row["registered_at"],
            last_seen=row["last_seen"],
            role=row.get("role", "bedside"),
        )
        self.students[student.student_id] = student
        return student

    def assign_student(self, student_id: str, encounter_id: str) -> None:
        """Bind a student to an encounter. Writes through to the DB so
        the assignment persists across restarts."""
        from . import ehr_db
        if student_id not in self.students:
            raise KeyError(f"unknown student {student_id!r}")
        if encounter_id not in self.encounters:
            raise KeyError(f"unknown encounter {encounter_id!r}")
        # Update in-memory state.
        old_eid = self.students[student_id].assigned_encounter_id
        if old_eid and old_eid != encounter_id and old_eid in self.encounters:
            prev_enc = self.encounters[old_eid]
            if student_id in prev_enc.assigned_student_ids:
                prev_enc.assigned_student_ids.remove(student_id)
        self.students[student_id].assigned_encounter_id = encounter_id
        enc = self.encounters[encounter_id]
        if student_id not in enc.assigned_student_ids:
            enc.assigned_student_ids.append(student_id)
        # Write through.
        ehr_db.update_student_assignment(student_id, encounter_id)

    def rehydrate_students_from_db(self) -> int:
        """Load every student row whose ``room_id`` matches this room
        into ``self.students``, and (re)populate each encounter's
        ``assigned_student_ids`` list from the DB. Returns the number
        of students loaded.

        Used by:
          - M9 student-join flow on a fresh page load (we may have
            cookies pointing at a room that was started before the
            server restarted).
          - Any future "reopen room" operator flow that needs to
            reattach a previously-rostered cohort.
        """
        from . import ehr_db
        rows = ehr_db.students_for_room(self.room_id)
        self.students = {}
        for enc in self.encounters.values():
            enc.assigned_student_ids = []
        for row in rows:
            student = Student(
                student_id=row["student_id"],
                display_name=row["display_name"],
                room_id=row["room_id"],
                assigned_encounter_id=row["assigned_encounter_id"],
                registered_at=row["registered_at"],
                last_seen=row["last_seen"],
                role=row.get("role", "bedside"),
            )
            self.students[student.student_id] = student
            eid = student.assigned_encounter_id
            if eid and eid in self.encounters:
                self.encounters[eid].assigned_student_ids.append(student.student_id)
        return len(rows)

    # ── Staff roster (med cart v2) ─────────────────────────────────────

    def add_staff(self, display_name: str, *, initials: str = "",
                  role: str = "nurse",
                  assignments: list[str] | None = None) -> "StaffMember":
        """Register a cabinet user to this room's staff roster. Writes a row
        to the ``staff_member`` table so it survives restarts."""
        from . import ehr_db
        valid = [eid for eid in (assignments or []) if eid in self.encounters]
        row = ehr_db.register_staff(
            self.room_id, display_name=display_name, initials=initials,
            role=role, assignments=valid,
        )
        sm = StaffMember(
            staff_id=row["staff_id"], room_id=row["room_id"],
            display_name=row["display_name"], initials=row["initials"],
            role=row["role"], assignments=list(row["assignments"]),
            created_at=row["created_at"], last_seen=row["last_seen"],
        )
        self.staff[sm.staff_id] = sm
        return sm

    def update_staff(self, staff_id: str, *, display_name: str | None = None,
                     initials: str | None = None,
                     role: str | None = None) -> None:
        """Patch a staff member's name / initials / role (write-through)."""
        from . import ehr_db
        sm = self.staff.get(staff_id)
        if sm is None:
            raise KeyError(f"unknown staff {staff_id!r}")
        if display_name is not None:
            sm.display_name = display_name
        if initials is not None:
            sm.initials = initials.upper()
        if role is not None and role in ehr_db._STAFF_ROLES:
            sm.role = role
        ehr_db.update_staff(staff_id, display_name=display_name,
                            initials=initials, role=role)

    def set_staff_assignments(self, staff_id: str,
                              encounter_ids: list[str]) -> None:
        """Replace a staff member's patient (encounter) assignments. Only
        encounter_ids that exist in this room are kept (write-through)."""
        from . import ehr_db
        sm = self.staff.get(staff_id)
        if sm is None:
            raise KeyError(f"unknown staff {staff_id!r}")
        valid = [eid for eid in (encounter_ids or [])
                 if eid in self.encounters]
        sm.assignments = valid
        ehr_db.set_staff_assignments(staff_id, valid)

    def remove_staff(self, staff_id: str) -> None:
        """Drop a staff member from the roster (write-through)."""
        from . import ehr_db
        self.staff.pop(staff_id, None)
        ehr_db.remove_staff(staff_id)

    def accessible_encounter_ids(self, staff_id: str) -> list[str]:
        """The encounter_ids a signed-in staff member may pull meds for,
        applying the role scoping rule. Unknown staff => [] (locked out)."""
        sm = self.staff.get(staff_id)
        if sm is None:
            return []
        if sm.sees_all_patients:
            return list(self.encounters.keys())
        # Nurse with explicit assignments — intersect with live encounters.
        return [eid for eid in sm.assignments if eid in self.encounters]

    def rehydrate_staff_from_db(self) -> int:
        """Load every staff row for this room into ``self.staff``. Mirrors
        ``rehydrate_students_from_db`` for the cabinet roster."""
        from . import ehr_db
        rows = ehr_db.staff_for_room(self.room_id)
        self.staff = {}
        for row in rows:
            sm = StaffMember(
                staff_id=row["staff_id"], room_id=row["room_id"],
                display_name=row["display_name"],
                initials=row.get("initials", ""),
                role=row.get("role", "nurse"),
                assignments=list(row.get("assignments") or []),
                created_at=row["created_at"], last_seen=row["last_seen"],
            )
            self.staff[sm.staff_id] = sm
        return len(rows)


# ── Module-level singleton (single-instructor model) ──────────────────

_active_room: ControlRoom | None = None


def create_room(label: str = "") -> ControlRoom:
    """Create an empty ControlRoom and make it the active room."""
    global _active_room
    room = ControlRoom(
        room_id=secrets.token_urlsafe(8),
        room_code=_new_room_code(),
        label=label,
    )
    _active_room = room
    return room


def get_active_room() -> ControlRoom | None:
    return _active_room


def end_active_room() -> None:
    global _active_room
    if _active_room is not None:
        _active_room.end()
    _active_room = None


def get_active() -> Encounter | None:
    """v6-compatible helper: return the only encounter in the active
    room.

    Behavior:
      - No active room → ``None``.
      - Active room with 0 encounters → ``None``.
      - Active room with exactly 1 encounter (single-patient mode) →
        that encounter (matches v6 ``control_session.get_active``).
      - Active room with N > 1 encounters (room-mode) → ``None``.
        v6 routes that landed here in single-patient mode and check
        ``if active is None`` already behave correctly in room mode:
        they render their "no active session" branch (or 404 / no-op)
        instead of silently picking a random encounter.

    Phase 7 1.6 — this used to raise ``RuntimeError`` on multi-encounter
    rooms (M2's loud-failure stance). That broke the v6 wizard page
    (`/portal/control`) and ~18 other v6 single-patient routes the
    instant a room finalized via /api/room/start. The new contract:
    if you NEED the single-encounter strictness, use
    ``get_active_strict``. Otherwise None is the safe default —
    v7 multi-patient surfaces (M5 dashboard, M22 per-patient
    console, M9 student join) all address encounters by id and never
    consult get_active.
    """
    if _active_room is None:
        return None
    encs = list(_active_room.encounters.values())
    if len(encs) == 1:
        return encs[0]
    return None


def get_active_strict() -> Encounter | None:
    """Like ``get_active`` but RAISES ``RuntimeError`` if the active
    room holds multiple encounters. Use this in test code or
    operator-debug paths that genuinely need to assert single-patient
    mode and would prefer a loud failure to a silent miss."""
    if _active_room is None:
        return None
    encs = list(_active_room.encounters.values())
    if not encs:
        return None
    if len(encs) > 1:
        raise RuntimeError(
            "get_active_strict() called on a multi-encounter room; "
            "use get_by_join_code() or address by encounter id."
        )
    return encs[0]


def get_by_join_code(code: str) -> Encounter | None:
    """Search across every encounter in the active room. v6 callers that
    held a single ControlSession find the same one here."""
    if _active_room is None:
        return None
    return _active_room.get_encounter_by_join_code(code)


def list_encounters() -> Iterable[Encounter]:
    if _active_room is None:
        return ()
    return _active_room.encounters.values()


def _reset_for_tests() -> None:
    """Used by v7 tests to clear singleton state between cases."""
    global _active_room
    _active_room = None
