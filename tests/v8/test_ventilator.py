"""FR-012 D5 — interactive ventilator: control surface (VC0) + closed-loop
physiology coupling (VC1).

Control changes validate + step-snap against mode-aware ranges, and adjusting
the ventilator moves patient physiology (FiO2/PEEP → SpO2 toward a condition
ceiling; minute ventilation → EtCO2), bounded so a sick lung can't be fully
normalised by the vent alone."""
from __future__ import annotations

import pytest

from portal import physiology, vent_model, vent_state


@pytest.fixture(autouse=True)
def _reset():
    for d in (vent_state._settings, vent_state._faults,
              physiology._sources, physiology._conditions):
        d.clear()
    yield
    for d in (vent_state._settings, vent_state._faults,
              physiology._sources, physiology._conditions):
        d.clear()


# ── VC0 control surface ──────────────────────────────────────────────────────

def test_validate_snaps_and_rejects():
    assert vent_model.validate("fio2", 0.404) == (0.4, None)          # step-snap to 0.01
    v, err = vent_model.validate("peep", 99)
    assert v is None and "out of range" in err
    v, err = vent_model.validate("fio2", "abc")
    assert v is None and "numeric" in err
    assert vent_model.validate("nope", 1)[1].startswith("unknown control")


def test_mode_aware_availability():
    vc = vent_model.controls_for("VC-CMV")
    psv = vent_model.controls_for("PSV")
    assert "tidal_volume_ml" in vc and "psupport" not in vc
    assert "psupport" in psv and "tidal_volume_ml" not in psv
    # a control not available in the mode is rejected
    assert vent_model.validate("tidal_volume_ml", 450, mode="PSV")[1] is not None
    assert vent_model.validate("mode", "PSV") == (None, None)
    assert vent_model.validate("mode", "BOGUS")[1].startswith("unknown mode")


# ── VC1 coupling (pure) ──────────────────────────────────────────────────────

def _targets(condition="normal", **settings):
    s = vent_model.state_from_settings({**vent_state.DEFAULT_SETTINGS, **settings})
    return vent_model.ventilator_targets(s, condition)


def test_fio2_and_peep_raise_spo2_to_condition_ceiling():
    low = _targets("ards", fio2=0.40, peep=5)["spo2"]
    high_fio2 = _targets("ards", fio2=0.80, peep=5)["spo2"]
    recruited = _targets("ards", fio2=0.80, peep=10)["spo2"]
    assert high_fio2 > low                       # more O2 -> better
    assert recruited >= high_fio2                # PEEP toward optimum recruits
    assert recruited <= 99.0                     # never beats the ARDS ceiling
    # a healthy lung sits higher than ARDS at the same settings
    assert _targets("normal", fio2=0.40, peep=5)["spo2"] > low


def test_over_peep_penalises_oxygenation():
    good = _targets("ards", fio2=0.6, peep=10)["spo2"]
    over = _targets("ards", fio2=0.6, peep=22)["spo2"]
    assert over < good
    assert _targets(peep=22)["overdistension"] is True
    assert _targets(fio2=0.8)["hyperoxia"] is True


def test_minute_ventilation_clears_co2():
    low_mv = _targets(rr=8)["etco2"]
    high_mv = _targets(rr=24)["etco2"]
    assert high_mv < low_mv                       # more ventilation -> lower EtCO2


# ── coupling applied through vent_state -> physiology ────────────────────────

def test_apply_control_moves_physiology():
    eid = "vent5-couple"
    physiology.set_condition(eid, "ards")
    vent_state.apply_control(eid, "fio2", 0.40)
    spo2_low = physiology.read(eid)["vitals"]["spo2"]
    vent_state.apply_control(eid, "fio2", 0.80)
    spo2_high = physiology.read(eid)["vitals"]["spo2"]
    assert spo2_high > spo2_low                   # raising FiO2 raised the patient's SpO2
    assert vent_state.settings_for(eid)["fio2"] == 0.80


def test_apply_control_rejects_invalid():
    view, err = vent_state.apply_control("vent5-bad", "peep", 999)
    assert view is None and "out of range" in err


def test_controls_view_shape():
    cv = vent_state.controls_view("vent5-view")
    assert cv["mode"] == "VC-CMV"
    assert "tidal_volume_ml" in cv["available"]
    assert cv["ranges"]["fio2"]["lo"] == 0.21
    assert any(r["label"] == "Ppeak" for r in cv["set_vs_measured"])


def test_maneuvers():
    eid = "vent5-maneuver"
    assert "pplateau" in vent_state.maneuver(eid, "insp_hold")
    assert "auto_peep" in vent_state.maneuver(eid, "exp_hold")
    vent_state.maneuver(eid, "o2_100")
    assert vent_state.settings_for(eid)["fio2"] == 1.0
