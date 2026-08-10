"""Tests for the shared list-cap helper (no database).

`services._list_cap` is the entire early-warning system for X3: if
`event=list.truncated` never appears, the ceiling never bit. These tests
pin both halves of that -- silence below the ceiling, exactly one line
above it -- because a false alarm trains people to ignore the signal and
a missed one defeats the purpose of having it.

Log assertions follow `test_logging.py`'s `caplog` pattern.
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app.domain.list_limits import MAX_LIST_ROWS
from app.services._list_cap import capped, report_if_truncated

TRUNCATION_EVENT = "list.truncated"


def _truncation_records(caplog):
    return [r for r in caplog.records if r.getMessage() == TRUNCATION_EVENT]


# --------------------------------------------------------------------------
# Below the ceiling: pass through, say nothing
# --------------------------------------------------------------------------

def test_a_normal_result_is_returned_unchanged(caplog):
    caplog.set_level(logging.DEBUG)
    rows = list(range(250))

    assert capped(rows, what="items") == rows
    assert _truncation_records(caplog) == []


def test_an_empty_result_is_silent(caplog):
    caplog.set_level(logging.DEBUG)

    assert capped([], what="items") == []
    assert _truncation_records(caplog) == []


def test_a_result_exactly_at_the_ceiling_is_silent(caplog):
    # This is a complete list that happens to sit on the boundary. Logging
    # it would be a false alarm.
    caplog.set_level(logging.DEBUG)
    rows = list(range(MAX_LIST_ROWS))

    assert len(capped(rows, what="items")) == MAX_LIST_ROWS
    assert _truncation_records(caplog) == []


# --------------------------------------------------------------------------
# Above the ceiling: trim, and say so exactly once
# --------------------------------------------------------------------------

def test_an_oversized_result_is_trimmed(caplog):
    caplog.set_level(logging.WARNING)
    rows = list(range(MAX_LIST_ROWS + 1))

    trimmed = capped(rows, what="items")

    assert len(trimmed) == MAX_LIST_ROWS
    assert trimmed == rows[:MAX_LIST_ROWS]


def test_an_oversized_result_logs_exactly_one_line(caplog):
    caplog.set_level(logging.WARNING)

    capped(list(range(MAX_LIST_ROWS + 500)), what="items")

    records = _truncation_records(caplog)
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING


def test_the_log_line_names_the_list_and_the_cap(caplog):
    # `list=` is the field someone will filter Render's logs on, and it is
    # what tells them which endpoint to paginate rather than all six.
    caplog.set_level(logging.WARNING)

    capped(list(range(MAX_LIST_ROWS + 1)), what="user_requests")

    fields = _truncation_records(caplog)[0].fields
    assert fields["list"] == "user_requests"
    assert fields["cap"] == MAX_LIST_ROWS


# --------------------------------------------------------------------------
# report_if_truncated -- the half work_orders uses on its own
# --------------------------------------------------------------------------

def test_report_if_truncated_is_silent_at_or_below_the_ceiling(caplog):
    caplog.set_level(logging.DEBUG)

    report_if_truncated(0, what="work_orders")
    report_if_truncated(MAX_LIST_ROWS, what="work_orders")

    assert _truncation_records(caplog) == []


def test_report_if_truncated_logs_past_the_ceiling(caplog):
    caplog.set_level(logging.WARNING)

    report_if_truncated(MAX_LIST_ROWS + 1, what="work_orders")

    records = _truncation_records(caplog)
    assert len(records) == 1
    assert records[0].fields["list"] == "work_orders"
