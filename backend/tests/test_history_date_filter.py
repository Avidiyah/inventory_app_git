"""Tests for the date-range bounds builder used by
`app.services.history.list_history`.

Pure helper, no DB -- consistent with `test_history_wo_filter.py`. The
helper is the single source of truth for turning the two optional calendar
dates (`date_from` / `date_to`) into the half-open, tz-aware UTC datetime
bounds the query filters on:

- "no filter" sides (None -> None),
- `start` = midnight UTC on `date_from`,
- `end` = midnight UTC on the day AFTER `date_to` (so `date_to` is included
  in full via `created_at < end`),
- both bounds are timezone-aware and in UTC.
"""

import os
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.history import _date_range_bounds


def test_both_none_returns_no_bounds():
    assert _date_range_bounds(None, None) == (None, None)


def test_from_only_sets_start_only():
    start, end = _date_range_bounds(date(2026, 6, 30), None)
    assert start == datetime(2026, 6, 30, 0, 0, tzinfo=timezone.utc)
    assert end is None


def test_to_only_sets_exclusive_next_day_end():
    # date_to is inclusive: the end bound is midnight on the *next* day so
    # `created_at < end` still admits anything stamped on 2026-06-30.
    start, end = _date_range_bounds(None, date(2026, 6, 30))
    assert start is None
    assert end == datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)


def test_both_sides():
    start, end = _date_range_bounds(date(2026, 6, 1), date(2026, 6, 30))
    assert start == datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)


def test_single_day_range_is_a_full_day_window():
    # from == to should cover that entire calendar day (24h half-open window).
    start, end = _date_range_bounds(date(2026, 6, 15), date(2026, 6, 15))
    assert start == datetime(2026, 6, 15, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 6, 16, 0, 0, tzinfo=timezone.utc)


def test_month_end_rolls_over_correctly():
    # date_to on a month boundary rolls into the next month, not day 32.
    _, end = _date_range_bounds(None, date(2026, 12, 31))
    assert end == datetime(2027, 1, 1, 0, 0, tzinfo=timezone.utc)


def test_bounds_are_timezone_aware_utc():
    start, end = _date_range_bounds(date(2026, 1, 1), date(2026, 1, 2))
    assert start.tzinfo is timezone.utc
    assert end.tzinfo is timezone.utc


def test_reversed_range_yields_empty_window():
    # from after to -> start >= end -> no rows match (empty page, not error).
    start, end = _date_range_bounds(date(2026, 6, 30), date(2026, 6, 1))
    assert start >= end
