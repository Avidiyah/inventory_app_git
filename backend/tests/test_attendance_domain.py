"""Pure state-machine and validation rules -- no Postgres, no FastAPI."""
import os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, datetime, timedelta, timezone

import pytest

from app.domain import attendance, labor_day
from app.domain.errors import PunchTimeInvalidError

NOW = datetime(2026, 9, 21, 18, 0, tzinfo=timezone.utc)   # 1:00 PM Central, Monday


def test_no_open_punch_is_gray():
    assert attendance.shift_state(
        punch_started_at=None, labor_running=False,
        last_labor_ended_at=None, now=NOW) == attendance.STATE_GRAY


def test_a_running_labor_session_is_green_however_long_the_punch():
    assert attendance.shift_state(
        punch_started_at=NOW - timedelta(hours=6), labor_running=True,
        last_labor_ended_at=None, now=NOW) == attendance.STATE_GREEN


@pytest.mark.parametrize("idle,expected", [
    (0, attendance.STATE_YELLOW),
    (9, attendance.STATE_YELLOW),
    (10, attendance.STATE_RED),     # the edge is inclusive
    (11, attendance.STATE_RED),
])
def test_idle_minutes_pick_yellow_or_red_at_the_ten_minute_edge(idle, expected):
    assert attendance.shift_state(
        punch_started_at=NOW - timedelta(hours=4), labor_running=False,
        last_labor_ended_at=NOW - timedelta(minutes=idle), now=NOW) == expected


def test_idle_counts_from_the_punch_when_no_labor_has_run_yet():
    # The accepted consequence in 2: a slow start after arrival shows red.
    assert attendance.idle_minutes(
        punch_started_at=NOW - timedelta(minutes=25),
        last_labor_ended_at=None, now=NOW) == 25


def test_idle_counts_from_the_later_of_the_two_anchors():
    assert attendance.idle_minutes(
        punch_started_at=NOW - timedelta(hours=5),
        last_labor_ended_at=NOW - timedelta(minutes=3), now=NOW) == 3


def test_a_punch_from_an_earlier_central_day_is_stale():
    # 11:00 PM Central Sunday, read at 1:00 PM Central Monday.
    assert attendance.is_stale(datetime(2026, 9, 21, 4, 0, tzinfo=timezone.utc), now=NOW)


def test_a_punch_from_this_central_day_is_not_stale():
    assert not attendance.is_stale(NOW - timedelta(hours=6), now=NOW)


def test_the_central_day_is_what_decides_staleness_not_utc():
    # 8:00 PM Central Monday = 01:00 UTC Tuesday. Same Central day, not stale.
    later = datetime(2026, 9, 22, 2, 0, tzinfo=timezone.utc)   # 9:00 PM Central Mon
    assert not attendance.is_stale(datetime(2026, 9, 22, 1, 0, tzinfo=timezone.utc), now=later)


@pytest.mark.parametrize("started,ended,fragment", [
    (NOW - timedelta(hours=1), NOW - timedelta(hours=2), "after it starts"),
    (NOW - timedelta(hours=1), NOW - timedelta(hours=1), "after it starts"),
    (NOW + timedelta(minutes=1), None, "future"),
    (NOW - timedelta(hours=1), NOW + timedelta(minutes=1), "future"),
])
def test_invalid_windows_are_refused(started, ended, fragment):
    with pytest.raises(PunchTimeInvalidError) as exc:
        attendance.validate_punch_window(started, ended, now=NOW)
    assert fragment in str(exc.value)


def test_an_open_window_ending_nowhere_is_valid():
    attendance.validate_punch_window(NOW - timedelta(hours=1), None, now=NOW)


def test_overlap_names_the_conflicting_punch():
    other = uuid.uuid4()
    existing = [(other, NOW - timedelta(hours=3), NOW - timedelta(hours=1))]
    assert attendance.find_overlap(
        NOW - timedelta(hours=2), NOW - timedelta(minutes=30),
        existing, now=NOW) == other


def test_punches_that_only_touch_do_not_overlap():
    other = uuid.uuid4()
    existing = [(other, NOW - timedelta(hours=3), NOW - timedelta(hours=1))]
    assert attendance.find_overlap(
        NOW - timedelta(hours=1), NOW, existing, now=NOW) is None


def test_an_open_existing_punch_overlaps_everything_up_to_now():
    other = uuid.uuid4()
    existing = [(other, NOW - timedelta(hours=3), None)]
    assert attendance.find_overlap(
        NOW - timedelta(minutes=20), NOW - timedelta(minutes=10),
        existing, now=NOW) == other


def test_the_spring_forward_week_is_167_hours():
    # The attendance week IS the report's week, so this is labor_day's rule
    # being reused, not a parallel one. 2026-03-08 is the US spring forward,
    # and it is the *Sunday* that ends the Mon 2 Mar week -- so that is the
    # week the lost hour falls in.
    monday, sunday = labor_day.week_bounds_containing(datetime(2026, 3, 8).date())
    start, _ = labor_day.day_bounds(monday)
    _, end = labor_day.day_bounds(sunday)
    assert (end - start) == timedelta(hours=167)


# --- charged time no punch covers (spec §9) ------------------------------

DAY = labor_day.day_bounds(date(2026, 9, 14))


def _at(hour, minute=0):
    # 2026-09-14 Central, expressed in UTC (CDT, UTC-5). Built by offset
    # rather than by a literal hour so the evening cases and the previous
    # evening both land on the right calendar day.
    return datetime(2026, 9, 14, tzinfo=timezone.utc) + timedelta(
        hours=hour + 5, minutes=minute
    )


SHIFT_NOW = _at(23)


def test_no_charged_time_outside_a_shift_that_contains_every_session():
    assert attendance.minutes_charged_outside_shift(
        sessions=[(_at(9), _at(11)), (_at(13), _at(16))],
        punches=[(_at(8), _at(17))],
        window=DAY, now=SHIFT_NOW,
    ) == 0


def test_an_hour_charged_before_punching_in_is_counted():
    assert attendance.minutes_charged_outside_shift(
        sessions=[(_at(7), _at(9))],
        punches=[(_at(8), _at(17))],
        window=DAY, now=SHIFT_NOW,
    ) == 60


def test_two_overlapping_sessions_are_one_minute_each_not_two():
    # The same minute charged on two work orders is one minute off shift.
    assert attendance.minutes_charged_outside_shift(
        sessions=[(_at(6), _at(7)), (_at(6, 30), _at(7, 30))],
        punches=[],
        window=DAY, now=SHIFT_NOW,
    ) == 90


def test_a_gap_between_two_punches_is_outside_the_shift():
    # Punched out for lunch, still charging.
    assert attendance.minutes_charged_outside_shift(
        sessions=[(_at(11), _at(14))],
        punches=[(_at(8), _at(12)), (_at(13), _at(17))],
        window=DAY, now=SHIFT_NOW,
    ) == 60


def test_only_the_part_inside_the_window_counts():
    # A session that starts the previous evening contributes only today.
    assert attendance.minutes_charged_outside_shift(
        sessions=[(_at(-2), _at(1))],   # 10 PM Sunday to 1 AM Monday
        punches=[],
        window=DAY, now=SHIFT_NOW,
    ) == 60


def test_an_open_session_and_an_open_punch_both_end_at_now():
    assert attendance.minutes_charged_outside_shift(
        sessions=[(_at(20), None)],
        punches=[(_at(20), None)],
        window=DAY, now=SHIFT_NOW,
    ) == 0


def test_no_sessions_is_zero_not_an_error():
    assert attendance.minutes_charged_outside_shift(
        sessions=[], punches=[(_at(8), _at(17))], window=DAY, now=SHIFT_NOW
    ) == 0
