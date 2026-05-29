"""M1 acceptance — migration v4 preserves existing v6 data.

A v6 snapshot DB has migrations 1..3 applied and may contain
ehr_session / ehr_station / chart_event / device_* rows. The v4
migration must:

1. Add new tables (control_room, student, activity) without touching
   existing rows.
2. Add five new ehr_session columns (room_id, label, activity_id,
   chart_mode, patient_persona_id). Legacy rows get NULL for the
   nullable columns and the default 'shared' for chart_mode.
3. Leave chart_event / device_event content byte-identical so the
   `fold()` projection still works against legacy sessions.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from portal import ehr_db


def _apply_versions(conn: sqlite3.Connection, up_to: int) -> None:
    """Apply migrations up to and including version `up_to`."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version "
        "(version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)"
    )
    for version, sql in ehr_db.SCHEMA_MIGRATIONS:
        if version <= up_to:
            conn.executescript(sql)
            conn.execute(
                "INSERT OR IGNORE INTO schema_version (version, applied_at) "
                "VALUES (?, ?)",
                (version, time.time()),
            )


def _seed_v6_data(conn: sqlite3.Connection) -> None:
    now = time.time()
    conn.execute(
        "INSERT INTO ehr_session "
        "(session_id, join_code, ehr_id, persona_id, seed_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("S-legacy", "ABCD12", "epic", "HLX-001", json.dumps({"patient": "x"}), now),
    )
    conn.execute(
        "INSERT INTO ehr_station "
        "(ehr_station_id, session_id, device_label, user_agent, joined_at, last_seen) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("ES-a", "S-legacy", "tablet-1", "ua", now, now),
    )
    conn.execute(
        "INSERT INTO chart_event "
        "(session_id, ehr_station_id, ts, type, surface, payload_json) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("S-legacy", "ES-a", now, "note.save", "notes", json.dumps({"body": "soap"})),
    )


def test_migration_v4_preserves_v6_data(tmp_path: Path) -> None:
    db_file = tmp_path / "v6_snapshot.db"
    conn = sqlite3.connect(str(db_file), isolation_level=None)
    try:
        # Build a v6 snapshot: migrations 1..3 applied, sample data seeded.
        _apply_versions(conn, up_to=3)
        _seed_v6_data(conn)

        # Snapshot row counts and chart_event payload before v4.
        sess_before = conn.execute(
            "SELECT session_id, join_code, ehr_id, persona_id FROM ehr_session"
        ).fetchall()
        event_payload_before = conn.execute(
            "SELECT payload_json FROM chart_event WHERE session_id=?",
            ("S-legacy",),
        ).fetchone()[0]

        # Apply v4.
        ehr_db._run_migrations(conn)

        # Legacy ehr_session row survives, identical in the columns it had.
        sess_after = conn.execute(
            "SELECT session_id, join_code, ehr_id, persona_id FROM ehr_session"
        ).fetchall()
        assert sess_after == sess_before

        # New columns exist; legacy row has NULL/default values for them.
        room_id, label, activity_id, chart_mode, patient_persona_id = conn.execute(
            "SELECT room_id, label, activity_id, chart_mode, patient_persona_id "
            "FROM ehr_session WHERE session_id=?",
            ("S-legacy",),
        ).fetchone()
        assert room_id is None
        assert label is None
        assert activity_id is None
        assert chart_mode == "shared"  # default from ADD COLUMN
        assert patient_persona_id is None

        # chart_event payload byte-identical.
        event_payload_after = conn.execute(
            "SELECT payload_json FROM chart_event WHERE session_id=?",
            ("S-legacy",),
        ).fetchone()[0]
        assert event_payload_after == event_payload_before

        # schema_version reached at least 4 (the v4 fields are what
        # this test cares about; later migrations may extend further).
        max_v = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        assert max_v >= 4
    finally:
        conn.close()
