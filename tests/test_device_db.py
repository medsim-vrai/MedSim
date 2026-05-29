"""V6 — device persistence layer + helper tests.

Covers: schema migration v3, device_station registry, device_event
append + replay ordering, character-assignment history (append-only,
current = latest), purge_session removing all three device tables.
"""
from __future__ import annotations

from portal import ehr_db


def _clear(session_id: str) -> str:
    ehr_db.purge_session(session_id)
    return session_id


def _stn(name: str) -> str:
    """Unique station ID per test so assignment/event history doesn't leak."""
    return f"stn_{name}"


def test_schema_at_v3():
    assert ehr_db.SCHEMA_VERSION >= 3


def test_register_and_get_station():
    sid, stn = _clear("t_dev_register"), _stn("register")
    ehr_db.register_device_station(
        sid, stn, device_kind="pump_iv", device_model="alaris",
        label="Bed 3", user_agent="ua")
    rows = ehr_db.device_stations(sid)
    assert len(rows) == 1
    assert rows[0]["device_model"] == "alaris"
    one = ehr_db.get_device_station(stn)
    assert one and one["label"] == "Bed 3"


def test_append_and_read_events_in_ts_order():
    sid, stn = _clear("t_dev_events"), _stn("events")
    ehr_db.register_device_station(sid, stn, device_kind="cabinet",
                                    device_model="pyxis")
    ev1 = ehr_db.append_device_event(sid, stn,
        type="auth.login", surface="device", payload={"user": "X"})
    ev2 = ehr_db.append_device_event(sid, stn,
        type="cabinet.select_verb", surface="device", payload={"verb": "remove"})
    assert ev2["ts"] >= ev1["ts"]
    events = ehr_db.device_events(station_id=stn)
    assert [e["type"] for e in events] == ["auth.login", "cabinet.select_verb"]
    by_sess = ehr_db.device_events(session_id=sid)
    assert len(by_sess) == 2


def test_assignment_history_is_append_only():
    sid, stn = _clear("t_dev_assign"), _stn("assign")
    ehr_db.register_device_station(sid, stn, device_kind="pump_iv",
                                    device_model="alaris")
    ehr_db.record_assignment(sid, stn, character_id="char_A",
                              assigned_by="instructor")
    ehr_db.record_assignment(sid, stn, character_id="char_B",
                              assigned_by="instructor")
    history = ehr_db.assignment_history(stn)
    assert [h["character_id"] for h in history] == ["char_A", "char_B"]
    cur = ehr_db.current_assignment(stn)
    assert cur and cur["character_id"] == "char_B"


def test_unassign_then_reassign():
    sid, stn = _clear("t_dev_unassign"), _stn("unassign")
    ehr_db.register_device_station(sid, stn, device_kind="cabinet",
                                    device_model="pyxis")
    ehr_db.record_assignment(sid, stn, character_id="char_X",
                              assigned_by="instructor")
    ehr_db.record_assignment(sid, stn, character_id=None,
                              assigned_by="instructor")
    assert ehr_db.current_assignment(stn)["character_id"] is None
    ehr_db.record_assignment(sid, stn, character_id="char_Y",
                              assigned_by="instructor")
    assert ehr_db.current_assignment(stn)["character_id"] == "char_Y"
    assert len(ehr_db.assignment_history(stn)) == 3


def test_purge_session_clears_device_tables():
    sid, stn = _clear("t_dev_purge"), _stn("purge")
    ehr_db.register_device_station(sid, stn, device_kind="pump_iv",
                                    device_model="alaris")
    ehr_db.record_assignment(sid, stn, character_id="cX",
                              assigned_by="instructor")
    ehr_db.append_device_event(sid, stn, type="pump.power",
                                 surface="device", payload={"state": "on"})
    ehr_db.purge_session(sid)
    assert ehr_db.device_stations(sid) == []
    assert ehr_db.device_events(session_id=sid) == []
    assert ehr_db.current_assignment(stn) is None
