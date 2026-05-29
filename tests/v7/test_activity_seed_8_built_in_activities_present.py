"""M11 acceptance — eight built-in activities seeded on first start.

``activities.seed_builtins()`` is idempotent; the first call inserts
every Activity in ``BUILTIN_ACTIVITIES``; subsequent calls insert
nothing new. The catalog covers the seven v6 sample scenarios plus
an eighth (acute respiratory failure) so the curriculum coverage
in v7 is at least as broad as the v6 wizard-template set.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

from portal import activities, ehr_db


def _isolated_db(tmp_path: Path) -> sqlite3.Connection:
    db_file = tmp_path / "seed.db"
    conn = sqlite3.connect(str(db_file), isolation_level=None)
    ehr_db._run_migrations(conn)
    return conn


def test_seed_builtins_writes_eight_rows(tmp_path: Path) -> None:
    conn = _isolated_db(tmp_path)
    try:
        with patch.object(ehr_db, "_conn", return_value=conn):
            written = activities.seed_builtins()
            assert written == 8, (
                f"seed_builtins must insert all 8 catalog rows on a "
                f"fresh DB; got {written}"
            )
            rows = ehr_db.list_activities(builtin_only=True)
            assert len(rows) == 8
            ids = {r["activity_id"] for r in rows}
            # Every BUILTIN_ACTIVITIES entry persisted.
            expected = {a.activity_id for a in activities.BUILTIN_ACTIVITIES}
            assert ids == expected
            # Every built-in row carries is_builtin=True.
            assert all(r["is_builtin"] for r in rows)
    finally:
        conn.close()


def test_seed_builtins_is_idempotent(tmp_path: Path) -> None:
    conn = _isolated_db(tmp_path)
    try:
        with patch.object(ehr_db, "_conn", return_value=conn):
            first  = activities.seed_builtins()
            second = activities.seed_builtins()
            third  = activities.seed_builtins()
            assert first == 8
            assert second == 0
            assert third == 0
            assert len(ehr_db.list_activities(builtin_only=True)) == 8
    finally:
        conn.close()


def test_seed_builtins_preserves_instructor_edits(tmp_path: Path) -> None:
    """Re-seed must NOT overwrite instructor edits to a built-in row.
    The contract: ``seed_builtins`` inserts missing rows only."""
    conn = _isolated_db(tmp_path)
    try:
        with patch.object(ehr_db, "_conn", return_value=conn):
            activities.seed_builtins()
            # Instructor edits a built-in.
            ehr_db.update_activity(
                "builtin_msurg_dka",
                label="Med-surg · DKA — edited by instructor",
            )
            # Re-seed should not roll back the edit.
            activities.seed_builtins()
            edited = ehr_db.get_activity("builtin_msurg_dka")
            assert edited["label"] == "Med-surg · DKA — edited by instructor"
    finally:
        conn.close()


def test_to_encounter_entry_maps_activity_to_wizard_row(tmp_path: Path) -> None:
    """`to_encounter_entry` produces the dict shape the M4
    /api/room/start route accepts for one encounter."""
    conn = _isolated_db(tmp_path)
    try:
        with patch.object(ehr_db, "_conn", return_value=conn):
            activities.seed_builtins()
            entry = activities.to_encounter_entry("builtin_msurg_dka")
            assert entry is not None
            assert entry["scenario_name"] == "Med-surg · DKA management"
            assert entry["persona_id"] == "P-005"
            assert entry["patient_persona_id"] == "P-005"
            assert "M22" in entry["modules"]
            assert "DKA" in entry["scenario_text"]
            assert entry["activity_id"] == "builtin_msurg_dka"
            assert entry["chart_mode"] == "shared"

            # Unknown id returns None (no exception).
            assert activities.to_encounter_entry("act_unknown_xxxx") is None
    finally:
        conn.close()


def test_builtin_catalog_covers_expected_curriculum_areas(tmp_path: Path) -> None:
    """The eight built-ins span the curriculum areas the v7 wizard
    is expected to support: sepsis, postop pain, mental health,
    substance use, peds, geri/end-of-life, endocrine/DKA, and
    respiratory failure."""
    expected_ids = {
        "builtin_ed_sepsis_delirium",
        "builtin_msurg_postop_pain",
        "builtin_mh_passive_si",
        "builtin_substance_etoh_withdrawal",
        "builtin_peds_febrile_child",
        "builtin_geri_goals_of_care",
        "builtin_msurg_dka",
        "builtin_msurg_resp_failure",
    }
    actual_ids = {a.activity_id for a in activities.BUILTIN_ACTIVITIES}
    assert actual_ids == expected_ids
    # Every built-in references a known NCLEX module set + a primary
    # patient persona id.
    for a in activities.BUILTIN_ACTIVITIES:
        assert a.is_builtin is True
        assert a.label.strip() != ""
        assert a.scenario_text.strip() != ""
        assert a.seed_persona_id and a.seed_persona_id.startswith("P-")
        assert len(a.seed_modules) >= 1
        assert a.default_chart_mode in ("shared", "private_clone")
