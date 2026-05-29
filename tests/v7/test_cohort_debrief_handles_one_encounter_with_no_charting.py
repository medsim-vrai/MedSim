"""M14 acceptance — cohort debrief is robust to empty encounters.

A room may include an encounter where the student never charted
anything (joined late, technical issue, etc.). The cohort builder
must still produce a valid debrief with that encounter in the
facets list (zeroed metrics) and the cohort aggregates computed
across whatever encounters DO have content.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

from portal import control_room, debrief as debrief_mod, ehr_db
from portal.control_session import ControlSession


def _isolated_db(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(tmp_path / "empty.db"), isolation_level=None)
    ehr_db._run_migrations(conn)
    return conn


def test_cohort_debrief_handles_one_encounter_with_no_charting(tmp_path: Path) -> None:
    conn = _isolated_db(tmp_path)
    try:
        with patch.object(ehr_db, "_conn", return_value=conn):
            control_room._reset_for_tests()
            room = control_room.create_room(label="Empty encounter test")

            # Bed 1 has chart activity; Bed 2 has none.
            e1 = room.add_encounter(ControlSession(
                id="e1", join_code="JCBED01",
                scenario_name="Bed 1 (active)",
                selected_personas=["P-001"], api_key="",
                patient_persona_id="P-001"))
            e2 = room.add_encounter(ControlSession(
                id="e2", join_code="JCBED02",
                scenario_name="Bed 2 (empty)",
                selected_personas=["P-013"], api_key="",
                patient_persona_id="P-013"))
            ehr_db.register_session(e1.id, e1.join_code, "helix", "P-001",
                                      {"patient": "active"})
            ehr_db.register_session(e2.id, e2.join_code, "helix", "P-013",
                                      {"patient": "empty"})
            ehr_db.register_station(e1.id, "st-1", device_label="t")
            ehr_db.append_event(e1.id, "st-1", type="vitals.record",
                                  surface="vitals", payload={"hr": 90})

            # No exception; full structure intact.
            d = debrief_mod.build_cohort_debrief(room)
            assert len(d["encounters"]) == 2

            # Bed 1 facet has the chart event; Bed 2 facet has zero.
            facet_e1 = next(f for f in d["encounters"]
                             if f["session_id"] == "e1")
            facet_e2 = next(f for f in d["encounters"]
                             if f["session_id"] == "e2")

            # Per-encounter facet structure intact for the empty one.
            assert facet_e2["session_id"] == "e2"
            assert facet_e2["scenario_name"] == "Bed 2 (empty)"
            # Empty encounter has no transcript / no stations / no
            # device sections.
            assert facet_e2.get("transcript", []) == []
            assert facet_e2.get("stations", []) == []

            # Cohort summary reflects only Bed 1's chart event.
            summary = d["pearls"]["summary"]
            assert summary["encounters_count"]   == 2
            assert summary["total_chart_events"] == 1
    finally:
        conn.close()
        control_room._reset_for_tests()


def test_cohort_debrief_handles_a_completely_empty_room(tmp_path: Path) -> None:
    """A room with NO encounters at all (operator started + ended
    immediately) still produces a valid cohort debrief."""
    conn = _isolated_db(tmp_path)
    try:
        with patch.object(ehr_db, "_conn", return_value=conn):
            control_room._reset_for_tests()
            room = control_room.create_room(label="Truly empty")
            d = debrief_mod.build_cohort_debrief(room)
            assert d["encounters"] == []
            summary = d["pearls"]["summary"]
            assert summary["encounters_count"]   == 0
            assert summary["total_chat_turns"]   == 0
            assert summary["total_chart_events"] == 0
            # avg fields safe-zero on division.
            assert summary["avg_duration_per_encounter_seconds"] == 0
            assert summary["avg_turns_per_encounter"]            == 0
    finally:
        conn.close()
        control_room._reset_for_tests()


def test_cohort_debrief_with_private_clones(tmp_path: Path) -> None:
    """A private_clone room has 1 template + N clones; the cohort
    debrief should treat each clone as its own facet (one debrief
    panel per student's run)."""
    conn = _isolated_db(tmp_path)
    try:
        with patch.object(ehr_db, "_conn", return_value=conn):
            control_room._reset_for_tests()
            room = control_room.create_room(label="Private clones")
            template = room.add_encounter(ControlSession(
                id="tpl", join_code="JCTPL00",
                scenario_name="Bed 1 — template",
                selected_personas=["P-001"], api_key="",
                patient_persona_id="P-001",
                chart_mode="private_clone"))
            # Spawn 2 clones (the M9 join flow would do this; here
            # we exercise the cohort builder directly).
            clone_a = room.clone_encounter(template.id,
                                             label_suffix="Alice")
            clone_b = room.clone_encounter(template.id,
                                             label_suffix="Bob")
            for e in (template, clone_a, clone_b):
                ehr_db.register_session(e.id, e.join_code, "helix",
                                          "P-001", {"patient": "p"})

            d = debrief_mod.build_cohort_debrief(room)
            # 3 facets — template + 2 clones.
            assert len(d["encounters"]) == 3
            scenario_names = [f["scenario_name"] for f in d["encounters"]]
            assert any("Alice" in s for s in scenario_names)
            assert any("Bob"   in s for s in scenario_names)
    finally:
        conn.close()
        control_room._reset_for_tests()
