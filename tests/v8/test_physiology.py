"""FR-012 D2 — the physiology spine.

read/write seam over the vitals event log, bounded by physiologic ranges +
condition ceilings, gated by a single-writer source-authority lease. This is
where the advanced devices (D3-D6) and, later, PhysioBridge plug in."""
from __future__ import annotations

import pytest

from portal import physiology


@pytest.fixture(autouse=True)
def _reset():
    physiology._sources.clear()
    physiology._conditions.clear()
    yield
    physiology._sources.clear()
    physiology._conditions.clear()


def test_read_returns_full_snapshot_with_defaults():
    snap = physiology.read("phys-test-defaults")
    v = snap["vitals"]
    for metric in ("hr", "sbp", "dbp", "spo2", "rr", "temp_f", "etco2", "map"):
        assert metric in v
    assert v["map"] == 89                     # derived from default 118/74
    assert snap["source"] == "virtual"        # default authority
    assert snap["condition"] == "normal"


def test_set_vitals_round_trips_through_event_log():
    physiology.set_vitals("phys-test-set", {"hr": 60, "spo2": 95})
    v = physiology.read("phys-test-set")["vitals"]
    assert v["hr"] == 60 and v["spo2"] == 95


def test_apply_delta_adds_to_current():
    physiology.set_vitals("phys-test-delta", {"hr": 80})
    physiology.apply_delta("phys-test-delta", {"hr": 15})
    assert physiology.read("phys-test-delta")["vitals"]["hr"] == 95


def test_delta_bounded_to_physiologic_range():
    physiology.set_vitals("phys-test-bound", {"spo2": 98})
    physiology.apply_delta("phys-test-bound", {"spo2": 50})   # would be 148
    assert physiology.read("phys-test-bound")["vitals"]["spo2"] == 100


def test_condition_ceiling_caps_spo2():
    physiology.set_condition("phys-test-ceiling", "ards")     # ceiling 99
    physiology.set_vitals("phys-test-ceiling", {"spo2": 100})
    assert physiology.read("phys-test-ceiling")["vitals"]["spo2"] == 99


def test_authority_lease_precedence_and_failover():
    eid = "phys-test-auth"
    assert physiology.authority(eid) == "virtual"            # floor
    physiology.register_source(eid, "physiobridge")
    assert physiology.authority(eid) == "physiobridge"       # higher precedence
    physiology.register_source(eid, "manikin")
    assert physiology.authority(eid) == "manikin"            # highest
    physiology.set_source_health(eid, "manikin", False)      # link loss
    assert physiology.authority(eid) == "physiobridge"       # fails over
    physiology.release_source(eid, "physiobridge")
    assert physiology.authority(eid) == "virtual"            # back to floor


def test_non_authority_writes_are_ignored():
    eid = "phys-test-nonauth"
    physiology.register_source(eid, "manikin")               # manikin holds lease
    physiology.set_vitals(eid, {"hr": 80}, source="manikin")
    # virtual is NOT the authority now -> its write must be a no-op.
    physiology.apply_delta(eid, {"hr": 40}, source="virtual")
    assert physiology.read(eid)["vitals"]["hr"] == 80


def test_set_rhythm_validates():
    with pytest.raises(ValueError):
        physiology.set_rhythm("phys-test-rhythm", "not_a_real_rhythm")
    assert physiology.set_rhythm("phys-test-rhythm", "nsr") == "nsr"


def test_set_condition_validates():
    with pytest.raises(ValueError):
        physiology.set_condition("phys-test-cond", "made_up")
    assert physiology.set_condition("phys-test-cond", "copd") == "copd"


def test_snapshot_restore_round_trip():
    physiology.set_condition("phys-test-snap", "sepsis")
    physiology.register_source("phys-test-snap", "physiobridge")
    blob = physiology.snapshot()
    physiology._sources.clear()
    physiology._conditions.clear()
    physiology.restore(blob)
    assert physiology.condition_for("phys-test-snap") == "sepsis"
    assert physiology.authority("phys-test-snap") == "physiobridge"
