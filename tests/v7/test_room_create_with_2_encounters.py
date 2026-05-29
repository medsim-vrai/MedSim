"""M2 acceptance — a ControlRoom holds N independent Encounters.

Each encounter has a distinct join_code, distinct id, and is reachable
via room.encounters[id]. This is the foundational data-shape test for
multi-patient mode.
"""
from __future__ import annotations

from portal import control_room
from portal.control_session import ControlSession


def _make_encounter(name: str) -> ControlSession:
    return ControlSession(
        id=f"E-{name}",
        join_code=f"JC-{name}",
        scenario_name=name,
        api_key="",
    )


def test_room_create_with_2_encounters() -> None:
    control_room._reset_for_tests()
    room = control_room.create_room(label="Morning Shift")

    enc_a = room.add_encounter(_make_encounter("alpha"))
    enc_b = room.add_encounter(_make_encounter("bravo"))

    assert len(room.encounters) == 2
    assert enc_a.id != enc_b.id
    assert enc_a.join_code != enc_b.join_code
    # Reverse lookup by id
    assert room.encounters[enc_a.id] is enc_a
    assert room.encounters[enc_b.id] is enc_b
    # Both encounters know their owning room
    assert enc_a.room_id == room.room_id
    assert enc_b.room_id == room.room_id
    # Room code is distinct from any encounter join code
    assert room.room_code not in (enc_a.join_code, enc_b.join_code)
