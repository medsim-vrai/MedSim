"""FR-012 — select a clinical state / waveform and the vitals align.

Monitor: picking an ECG rhythm sets the HR (and BP/SpO2 for arrest rhythms) to
match, carrying to the monitor + nurse station. Ventilator: picking a state sets
the settings + condition + coupled vitals. Per-parameter inject still fine-tunes."""
from __future__ import annotations

import pytest

from portal import control_room, control_session, physiology, vent_state


@pytest.fixture(autouse=True)
def _reset():
    def _clear():
        for d in (physiology._sources, physiology._conditions, vent_state._settings,
                  vent_state._faults, vent_state._fault_overrides, vent_state._fault_penalty):
            d.clear()
    _clear()
    yield
    if control_session.get_active() is not None:
        control_room.end_active_room()
    _clear()


def _session() -> str:
    return control_session.create_session(scenario_name="State", api_key="k",
                                          selected_personas=["P-014"]).id


# ── rhythm selection aligns the vitals ───────────────────────────────────────

def test_select_sinus_tachy_sets_hr():
    eid = _session()
    physiology.apply_rhythm(eid, "sinus_tachy")
    snap = physiology.read(eid)
    assert snap["rhythm"] == "sinus_tachy"
    assert snap["vitals"]["hr"] == 120          # catalog default_rate


def test_select_sinus_brady_sets_hr():
    eid = _session()
    physiology.apply_rhythm(eid, "sinus_brady")
    assert physiology.read(eid)["vitals"]["hr"] == 48


def test_arrest_rhythm_crashes_perfusion():
    eid = _session()
    physiology.apply_rhythm(eid, "vfib")
    v = physiology.read(eid)["vitals"]
    assert physiology.read(eid)["rhythm"] == "vfib"
    assert v["hr"] == 0 and v["sbp"] == 0 and v["spo2"] <= 60


def test_vt_is_hypotensive_but_perfusing():
    eid = _session()
    physiology.apply_rhythm(eid, "vtach_mono")
    v = physiology.read(eid)["vitals"]
    assert v["hr"] == 180 and 0 < v["sbp"] < 90


def test_pea_organized_rhythm_no_pulse():
    eid = _session()
    physiology.apply_rhythm(eid, "pea")
    v = physiology.read(eid)["vitals"]
    assert v["hr"] == 50 and v["sbp"] == 0      # organized rate, no pulse


# ── ventilator state presets align settings + condition + vitals ─────────────

def test_state_presets_listed():
    ids = {p["id"] for p in vent_state.state_presets()}
    assert {"stable", "ards", "copd", "pneumonia", "weaning"} <= ids


def test_apply_ards_state_aligns_everything():
    eid = _session()
    view, err = vent_state.apply_state(eid, "ards")
    assert err is None
    s = vent_state.settings_for(eid)
    assert s["mode"] == "PC-CMV" and s["peep"] == 12 and s["fio2"] == 0.70
    assert physiology.condition_for(eid) == "ards"
    ards_spo2 = physiology.read(eid)["vitals"]["spo2"]
    vent_state.apply_state(eid, "stable")       # back to normal lungs
    assert physiology.read(eid)["vitals"]["spo2"] > ards_spo2


def test_apply_unknown_state_errors():
    view, err = vent_state.apply_state("x", "not_a_state")
    assert view is None and "unknown" in err
