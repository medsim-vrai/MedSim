"""FR-012 D4 — ventilator model + per-encounter vent state + vent alarms.

The lumped R-C breath model (ported from PhysioBridge) → bedside numerics, and
the change-driven vent-alarm evaluator that auto-fires on a vent_monitor /
ventilator when the numerics breach limits."""
from __future__ import annotations

import pytest

from portal import ehr_db, vent_model, vent_state
from portal.devices.engine.state_machine import make_engine


@pytest.fixture(autouse=True)
def _reset():
    vent_state._settings.clear()
    vent_state._faults.clear()
    yield
    vent_state._settings.clear()
    vent_state._faults.clear()


# ── breath model ─────────────────────────────────────────────────────────────

def test_default_numerics():
    num = vent_model.ventilator_numerics(vent_model.VentState())
    assert num["pplateau"] == 14.0                 # 5 + 450/50
    assert 15 <= num["ppeak"] <= 20                # peep + flow*R + Vt/C
    assert num["minute_vent_l"] == 6.3             # 450 * 14 / 1000
    assert num["mode"] == "VC"


def test_chatburn_mode_maps_to_breath_model():
    assert vent_model.model_mode("VC-CMV") == "VC"
    assert vent_model.model_mode("SIMV") == "VC"
    assert vent_model.model_mode("PC-CMV") == "PC"
    assert vent_model.model_mode("PRVC") == "PC"


def test_synthesize_has_inspiration_and_expiration():
    wf = vent_model.synthesize(vent_model.VentState(), breaths=2)
    assert wf.pressure and wf.flow and wf.volume
    assert max(wf.flow) > 0 and min(wf.flow) < 0     # insp +, exp -
    assert max(wf.pressure) == pytest.approx(
        vent_model.ventilator_numerics(vent_model.VentState())["ppeak"], abs=1.0)


def test_leak_lowers_exhaled_volume():
    s = vent_model.state_from_settings(vent_state.DEFAULT_SETTINGS,
                                       {"leak_fraction": 0.5})
    num = vent_model.ventilator_numerics(s)
    assert num["vt_exhaled_ml"] == 225               # 450 * (1 - 0.5)


# ── vent alarms (pure) ───────────────────────────────────────────────────────

def _alarms_for(settings=None, faults=None):
    s = vent_model.state_from_settings({**vent_state.DEFAULT_SETTINGS, **(settings or {})},
                                       faults or {})
    return vent_state.expected_alarms(vent_model.ventilator_numerics(s), s)


def test_default_has_no_alarms():
    assert _alarms_for() == set()


def test_low_compliance_raises_high_pressure():
    assert "high_pressure" in _alarms_for({"compliance_ml_cmh2o": 15})


def test_big_leak_raises_low_vt_and_mv():
    a = _alarms_for(faults={"leak_fraction": 0.6})
    assert "low_tidal_volume" in a and "low_minute_volume" in a


def test_short_expiratory_time_raises_auto_peep():
    assert "auto_peep" in _alarms_for({"rr": 36})


# ── change-driven evaluation on a device ─────────────────────────────────────

def test_evaluate_fires_on_vent_monitor():
    eid, sid = "vent-test-fire", "vent-st-fire"
    ehr_db.register_device_station(eid, sid, device_kind="vent_monitor",
                                   device_model="generic_vent_display")
    vent_state.set_settings(eid, {"compliance_ml_cmh2o": 15})   # stiff lung -> high P
    vent_state.evaluate(eid)
    eng = make_engine(session_id=eid, station_id=sid,
                      device_kind="vent_monitor", device_model="generic_vent_display")
    tones = {a["tone"] for a in eng.fold().get("active_alarms", [])}
    assert "high_pressure" in tones
    # Resolve the stiffness -> auto-clears.
    vent_state.set_settings(eid, {"compliance_ml_cmh2o": 50})
    vent_state.evaluate(eid)
    tones = {a["tone"] for a in eng.fold().get("active_alarms", [])}
    assert "high_pressure" not in tones


def test_snapshot_restore_round_trip():
    eid = "vent-test-snap"
    vent_state.set_settings(eid, {"peep": 8.0})
    vent_state.set_faults(eid, {"secretions": True})
    blob = vent_state.snapshot()
    vent_state._settings.clear(); vent_state._faults.clear()
    vent_state.restore(blob)
    assert vent_state.settings_for(eid)["peep"] == 8.0
    assert vent_state.faults_for(eid)["secretions"] is True
