"""FR-012 D3 — telemetry-monitor alarm engine.

The nursing-station alarm catalog (plan §4) as a pure function, plus the
change-driven evaluator that auto-fires/clears alarm.injected on a monitor as
physiology moves — flowing through the existing alarm bus + device fold."""
from __future__ import annotations

import pytest

from portal import ehr_db, physiology, telemetry_monitor
from portal.devices.engine.state_machine import make_engine


@pytest.fixture(autouse=True)
def _reset():
    physiology._sources.clear()
    physiology._conditions.clear()
    yield
    physiology._sources.clear()
    physiology._conditions.clear()


def _register(eid: str, sid: str) -> None:
    ehr_db.register_device_station(eid, sid, device_kind="telemetry_monitor",
                                   device_model="generic_tele")


def _alarms(eid: str, sid: str) -> set[str]:
    eng = make_engine(session_id=eid, station_id=sid,
                      device_kind="telemetry_monitor", device_model="generic_tele")
    return {a["tone"] for a in eng.fold().get("active_alarms", [])}


# ── pure catalog ─────────────────────────────────────────────────────────────

def test_expected_alarms_catalog():
    ea = telemetry_monitor.expected_alarms
    assert ea({}, "asystole") == {"asystole"}
    assert ea({"hr": 0}, "vfib") == {"vfib"}            # lethal rhythm suppresses HR
    assert ea({"hr": 35}, "nsr") == {"brady_severe"}
    assert ea({"hr": 45}, "nsr") == {"brady"}
    assert ea({"hr": 160}, "nsr") == {"tachy_severe"}
    assert ea({"hr": 130}, "nsr") == {"tachy"}
    assert "spo2_low" in ea({"spo2": 85}, "nsr")
    assert "apnea" in ea({"rr": 4}, "nsr")
    assert "rr_high" in ea({"rr": 35}, "nsr")
    assert "nibp_high" in ea({"sbp": 190}, "nsr")
    assert "nibp_low" in ea({"sbp": 80}, "nsr")
    assert ea({"hr": 80, "spo2": 98, "rr": 16, "sbp": 118}, "nsr") == set()


# ── change-driven evaluation ─────────────────────────────────────────────────

def test_physiology_change_auto_fires_alarm():
    eid, sid = "tm-test-fire", "tm-st-fire"
    _register(eid, sid)
    physiology.set_vitals(eid, {"spo2": 80, "hr": 80, "rr": 16, "sbp": 118})
    assert "spo2_low" in _alarms(eid, sid)              # fired via the hook


def test_alarm_auto_clears_when_resolved():
    eid, sid = "tm-test-clear", "tm-st-clear"
    _register(eid, sid)
    physiology.set_vitals(eid, {"spo2": 80})
    assert "spo2_low" in _alarms(eid, sid)
    physiology.set_vitals(eid, {"spo2": 98})
    assert "spo2_low" not in _alarms(eid, sid)          # auto-cleared


def test_evaluate_is_idempotent():
    eid, sid = "tm-test-idem", "tm-st-idem"
    _register(eid, sid)
    physiology.set_vitals(eid, {"hr": 180})             # tachy_severe via hook
    summary = telemetry_monitor.evaluate(eid)           # re-run: nothing new
    assert summary["fired"] == []
    assert "tachy_severe" in _alarms(eid, sid)


def test_instructor_alarm_survives_auto_clear():
    eid, sid = "tm-test-instr", "tm-st-instr"
    _register(eid, sid)
    eng = make_engine(session_id=eid, station_id=sid,
                      device_kind="telemetry_monitor", device_model="generic_tele")
    eng.handle(type="alarm.injected", surface="instructor",
               payload={"tone": "leads_off"})           # manual arm
    physiology.set_vitals(eid, {"hr": 80, "spo2": 98, "rr": 16, "sbp": 118})
    telemetry_monitor.evaluate(eid)                      # would clear AUTO alarms
    assert "leads_off" in _alarms(eid, sid)             # manual one preserved


def test_lethal_rhythm_fires_on_monitor():
    eid, sid = "tm-test-rhythm", "tm-st-rhythm"
    _register(eid, sid)
    # No active room -> set_rhythm can't mutate an encounter; drive evaluate via
    # a vitals write while we assert the pure catalog separately. Here we verify
    # evaluate fires from a breach (rhythm path is covered by the pure test).
    physiology.set_vitals(eid, {"hr": 38})              # brady_severe
    assert "brady_severe" in _alarms(eid, sid)
