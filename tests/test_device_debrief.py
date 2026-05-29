"""V6 — debrief assembly + compare/rules_devices scoring."""
from __future__ import annotations

import json
import time

from portal import control_session, debrief, ehr_db
from portal.compare import rules_devices
from portal.devices.engine.state_machine import make_engine


def _sess_with_devices(scenario: str = "dbg-test"):
    """Boot a fresh session with one pump and one cabinet, returning the
    ControlSession plus station IDs. Station IDs incorporate the scenario
    name so they don't collide with events from earlier tests sharing the
    same on-disk DB."""
    sess = control_session.create_session(
        scenario_name=scenario, selected_personas=["P-001"],
        selected_modules=[], api_key="dummy")
    ehr_db.purge_session(sess.id)
    pid = f"dbg_pump_{scenario}"
    cid = f"dbg_cab_{scenario}"
    for kind, model, label, sid in [
        ("pump_iv", "alaris", "Bed 3 IV", pid),
        ("cabinet", "pyxis",  "Cart A",  cid),
    ]:
        ehr_db.register_device_station(sess.id, sid, device_kind=kind,
                                         device_model=model, label=label)
        sess.add_device_station(sid, device_kind=kind, device_model=model,
                                 label=label)
        ehr_db.record_assignment(sess.id, sid, character_id="P-001",
                                  assigned_by="instructor")
    return sess, pid, cid


def test_debrief_carries_v6_device_sections():
    sess, pid, cid = _sess_with_devices()
    pe = make_engine(session_id=sess.id, station_id=pid,
                      device_kind="pump_iv", device_model="alaris")
    pe.handle(type="pump.power", surface="device", payload={"state": "on"})
    db = debrief.build(sess)
    for key in ("devices", "device_timeline", "alarm_log",
                 "medication_dispense_log", "pump_program_log"):
        assert key in db
    assert len(db["devices"]) == 2
    assert any(d["device_model"] == "alaris" for d in db["devices"])
    control_session.end_active()


def test_alarm_log_records_silence_and_clear_latency():
    sess, pid, _ = _sess_with_devices("dbg-latency")
    pe = make_engine(session_id=sess.id, station_id=pid,
                      device_kind="pump_iv", device_model="alaris")
    pe.handle(type="alarm.injected", surface="instructor",
              payload={"tone": "occlusion_downstream"})
    time.sleep(0.05)
    pe.handle(type="alarm.silenced", surface="device",
              payload={"tone": "occlusion_downstream"})
    time.sleep(0.05)
    pe.handle(type="alarm.cleared",  surface="device",
              payload={"tone": "occlusion_downstream"})
    db = debrief.build(sess)
    alarms = db["alarm_log"]
    assert len(alarms) == 1
    a = alarms[0]
    assert a["tone"] == "occlusion_downstream"
    assert a["cleared"] is True
    assert a["time_to_silence_s"] is not None
    assert a["time_to_clear_s"]   is not None
    control_session.end_active()


def test_uncleared_alarm_flagged_in_debrief():
    sess, pid, _ = _sess_with_devices("dbg-uncleared")
    pe = make_engine(session_id=sess.id, station_id=pid,
                      device_kind="pump_iv", device_model="alaris")
    pe.handle(type="alarm.injected", surface="instructor",
              payload={"tone": "low_battery"})
    db = debrief.build(sess)
    assert db["alarm_log"][0]["cleared"] is False
    rows = rules_devices.score(db)
    assert any(r["rule"] == "alarm.uncleared" and not r["pass"] for r in rows)
    control_session.end_active()


def test_witness_compliance_flag_for_waste_without_witness():
    sess, _, cid = _sess_with_devices("dbg-witness")
    ce = make_engine(session_id=sess.id, station_id=cid,
                      device_kind="cabinet", device_model="pyxis")
    ce.handle(type="auth.login", surface="device",
              payload={"user": "X", "method": "password"})
    ce.handle(type="cabinet.select_med", surface="device",
              payload={"med_id": "med_lorazepam_2"})
    ce.handle(type="cabinet.waste", surface="device", payload={
        "med_id": "med_lorazepam_2", "amount": "1 mg",
        "reason": "spilled"})   # no witness_user
    db = debrief.build(sess)
    rows = rules_devices.score(db)
    rule = next(r for r in rows if r["rule"] == "cabinet.witness_compliance")
    assert rule["pass"] is False
    assert rule["evidence"]["missing"] == 1
    control_session.end_active()


def test_scan_compliance_flag_for_remove_without_prior_scan():
    sess, _, cid = _sess_with_devices("dbg-scan")
    ce = make_engine(session_id=sess.id, station_id=cid,
                      device_kind="cabinet", device_model="pyxis")
    ce.handle(type="auth.login", surface="device",
              payload={"user": "X", "method": "password"})
    ce.handle(type="cabinet.select_med", surface="device",
              payload={"med_id": "med_morphine_10"})
    # no scan.verify
    ce.handle(type="cabinet.remove", surface="device", payload={
        "med_id": "med_morphine_10", "qty": 1,
        "witness_user": "K. Lee, RN"})
    db = debrief.build(sess)
    rows = rules_devices.score(db)
    rule = next(r for r in rows if r["rule"] == "cabinet.scan_compliance")
    assert rule["pass"] is False
    assert rule["evidence"]["unscanned"] == 1
    control_session.end_active()


def test_pump_library_override_counted():
    sess, pid, _ = _sess_with_devices("dbg-override")
    pe = make_engine(session_id=sess.id, station_id=pid,
                      device_kind="pump_iv", device_model="alaris")
    pe.handle(type="pump.power", surface="device", payload={"state": "on"})
    pe.handle(type="pump.program", surface="device", payload={
        "channel": "A", "drug_label": "Heparin", "rate_ml_hr": 30,
        "vtbi_ml": 250, "library_used": True, "soft_override": True})
    db = debrief.build(sess)
    rows = rules_devices.score(db)
    rule = next(r for r in rows if r["rule"] == "pump.library_override")
    assert rule["pass"] is False
    assert rule["evidence"]["overrides"] == 1
    control_session.end_active()


def test_debrief_is_json_serializable():
    sess, pid, _ = _sess_with_devices("dbg-serialize")
    pe = make_engine(session_id=sess.id, station_id=pid,
                      device_kind="pump_iv", device_model="alaris")
    pe.handle(type="pump.power", surface="device", payload={"state": "on"})
    db = debrief.build(sess)
    serialized = json.dumps(db, default=str)
    reloaded = json.loads(serialized)
    assert reloaded["session_id"] == sess.id
    assert "devices" in reloaded
    control_session.end_active()
