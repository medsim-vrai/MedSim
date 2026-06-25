"""V6 — engine reducers and time-driven tick events.

Covers all three engines (Alaris IV pump, Kangaroo OMNI enteral pump,
BD Pyxis cabinet): event reducers produce the expected state, refold
from log alone is bit-identical to in-memory state (the pause/resume
invariant), and tick() emits pump.tick / feed.tick events so derived
state (battery, infused volume) survives a re-fold.
"""
from __future__ import annotations

import json
import time

from portal import ehr_db
from portal.devices.engine.state_machine import make_engine


def _setup(sid: str, stn_base: str, *, device_kind: str, device_model: str):
    """Each test gets a session-scoped unique station id so neither
    events nor assignments leak across tests sharing the same on-disk DB."""
    stn = f"{stn_base}_{sid}"
    ehr_db.purge_session(sid)
    ehr_db.register_device_station(sid, stn, device_kind=device_kind,
                                    device_model=device_model, label=stn)
    ehr_db.record_assignment(sid, stn, character_id="char_test",
                              assigned_by="instructor")
    eng = make_engine(session_id=sid, station_id=stn,
                       device_kind=device_kind, device_model=device_model)
    eng.__test_station_id = stn   # tests can read this back if needed
    return eng


# ── Alaris ──────────────────────────────────────────────────────────────

def test_alaris_power_program_start_then_run_ticks_infused_volume():
    eng = _setup("t_alaris_run", "stn1",
                  device_kind="pump_iv", device_model="alaris")
    eng.handle(type="pump.power",   surface="device", payload={"state": "on"})
    eng.handle(type="pump.program", surface="device", payload={
        "channel": "A", "drug_code": "ns", "drug_label": "0.9% NaCl",
        "rate_ml_hr": 1000, "vtbi_ml": 500,
        "library_used": True, "soft_override": False,
    })
    eng.handle(type="pump.start", surface="device", payload={"channel": "A"})
    # Simulate 30 min of elapsed time.
    eng._last_tick = time.time() - 1800
    state = eng.run_tick(now=time.time())
    # 1000 mL/hr × 0.5 h = 500 mL VTBI fully infused
    assert state["channels"]["A"]["infused_ml"] == 500
    assert state["channels"]["A"]["running"] is False
    # Engine raised infusion_complete tone
    assert any(a["tone"] == "infusion_complete" for a in state["active_alarms"])


def test_alaris_refold_matches_in_memory_state():
    eng = _setup("t_alaris_refold", "stn1",
                  device_kind="pump_iv", device_model="alaris")
    eng.handle(type="pump.power",   surface="device", payload={"state": "on"})
    eng.handle(type="pump.program", surface="device", payload={
        "channel": "A", "drug_code": "ns", "drug_label": "0.9% NaCl",
        "rate_ml_hr": 250, "vtbi_ml": 100,
        "library_used": True, "soft_override": False,
    })
    eng.handle(type="pump.start", surface="device", payload={"channel": "A"})
    eng._last_tick = time.time() - 600
    a = eng.run_tick(now=time.time())
    # Fresh engine reads only the event log
    eng2 = make_engine(session_id="t_alaris_refold",
                        station_id=eng.__test_station_id,
                        device_kind="pump_iv", device_model="alaris")
    b = eng2.fold()
    # V6.1.2 — fold() now projects live infused_ml using time.time() at the
    # moment of the call. Microsecond drift between `a` and `b` shows up in
    # the 7th decimal place of infused_ml. Compare structurally instead.
    assert a.keys() == b.keys()
    assert a["screen"] == b["screen"]
    assert a["power"] == b["power"]
    for ch_id, ch_a in a["channels"].items():
        ch_b = b["channels"][ch_id]
        for k in ch_a:
            if k == "infused_ml":
                assert abs(ch_a[k] - ch_b[k]) < 0.01, f"infused_ml drift > 0.01"
            else:
                assert ch_a[k] == ch_b[k], f"channel {ch_id}.{k} mismatch"


def test_alaris_soft_override_increments_counter():
    eng = _setup("t_alaris_override", "stn1",
                  device_kind="pump_iv", device_model="alaris")
    eng.handle(type="pump.power", surface="device", payload={"state": "on"})
    eng.handle(type="pump.program", surface="device", payload={
        "channel": "A", "drug_label": "Heparin", "rate_ml_hr": 30,
        "vtbi_ml": 250, "library_used": True, "soft_override": True,
    })
    assert eng.fold()["library_overrides"] == 1


def test_alaris_apply_resilient_to_missing_channels_key():
    """Regression: bootstrap 500 KeyError 'channels' — if a corrupt or
    schema-shifted state lands in apply() without the channels key, the
    engine must self-heal rather than crash."""
    eng = _setup("t_alaris_resilient", "stn_resilient",
                  device_kind="pump_iv", device_model="alaris")
    corrupt_state = {"power": True, "screen": "running", "active_alarms": []}
    # Drive a real pump event through apply() with the corrupt state —
    # without the defensive guard this would raise KeyError.
    new_state = eng.apply(corrupt_state, {
        "type": "pump.program",
        "ts":   1234567890.0,
        "payload": {"channel": "A", "rate_ml_hr": 125, "vtbi_ml": 500,
                     "drug_code": "ns", "library_used": True, "soft_override": False},
    })
    assert "channels" in new_state
    assert "A" in new_state["channels"]
    assert new_state["channels"]["A"]["rate_ml_hr"] == 125


def test_alaris_program_channel_b_from_single_channel_state():
    """Regression (#83): a state carrying only {'A'} — e.g. a single-channel
    pump switched to a dual-channel model via the in-control picker — must NOT
    silently drop a pump.program for 'B'. The self-heal adds every spec channel
    so channel B programs instead of vanishing."""
    from portal.devices.pumps.alaris.engine import PumpIvEngine
    eng = _setup("t_alaris_chan_b", "stn_chan_b",
                  device_kind="pump_iv", device_model="alaris")
    single = {"power": True, "screen": "running", "active_alarms": [],
              "channels": {"A": PumpIvEngine._empty_channel()}}
    new_state = eng.apply(single, {
        "type": "pump.program", "ts": 1234567890.0,
        "payload": {"channel": "B", "drug_label": "Norepinephrine",
                     "rate_ml_hr": 12, "vtbi_ml": 100},
    })
    assert "B" in new_state["channels"]                    # channel healed in
    assert new_state["channels"]["B"]["rate_ml_hr"] == 12  # B actually programmed
    assert new_state["channels"]["A"]["rate_ml_hr"] == 0   # A untouched


def test_alaris_alarm_inject_silence_clear():
    eng = _setup("t_alaris_alarm", "stn1",
                  device_kind="pump_iv", device_model="alaris")
    eng.handle(type="alarm.injected", surface="instructor",
               payload={"tone": "occlusion_downstream"})
    assert any(a["tone"] == "occlusion_downstream"
               for a in eng.fold()["active_alarms"])
    eng.handle(type="alarm.silenced", surface="device",
               payload={"tone": "occlusion_downstream"})
    eng.handle(type="alarm.cleared", surface="device",
               payload={"tone": "occlusion_downstream"})
    assert eng.fold()["active_alarms"] == []


# ── Kangaroo OMNI ───────────────────────────────────────────────────────

def test_kangaroo_omni_state_color_screen_on_complete():
    eng = _setup("t_kangaroo_complete", "stn1",
                  device_kind="pump_enteral", device_model="kangaroo_omni")
    eng.handle(type="feed.power",   surface="device", payload={"state": "on"})
    eng.handle(type="feed.program", surface="device", payload={
        "mode": "continuous", "rate_ml_hr": 500, "volume_ml": 250})
    eng.handle(type="feed.start",   surface="device", payload={})
    eng._last_tick = time.time() - 1800
    state = eng.run_tick(now=time.time())
    assert state["fed_ml"] == 250
    assert state["completed"] is True
    assert state["screen"] == "feed_complete"
    # Screen colour comes from the spec map
    assert eng.spec["screen_color_by_state"][state["screen"]] == "#3DA35D"
    # Auto alarm fired
    assert any(a["tone"] == "feed_complete" for a in state["active_alarms"])


# ── Pyxis cabinet ───────────────────────────────────────────────────────

def test_pyxis_full_workflow_login_to_remove_with_witness():
    eng = _setup("t_pyxis_remove", "stn1",
                  device_kind="cabinet", device_model="pyxis")
    eng.handle(type="auth.login", surface="device",
               payload={"user": "J. Rivera, RN", "method": "bioid"})
    eng.handle(type="cabinet.select_patient", surface="device", payload={
        "patient_id": "char_test", "patient_name": "Mr. Test", "mrn": "1"})
    eng.handle(type="cabinet.select_verb", surface="device",
               payload={"verb": "remove"})
    eng.handle(type="cabinet.select_med", surface="device",
               payload={"med_id": "med_morphine_10"})
    # Scan match
    eng.handle(type="cabinet.scan_verify", surface="device", payload={
        "expected_ndc": "11111111101", "scanned_ndc": "11111111101",
        "result": "match"})
    # Remove without witness — should mark witness_pending
    eng.handle(type="cabinet.remove", surface="device", payload={
        "patient_id": "char_test", "med_id": "med_morphine_10", "qty": 1})
    s = eng.fold()
    assert s["witness_pending"] is True
    assert s["screen"] == "witness"
    # Inventory decremented
    assert s["medications"]["med_morphine_10"]["count"] == 11


def test_pyxis_scan_mismatch_emits_alert():
    eng = _setup("t_pyxis_scan", "stn1",
                  device_kind="cabinet", device_model="pyxis")
    eng.handle(type="auth.login", surface="device",
               payload={"user": "X", "method": "password"})
    eng.handle(type="cabinet.select_med", surface="device",
               payload={"med_id": "med_morphine_10"})
    eng.handle(type="cabinet.scan_verify", surface="device", payload={
        "expected_ndc": "11111111101", "scanned_ndc": "WRONG",
        "result": "mismatch"})
    assert "scan_mismatch" in eng.fold()["active_alerts"]


def test_pyxis_refold_matches_in_memory_after_complex_flow():
    eng = _setup("t_pyxis_refold", "stn1",
                  device_kind="cabinet", device_model="pyxis")
    eng.handle(type="auth.login", surface="device",
               payload={"user": "X", "method": "bioid"})
    eng.handle(type="cabinet.select_patient", surface="device", payload={
        "patient_id": "char_a", "patient_name": "A", "mrn": "1"})
    eng.handle(type="cabinet.select_verb", surface="device",
               payload={"verb": "waste"})
    eng.handle(type="cabinet.select_med", surface="device",
               payload={"med_id": "med_lorazepam_2"})
    eng.handle(type="cabinet.waste", surface="device", payload={
        "med_id": "med_lorazepam_2", "amount": "1 mg",
        "witness_user": "K. Lee, RN", "reason": "spilled"})
    eng.handle(type="auth.logout", surface="device", payload={})
    in_mem = eng.fold()
    fresh  = make_engine(session_id="t_pyxis_refold",
                          station_id=eng.__test_station_id,
                          device_kind="cabinet", device_model="pyxis").fold()
    assert json.dumps(in_mem, sort_keys=True, default=str) == \
           json.dumps(fresh,  sort_keys=True, default=str)


# ── Character-id stamping ───────────────────────────────────────────────

def test_character_id_stamped_into_event_payloads_at_write_time():
    eng = _setup("t_stamp", "stn1",
                  device_kind="pump_iv", device_model="alaris")
    stn = eng.__test_station_id
    # First event under char_test
    eng.handle(type="pump.power", surface="device", payload={"state": "on"})
    # Reassign to a new character
    ehr_db.record_assignment("t_stamp", stn, character_id="char_after",
                              assigned_by="instructor")
    # Second event under char_after
    eng.handle(type="pump.program", surface="device", payload={
        "channel": "A", "drug_label": "X", "rate_ml_hr": 50, "vtbi_ml": 100,
        "library_used": False, "soft_override": False})
    events = ehr_db.device_events(station_id=stn)
    by_type = {e["type"]: e["payload"].get("character_id") for e in events}
    assert by_type["pump.power"]    == "char_test"
    assert by_type["pump.program"]  == "char_after"
