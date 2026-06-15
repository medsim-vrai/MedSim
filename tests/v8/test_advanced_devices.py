"""FR-012 D1 — advanced clinical devices scaffold.

The three new device kinds (telemetry monitor, vent monitor, ventilator) are
registered, discoverable by the picker, load their spec/skin, build an engine,
and carry the right alarm catalogues + severities. Live physiology + waveforms +
fault injection land in D2-D6."""
from __future__ import annotations

import pytest

from portal import alarms as room_alarms
from portal.devices import registry
from portal.devices.engine import alarms as alarms_lib
from portal.devices.engine.state_machine import make_engine

KIND_MODEL = [
    ("telemetry_monitor", "generic_tele"),
    ("vent_monitor", "generic_vent_display"),
    ("ventilator", "generic_vent"),
]


def test_kinds_registered():
    for kind, _ in KIND_MODEL:
        assert kind in registry.KIND_DIRS


@pytest.mark.parametrize("kind,model", KIND_MODEL)
def test_picker_discovers_exactly_the_model(kind, model):
    # The "Add device" dropdown calls available_models(kind); each new kind
    # must surface its one generic model (and not bleed across kinds).
    assert registry.available_models(kind) == [model]


@pytest.mark.parametrize("kind,model", KIND_MODEL)
def test_spec_and_skin_load(kind, model):
    spec = registry.load_spec(kind, model)
    assert spec["device_kind"] == kind
    assert spec.get("category") == "advanced"
    assert registry.load_skin(kind, model).strip().startswith("<svg")


@pytest.mark.parametrize("kind,model", KIND_MODEL)
def test_engine_builds_and_folds(kind, model):
    eng = make_engine(session_id="sess1", station_id="st1",
                      device_kind=kind, device_model=model)
    state = eng.initial_state()
    assert "active_alarms" in state and "screen" in state


def test_engine_folds_an_injected_alarm():
    eng = make_engine(session_id="s", station_id="st",
                      device_kind="telemetry_monitor", device_model="generic_tele")
    state = eng.apply(eng.initial_state(),
                      {"type": "alarm.injected", "ts": 1.0,
                       "surface": "instructor", "payload": {"tone": "asystole"}})
    assert any(a["tone"] == "asystole" for a in state["active_alarms"])


def test_ventilator_settings_round_trip():
    eng = make_engine(session_id="s", station_id="st",
                      device_kind="ventilator", device_model="generic_vent")
    state = eng.apply(eng.initial_state(),
                      {"type": "vent.set", "ts": 1.0, "surface": "device",
                       "payload": {"fio2": 0.6, "peep": 8.0}})
    assert state["settings"]["fio2"] == 0.6 and state["settings"]["peep"] == 8.0


def test_alarm_catalogs_and_audio_resolve():
    mon = alarms_lib.catalog_for("telemetry_monitor")
    vent = alarms_lib.catalog_for("ventilator")
    assert "asystole" in mon and "high_pressure" in vent
    # bootstrap builds {tone: audio_url(...)} — must not raise + must be a wav.
    for tone in mon:
        assert alarms_lib.audio_url("telemetry_monitor", tone).endswith(".wav")
    assert alarms_lib.catalog_for("vent_monitor") == vent  # shared catalogue


def test_room_bus_severity_for_new_tones():
    assert room_alarms._classify("asystole") == "danger"
    assert room_alarms._classify("vfib") == "danger"
    assert room_alarms._classify("high_pressure") == "critical"
    assert room_alarms._classify("auto_peep") == "warning"
    assert room_alarms._classify("leads_off") == "info"
