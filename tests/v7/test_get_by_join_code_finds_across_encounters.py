"""M2 acceptance — join-code dispatch finds the right encounter.

In v6 there was one ControlSession and one join code. In v7 the active
ControlRoom holds N encounters, each with its own join code. The
v6-compat ``get_by_join_code`` must dispatch to the matching encounter
without bleed between them.
"""
from __future__ import annotations

from portal import control_room, control_session
from portal.control_session import ControlSession


def test_get_by_join_code_finds_right_encounter_among_many() -> None:
    control_room._reset_for_tests()
    room = control_room.create_room(label="Floor")

    enc_a = room.add_encounter(ControlSession(
        id="E-alpha", join_code="ALPHA1",
        scenario_name="A", api_key=""))
    enc_b = room.add_encounter(ControlSession(
        id="E-bravo", join_code="BRAVO2",
        scenario_name="B", api_key=""))
    enc_c = room.add_encounter(ControlSession(
        id="E-charlie", join_code="CHRL34",
        scenario_name="C", api_key=""))

    # Case-insensitive match.
    assert control_session.get_by_join_code("alpha1") is enc_a
    assert control_session.get_by_join_code("BRAVO2") is enc_b
    assert control_session.get_by_join_code("Chrl34") is enc_c

    # Unknown code returns None — not the first encounter, not raise.
    assert control_session.get_by_join_code("UNKNOWN") is None

    # No bleed: each encounter's stations are independent.
    enc_a.add_station("station-1", user_agent="ipad-a")
    enc_b.add_station("station-2", user_agent="ipad-b")
    assert "station-1" in enc_a.stations
    assert "station-1" not in enc_b.stations
    assert "station-2" in enc_b.stations
    assert "station-2" not in enc_a.stations


def test_get_by_join_code_returns_none_when_no_active_room() -> None:
    control_room._reset_for_tests()
    assert control_session.get_by_join_code("ANYTHING") is None
