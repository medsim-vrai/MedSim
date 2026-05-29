"""Control-room session state for MEDSIM (V2 + V3).

The control room produces a ControlSession (via the wizard). That session
has: a scenario name + notes, curriculum context (program, week, selected
modules, free-form text), selected personas, a roster of joined chat
stations, and — V3 — a chosen EHR + roster of joined EHR stations.

Held in memory only — single-instructor, single-active-session model.
"""
from __future__ import annotations

import secrets
import string
import time
from dataclasses import dataclass, field
from typing import Any


def _new_join_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    # Exclude visually similar chars
    alphabet = alphabet.replace("0", "").replace("O", "").replace("1", "").replace("I", "").replace("L", "")
    return "".join(secrets.choice(alphabet) for _ in range(6))


@dataclass
class Station:
    """A mobile/desktop device that joined the session as a chat station."""
    station_id: str
    persona_id: str | None = None
    user_agent: str = ""
    joined_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    history: list[dict[str, Any]] = field(default_factory=list)  # local chat history

    def touch(self) -> None:
        self.last_seen = time.time()

    @property
    def online(self) -> bool:
        return (time.time() - self.last_seen) < 30.0  # 30s heartbeat threshold


@dataclass
class EhrStation:
    """V3 — a Chrome device documenting into the EHR for the current session.

    Distinct from a chat Station: chat stations carry the verbal encounter
    with a persona; EHR stations carry the charting workflow. One session
    typically has both. Audit logs are scoped per-station so the comparison
    engine can attribute events.
    """
    ehr_station_id: str
    device_label: str = ""        # operator-visible — student types this at join
    user_agent: str = ""
    joined_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    event_count: int = 0          # mirror of chart_event rows for this station

    def touch(self) -> None:
        self.last_seen = time.time()

    @property
    def online(self) -> bool:
        return (time.time() - self.last_seen) < 45.0  # heartbeat cadence is 20s


@dataclass
class DeviceStation:
    """V6 — a simulated medical device (IV pump, enteral pump, dispensing
    cabinet) joined to the session via QR. Distinct from chat and EHR
    stations: device stations carry the device-operation workflow, and
    each has a current character assignment (re-assignable mid-scenario)
    plus an immutable assignment history (see ehr_db.assignment_history).
    """
    station_id: str
    device_kind: str            # 'pump_iv' | 'pump_enteral' | 'cabinet'
    device_model: str           # 'alaris' | 'kangaroo_omni' | 'pyxis'
    label: str = ""             # operator-visible — 'Bed 3 IV', 'Cart A'
    user_agent: str = ""
    joined_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    character_id: str | None = None   # latest assignment, denormalized
    runtime_state: str = "idle"       # 'idle'|'running'|'alarmed'|'paused'

    def touch(self) -> None:
        self.last_seen = time.time()

    @property
    def online(self) -> bool:
        return (time.time() - self.last_seen) < 45.0


@dataclass
class TranscriptEntry:
    """One direction of one turn — either the student (input) or the
    character (response). Two entries per round-trip, time-ordered."""
    ts: float
    source: str            # "station:<id>" or "operator"
    source_label: str      # human-readable, e.g. "Mrs. Kowalski station" or "Operator"
    persona_id: str
    persona_name: str
    direction: str         # "student" or "character"
    text: str
    latency_ms: int | None = None  # only set on character entries


@dataclass
class ControlSession:
    """A configured-and-running medsim session.

    V7 note: in multi-patient mode, a ControlSession is one *Encounter*
    within a ControlRoom — the room owns N of these. In single-patient
    mode (the v6 default), the wizard creates a ControlRoom-of-1 with
    one ControlSession inside, so every v6 code path keeps working.
    The new v7 fields (room_id, encounter_label, activity_id,
    chart_mode, patient_persona_id, assigned_student_ids) default to
    safe single-patient values, so existing code that ignores them sees
    no behavior change.
    """
    id: str
    join_code: str
    scenario_name: str
    scenario_notes: str = ""
    program_id: str | None = None
    week: int | None = None
    selected_modules: list[str] = field(default_factory=list)
    scenario_text: str = ""
    selected_personas: list[str] = field(default_factory=list)
    stations: dict[str, Station] = field(default_factory=dict)
    transcript: list[TranscriptEntry] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    state: str = "configured"  # configured | running | paused | ended
    api_key: str = ""
    # ── V3 additions ───────────────────────────────────────────────────
    ehr_id: str | None = None                                          # 'helix' | 'cyrus' | 'meridian'
    ehr_stations: dict[str, EhrStation] = field(default_factory=dict)  # keyed by ehr_station_id
    charting_locked_at: float | None = None                            # set when operator fires lock-in
    # ── V4 additions ───────────────────────────────────────────────────
    elevenlabs_api_key: str = ""                                       # captured at start; "" → browser TTS
    voice_assignments: dict[str, str] = field(default_factory=dict)    # persona_id → ElevenLabs voice_id
                                                                       # ("" or "browser" → SpeechSynthesis fallback)
    # ── V6 additions ───────────────────────────────────────────────────
    device_stations: dict[str, DeviceStation] = field(default_factory=dict)  # keyed by station_id
    # ── V7 additions (multi-patient) ───────────────────────────────────
    room_id: str | None = None                            # owning ControlRoom; None on legacy v6 sessions
    encounter_label: str = ""                             # short instructor-visible tag, e.g. "Bed 3 — Kowalski"
    activity_id: str | None = None                        # source Activity catalog entry, if any
    chart_mode: str = "shared"                            # 'shared' | 'private_clone'
    patient_persona_id: str | None = None                 # canonical persona library reference
    assigned_student_ids: list[str] = field(default_factory=list)
    # M13 — private-clone template/instance tracking. A template is a
    # wizard-finalized encounter with chart_mode='private_clone' whose
    # role is to be cloned per student. Templates have
    # cloned_from_id=None; clones point at their template.
    cloned_from_id: str | None = None
    # M30 — lead student per encounter. Optional. When set, the
    # debrief facets + dashboard cards show the lead's display_name
    # so the operator can see "Bed 3 (lead: Alice Pham)" at a glance.
    # Distinct from assigned_student_ids — multiple students may be
    # on a shared-mode encounter; the lead is the one who owns the
    # case at debrief time.
    lead_student_id: str | None = None
    # M53 — free-text lead label, set from the Multi-Patient Control
    # "👤 Lead assignments" panel. The instructor can type any of:
    #   - a single student's name ("Alice Pham")
    #   - a group name             ("Team Alpha")
    #   - a comma-separated list   ("Alice, Bob, Charlie")
    # Bulk-applied to one or more encounters. Independent of the M30
    # roster-picked `lead_student_id` — when both are set, the
    # free-text label wins for display purposes (operator typed it
    # most recently). Either may be empty.
    lead_label: str = ""
    # M62 — Medical Records workstation: instructor / supervisor /
    # bedside inserts. Each entry: {ts, kind, persona_id, title,
    # body, author_name, author_role, author_initials}. Stored on
    # the encounter (not per-persona) so the chart route can fetch
    # them in one shot. In-memory only — dies with the room.
    chart_inserts: list[dict[str, Any]] = field(default_factory=list)
    # M55 — per-persona list of medications marked "active at start"
    # of the scenario by the instructor on the Per-Patient Console's
    # 💊 Medications card. Maps persona_id → list of lowercased med
    # names. Semantics:
    #   - persona_id NOT in dict → default behaviour: every med from
    #     the persona's MAR seed appears on the med cart (back-compat
    #     with pre-M55 carts that showed every med).
    #   - persona_id IN dict → only meds whose lowercased `name` is
    #     in the list appear on the cart. Empty list = no meds for
    #     that patient.
    # The instructor's checkbox interactions on the encounter console
    # POST a fresh list every time, replacing whatever the server had.
    active_medications: dict[str, list[str]] = field(default_factory=dict)
    # M23 — per-encounter telemetry overrides (operator force-set).
    # Lives in memory; the room dies with the server so these don't
    # need to survive a restart. Keyed by metric ('hr', 'sbp', etc.).
    telemetry_overrides: dict[str, Any] = field(default_factory=dict)
    # M24 — ECG display. `ecg_enabled=True` shows the ECG strip on
    # the Per-Patient Console + Nursing Station card. `ecg_rhythm_id`
    # is the chosen waveform from the M24 catalog ("nsr" default).
    ecg_enabled: bool = False
    ecg_rhythm_id: str = "nsr"

    def add_station(self, station_id: str, user_agent: str = "") -> Station:
        st = Station(station_id=station_id, user_agent=user_agent)
        self.stations[station_id] = st
        return st

    def add_ehr_station(self, ehr_station_id: str, *, device_label: str = "",
                         user_agent: str = "") -> EhrStation:
        st = EhrStation(ehr_station_id=ehr_station_id,
                        device_label=device_label, user_agent=user_agent)
        self.ehr_stations[ehr_station_id] = st
        return st

    def add_device_station(self, station_id: str, *, device_kind: str,
                            device_model: str, label: str = "",
                            user_agent: str = "") -> DeviceStation:
        st = DeviceStation(station_id=station_id, device_kind=device_kind,
                           device_model=device_model, label=label,
                           user_agent=user_agent)
        self.device_stations[station_id] = st
        return st

    def log_turn(
        self,
        *,
        source: str,
        source_label: str,
        persona_id: str,
        persona_name: str,
        student_text: str,
        character_text: str,
        latency_ms: int | None = None,
    ) -> None:
        """Append a complete round-trip (two entries — student then character)
        to the session transcript."""
        now = time.time()
        self.transcript.append(TranscriptEntry(
            ts=now, source=source, source_label=source_label,
            persona_id=persona_id, persona_name=persona_name,
            direction="student", text=student_text,
        ))
        self.transcript.append(TranscriptEntry(
            ts=now + 0.001, source=source, source_label=source_label,
            persona_id=persona_id, persona_name=persona_name,
            direction="character", text=character_text, latency_ms=latency_ms,
        ))


# ────────────────────────────────────────────────────────────────────
# V7 NOTE — singleton storage moved to portal.control_room.
#
# v6 code calls ``portal.control_session.get_active()`` and
# ``create_session()`` directly. In v7 those calls still work, but the
# active session lives inside a ControlRoom. ``create_session`` now
# transparently creates a room-of-1 and adds the encounter to it;
# ``get_active`` / ``get_by_join_code`` / ``end_active`` delegate to the
# control_room module. Behavior is byte-identical in single-patient mode.
# ────────────────────────────────────────────────────────────────────


def create_session(
    scenario_name: str,
    api_key: str,
    *,
    scenario_notes: str = "",
    program_id: str | None = None,
    week: int | None = None,
    selected_modules: list[str] | None = None,
    scenario_text: str = "",
    selected_personas: list[str] | None = None,
    ehr_id: str | None = None,           # V3 — wizard step 2b
    elevenlabs_api_key: str = "",        # V4 — captured for character TTS
) -> ControlSession:
    """v6-compat session factory.

    In v7 this creates (or reuses) a ControlRoom-of-1 holding one
    Encounter. The returned ControlSession is that Encounter — every
    existing v6 caller keeps working unchanged.
    """
    from . import control_room  # local import to avoid module-load cycle
    sess = ControlSession(
        id=secrets.token_urlsafe(8),
        join_code=_new_join_code(),
        scenario_name=scenario_name,
        scenario_notes=scenario_notes,
        program_id=program_id,
        week=week,
        selected_modules=list(selected_modules or []),
        scenario_text=scenario_text,
        selected_personas=list(selected_personas or []),
        api_key=api_key,
        ehr_id=ehr_id,
        elevenlabs_api_key=elevenlabs_api_key,
    )
    room = control_room.get_active_room() or control_room.create_room(
        label=scenario_name or "Single Patient"
    )
    # If the room already held an encounter from a prior wizard run, end
    # it before swapping in the new one. v6 behavior was "one active
    # session at a time" — preserve that for the single-patient branch.
    if room.encounters:
        control_room.end_active_room()
        room = control_room.create_room(label=scenario_name or "Single Patient")
    room.add_encounter(sess)
    return sess


def get_active() -> ControlSession | None:
    """v6-compat accessor — returns the sole encounter of the active room.

    Raises if the active room holds multiple encounters; v7 callers in
    that case should use ``portal.control_room.get_by_join_code`` or
    address encounters by id.
    """
    from . import control_room
    return control_room.get_active()


def get_by_join_code(code: str) -> ControlSession | None:
    from . import control_room
    return control_room.get_by_join_code(code)


def end_active() -> None:
    from . import control_room
    control_room.end_active_room()


def set_state(state: str) -> None:
    from . import control_room
    room = control_room.get_active_room()
    if room is None:
        return
    for enc in room.encounters.values():
        enc.state = state
    # Reflect the aggregate on the room as well, so the dashboard sees it.
    if state == "paused":
        room.status = "frozen"
    elif state == "running":
        room.status = "active"
    elif state == "ended":
        room.status = "ended"


# ────────────────────────────────────────────────────────────────────
# Legacy `_active = None` reset hook (v6 back-compat).
#
# v6 test fixtures (and a handful of operator-debug paths) reset the
# active session by assigning the module attribute directly:
#     control_session._active = None
# In v7 the real singleton has moved to control_room._active_room, so
# that assignment would silently no-op if we left this module alone.
# Intercept module attribute writes by swapping in a ModuleType subclass
# that propagates the reset to control_room when `_active` is set to
# None. This is a PEP 562-adjacent pattern (PEP 562 only covers
# __getattr__ on modules; here we need __setattr__).
# ────────────────────────────────────────────────────────────────────

import sys as _sys
import types as _types


class _ControlSessionModule(_types.ModuleType):
    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_active" and value is None:
            try:
                from . import control_room as _cr
                _cr._active_room = None
            except Exception:  # noqa: BLE001 — keep the reset best-effort
                pass
        super().__setattr__(name, value)


_sys.modules[__name__].__class__ = _ControlSessionModule

# Initialize the legacy attribute so reads do not raise; it carries no
# state (the real state lives in control_room._active_room).
_active: Any = None
