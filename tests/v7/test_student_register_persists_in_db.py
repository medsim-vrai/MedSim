"""M8 acceptance — Student rows persist in the ``student`` table.

Calling ``ControlRoom.add_student(display_name)`` must write a row to
the M1 schema's `student` table immediately (no batched flush, no
in-memory-only state). The row's fields mirror the dataclass:
student_id, room_id, display_name, assigned_encounter_id (None at
register time), registered_at, last_seen.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

from portal import control_room, ehr_db
from portal.control_session import ControlSession


def _isolated_db(tmp_path: Path) -> sqlite3.Connection:
    """Stand up a fresh DB with the v7 schema applied and return the
    open connection. Tests substitute it for ehr_db._conn so the
    runtime singleton in ~/.medsim/v7/medsim.db is not touched."""
    db_file = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_file), isolation_level=None)
    ehr_db._run_migrations(conn)
    return conn


def test_add_student_writes_row_to_student_table(tmp_path: Path) -> None:
    control_room._reset_for_tests()
    conn = _isolated_db(tmp_path)
    try:
        with patch.object(ehr_db, "_conn", return_value=conn):
            room = control_room.create_room(label="Roster persist test")
            student = room.add_student("Alice Pham")

            # In-memory state is correct.
            assert student.student_id in room.students
            assert student.display_name == "Alice Pham"
            assert student.room_id == room.room_id
            assert student.assigned_encounter_id is None

            # DB row exists with the matching fields.
            rows = conn.execute(
                "SELECT student_id, room_id, display_name, "
                " assigned_encounter_id, registered_at, last_seen "
                "FROM student"
            ).fetchall()
            assert len(rows) == 1
            db_row = rows[0]
            assert db_row[0] == student.student_id
            assert db_row[1] == room.room_id
            assert db_row[2] == "Alice Pham"
            assert db_row[3] is None
            assert isinstance(db_row[4], float)
            assert isinstance(db_row[5], float)
    finally:
        conn.close()


def test_three_students_each_get_distinct_ids(tmp_path: Path) -> None:
    control_room._reset_for_tests()
    conn = _isolated_db(tmp_path)
    try:
        with patch.object(ehr_db, "_conn", return_value=conn):
            room = control_room.create_room(label="Triple")
            a = room.add_student("Alice")
            b = room.add_student("Bob")
            c = room.add_student("Cara")

            assert len({a.student_id, b.student_id, c.student_id}) == 3

            db_rows = conn.execute(
                "SELECT student_id, display_name FROM student "
                "ORDER BY registered_at ASC"
            ).fetchall()
            assert [r[1] for r in db_rows] == ["Alice", "Bob", "Cara"]
            assert {r[0] for r in db_rows} == \
                {a.student_id, b.student_id, c.student_id}
    finally:
        conn.close()


def test_students_for_room_filters_by_room_id(tmp_path: Path) -> None:
    """Two rooms in sequence (the second supersedes the first) — the
    ``students_for_room`` lookup must scope to the requested room_id."""
    control_room._reset_for_tests()
    conn = _isolated_db(tmp_path)
    try:
        with patch.object(ehr_db, "_conn", return_value=conn):
            room1 = control_room.create_room(label="Room 1")
            room1_id = room1.room_id
            room1.add_student("Alice")
            room1.add_student("Bob")

            control_room.end_active_room()
            room2 = control_room.create_room(label="Room 2")
            room2.add_student("Cara")

            r1_students = ehr_db.students_for_room(room1_id)
            r2_students = ehr_db.students_for_room(room2.room_id)

            assert [s["display_name"] for s in r1_students] == ["Alice", "Bob"]
            assert [s["display_name"] for s in r2_students] == ["Cara"]
            # No bleed.
            assert all(s["room_id"] == room1_id for s in r1_students)
            assert all(s["room_id"] == room2.room_id for s in r2_students)
    finally:
        conn.close()


def test_assign_student_writes_through_to_db(tmp_path: Path) -> None:
    """Calling ``ControlRoom.assign_student(sid, eid)`` updates the DB
    row's ``assigned_encounter_id`` so the assignment survives a
    server restart."""
    control_room._reset_for_tests()
    conn = _isolated_db(tmp_path)
    try:
        with patch.object(ehr_db, "_conn", return_value=conn):
            room = control_room.create_room()
            enc = room.add_encounter(ControlSession(
                id="ENC-A", join_code="JC1A12",
                scenario_name="Bed A", api_key=""))
            student = room.add_student("Alice")

            # Before: NULL in DB.
            row = conn.execute(
                "SELECT assigned_encounter_id FROM student WHERE student_id=?",
                (student.student_id,),
            ).fetchone()
            assert row[0] is None

            room.assign_student(student.student_id, enc.id)

            # After: the encounter id is set in the DB.
            row = conn.execute(
                "SELECT assigned_encounter_id FROM student WHERE student_id=?",
                (student.student_id,),
            ).fetchone()
            assert row[0] == enc.id
            # And the encounter's roster reflects it.
            assert student.student_id in enc.assigned_student_ids
    finally:
        conn.close()
