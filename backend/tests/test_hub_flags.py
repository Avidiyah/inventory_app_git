"""Pure tests for the User Hub's attention-flag thresholds.

Layer: unit (no DB, no HTTP). Every threshold in `app.domain.hub` is tested
at, above, and below its edge, plus the 10:00 a.m. idle guard -- the same
exhaustive-edge style `test_labor_day.py` uses for its own arithmetic.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

from app.domain import hub


# --- session_flag ---------------------------------------------------------


def test_no_flag_below_the_long_session_threshold():
    assert hub.session_flag(hub.LONG_SESSION_WARN_MINUTES - 1) is None


def test_long_session_flag_at_exactly_eight_hours():
    assert hub.session_flag(hub.LONG_SESSION_WARN_MINUTES) == hub.FLAG_LONG_SESSION


def test_long_session_flag_between_the_two_thresholds():
    assert (
        hub.session_flag(hub.SESSION_CAP_WARN_MINUTES - 1) == hub.FLAG_LONG_SESSION
    )


def test_approaching_cap_flag_at_exactly_eleven_hours():
    assert hub.session_flag(hub.SESSION_CAP_WARN_MINUTES) == hub.FLAG_APPROACHING_CAP


def test_approaching_cap_flag_stays_past_eleven_hours():
    assert hub.session_flag(700) == hub.FLAG_APPROACHING_CAP


def test_session_flag_at_zero_minutes_is_none():
    assert hub.session_flag(0) is None


# --- is_assigned_idle -------------------------------------------------------


def _central(hour, minute=0, day=20, month=8, year=2026):
    # CDT is UTC-5 in August, so this local hour is `hour + 5` UTC.
    return datetime(year, month, day, hour + 5, minute, tzinfo=timezone.utc)


def test_idle_requires_at_least_one_assigned_work_order():
    assert not hub.is_assigned_idle(
        assigned_count=0, minutes_today=0, now=_central(11)
    )


def test_idle_is_false_once_any_time_is_tracked_today():
    assert not hub.is_assigned_idle(
        assigned_count=3, minutes_today=1, now=_central(11)
    )


def test_idle_guard_blocks_before_ten_am_central():
    assert not hub.is_assigned_idle(
        assigned_count=1, minutes_today=0, now=_central(9, 59)
    )


def test_idle_fires_at_exactly_ten_am_central():
    assert hub.is_assigned_idle(assigned_count=1, minutes_today=0, now=_central(10, 0))


def test_idle_fires_after_ten_am_central():
    assert hub.is_assigned_idle(assigned_count=4, minutes_today=0, now=_central(14))


# --- is_stale_work_order ----------------------------------------------------


def test_no_session_ever_reads_as_stale():
    now = datetime(2026, 8, 20, 18, 0, tzinfo=timezone.utc)
    assert hub.is_stale_work_order(last_activity_at=None, now=now)


def test_activity_just_now_is_not_stale():
    now = datetime(2026, 8, 20, 18, 0, tzinfo=timezone.utc)
    assert not hub.is_stale_work_order(last_activity_at=now, now=now)


def test_activity_just_under_the_window_is_not_stale():
    now = datetime(2026, 8, 20, 18, 0, tzinfo=timezone.utc)
    last_activity = now - timedelta(days=hub.STALE_WORK_ORDER_DAYS) + timedelta(minutes=1)
    assert not hub.is_stale_work_order(last_activity_at=last_activity, now=now)


def test_activity_at_exactly_the_window_is_stale():
    now = datetime(2026, 8, 20, 18, 0, tzinfo=timezone.utc)
    last_activity = now - timedelta(days=hub.STALE_WORK_ORDER_DAYS)
    assert hub.is_stale_work_order(last_activity_at=last_activity, now=now)


def test_activity_well_past_the_window_is_stale():
    now = datetime(2026, 8, 20, 18, 0, tzinfo=timezone.utc)
    last_activity = now - timedelta(days=hub.STALE_WORK_ORDER_DAYS + 5)
    assert hub.is_stale_work_order(last_activity_at=last_activity, now=now)


# --- constants --------------------------------------------------------------


def test_thresholds_match_the_spec():
    assert hub.LONG_SESSION_WARN_MINUTES == 480
    assert hub.SESSION_CAP_WARN_MINUTES == 660
    assert hub.IDLE_CHECK_HOUR == 10
    assert hub.STALE_WORK_ORDER_DAYS == 3
