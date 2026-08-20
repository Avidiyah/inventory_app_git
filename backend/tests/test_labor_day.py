"""Pure tests for Central-day arithmetic.

Layer: unit (no DB, no HTTP). Every hub number in every later phase is
derived from these four functions, so they are tested exhaustively here --
including both DST transitions, which are the cases a hand-rolled
`timedelta(hours=24)` would get wrong.

2026 US DST transitions used below: spring forward Sunday 2026-03-08
(a 23-hour Central day), fall back Sunday 2026-11-01 (a 25-hour day).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, datetime, timedelta, timezone

from app.domain import labor_day


def test_summer_day_bounds_are_five_hours_behind_utc():
    # CDT is UTC-5, so a Central day runs 05:00Z to 05:00Z.
    start, end = labor_day.day_bounds(date(2026, 8, 20))
    assert start == datetime(2026, 8, 20, 5, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 8, 21, 5, 0, tzinfo=timezone.utc)


def test_winter_day_bounds_are_six_hours_behind_utc():
    # CST is UTC-6. A fixed offset would put this an hour wrong.
    start, end = labor_day.day_bounds(date(2026, 1, 15))
    assert start == datetime(2026, 1, 15, 6, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 1, 16, 6, 0, tzinfo=timezone.utc)


def test_spring_forward_day_is_twenty_three_hours_long():
    start, end = labor_day.day_bounds(date(2026, 3, 8))
    assert end - start == timedelta(hours=23)


def test_fall_back_day_is_twenty_five_hours_long():
    start, end = labor_day.day_bounds(date(2026, 11, 1))
    assert end - start == timedelta(hours=25)


def test_days_tile_with_no_gap_or_overlap():
    _, first_end = labor_day.day_bounds(date(2026, 8, 20))
    second_start, _ = labor_day.day_bounds(date(2026, 8, 21))
    assert first_end == second_start


def test_central_date_of_rolls_back_before_local_midnight():
    # 04:59Z on the 21st is 11:59 PM Central on the 20th.
    assert labor_day.central_date_of(
        datetime(2026, 8, 21, 4, 59, tzinfo=timezone.utc)
    ) == date(2026, 8, 20)
    assert labor_day.central_date_of(
        datetime(2026, 8, 21, 5, 0, tzinfo=timezone.utc)
    ) == date(2026, 8, 21)


def test_central_date_of_reads_a_naive_instant_as_utc():
    # Matches `work_orders.format_note_timestamp`: the app stores UTC, and a
    # naive value that slipped through must not be read as local time.
    assert labor_day.central_date_of(datetime(2026, 8, 21, 4, 59)) == date(2026, 8, 20)


def test_central_date_of_agrees_with_day_bounds_at_both_edges():
    day = date(2026, 11, 1)
    start, end = labor_day.day_bounds(day)
    assert labor_day.central_date_of(start) == day
    assert labor_day.central_date_of(end - timedelta(microseconds=1)) == day
    assert labor_day.central_date_of(end) == date(2026, 11, 2)


def test_as_utc_leaves_an_aware_instant_alone():
    aware = datetime(2026, 8, 20, 13, 12, tzinfo=timezone.utc)
    assert labor_day.as_utc(aware) is aware


def test_as_utc_stamps_a_naive_instant_as_utc():
    assert labor_day.as_utc(datetime(2026, 8, 20, 13, 12)) == datetime(
        2026, 8, 20, 13, 12, tzinfo=timezone.utc
    )


def test_display_anchor_is_eight_am():
    assert labor_day.DISPLAY_ANCHOR_HOUR == 8
