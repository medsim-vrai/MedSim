"""M11 acceptance — Activity CRUD round-trip.

Covers create → get → list → update → delete on the `activity` table
through the ``ehr_db`` helpers. Also exercises the protection on
built-in activities: ``delete_activity`` must refuse to drop a row
flagged ``is_builtin=True``.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

from portal import ehr_db


def _isolated_db(tmp_path: Path) -> sqlite3.Connection:
    db_file = tmp_path / "activities.db"
    conn = sqlite3.connect(str(db_file), isolation_level=None)
    ehr_db._run_migrations(conn)
    return conn


def test_activity_create_get_list_update_delete(tmp_path: Path) -> None:
    conn = _isolated_db(tmp_path)
    try:
        with patch.object(ehr_db, "_conn", return_value=conn):
            # Create.
            a = ehr_db.create_activity(
                label="Test · Custom activity",
                seed_persona_id="P-001",
                seed_modules=["M02", "M06"],
                scenario_text="Custom scenario text.",
                default_chart_mode="private_clone",
                answer_key={"goals": ["recognize sepsis", "escalate"]},
                is_builtin=False,
            )
            assert a["activity_id"].startswith("act_")
            assert a["is_builtin"] is False
            assert a["default_chart_mode"] == "private_clone"

            # Get round-trips identical content.
            got = ehr_db.get_activity(a["activity_id"])
            assert got is not None
            assert got["label"] == "Test · Custom activity"
            assert got["seed_persona_id"] == "P-001"
            assert got["seed_modules"] == ["M02", "M06"]
            assert got["scenario_text"] == "Custom scenario text."
            assert got["answer_key"]["goals"] == ["recognize sepsis", "escalate"]

            # List shows it.
            rows = ehr_db.list_activities()
            assert any(r["activity_id"] == a["activity_id"] for r in rows)

            # Update — patch label + modules, leave the rest alone.
            updated = ehr_db.update_activity(
                a["activity_id"],
                label="Test · Renamed",
                seed_modules=["M02"],
            )
            assert updated is not None
            assert updated["label"] == "Test · Renamed"
            assert updated["seed_modules"] == ["M02"]
            # Unchanged fields survive the patch.
            assert updated["scenario_text"] == "Custom scenario text."
            assert updated["seed_persona_id"] == "P-001"

            # update_activity on a missing id returns None, doesn't insert.
            assert ehr_db.update_activity("act_does_not_exist",
                                            label="should not appear") is None

            # Delete (non-builtin).
            assert ehr_db.delete_activity(a["activity_id"]) is True
            assert ehr_db.get_activity(a["activity_id"]) is None

            # Delete is idempotent — calling again is still True.
            assert ehr_db.delete_activity(a["activity_id"]) is True
    finally:
        conn.close()


def test_delete_refuses_to_drop_builtin_rows(tmp_path: Path) -> None:
    conn = _isolated_db(tmp_path)
    try:
        with patch.object(ehr_db, "_conn", return_value=conn):
            a = ehr_db.create_activity(
                activity_id="builtin_protected",
                label="Built-in",
                is_builtin=True,
            )
            assert a["is_builtin"] is True
            assert ehr_db.delete_activity(a["activity_id"]) is False
            assert ehr_db.get_activity(a["activity_id"]) is not None
    finally:
        conn.close()


def test_list_activities_orders_builtins_first(tmp_path: Path) -> None:
    """The wizard's activity picker shows built-ins first, then
    custom ones, both alphabetical within each group."""
    conn = _isolated_db(tmp_path)
    try:
        with patch.object(ehr_db, "_conn", return_value=conn):
            ehr_db.create_activity(label="Zeta custom", is_builtin=False)
            ehr_db.create_activity(label="Alpha custom", is_builtin=False)
            ehr_db.create_activity(activity_id="b1", label="Alpha builtin",
                                     is_builtin=True)
            ehr_db.create_activity(activity_id="b2", label="Beta builtin",
                                     is_builtin=True)
            rows = ehr_db.list_activities()
            assert [r["label"] for r in rows] == [
                "Alpha builtin", "Beta builtin",
                "Alpha custom", "Zeta custom",
            ]


            builtins_only = ehr_db.list_activities(builtin_only=True)
            assert {r["label"] for r in builtins_only} == {
                "Alpha builtin", "Beta builtin"
            }
    finally:
        conn.close()


def test_create_round_trips_empty_modules_and_no_answer_key(tmp_path: Path) -> None:
    """A minimal Activity (label only) round-trips with safe defaults."""
    conn = _isolated_db(tmp_path)
    try:
        with patch.object(ehr_db, "_conn", return_value=conn):
            a = ehr_db.create_activity(label="Bare")
            got = ehr_db.get_activity(a["activity_id"])
            assert got is not None
            assert got["seed_persona_id"] is None
            assert got["seed_modules"] == []
            assert got["scenario_text"] == ""
            assert got["default_chart_mode"] == "shared"
            assert got["answer_key"] is None
            assert got["is_builtin"] is False
    finally:
        conn.close()
