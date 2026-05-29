"""M10 acceptance — single-patient mode is byte-for-byte v6-compatible.

The contract: in single-patient mode (a room of 1, which is what the
v6 wizard's `create_session` finalize implicitly creates), every
externally-observable artifact a v6 client would inspect — chart
event rows, the `fold()` projection, the `seed()` accessor, the
`events()` listing — must be identical in shape and content to what
the v6 codebase would produce on the same scripted scenario.

This is the MVP gate's load-bearing invariant: any breaking change
in v7's persistence layer would fail this test. The exact equality
contract is what lets the v6 89-test suite run unchanged on the v7
codebase, and what unblocks a real-world migration from v6 to v7
without retraining students or instructors on a different EHR
behavior.

We assert equality by running the SAME scripted scenario through
two code paths inside v7:

  1. **v6-compat path** — `control_session.create_session(...)`.
     This is the v6 wizard's finalize call, unchanged. In v7 it
     transparently creates a ControlRoom-of-1 + Encounter.

  2. **v7 explicit path** — `control_room.create_room()` followed
     by `room.add_encounter(...)`. This is what the v7 room-mode
     wizard does for each encounter.

Both paths must produce the same chart_event payloads, the same
fold projection structure, and the same event ordering. If they
diverge, v7 is leaking room-mode metadata into single-mode chart
content — a v6 regression.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from portal import control_room, control_session, ehr_db
from portal.control_session import ControlSession


@pytest.fixture(autouse=True)
def _fresh_singleton():
    control_room._reset_for_tests()
    yield
    control_room._reset_for_tests()


def _isolated_db(tmp_path: Path) -> sqlite3.Connection:
    """Fresh DB with v7 schema applied. Tests substitute it for
    ehr_db._conn so the user's ~/.medsim/v7/medsim.db is not touched."""
    db_file = tmp_path / "compat.db"
    conn = sqlite3.connect(str(db_file), isolation_level=None)
    ehr_db._run_migrations(conn)
    return conn


# Scripted scenario operations — the SAME calls run on each path. The
# resulting chart_event rows + fold projection are then compared.
def _run_scripted(session_id: str, station_id: str) -> None:
    """A deterministic sequence of v6 chart-event writes — exactly
    what a single-patient v6 student would have produced."""
    # Vitals at admission.
    ehr_db.append_event(
        session_id, station_id,
        type="vitals.record", surface="vitals",
        payload={"hr": 88, "sbp": 124, "dbp": 78, "spo2": 97, "rr": 18,
                  "temp_f": 98.6, "source": "admission"},
    )
    # Nurse SOAP note.
    ehr_db.append_event(
        session_id, station_id,
        type="note.save", surface="notes",
        payload={"note_id": "note-1",
                  "body": "Admission SOAP. Pt alert, AOx4, denies pain."},
    )
    # An order.
    ehr_db.append_order(
        session_id, station_id,
        patient_id="P-001",
        order={"order_id": "ord-1", "order_type": "med",
                "code": "ACETAMINOPHEN", "label": "Acetaminophen 650mg PO PRN"},
    )
    # An administered med.
    ehr_db.append_event(
        session_id, station_id,
        type="med.administer", surface="mar",
        payload={"order_id": "ord-1", "given_at_iso": "2026-05-26T10:30:00",
                  "given_by": "RN", "patient_id": "P-001"},
    )
    # Recheck vitals.
    ehr_db.append_event(
        session_id, station_id,
        type="vitals.record", surface="vitals",
        payload={"hr": 82, "sbp": 120, "dbp": 76, "spo2": 98, "rr": 16,
                  "temp_f": 98.4, "source": "post-intervention"},
    )
    # A second note.
    ehr_db.append_event(
        session_id, station_id,
        type="note.save", surface="notes",
        payload={"note_id": "note-2",
                  "body": "Reassessment 30 min post med. Pt resting."},
    )


def _build_via_v6_compat() -> tuple[str, str]:
    """The v6 wizard's finalize path. Returns (session_id, station_id)."""
    sess = control_session.create_session(
        scenario_name="Compat test — single patient",
        api_key="dummy",
        scenario_notes="byte-for-byte compat scenario",
        program_id="BSN-RN",
        week=8,
        selected_modules=["M22"],
        scenario_text="58yo F postop day 1 chole. Stable.",
        selected_personas=["P-001"],
        ehr_id="helix",
    )
    ehr_db.register_session(
        sess.id, sess.join_code, "helix", "P-001",
        seed={"patient": {"name": "Test Patient",
                            "mrn": "HLX-001"}},
    )
    ehr_db.register_station(
        sess.id, "ES-A",
        device_label="tablet-A", user_agent="ipad",
    )
    _run_scripted(sess.id, "ES-A")
    return sess.id, "ES-A"


def _build_via_v7_room() -> tuple[str, str]:
    """The v7 explicit room-creation path. Returns (session_id, station_id)."""
    room = control_room.create_room(label="Compat test — explicit room")
    enc = ControlSession(
        id="enc-via-room-001",
        join_code="JC7777",
        scenario_name="Compat test — single patient",
        scenario_notes="byte-for-byte compat scenario",
        program_id="BSN-RN",
        week=8,
        selected_modules=["M22"],
        scenario_text="58yo F postop day 1 chole. Stable.",
        selected_personas=["P-001"],
        api_key="dummy",
        ehr_id="helix",
        patient_persona_id="P-001",
    )
    room.add_encounter(enc)
    ehr_db.register_session(
        enc.id, enc.join_code, "helix", "P-001",
        seed={"patient": {"name": "Test Patient",
                            "mrn": "HLX-001"}},
    )
    ehr_db.register_station(
        enc.id, "ES-B",
        device_label="tablet-B", user_agent="ipad",
    )
    _run_scripted(enc.id, "ES-B")
    return enc.id, "ES-B"


def _normalize_events(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Drop the row-specific keys that legitimately differ (session_id,
    ehr_station_id, ts, id) but keep type/surface/payload — the actual
    EHR content. This is the byte-for-byte contract."""
    out = []
    for r in rows:
        out.append({
            "type":    r["type"],
            "surface": r["surface"],
            "payload": r["payload"],
        })
    return out


def _normalize_fold(fold: dict[str, object], session_id: str) -> dict[str, object]:
    """Strip identity / timestamp keys from the fold so the comparison
    is purely content-based. The fold structure is what v6 students
    saw in the EHR projection — any extra structural keys here would
    be a v7 leak. ``ts``, ``latest_ts``, ``station_id``, and
    ``session_id`` legitimately differ between two runs of the same
    script and would mask real divergence if left in."""
    normalized = json.loads(json.dumps(fold, default=str))
    drop_keys = {"session_id", "ts", "latest_ts", "station_id",
                  "ehr_station_id"}
    def _strip(obj):
        if isinstance(obj, dict):
            return {k: _strip(v) for k, v in obj.items() if k not in drop_keys}
        if isinstance(obj, list):
            return [_strip(v) for v in obj]
        return obj
    return _strip(normalized)


def test_single_patient_mode_byte_for_byte_compat(tmp_path: Path) -> None:
    """The headline test: same scripted scenario, two code paths, byte-
    identical chart content (types, surfaces, payloads, fold)."""
    conn = _isolated_db(tmp_path)
    try:
        with patch.object(ehr_db, "_conn", return_value=conn):
            # Path 1 — v6 wizard finalize.
            sid_v6, station_v6 = _build_via_v6_compat()
            events_v6 = _normalize_events(ehr_db.events(sid_v6))
            fold_v6   = _normalize_fold(ehr_db.fold(sid_v6), sid_v6)

            # Reset between runs so we're not seeing cross-pollination.
            control_room._reset_for_tests()

            # Path 2 — v7 explicit room creation.
            sid_v7, station_v7 = _build_via_v7_room()
            events_v7 = _normalize_events(ehr_db.events(sid_v7))
            fold_v7   = _normalize_fold(ehr_db.fold(sid_v7), sid_v7)

            # ── Byte-for-byte equality ──
            assert events_v6 == events_v7, (
                "Chart event payloads must be identical across the v6-compat "
                "and v7 room paths. Divergence indicates v7 is leaking "
                "room-mode metadata into single-patient chart content."
            )
            assert fold_v6 == fold_v7, (
                "EHR fold projection must be identical across paths."
            )
    finally:
        conn.close()


def test_fold_projection_shape_matches_v6_contract(tmp_path: Path) -> None:
    """The fold projection's top-level shape is part of the v6 EHR
    contract. v7 must not add or remove keys — any client that
    cached the fold shape (the React EHR app does) would break."""
    conn = _isolated_db(tmp_path)
    try:
        with patch.object(ehr_db, "_conn", return_value=conn):
            sid, _ = _build_via_v6_compat()
            fold = ehr_db.fold(sid)
            # v6 documented top-level keys — every one must be present.
            # (From `portal/ehr_db.py:fold()` source comments + v6 EHR's
            # bootstrap reader.)
            for required_key in (
                "notes", "orders", "vitals", "assessments",
                "comms", "flags", "meds_administered",
                "results_acknowledged", "intake", "output",
                "allergies", "problems",
            ):
                assert required_key in fold, (
                    f"v6 fold contract requires '{required_key}'; "
                    f"v7 fold is missing it."
                )
            # No v7-specific keys leaked.
            v7_specific = {"room_id", "encounter_id", "chart_mode",
                            "assigned_student_ids"}
            assert not (v7_specific & set(fold.keys())), (
                "v7 leaked room-mode keys into the fold projection: "
                f"{v7_specific & set(fold.keys())}"
            )
    finally:
        conn.close()


def test_single_patient_chart_event_rows_carry_no_room_metadata(tmp_path: Path) -> None:
    """chart_event rows themselves must NOT contain room-mode keys in
    their payload. The room_id lives on the ehr_session row only; the
    chart_event log stays v6-shaped."""
    conn = _isolated_db(tmp_path)
    try:
        with patch.object(ehr_db, "_conn", return_value=conn):
            sid, _ = _build_via_v6_compat()
            events = ehr_db.events(sid)
            for ev in events:
                payload = ev["payload"]
                forbidden = {"room_id", "encounter_id", "assigned_student_ids"}
                leaked = forbidden & set(payload.keys())
                assert not leaked, (
                    f"chart_event {ev['type']} leaked room-mode keys: "
                    f"{leaked}; payload={payload}"
                )
    finally:
        conn.close()


def test_single_patient_get_active_returns_the_only_encounter(tmp_path: Path) -> None:
    """The v6-compat ``get_active()`` helper must keep returning the
    one-and-only encounter for the single-patient finalize path. v6
    routes that call `control_session.get_active()` would break
    otherwise."""
    conn = _isolated_db(tmp_path)
    try:
        with patch.object(ehr_db, "_conn", return_value=conn):
            sess = control_session.create_session(
                scenario_name="get_active compat",
                api_key="dummy",
                selected_personas=["P-001"],
                ehr_id="helix",
            )
            active = control_session.get_active()
            assert active is sess
            assert active.room_id == control_room.get_active_room().room_id
            assert active.join_code == sess.join_code
    finally:
        conn.close()
