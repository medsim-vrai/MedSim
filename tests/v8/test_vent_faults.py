"""FR-012 D6 — ventilator fault injection.

Each fault perturbs the effective vent state (so the airway waveforms + numerics
show the signature and the equipment alarm fires) AND degrades global patient
physiology; clearing it lets the coupling recover the patient."""
from __future__ import annotations

import pytest

from portal import (control_room, control_session, ehr_db, physiology,
                    vent_faults, vent_state)
from portal.devices.engine.state_machine import make_engine


@pytest.fixture(autouse=True)
def _reset():
    def _clear():
        for d in (vent_state._settings, vent_state._faults, vent_state._fault_overrides,
                  vent_state._fault_penalty, vent_faults._armed,
                  physiology._sources, physiology._conditions):
            d.clear()
    _clear()
    yield
    if control_session.get_active() is not None:
        control_room.end_active_room()
    _clear()


def _vent_session() -> str:
    sess = control_session.create_session(scenario_name="Vent Fault", api_key="k",
                                          selected_personas=["P-014"])
    ehr_db.register_device_station(sess.id, "vm1", device_kind="vent_monitor",
                                   device_model="generic_vent_display")
    return sess.id


def _alarms(eid: str) -> set[str]:
    eng = make_engine(session_id=eid, station_id="vm1", device_kind="vent_monitor",
                      device_model="generic_vent_display")
    return {a["tone"] for a in eng.fold().get("active_alarms", [])}


def test_catalog_covers_the_common_faults():
    ids = {f["id"] for f in vent_faults.catalog()}
    assert {"air_leak", "circuit_disconnect", "et_obstruction", "secretions",
            "bronchospasm", "patient_bucking", "compliance_drop", "auto_peep",
            "apnea", "o2_supply"} <= ids


def test_air_leak_low_volume_alarms_desat_and_set_vs_measured_diverges():
    eid = _vent_session()
    vent_faults.arm(eid, "air_leak")
    a = _alarms(eid)
    assert "low_tidal_volume" in a and "low_minute_volume" in a
    assert physiology.read(eid)["vitals"]["spo2"] <= 92          # patient desats
    cv = vent_state.controls_view(eid)
    assert cv["settings"]["tidal_volume_ml"] == 450             # set value unchanged
    assert cv["numerics"]["vt_exhaled_ml"] < 300                # measured (exhaled) collapses


def test_obstruction_fires_high_pressure():
    eid = _vent_session()
    vent_faults.arm(eid, "et_obstruction")
    assert "high_pressure" in _alarms(eid)
    assert vent_state.numerics(eid)["ppeak"] > 35


def test_apnea_fires_apnea():
    eid = _vent_session()
    vent_faults.arm(eid, "apnea")
    assert "apnea" in _alarms(eid)


def test_bucking_raises_hr_then_clear_restores():
    eid = _vent_session()
    physiology.set_vitals(eid, {"hr": 80})
    vent_faults.arm(eid, "patient_bucking")
    assert physiology.read(eid)["vitals"]["hr"] >= 95           # +18 from the cough/agitation
    assert "high_pressure" in _alarms(eid)
    vent_faults.clear(eid, "patient_bucking")
    assert physiology.read(eid)["vitals"]["hr"] == 80           # HR walked back
    assert "high_pressure" not in _alarms(eid)                 # alarm cleared


def test_clear_lets_the_coupling_recover_spo2():
    eid = _vent_session()
    vent_faults.arm(eid, "air_leak")
    desat = physiology.read(eid)["vitals"]["spo2"]
    vent_faults.clear(eid, "air_leak")
    assert physiology.read(eid)["vitals"]["spo2"] > desat       # recovered
    assert vent_faults.active(eid) == []


def test_snapshot_restore():
    eid = _vent_session()
    vent_faults.arm(eid, "secretions")
    blob = vent_faults.snapshot()
    vent_faults._armed.clear()
    vent_faults.restore(blob)
    assert any(f["id"] == "secretions" for f in vent_faults.active(eid))
