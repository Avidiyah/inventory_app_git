"""Pure tests for the list-size ceiling policy (no database).

`domain.list_limits` is deliberately I/O-free so the ceiling, the `+1`
fetch, and the truncation boundary can be pinned exactly. The boundary is
the part worth pinning: off by one there means either a complete result
reported as truncated (a false alarm in the logs) or a truncated one
reported as complete (silently wrong data, which is the failure this
whole item exists to make visible).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app.domain.list_limits import (
    MAX_LIST_ROWS,
    cap,
    fetch_limit,
    was_truncated,
)


def test_the_ceiling_is_five_thousand():
    assert MAX_LIST_ROWS == 5000


def test_the_fetch_asks_for_one_more_than_the_ceiling():
    # The extra row is what makes truncation detectable without a second
    # COUNT(*). Same trick as routers/_uploads.py::read_capped.
    assert fetch_limit() == MAX_LIST_ROWS + 1


# --------------------------------------------------------------------------
# The truncation boundary
# --------------------------------------------------------------------------

@pytest.mark.parametrize("count", [0, 1, MAX_LIST_ROWS - 1])
def test_below_the_ceiling_is_not_truncation(count):
    assert not was_truncated(count)


def test_exactly_the_ceiling_is_not_truncation():
    # A complete result that happens to land on the boundary. Reporting
    # this would cry wolf in the logs.
    assert not was_truncated(MAX_LIST_ROWS)


def test_one_past_the_ceiling_is_truncation():
    # The only signal that more rows existed.
    assert was_truncated(MAX_LIST_ROWS + 1)


# --------------------------------------------------------------------------
# cap
# --------------------------------------------------------------------------

def test_cap_is_a_no_op_below_the_ceiling():
    rows = list(range(10))
    assert cap(rows) == rows


def test_cap_trims_to_the_ceiling():
    rows = list(range(MAX_LIST_ROWS + 25))
    trimmed = cap(rows)
    assert len(trimmed) == MAX_LIST_ROWS
    # Keeps the head, so the caller's ordering survives.
    assert trimmed == rows[:MAX_LIST_ROWS]


def test_cap_returns_a_list_rather_than_the_input_sequence():
    # Services hand this straight back to Pydantic; returning a list
    # keeps the return type stable whatever the query returned.
    rows = (1, 2, 3)
    assert cap(rows) == [1, 2, 3]


def test_cap_handles_an_empty_result():
    assert cap([]) == []
