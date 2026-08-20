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


# --- overlap and the midnight split -------------------------------------

# The 2026-08-20 Central day, as UTC instants (CDT, UTC-5).
DAY = date(2026, 8, 20)
DAY_START = datetime(2026, 8, 20, 5, 0, tzinfo=timezone.utc)
DAY_END = datetime(2026, 8, 21, 5, 0, tzinfo=timezone.utc)


def _utc(month, day, hour, minute=0, second=0):
    return datetime(2026, month, day, hour, minute, second, tzinfo=timezone.utc)


def test_overlap_of_a_session_wholly_inside_the_window():
    # 8:12 AM - 10:31 AM Central == 13:12Z - 15:31Z. 2h19m.
    assert (
        labor_day.overlap_minutes(
            _utc(8, 20, 13, 12), _utc(8, 20, 15, 31), DAY_START, DAY_END,
            now=_utc(8, 20, 16, 0),
        )
        == 139
    )


def test_a_running_session_counts_up_to_now():
    assert (
        labor_day.overlap_minutes(
            _utc(8, 20, 13, 12), None, DAY_START, DAY_END, now=_utc(8, 20, 15, 59)
        )
        == 167
    )


def test_a_running_session_is_clamped_to_the_window_end():
    # `now` is tomorrow; today's share still stops at today's midnight.
    # 13:12Z to 05:00Z next day = 15h48m = 948 minutes.
    assert (
        labor_day.overlap_minutes(
            _utc(8, 20, 13, 12), None, DAY_START, DAY_END, now=_utc(8, 21, 12, 0)
        )
        == 948
    )


def test_a_session_that_started_before_the_window_is_clipped_to_it():
    # 23:30 Central Wed -> 00:30 Central Thu, measured against Thursday.
    assert (
        labor_day.overlap_minutes(
            _utc(8, 20, 4, 30), _utc(8, 20, 5, 30), DAY_START, DAY_END,
            now=_utc(8, 20, 6, 0),
        )
        == 30
    )


def test_a_session_wholly_before_the_window_contributes_nothing():
    assert (
        labor_day.overlap_minutes(
            _utc(8, 19, 14, 0), _utc(8, 19, 16, 0), DAY_START, DAY_END,
            now=_utc(8, 20, 16, 0),
        )
        == 0
    )


def test_a_session_wholly_after_the_window_contributes_nothing():
    assert (
        labor_day.overlap_minutes(
            _utc(8, 21, 14, 0), _utc(8, 21, 16, 0), DAY_START, DAY_END,
            now=_utc(8, 21, 16, 0),
        )
        == 0
    )


def test_a_session_that_merely_touches_the_boundary_contributes_nothing():
    # Ends exactly at the window's start instant. Nothing lies inside it.
    assert (
        labor_day.overlap_minutes(
            _utc(8, 20, 3, 0), DAY_START, DAY_START, DAY_END, now=_utc(8, 20, 6, 0)
        )
        == 0
    )


def test_overlap_does_not_floor_at_one_minute():
    # Deliberately unlike `work_orders.capped_session_minutes`, which floors at
    # 1 so a short visit survives `validate_labor_minutes`. Flooring here would
    # invent a minute on every midnight crossing.
    assert (
        labor_day.overlap_minutes(
            _utc(8, 20, 13, 0, 0), _utc(8, 20, 13, 0, 20), DAY_START, DAY_END,
            now=_utc(8, 20, 14, 0),
        )
        == 0
    )


def test_overlap_tolerates_an_end_before_its_start():
    # Defensive: a clock-skewed row must read as zero, never as negative time.
    assert (
        labor_day.overlap_minutes(
            _utc(8, 20, 15, 0), _utc(8, 20, 14, 0), DAY_START, DAY_END,
            now=_utc(8, 20, 16, 0),
        )
        == 0
    )


def test_overlap_reads_naive_timestamps_as_utc():
    assert (
        labor_day.overlap_minutes(
            datetime(2026, 8, 20, 13, 12),
            datetime(2026, 8, 20, 15, 31),
            DAY_START,
            DAY_END,
            now=_utc(8, 20, 16, 0),
        )
        == 139
    )


def test_split_by_day_divides_a_midnight_crossing():
    # 23:30 Central Thu -> 00:30 Central Fri.
    assert labor_day.split_by_day(
        _utc(8, 21, 4, 30), _utc(8, 21, 5, 30), now=_utc(8, 21, 6, 0)
    ) == [(date(2026, 8, 20), 30), (date(2026, 8, 21), 30)]


def test_split_by_day_omits_a_day_that_gains_nothing():
    # Ends exactly at midnight: Friday is not touched.
    assert labor_day.split_by_day(
        _utc(8, 21, 3, 0), _utc(8, 21, 5, 0), now=_utc(8, 21, 6, 0)
    ) == [(date(2026, 8, 20), 120)]


def test_split_by_day_follows_a_running_session_to_now():
    assert labor_day.split_by_day(
        _utc(8, 21, 4, 30), None, now=_utc(8, 21, 6, 0)
    ) == [(date(2026, 8, 20), 30), (date(2026, 8, 21), 60)]


def test_split_by_day_covers_every_day_a_long_session_spans():
    # 01:00 Central Thu -> 01:00 Central Sat: 23h + 24h + 1h.
    pairs = labor_day.split_by_day(
        _utc(8, 20, 6, 0), _utc(8, 22, 6, 0), now=_utc(8, 22, 7, 0)
    )
    assert [d for d, _ in pairs] == [
        date(2026, 8, 20),
        date(2026, 8, 21),
        date(2026, 8, 22),
    ]
    assert [m for _, m in pairs] == [1380, 1440, 60]
    assert sum(m for _, m in pairs) == 48 * 60


def test_split_by_day_returns_nothing_for_a_zero_length_session():
    instant = _utc(8, 20, 13, 0)
    assert labor_day.split_by_day(instant, instant, now=_utc(8, 20, 14, 0)) == []


def test_a_full_spring_forward_day_totals_twenty_three_hours():
    start, end = labor_day.day_bounds(date(2026, 3, 8))
    assert labor_day.split_by_day(start, end, now=end) == [(date(2026, 3, 8), 23 * 60)]


def test_a_full_fall_back_day_totals_twenty_five_hours():
    start, end = labor_day.day_bounds(date(2026, 11, 1))
    assert labor_day.split_by_day(start, end, now=end) == [
        (date(2026, 11, 1), 25 * 60)
    ]


def test_a_session_spanning_the_spring_forward_gap_loses_the_skipped_hour():
    # 1:30 AM CST -> 3:30 AM CDT is one real hour of work, because 2:00-2:59
    # did not happen. Instant-based arithmetic gets this right for free.
    pairs = labor_day.split_by_day(
        datetime(2026, 3, 8, 7, 30, tzinfo=timezone.utc),
        datetime(2026, 3, 8, 8, 30, tzinfo=timezone.utc),
        now=datetime(2026, 3, 8, 9, 0, tzinfo=timezone.utc),
    )
    assert pairs == [(date(2026, 3, 8), 60)]
