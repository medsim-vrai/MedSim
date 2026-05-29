"""M14 acceptance — cohort debrief has the four PEARLS sections.

PEARLS (Eppich & Cheng 2015) phases:
  1. Reactions
  2. Description
  3. Analysis
  4. Application
Plus a Summary block carrying the room-level aggregates.

The cohort debrief JSON exposes each phase under `pearls.<phase>`
so M15's renderer can lay them out as tabs / accordion sections.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

from portal import control_room, debrief as debrief_mod, ehr_db
from portal.control_session import ControlSession


def _isolated_db(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(tmp_path / "pearls.db"), isolation_level=None)
    ehr_db._run_migrations(conn)
    return conn


def test_cohort_debrief_includes_pearls_sections(tmp_path: Path) -> None:
    conn = _isolated_db(tmp_path)
    try:
        with patch.object(ehr_db, "_conn", return_value=conn):
            control_room._reset_for_tests()
            room = control_room.create_room(label="PEARLS sections test")
            for i in range(2):
                room.add_encounter(ControlSession(
                    id=f"e{i}", join_code=f"JC0000{i}",
                    scenario_name=f"Bed {i}",
                    selected_personas=["P-001"], api_key="",
                    patient_persona_id="P-001",
                ))

            d = debrief_mod.build_cohort_debrief(room)
            pearls = d["pearls"]

            # All four PEARLS phases + summary present.
            assert set(pearls.keys()) >= {
                "reactions", "description", "analysis", "application",
                "summary",
            }

            # Each phase carries a prompt the instructor reads aloud.
            assert pearls["reactions"]["prompt"]
            assert pearls["description"]["prompt"]
            assert pearls["analysis"]["prompt"]
            assert pearls["application"]["prompt"]

            # Description has cohort facts.
            assert isinstance(pearls["description"]["facts"], list)
            assert len(pearls["description"]["facts"]) >= 2

            # Analysis has one performance frame per encounter.
            frames = pearls["analysis"]["performance_frames"]
            assert len(frames) == 2
            assert {f["session_id"] for f in frames} == {"e0", "e1"}

            # Application has a commitments list (empty at build time;
            # the instructor fills it live during the debrief).
            assert pearls["application"]["commitments"] == []

            # Summary has every aggregate metric the description block
            # references.
            summary = pearls["summary"]
            for key in ("encounters_count", "students_count",
                         "total_chat_turns", "total_chart_events",
                         "total_duration_seconds",
                         "avg_duration_per_encounter_seconds",
                         "avg_turns_per_encounter"):
                assert key in summary
    finally:
        conn.close()
        control_room._reset_for_tests()


def test_cohort_debrief_persona_engagement_ranked(tmp_path: Path) -> None:
    """The analysis block's persona_engagement_ranked aggregates
    persona engagement across every encounter in the room."""
    conn = _isolated_db(tmp_path)
    try:
        with patch.object(ehr_db, "_conn", return_value=conn):
            control_room._reset_for_tests()
            room = control_room.create_room(label="Persona ranking")
            for persona in ("P-001", "P-013"):
                e = room.add_encounter(ControlSession(
                    id=f"enc-{persona}", join_code=f"JC{persona[2:]}AB",
                    scenario_name=f"Bed {persona}",
                    selected_personas=[persona], api_key="",
                    patient_persona_id=persona,
                ))
            d = debrief_mod.build_cohort_debrief(room)
            ranked = d["pearls"]["analysis"]["persona_engagement_ranked"]
            assert isinstance(ranked, list)
            # Empty room (no chat turns) — ranked is empty but the
            # key exists. M15 should hide the section in this case.
            assert ranked == []
    finally:
        conn.close()
        control_room._reset_for_tests()
