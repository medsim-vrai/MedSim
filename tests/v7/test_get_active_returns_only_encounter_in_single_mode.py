"""M2 acceptance — v6-compat ``get_active()`` semantics preserved.

The wizard's single-patient finalize path calls
``control_session.create_session(...)``. In v7 that quietly creates a
ControlRoom-of-1 and adds one Encounter. ``get_active()`` then returns
that Encounter — same shape, same identity, the same code path v6 used.

If a second Encounter joins the room (multi-patient mode),
``get_active()`` raises so v6 callers fail loud rather than silently
picking one.
"""
from __future__ import annotations

import pytest

from portal import control_room, control_session


def test_create_session_makes_room_of_one_and_get_active_returns_it() -> None:
    control_room._reset_for_tests()
    sess = control_session.create_session("Test Scenario", api_key="x")

    room = control_room.get_active_room()
    assert room is not None
    assert len(room.encounters) == 1
    assert sess.id in room.encounters

    # v6-compat helper returns the single encounter.
    assert control_session.get_active() is sess
    assert control_room.get_active() is sess
    # Encounter knows its owning room.
    assert sess.room_id == room.room_id


def test_get_active_returns_none_when_room_holds_multiple_encounters() -> None:
    """Phase 7 1.6 — `get_active` now returns None (not raises) when
    the room holds multiple encounters. v6 single-patient routes
    handle None gracefully (they render "no active session" instead
    of crashing the page). Use `get_active_strict` for the loud
    check."""
    control_room._reset_for_tests()
    room = control_room.create_room(label="Multi")
    from portal.control_session import ControlSession
    room.add_encounter(ControlSession(id="E1", join_code="J1",
                                       scenario_name="a", api_key=""))
    room.add_encounter(ControlSession(id="E2", join_code="J2",
                                       scenario_name="b", api_key=""))
    # Soft helper: None.
    assert control_room.get_active() is None
    assert control_session.get_active() is None
    # Strict helper still raises (kept for test code + operator-debug).
    with pytest.raises(RuntimeError):
        control_room.get_active_strict()


def test_end_active_clears_singleton() -> None:
    control_room._reset_for_tests()
    control_session.create_session("S", api_key="x")
    assert control_room.get_active_room() is not None
    control_session.end_active()
    assert control_room.get_active_room() is None
    assert control_session.get_active() is None
