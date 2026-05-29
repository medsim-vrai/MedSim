"""V6 — pause/resume integrity.

The contract: pause → engine.fold() reconstructs the exact same state
on a brand-new engine instance (the fold-from-log invariant). Tick
emits events; events go through persistence; persistence is what fold
reads. So as long as the event log is durable (it is — SQLite WAL),
pause can be arbitrarily long without state drift.
"""
from __future__ import annotations

import json
import time

from portal import control_session, ehr_db
from portal.devices.engine.state_machine import make_engine


def test_pause_flag_in_session_state_machine():
    sess = control_session.create_session(
        scenario_name="t-pause", selected_personas=["P-001"],
        selected_modules=[], api_key="dummy")
    assert sess.state in ("configured", "running")
    control_session.set_state("paused")
    assert control_session.get_active().state == "paused"
    control_session.set_state("running")
    assert control_session.get_active().state == "running"
    control_session.end_active()


def test_refold_after_simulated_pause_is_identical():
    """Drive a pump for 5 minutes, pause for 'a long time' (simulated by
    rewinding _last_tick), then verify fold reconstructs verbatim."""
    sess = control_session.create_session(
        scenario_name="t-refold", selected_personas=["P-001"],
        selected_modules=[], api_key="dummy")
    sid = "t_refold_stn"
    ehr_db.purge_session(sess.id)
    ehr_db.register_device_station(sess.id, sid, device_kind="pump_iv",
                                     device_model="alaris", label="X")
    eng = make_engine(session_id=sess.id, station_id=sid,
                      device_kind="pump_iv", device_model="alaris")
    eng.handle(type="pump.power",   surface="device", payload={"state": "on"})
    eng.handle(type="pump.program", surface="device", payload={
        "channel": "A", "drug_label": "X", "rate_ml_hr": 100,
        "vtbi_ml": 200, "library_used": True, "soft_override": False})
    eng.handle(type="pump.start", surface="device", payload={"channel": "A"})
    eng._last_tick = time.time() - 300   # advance 5 min
    eng.run_tick(now=time.time())
    in_mem = eng.fold()
    # Simulate "long pause" then a fresh engine instance picking up after
    # the server resumes (or restarts) — no further events recorded.
    control_session.set_state("paused")
    fresh = make_engine(session_id=sess.id, station_id=sid,
                         device_kind="pump_iv", device_model="alaris")
    # V6.1.2 — fold() projects live infused_ml using time.time(); the few
    # microseconds between the two fold calls drift infused_ml's float.
    # Structural identity is what we actually care about (every reducer
    # field reconstructed from the persisted log); compare those exactly
    # and infused_ml within a small tolerance.
    def _assert_folds_match(x, y):
        for ch_id, ch_a in x["channels"].items():
            ch_b = y["channels"][ch_id]
            for k in ch_a:
                if k == "infused_ml":
                    assert abs(ch_a[k] - ch_b[k]) < 0.1
                else:
                    assert ch_a[k] == ch_b[k]
        for k in x:
            if k != "channels":
                assert x[k] == y[k]
    _assert_folds_match(in_mem, fresh.fold())
    # Resume — same property still holds.
    control_session.set_state("running")
    _assert_folds_match(in_mem, fresh.fold())
    control_session.end_active()


def test_no_state_drift_when_engine_recreated_from_log():
    """Validate the core fold invariant: every reducer is pure, so two
    independent engine instances applied to the same event log produce
    identical state. This is what makes pause / resume / server-crash
    recovery 'just work'."""
    sess = control_session.create_session(
        scenario_name="t-drift", selected_personas=["P-001"],
        selected_modules=[], api_key="dummy")
    sid = "t_drift_stn"
    ehr_db.purge_session(sess.id)
    ehr_db.register_device_station(sess.id, sid, device_kind="cabinet",
                                     device_model="pyxis", label="C")
    eng = make_engine(session_id=sess.id, station_id=sid,
                      device_kind="cabinet", device_model="pyxis")
    for evt in [
        ("auth.login",                 {"user": "X", "method": "bioid"}),
        ("cabinet.select_patient",     {"patient_id": "P-001",
                                          "patient_name": "Q", "mrn": "1"}),
        ("cabinet.select_verb",        {"verb": "remove"}),
        ("cabinet.select_med",         {"med_id": "med_morphine_10"}),
        ("cabinet.scan_verify",        {"expected_ndc": "11111111101",
                                          "scanned_ndc": "11111111101",
                                          "result": "match"}),
        ("cabinet.remove",             {"med_id": "med_morphine_10",
                                          "qty": 1,
                                          "witness_user": "K. Lee, RN"}),
        ("alarm.injected",             {"tone": "discrepancy_alert"}),
    ]:
        eng.handle(type=evt[0], surface="device", payload=evt[1])
    eng_a = make_engine(session_id=sess.id, station_id=sid,
                         device_kind="cabinet", device_model="pyxis")
    eng_b = make_engine(session_id=sess.id, station_id=sid,
                         device_kind="cabinet", device_model="pyxis")
    state_a = eng_a.fold()
    state_b = eng_b.fold()
    assert json.dumps(state_a, sort_keys=True, default=str) == \
           json.dumps(state_b, sort_keys=True, default=str)
    control_session.end_active()
