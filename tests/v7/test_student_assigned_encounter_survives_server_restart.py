"""M8 acceptance — student assignments survive a server restart.

We simulate a restart by:
  1. Creating a room, adding students, assigning some to encounters.
  2. Clearing the in-memory singleton (``_reset_for_tests``) — this
     is what would happen across a process restart, since the
     ControlRoom is in-memory only.
  3. Reconstructing a new ControlRoom with the SAME room_id and
     calling ``rehydrate_students_from_db()``.
  4. Asserting the students dict and the encounters'
     ``assigned_student_ids`` lists are restored verbatim.

The DB row contents are what bridges the restart — chart_event,
ehr_session, AND student all share that contract.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

from portal import control_room, ehr_db
from portal.control_session import ControlSession


def _isolated_db(tmp_path: Path) -> sqlite3.Connection:
    db_file = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_file), isolation_level=None)
    ehr_db._run_migrations(conn)
    return conn


def test_student_assigned_encounter_survives_server_restart(tmp_path: Path) -> None:
    conn = _isolated_db(tmp_path)
    try:
        with patch.object(ehr_db, "_conn", return_value=conn):
            # ── Phase 1 — pre-restart: build the room ──
            control_room._reset_for_tests()
            room1 = control_room.create_room(label="Pre-restart room")
            enc_a = room1.add_encounter(ControlSession(
                id="ENC-A", join_code="JCAAAA",
                scenario_name="Bed A", api_key=""))
            enc_b = room1.add_encounter(ControlSession(
                id="ENC-B", join_code="JCBBBB",
                scenario_name="Bed B", api_key=""))
            s_alice = room1.add_student("Alice")
            s_bob   = room1.add_student("Bob")
            s_cara  = room1.add_student("Cara")
            room1.assign_student(s_alice.student_id, enc_a.id)
            room1.assign_student(s_bob.student_id,   enc_a.id)
            room1.assign_student(s_cara.student_id,  enc_b.id)

            # Capture the room metadata the post-restart phase will need.
            preserved_room_id   = room1.room_id
            preserved_room_code = room1.room_code

            # ── Phase 2 — simulate restart ──
            # In-memory singleton dies; DB content survives.
            control_room._reset_for_tests()
            assert control_room.get_active_room() is None

            # ── Phase 3 — rehydrate ──
            # The operator opens the room back up — we rebuild the room
            # shell (encounters need to be re-added from the DB too in
            # a real implementation; here we re-create them with the
            # same ids to focus the test on student rehydration).
            global _active_room
            room2 = control_room.ControlRoom(
                room_id=preserved_room_id,
                room_code=preserved_room_code,
                label="Post-restart room",
            )
            control_room._active_room = room2  # noqa: SLF001 — restoring singleton
            room2.add_encounter(ControlSession(
                id=enc_a.id, join_code=enc_a.join_code,
                scenario_name=enc_a.scenario_name, api_key=""))
            room2.add_encounter(ControlSession(
                id=enc_b.id, join_code=enc_b.join_code,
                scenario_name=enc_b.scenario_name, api_key=""))
            loaded = room2.rehydrate_students_from_db()

            # ── Phase 4 — assert ──
            assert loaded == 3
            assert len(room2.students) == 3
            # IDs preserved.
            assert s_alice.student_id in room2.students
            assert s_bob.student_id   in room2.students
            assert s_cara.student_id  in room2.students
            # Display names preserved.
            assert room2.students[s_alice.student_id].display_name == "Alice"
            assert room2.students[s_cara.student_id].display_name == "Cara"
            # Assignments preserved.
            assert room2.students[s_alice.student_id].assigned_encounter_id == enc_a.id
            assert room2.students[s_bob.student_id].assigned_encounter_id   == enc_a.id
            assert room2.students[s_cara.student_id].assigned_encounter_id  == enc_b.id
            # Each encounter's roster list reflects the assignments.
            assert set(room2.encounters[enc_a.id].assigned_student_ids) == {
                s_alice.student_id, s_bob.student_id,
            }
            assert room2.encounters[enc_b.id].assigned_student_ids == [
                s_cara.student_id,
            ]
    finally:
        conn.close()


def test_rehydrate_is_idempotent(tmp_path: Path) -> None:
    """Calling rehydrate twice produces the same in-memory state — no
    duplicate students, no duplicate encounter assignments."""
    conn = _isolated_db(tmp_path)
    try:
        with patch.object(ehr_db, "_conn", return_value=conn):
            control_room._reset_for_tests()
            room = control_room.create_room(label="Idempotent test")
            enc = room.add_encounter(ControlSession(
                id="ENC-X", join_code="JCXXXX",
                scenario_name="Bed X", api_key=""))
            student = room.add_student("Solo")
            room.assign_student(student.student_id, enc.id)

            # First rehydrate is a no-op for state (same DB, same room).
            n1 = room.rehydrate_students_from_db()
            n2 = room.rehydrate_students_from_db()

            assert n1 == n2 == 1
            assert len(room.students) == 1
            assert room.encounters[enc.id].assigned_student_ids == [
                student.student_id,
            ]
    finally:
        conn.close()


def test_unassigned_student_after_restart_keeps_null_encounter(tmp_path: Path) -> None:
    """A student registered without an encounter assignment must
    survive the restart with NULL ``assigned_encounter_id`` — and the
    encounters' roster lists must not pick them up."""
    conn = _isolated_db(tmp_path)
    try:
        with patch.object(ehr_db, "_conn", return_value=conn):
            control_room._reset_for_tests()
            room = control_room.create_room()
            enc = room.add_encounter(ControlSession(
                id="ENC-1", join_code="JC1111",
                scenario_name="Bed 1", api_key=""))
            unassigned = room.add_student("Unassigned Sam")

            preserved_room_id   = room.room_id
            preserved_room_code = room.room_code

            control_room._reset_for_tests()
            room2 = control_room.ControlRoom(
                room_id=preserved_room_id,
                room_code=preserved_room_code,
            )
            control_room._active_room = room2  # noqa: SLF001
            room2.add_encounter(ControlSession(
                id=enc.id, join_code=enc.join_code,
                scenario_name=enc.scenario_name, api_key=""))
            room2.rehydrate_students_from_db()

            assert unassigned.student_id in room2.students
            assert room2.students[unassigned.student_id].assigned_encounter_id is None
            assert room2.encounters[enc.id].assigned_student_ids == []
    finally:
        conn.close()
