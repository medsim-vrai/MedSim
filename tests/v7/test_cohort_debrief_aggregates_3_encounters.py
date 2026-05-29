"""M14 acceptance — cohort debrief aggregates every encounter in a room.

A 3-encounter room (with varying chart activity per encounter)
produces a cohort debrief whose `encounters[]` facet list has one
entry per encounter, and whose `pearls.summary` aggregates the
metrics (total chat turns, total chart events, total duration,
average duration per encounter).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

from portal import control_room, debrief as debrief_mod, ehr_db
from portal.control_session import ControlSession


def _isolated_db(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(tmp_path / "cohort.db"), isolation_level=None)
    ehr_db._run_migrations(conn)
    return conn


def test_cohort_debrief_aggregates_3_encounters(tmp_path: Path) -> None:
    conn = _isolated_db(tmp_path)
    try:
        with patch.object(ehr_db, "_conn", return_value=conn):
            control_room._reset_for_tests()
            room = control_room.create_room(label="Cohort debrief test")
            encs = []
            for i, persona in enumerate(("P-001", "P-013", "P-005"), start=1):
                e = room.add_encounter(ControlSession(
                    id=f"enc-{i}", join_code=f"JC0000{i}",
                    scenario_name=f"Bed {i}",
                    selected_personas=[persona], api_key="",
                    ehr_id="helix", patient_persona_id=persona,
                ))
                ehr_db.register_session(e.id, e.join_code, "helix",
                                          persona, {"patient": f"P{i}"})
                ehr_db.register_station(e.id, f"st-{i}", device_label="t")
                encs.append(e)

            # Bed 1: 3 chart events. Bed 2: 1. Bed 3: 0 (untouched).
            ehr_db.append_event(encs[0].id, "st-1", type="vitals.record",
                                  surface="vitals", payload={"hr": 80})
            ehr_db.append_event(encs[0].id, "st-1", type="note.save",
                                  surface="notes",
                                  payload={"note_id": "n1", "body": "x"})
            ehr_db.append_event(encs[0].id, "st-1", type="note.save",
                                  surface="notes",
                                  payload={"note_id": "n2", "body": "y"})
            ehr_db.append_event(encs[1].id, "st-2", type="vitals.record",
                                  surface="vitals", payload={"hr": 70})

            d = debrief_mod.build_cohort_debrief(room)

            assert d["room_id"] == room.room_id
            assert d["room_code"] == room.room_code
            assert d["room_label"] == "Cohort debrief test"
            # One facet per encounter, in insertion order.
            assert len(d["encounters"]) == 3
            facet_ids = [f["session_id"] for f in d["encounters"]]
            assert facet_ids == [e.id for e in encs]

            # Cohort aggregates.
            summary = d["pearls"]["summary"]
            assert summary["encounters_count"]   == 3
            assert summary["total_chart_events"] == 4   # 3 + 1 + 0
            assert summary["students_count"]     == 0   # no students rostered

            # Description block carries the facts pre-fill.
            descr = d["pearls"]["description"]["facts"]
            assert any("3 encounters" in f for f in descr)
            assert any("4" in f and "chart event" in f for f in descr)
    finally:
        conn.close()
        control_room._reset_for_tests()


def test_cohort_debrief_persists_to_data_debriefs_cohort(tmp_path: Path,
                                                            monkeypatch) -> None:
    """save_cohort writes to data/debriefs/cohort/<room_id>.json."""
    conn = _isolated_db(tmp_path)
    sandbox_root = tmp_path / "data"
    monkeypatch.setattr(debrief_mod, "DEBRIEFS_DIR", sandbox_root / "debriefs")
    monkeypatch.setattr(debrief_mod, "COHORT_DEBRIEFS_DIR",
                         sandbox_root / "debriefs" / "cohort")
    try:
        with patch.object(ehr_db, "_conn", return_value=conn):
            control_room._reset_for_tests()
            room = control_room.create_room(label="Save test")
            room.add_encounter(ControlSession(
                id="enc-a", join_code="JCAAAA1",
                scenario_name="A", selected_personas=["P-001"], api_key=""))
            d = debrief_mod.build_cohort_debrief(room)
            path = debrief_mod.save_cohort(d)
            assert path.exists()
            # load_cohort round-trips.
            loaded = debrief_mod.load_cohort(room.room_id)
            assert loaded is not None
            assert loaded["room_id"] == room.room_id

            # list_saved_cohorts surfaces it.
            saved = debrief_mod.list_saved_cohorts()
            assert any(s["room_id"] == room.room_id for s in saved)
    finally:
        conn.close()
        control_room._reset_for_tests()
