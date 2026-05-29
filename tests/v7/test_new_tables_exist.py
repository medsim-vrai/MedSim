"""M1 acceptance — v4 schema additions are present.

After running all SCHEMA_MIGRATIONS, the DB has:
  - new tables: control_room, student, activity
  - new columns on ehr_session: room_id, label, activity_id, chart_mode,
    patient_persona_id
  - supporting indexes
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from portal import ehr_db


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {row[0] for row in rows}


def _index_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'"
    ).fetchall()
    return {row[0] for row in rows}


def test_new_tables_exist(tmp_path: Path) -> None:
    db_file = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_file), isolation_level=None)
    try:
        ehr_db._run_migrations(conn)

        tables = _table_names(conn)
        assert {"control_room", "student", "activity"} <= tables

        # control_room columns
        cr_cols = _columns(conn, "control_room")
        assert {
            "room_id", "room_code", "label", "status", "created_at",
            "ended_at", "haiku_rate_cap", "voice_char_cap",
        } <= cr_cols

        # student columns
        st_cols = _columns(conn, "student")
        assert {
            "student_id", "room_id", "display_name",
            "assigned_encounter_id", "registered_at", "last_seen",
        } <= st_cols

        # activity columns
        ac_cols = _columns(conn, "activity")
        assert {
            "activity_id", "label", "seed_persona_id", "seed_modules_json",
            "scenario_text", "default_chart_mode", "answer_key_json",
            "is_builtin", "created_at",
        } <= ac_cols

        # ehr_session new columns
        es_cols = _columns(conn, "ehr_session")
        assert {
            "room_id", "label", "activity_id", "chart_mode",
            "patient_persona_id",
        } <= es_cols

        # supporting indexes
        indexes = _index_names(conn)
        assert {
            "ix_control_room_status",
            "ix_student_room",
            "ix_student_assigned_encounter",
            "ix_activity_builtin",
            "ix_ehr_session_room",
        } <= indexes
    finally:
        conn.close()
