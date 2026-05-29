"""M3 acceptance — EHR chart_event writes are per-encounter.

The chart_event table is the system of record for clinical
documentation. In v7 it is keyed by session_id (== encounter id),
which is what M3's route refactor relies on: every chart write goes
into ``ehr_db.append_event(session_id=enc.id, ...)`` and the EHR fold
reads back only that encounter's rows.

This test creates two encounters under one room, seeds each with a
distinct EHR session, writes a few chart_events to each, and asserts
that each encounter's ``ehr_db.fold(session_id)`` projection returns
only its own rows. Bleed between encounters would mean the route
layer is grabbing the wrong session_id at write or read time — which
would be a regression of M3's contract.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from unittest.mock import patch

from portal import control_room, ehr_db
from portal.control_session import ControlSession


def _isolated_ehr_db(tmp_path: Path):
    """Open a fresh sqlite DB for ehr_db's _conn(), bypass the module
    singleton's cache. Returns a connection-providing closure that the
    test substitutes for ehr_db._conn during the test."""
    db_file = tmp_path / "test_v7.db"
    conn = sqlite3.connect(str(db_file), isolation_level=None)
    ehr_db._run_migrations(conn)
    return conn


def test_two_encounters_two_ehr_charts_independent(tmp_path: Path) -> None:
    control_room._reset_for_tests()

    # Stand up an isolated DB and aim ehr_db's connection accessor at it.
    conn = _isolated_ehr_db(tmp_path)
    try:
        with patch.object(ehr_db, "_conn", return_value=conn):
            room = control_room.create_room(label="Multi-EHR Room")

            enc_a = room.add_encounter(ControlSession(
                id="ENC-A-001", join_code="ALPHA1",
                scenario_name="Bed A", api_key="",
                ehr_id="helix"))
            enc_b = room.add_encounter(ControlSession(
                id="ENC-B-002", join_code="BRAVO2",
                scenario_name="Bed B", api_key="",
                ehr_id="cyrus"))

            # Seed each EHR session row.
            ehr_db.register_session(
                session_id=enc_a.id, join_code=enc_a.join_code,
                ehr_id="helix", persona_id="P-001",
                seed={"patient": "Diaz, R.", "mrn": "HLX-001"},
            )
            ehr_db.register_session(
                session_id=enc_b.id, join_code=enc_b.join_code,
                ehr_id="cyrus", persona_id="P-013",
                seed={"patient": "Kowalski, M.", "mrn": "CYR-013"},
            )

            # Register one EHR station per encounter.
            ehr_db.register_station(enc_a.id, "ES-A",
                                     device_label="tablet-A",
                                     user_agent="ipad-A")
            ehr_db.register_station(enc_b.id, "ES-B",
                                     device_label="tablet-B",
                                     user_agent="ipad-B")

            # Write distinct chart events to each encounter.
            ehr_db.append_event(
                enc_a.id, "ES-A",
                type="vitals.record", surface="vitals",
                payload={"hr": 92, "bp": "138/86", "sat": 96})
            ehr_db.append_event(
                enc_a.id, "ES-A",
                type="note.save", surface="notes",
                payload={"body": "SOAP — A: pain 6/10, family at bedside."})
            ehr_db.append_event(
                enc_b.id, "ES-B",
                type="vitals.record", surface="vitals",
                payload={"hr": 78, "bp": "122/76", "sat": 99})

            # ── Read each encounter and assert isolation ──
            # Seed is fetched via the dedicated accessor; fold projects
            # the chart_event log into the current chart state.
            seed_a = ehr_db.seed(enc_a.id)
            seed_b = ehr_db.seed(enc_b.id)
            assert seed_a["patient"] == "Diaz, R."
            assert seed_b["patient"] == "Kowalski, M."

            fold_a = ehr_db.fold(enc_a.id)
            fold_b = ehr_db.fold(enc_b.id)
            # Folds contain only THIS encounter's vitals.
            assert len(fold_a["vitals"]) == 1
            assert len(fold_b["vitals"]) == 1
            assert fold_a["vitals"][0]["hr"] == 92
            assert fold_b["vitals"][0]["hr"] == 78

            # A has both events; B has one — no bleed.
            events_a = ehr_db.events(enc_a.id)
            events_b = ehr_db.events(enc_b.id)
            assert len(events_a) == 2
            assert len(events_b) == 1
            assert all(e["session_id"] == enc_a.id for e in events_a)
            assert all(e["session_id"] == enc_b.id for e in events_b)

            # A's note text is not visible in B's fold and vice versa.
            assert any(e["type"] == "note.save" for e in events_a)
            assert not any(e["type"] == "note.save" for e in events_b)

            # Vitals snapshots differ — direct evidence of independent state.
            vitals_a = [e for e in events_a if e["type"] == "vitals.record"]
            vitals_b = [e for e in events_b if e["type"] == "vitals.record"]
            assert vitals_a[0]["payload"]["hr"] == 92
            assert vitals_b[0]["payload"]["hr"] == 78
    finally:
        conn.close()


def test_get_by_join_code_dispatches_chart_writes_correctly(tmp_path: Path) -> None:
    """Realistic dispatch: a station joins by URL code, the server
    resolves to the right Encounter, and writes against THAT
    encounter's session_id. This proves the route-layer pattern works
    end-to-end through the v6-compat get_by_join_code helper."""
    from portal import control_session as cs

    control_room._reset_for_tests()
    conn = _isolated_ehr_db(tmp_path)
    try:
        with patch.object(ehr_db, "_conn", return_value=conn):
            room = control_room.create_room(label="Dispatch Test")
            enc_a = room.add_encounter(ControlSession(
                id="DIS-A", join_code="JCODE1",
                scenario_name="A", api_key=""))
            enc_b = room.add_encounter(ControlSession(
                id="DIS-B", join_code="JCODE2",
                scenario_name="B", api_key=""))

            ehr_db.register_session(enc_a.id, enc_a.join_code,
                                     "helix", "P-001", {"patient": "A"})
            ehr_db.register_session(enc_b.id, enc_b.join_code,
                                     "cyrus", "P-013", {"patient": "B"})
            ehr_db.register_station(enc_a.id, "ES-A1",
                                     device_label="tA", user_agent="")
            ehr_db.register_station(enc_b.id, "ES-B1",
                                     device_label="tB", user_agent="")

            # Simulate a server route: a station POSTed to /api/ehr/JCODE1/notes
            resolved = cs.get_by_join_code("JCODE1")
            assert resolved is enc_a
            ehr_db.append_event(
                resolved.id, "ES-A1",
                type="note.save", surface="notes",
                payload={"body": "from JCODE1"})

            # Now JCODE2
            resolved = cs.get_by_join_code("JCODE2")
            assert resolved is enc_b
            ehr_db.append_event(
                resolved.id, "ES-B1",
                type="note.save", surface="notes",
                payload={"body": "from JCODE2"})

            events_a = ehr_db.events(enc_a.id)
            events_b = ehr_db.events(enc_b.id)
            assert len(events_a) == 1
            assert len(events_b) == 1
            assert events_a[0]["payload"]["body"] == "from JCODE1"
            assert events_b[0]["payload"]["body"] == "from JCODE2"
    finally:
        conn.close()
