"""Unit tests for `app.domain.mass_staging` -- the pure allocation and
lifecycle rules for mass-staging. No DB, no HTTP, consistent with the rest
of the domain suite.

- allocate_load: fill rooms in sort_order, overflow onto the last room,
  under-load stops early.
- allocate_return: reverse-fill, capped at net loaded.
- validate_transition: planning -> loading -> completed only.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decimal import Decimal

import pytest

from app.domain.errors import (
    InvalidStageTransitionError,
    ReturnExceedsLoadedError,
)
from app.domain.mass_staging import (
    Allocation,
    RoomLoaded,
    RoomPlan,
    STATUS_COMPLETED,
    STATUS_LOADING,
    STATUS_PLANNING,
    allocate_load,
    allocate_return,
    can_edit_plan,
    can_load,
    validate_transition,
)


def D(x):
    return Decimal(str(x))


def as_map(allocs):
    """{key: quantity} for order-independent value checks (order is asserted
    separately where it matters)."""
    return {a.key: a.quantity for a in allocs}


# --- allocate_load -------------------------------------------------------

def test_load_single_room_exact():
    assert allocate_load([RoomPlan("a", D(5))], D(5)) == [Allocation("a", D(5))]


def test_load_multi_room_exact_fill():
    rooms = [RoomPlan("a", D(10)), RoomPlan("b", D(5))]
    assert as_map(allocate_load(rooms, D(15))) == {"a": D(10), "b": D(5)}


def test_load_overflow_goes_to_last_room():
    rooms = [RoomPlan("a", D(10)), RoomPlan("b", D(5))]
    result = allocate_load(rooms, D(16))
    # Each room filled to plan; the +1 overflow lands on the last room.
    assert as_map(result) == {"a": D(10), "b": D(6)}
    # One allocation per room, emitted in sort order.
    assert [a.key for a in result] == ["a", "b"]


def test_load_under_load_stops_early():
    rooms = [RoomPlan("a", D(10)), RoomPlan("b", D(5))]
    result = allocate_load(rooms, D(8))
    assert as_map(result) == {"a": D(8)}  # b gets nothing and is omitted
    assert len(result) == 1


def test_load_incremental_equals_combined():
    # First load of 8 fills room a partially.
    first = allocate_load([RoomPlan("a", D(10)), RoomPlan("b", D(5))], D(8))
    assert as_map(first) == {"a": D(8)}
    # Second load of 8, now with a already at 8: a takes 2, b takes 5,
    # the +1 overflow lands on b -> a:2, b:6. Per-room totals match a single
    # combined load of 16 (a:10, b:6).
    second = allocate_load(
        [RoomPlan("a", D(10), D(8)), RoomPlan("b", D(5), D(0))], D(8)
    )
    assert as_map(second) == {"a": D(2), "b": D(6)}


def test_load_overflow_when_last_room_already_full():
    # Both rooms already filled to plan; a pure-overflow load lands entirely
    # on the last room.
    rooms = [RoomPlan("a", D(10), D(10)), RoomPlan("b", D(5), D(5))]
    assert as_map(allocate_load(rooms, D(3))) == {"b": D(3)}


def test_load_empty_rooms_raises():
    with pytest.raises(ValueError):
        allocate_load([], D(1))


# --- allocate_return -----------------------------------------------------

def test_return_reverse_fill_basic():
    rooms = [RoomLoaded("a", D(10)), RoomLoaded("b", D(6))]
    # Reverse order: the last room gives back first.
    assert as_map(allocate_return(rooms, D(3))) == {"b": D(3)}


def test_return_spills_to_earlier_rooms():
    rooms = [RoomLoaded("a", D(10)), RoomLoaded("b", D(6))]
    result = allocate_return(rooms, D(9))  # b:6 then a:3
    assert as_map(result) == {"a": D(3), "b": D(6)}
    assert [a.key for a in result] == ["a", "b"]  # output in sort order


def test_return_respects_already_returned():
    rooms = [RoomLoaded("a", D(10), D(10)), RoomLoaded("b", D(6), D(0))]
    # a is fully returned already -> only b's 6 is returnable.
    assert as_map(allocate_return(rooms, D(6))) == {"b": D(6)}
    with pytest.raises(ReturnExceedsLoadedError):
        allocate_return(rooms, D(7))


def test_return_exact_returnable_allowed():
    rooms = [RoomLoaded("a", D(10)), RoomLoaded("b", D(6))]
    assert as_map(allocate_return(rooms, D(16))) == {"a": D(10), "b": D(6)}


def test_return_over_raises_with_attrs():
    with pytest.raises(ReturnExceedsLoadedError) as exc:
        allocate_return([RoomLoaded("a", D(5))], D(8))
    assert exc.value.requested == D(8)
    assert exc.value.returnable == D(5)


# --- validate_transition + predicates ------------------------------------

def test_transition_allowed():
    assert validate_transition(STATUS_PLANNING, STATUS_LOADING) is None
    assert validate_transition(STATUS_LOADING, STATUS_COMPLETED) is None


@pytest.mark.parametrize(
    "current,target",
    [
        (STATUS_PLANNING, STATUS_COMPLETED),  # skips loading
        (STATUS_LOADING, STATUS_PLANNING),    # backward
        (STATUS_COMPLETED, STATUS_LOADING),   # terminal
        (STATUS_COMPLETED, STATUS_PLANNING),  # terminal
        (STATUS_PLANNING, STATUS_PLANNING),   # same-state
        (STATUS_LOADING, STATUS_LOADING),     # same-state
        (STATUS_COMPLETED, STATUS_COMPLETED), # same-state
    ],
)
def test_transition_disallowed(current, target):
    with pytest.raises(InvalidStageTransitionError):
        validate_transition(current, target)


def test_transition_unknown_status_raises():
    with pytest.raises(InvalidStageTransitionError):
        validate_transition("bogus", STATUS_LOADING)
    with pytest.raises(InvalidStageTransitionError):
        validate_transition(STATUS_PLANNING, "bogus")


def test_transition_error_carries_ends():
    with pytest.raises(InvalidStageTransitionError) as exc:
        validate_transition(STATUS_PLANNING, STATUS_COMPLETED)
    assert exc.value.current == STATUS_PLANNING
    assert exc.value.target == STATUS_COMPLETED


def test_can_edit_plan_only_planning():
    assert can_edit_plan(STATUS_PLANNING) is True
    assert can_edit_plan(STATUS_LOADING) is False
    assert can_edit_plan(STATUS_COMPLETED) is False
    assert can_edit_plan("bogus") is False


def test_can_load_only_loading():
    assert can_load(STATUS_LOADING) is True
    assert can_load(STATUS_PLANNING) is False
    assert can_load(STATUS_COMPLETED) is False
    assert can_load("bogus") is False
