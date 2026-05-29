"""M1 acceptance — migration v4 is idempotent (runs once, then no-ops).

The migration runner in ehr_db gates each migration on the
`schema_version` table: a migration only runs when its version is
strictly greater than MAX(version). Applying the same migration set a
second time should be a no-op — same schema_version, same row counts,
no errors.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from portal import ehr_db


def _apply_all(conn: sqlite3.Connection) -> None:
    ehr_db._run_migrations(conn)


def test_migration_v4_idempotent(tmp_path: Path) -> None:
    db_file = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_file), isolation_level=None)
    try:
        # First pass — every defined migration applies.
        _apply_all(conn)
        rows_first = conn.execute(
            "SELECT version FROM schema_version ORDER BY version"
        ).fetchall()
        # Migrations include v4 (M1) and v5 (Phase 7 1.2); any future
        # migration that gets appended should also show up here.
        applied_versions = [r[0] for r in rows_first]
        assert 4 in applied_versions
        assert applied_versions == sorted(set(applied_versions))   # no dupes

        # Second pass — runner should detect MAX(version)>=current and skip
        # everything. No exception, same row set.
        _apply_all(conn)
        rows_second = conn.execute(
            "SELECT version FROM schema_version ORDER BY version"
        ).fetchall()
        assert rows_second == rows_first
    finally:
        conn.close()
