"""Database tests for the hub's time engine.

Covers the global stale-session sweep (this task) and the daily labor
aggregate (next task). Skips without a reachable Postgres, like every other
`db`-fixture test in this suite.

Seed helpers mirror `tests/test_work_orders_service.py` so the two files read
the same way.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.domain import roles
from app.domain import work_orders as wo
from app.models import (
    User,
    WorkOrder,
    WorkOrderLabor,
    WorkOrderLaborSession,
)
from app.services import auth
from app.services import work_orders as wos


# --- seed helpers --------------------------------------------------------

def _seed_user(db, role=roles.ROLE_TECHNICIAN, *, first_name="Jose", last_name="Rivera"):
    user = User(
        username=f"u-{uuid.uuid4().hex[:10]}",
        first_name=first_name,
        last_name=last_name,
        password_hash=auth.hash_password("hunter2"),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def _seed_work_order(db, *, created_by, assigned_to=None, number=None):
    return wos.get_or_create_work_order(
        db,
        number=number or f"WO-{uuid.uuid4().hex[:8]}",
        created_by_id=created_by.id,
        assigned_to_id=assigned_to.id if assigned_to else None,
    )


def _seed_session(db, work_order, technician, *, started_at, ended_at=None):
    """A session written straight to the table.

    Bypasses `start_labor_session` on purpose: these tests need exact
    timestamps, including ones in the past, and the service always stamps
    `now`.
    """
    session = WorkOrderLaborSession(
        id=uuid.uuid4(),
        work_order_id=work_order.id,
        technician_id=technician.id,
        started_at=started_at,
        ended_at=ended_at,
    )
    db.add(session)
    db.flush()
    return session


# --- the global sweep ----------------------------------------------------

def test_sweep_closes_a_stale_session_at_the_capped_instant(db):
    tech = _seed_user(db)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    started = datetime.now(timezone.utc) - timedelta(hours=20)
    session = _seed_session(db, work_order, tech, started_at=started)

    closed = wos.sweep_stale_sessions(db, technician_id=tech.id)

    assert closed == 1
    db.refresh(session)
    # Closed at start + 720 minutes, NOT at sweep time: the billed figure has
    # to be right even though the flag is late.
    assert session.ended_at == started + timedelta(
        minutes=wo.LABOR_SESSION_MAX_MINUTES
    )
    assert session.auto_closed_at is not None


def test_sweep_writes_a_labor_row_capped_at_twelve_hours(db):
    tech = _seed_user(db)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    _seed_session(
        db, work_order, tech, started_at=datetime.now(timezone.utc) - timedelta(hours=20)
    )

    wos.sweep_stale_sessions(db, technician_id=tech.id)

    entries = (
        db.query(WorkOrderLabor)
        .filter(WorkOrderLabor.work_order_id == work_order.id)
        .all()
    )
    assert [e.minutes for e in entries] == [wo.LABOR_SESSION_MAX_MINUTES]


def test_sweep_does_not_auto_hold(db):
    # A supervisor's phone must not buzz because somebody opened a dashboard.
    tech = _seed_user(db)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    work_order.status = wo.STATUS_IN_PROGRESS
    db.flush()
    _seed_session(
        db, work_order, tech, started_at=datetime.now(timezone.utc) - timedelta(hours=20)
    )

    wos.sweep_stale_sessions(db, technician_id=tech.id)

    db.refresh(work_order)
    assert work_order.status == wo.STATUS_IN_PROGRESS


def test_sweep_leaves_a_fresh_session_running(db):
    tech = _seed_user(db)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    session = _seed_session(
        db, work_order, tech, started_at=datetime.now(timezone.utc) - timedelta(hours=2)
    )

    assert wos.sweep_stale_sessions(db, technician_id=tech.id) == 0
    db.refresh(session)
    assert session.ended_at is None


def test_sweep_is_idempotent(db):
    tech = _seed_user(db)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    _seed_session(
        db, work_order, tech, started_at=datetime.now(timezone.utc) - timedelta(hours=20)
    )

    assert wos.sweep_stale_sessions(db, technician_id=tech.id) == 1
    assert wos.sweep_stale_sessions(db, technician_id=tech.id) == 0


def test_a_scoped_sweep_leaves_other_peoples_clocks_alone(db):
    mine = _seed_user(db)
    theirs = _seed_user(db, first_name="Marisol", last_name="Chen")
    work_order = _seed_work_order(db, created_by=mine, assigned_to=mine)
    stale_other = _seed_session(
        db, work_order, theirs, started_at=datetime.now(timezone.utc) - timedelta(hours=20)
    )
    _seed_session(
        db, work_order, mine, started_at=datetime.now(timezone.utc) - timedelta(hours=20)
    )

    assert wos.sweep_stale_sessions(db, technician_id=mine.id) == 1
    db.refresh(stale_other)
    assert stale_other.ended_at is None


def test_an_unscoped_sweep_closes_every_stale_session(db):
    mine = _seed_user(db)
    theirs = _seed_user(db, first_name="Marisol", last_name="Chen")
    work_order = _seed_work_order(db, created_by=mine, assigned_to=mine)
    _seed_session(
        db, work_order, mine, started_at=datetime.now(timezone.utc) - timedelta(hours=20)
    )
    _seed_session(
        db, work_order, theirs, started_at=datetime.now(timezone.utc) - timedelta(hours=20)
    )

    assert wos.sweep_stale_sessions(db) == 2


def test_tracking_start_statuses_is_exported_for_the_hub_picker(db):
    # The hub's `Start on...` picker must offer exactly what
    # `start_labor_session` accepts, so it reads the same tuple.
    assert wos.TRACKING_START_STATUSES == (
        wo.STATUS_CREATED,
        wo.STATUS_ASSIGNED,
        wo.STATUS_IN_PROGRESS,
        wo.STATUS_ON_HOLD,
    )


# --- the daily aggregate -------------------------------------------------

from datetime import date

from app.domain import labor_day
from app.services import labor_summary


def _seed_adjustment(db, work_order, technician, *, minutes, recorded_by, created_at):
    """A hand-entered labor row: no session points at it (spec D5)."""
    entry = WorkOrderLabor(
        id=uuid.uuid4(),
        work_order_id=work_order.id,
        technician_id=technician.id,
        minutes=minutes,
        recorded_by_id=recorded_by.id,
        created_at=created_at,
    )
    db.add(entry)
    db.flush()
    return entry


def _seed_tracked_labor(db, session, *, minutes):
    """A labor row produced by a session, linked the way `_close_session` links
    it. Must never be reported as an adjustment."""
    entry = WorkOrderLabor(
        id=uuid.uuid4(),
        work_order_id=session.work_order_id,
        technician_id=session.technician_id,
        minutes=minutes,
        recorded_by_id=session.technician_id,
        created_at=session.ended_at,
    )
    db.add(entry)
    db.flush()
    session.labor_id = entry.id
    db.flush()
    return entry


# The reference day: Thursday 2026-08-20 Central (CDT, UTC-5).
DAY = date(2026, 8, 20)
DAY_START = datetime(2026, 8, 20, 5, 0, tzinfo=timezone.utc)


def _at(hour, minute=0, day=20, month=8):
    return datetime(2026, month, day, hour, minute, tzinfo=timezone.utc)


def test_closed_sessions_sum_into_closed_minutes(db):
    tech = _seed_user(db)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    _seed_session(db, work_order, tech, started_at=_at(13, 12), ended_at=_at(15, 31))
    _seed_session(db, work_order, tech, started_at=_at(15, 47), ended_at=_at(16, 52))

    summary = labor_summary.day_summary(db, tech.id, DAY, now=_at(18, 0))

    assert summary.closed_minutes == 139 + 65
    assert summary.running_minutes == 0
    assert summary.running is None
    assert summary.total_minutes == 204


def test_a_running_session_reports_its_anchors(db):
    tech = _seed_user(db)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech, number="88214")
    _seed_session(db, work_order, tech, started_at=_at(13, 12))

    summary = labor_summary.day_summary(db, tech.id, DAY, now=_at(15, 59))

    assert summary.running is not None
    assert summary.running.number == "88214"
    assert summary.running.started_at == _at(13, 12)
    # Started today, so today's total ticks from the same instant.
    assert summary.running.day_counting_from == _at(13, 12)
    assert summary.running_minutes == 167


def test_a_clock_inherited_from_yesterday_counts_only_from_midnight(db):
    # The correction the spec's payload sketch needs: a session that started
    # 11:30 PM yesterday and is still running at 12:30 AM has given *today*
    # thirty minutes, not sixty. `day_counting_from` is what the client ticks
    # today's total from.
    tech = _seed_user(db)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    _seed_session(db, work_order, tech, started_at=_at(4, 30, day=21))

    summary = labor_summary.day_summary(
        db, tech.id, date(2026, 8, 21), now=_at(5, 30, day=21)
    )

    day_start, _ = labor_day.day_bounds(date(2026, 8, 21))
    assert summary.running.started_at == _at(4, 30, day=21)
    assert summary.running.day_counting_from == day_start
    assert summary.running_minutes == 30


def test_a_session_from_another_day_is_excluded(db):
    tech = _seed_user(db)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    _seed_session(
        db, work_order, tech, started_at=_at(14, 0, day=19), ended_at=_at(16, 0, day=19)
    )

    summary = labor_summary.day_summary(db, tech.id, DAY, now=_at(18, 0))

    assert summary.closed_minutes == 0
    assert summary.timeline == []


def test_another_persons_session_is_excluded(db):
    mine = _seed_user(db)
    theirs = _seed_user(db, first_name="Marisol", last_name="Chen")
    work_order = _seed_work_order(db, created_by=mine, assigned_to=mine)
    _seed_session(db, work_order, theirs, started_at=_at(13, 0), ended_at=_at(15, 0))

    summary = labor_summary.day_summary(db, mine.id, DAY, now=_at(18, 0))

    assert summary.closed_minutes == 0


def test_the_timeline_is_ordered_and_carries_the_work_order_number(db):
    tech = _seed_user(db)
    first = _seed_work_order(db, created_by=tech, assigned_to=tech, number="88214")
    second = _seed_work_order(db, created_by=tech, assigned_to=tech, number="88190")
    _seed_session(db, second, tech, started_at=_at(15, 47), ended_at=_at(16, 52))
    _seed_session(db, first, tech, started_at=_at(13, 12), ended_at=_at(15, 31))

    summary = labor_summary.day_summary(db, tech.id, DAY, now=_at(18, 0))

    assert [e.number for e in summary.timeline] == ["88214", "88190"]
    assert [e.minutes for e in summary.timeline] == [139, 65]
    assert all(e.auto_closed is False for e in summary.timeline)


def test_an_auto_closed_session_is_flagged_on_the_timeline(db):
    tech = _seed_user(db)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    session = _seed_session(
        db, work_order, tech, started_at=_at(13, 0), ended_at=_at(15, 0)
    )
    session.auto_closed_at = _at(17, 0)
    db.flush()

    summary = labor_summary.day_summary(db, tech.id, DAY, now=_at(18, 0))

    assert summary.timeline[0].auto_closed is True


def test_a_session_that_only_touches_the_day_is_left_off_the_timeline(db):
    # Stopped exactly at midnight: it earned today nothing and there is
    # nothing to draw.
    tech = _seed_user(db)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    _seed_session(
        db, work_order, tech, started_at=_at(3, 0, day=21), ended_at=DAY_START + timedelta(days=1)
    )

    summary = labor_summary.day_summary(
        db, tech.id, date(2026, 8, 21), now=_at(8, 0, day=21)
    )

    assert summary.timeline == []
    assert summary.closed_minutes == 0


def test_a_hand_entered_row_is_reported_as_an_adjustment(db):
    tech = _seed_user(db)
    supervisor = _seed_user(
        db, roles.ROLE_SUPERVISOR, first_name="Marisol", last_name="Chen"
    )
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech, number="88190")
    _seed_adjustment(
        db, work_order, tech, minutes=30, recorded_by=supervisor, created_at=_at(19, 0)
    )

    summary = labor_summary.day_summary(db, tech.id, DAY, now=_at(20, 0))

    assert summary.adjustment_minutes == 30
    assert len(summary.adjustments) == 1
    assert summary.adjustments[0].minutes == 30
    assert summary.adjustments[0].recorded_by_name == "Marisol Chen"
    assert summary.adjustments[0].work_order_number == "88190"
    # Adjustments carry no start/stop, so there is nothing to draw.
    assert summary.timeline == []


def test_adjustments_are_included_in_the_day_total(db):
    # Decision D15: one number means one thing on every surface.
    tech = _seed_user(db)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    _seed_session(db, work_order, tech, started_at=_at(13, 0), ended_at=_at(18, 50))
    _seed_adjustment(
        db, work_order, tech, minutes=30, recorded_by=supervisor, created_at=_at(19, 0)
    )

    summary = labor_summary.day_summary(db, tech.id, DAY, now=_at(20, 0))

    assert summary.closed_minutes == 350
    assert summary.adjustment_minutes == 30
    assert summary.total_minutes == 380


def test_a_session_produced_labor_row_is_not_an_adjustment(db):
    tech = _seed_user(db)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    session = _seed_session(
        db, work_order, tech, started_at=_at(13, 0), ended_at=_at(15, 0)
    )
    _seed_tracked_labor(db, session, minutes=120)

    summary = labor_summary.day_summary(db, tech.id, DAY, now=_at(18, 0))

    assert summary.adjustments == []
    assert summary.adjustment_minutes == 0
    assert summary.total_minutes == 120


def test_an_adjustment_with_no_recorder_still_names_something(db):
    tech = _seed_user(db)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    entry = WorkOrderLabor(
        id=uuid.uuid4(),
        work_order_id=work_order.id,
        technician_id=tech.id,
        minutes=15,
        recorded_by_id=None,
        created_at=_at(19, 0),
    )
    db.add(entry)
    db.flush()

    summary = labor_summary.day_summary(db, tech.id, DAY, now=_at(20, 0))

    assert summary.adjustments[0].recorded_by_name == "Name unavailable"


def test_an_adjustment_is_filed_under_the_central_date_it_was_entered(db):
    # Known limitation, accepted for iteration 1: a correction entered Friday
    # for Tuesday's work lands on Friday.
    tech = _seed_user(db)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    # 04:00Z on the 21st is 11:00 PM Central on the 20th.
    _seed_adjustment(
        db, work_order, tech, minutes=45, recorded_by=supervisor,
        created_at=_at(4, 0, day=21),
    )

    assert labor_summary.day_summary(db, tech.id, DAY, now=_at(6, 0, day=21)).adjustment_minutes == 45
    assert labor_summary.day_summary(
        db, tech.id, date(2026, 8, 21), now=_at(6, 0, day=21)
    ).adjustment_minutes == 0


def test_an_empty_day_reports_zeros_not_none(db):
    tech = _seed_user(db)

    summary = labor_summary.day_summary(db, tech.id, DAY, now=_at(18, 0))

    assert summary.day == DAY
    assert summary.closed_minutes == 0
    assert summary.running_minutes == 0
    assert summary.adjustment_minutes == 0
    assert summary.total_minutes == 0
    assert summary.running is None
    assert summary.timeline == []
    assert summary.adjustments == []


# --- crew_day_summaries and last_worked (P3a) -----------------------------


def test_crew_day_summaries_returns_one_entry_per_technician(db):
    a = _seed_user(db, first_name="Jose", last_name="Rivera")
    b = _seed_user(db, first_name="Marisol", last_name="Chen")
    work_order = _seed_work_order(db, created_by=a, assigned_to=a)
    _seed_session(db, work_order, a, started_at=_at(13, 0), ended_at=_at(15, 0))
    _seed_session(db, work_order, b, started_at=_at(14, 0), ended_at=_at(14, 30))

    summaries = labor_summary.crew_day_summaries(db, [a.id, b.id], DAY, now=_at(18, 0))

    assert set(summaries.keys()) == {a.id, b.id}
    assert summaries[a.id].closed_minutes == 120
    assert summaries[b.id].closed_minutes == 30


def test_crew_day_summaries_reports_a_zero_day_for_a_technician_with_no_activity(db):
    a = _seed_user(db)
    b = _seed_user(db, first_name="Marisol", last_name="Chen")

    summaries = labor_summary.crew_day_summaries(db, [a.id, b.id], DAY, now=_at(18, 0))

    assert summaries[b.id].closed_minutes == 0
    assert summaries[b.id].total_minutes == 0


def test_crew_day_summaries_of_an_empty_crew_is_an_empty_dict(db):
    assert labor_summary.crew_day_summaries(db, [], DAY, now=_at(18, 0)) == {}


def test_last_worked_is_the_most_recent_sessions_ended_at(db):
    tech = _seed_user(db)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    _seed_session(db, work_order, tech, started_at=_at(9, 0, day=18), ended_at=_at(10, 0, day=18))
    _seed_session(db, work_order, tech, started_at=_at(9, 0, day=19), ended_at=_at(10, 0, day=19))

    assert labor_summary.last_worked(db, tech.id) == _at(10, 0, day=19)


def test_last_worked_ignores_a_currently_running_session(db):
    # D11: "Last worked" is the most recent *stop*. A running session has no
    # `ended_at` and must not be read as "still going" here -- the clock
    # widget already shows that; this is specifically the off-clock label.
    tech = _seed_user(db)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    _seed_session(db, work_order, tech, started_at=_at(9, 0, day=18), ended_at=_at(10, 0, day=18))
    _seed_session(db, work_order, tech, started_at=_at(9, 0, day=20))

    assert labor_summary.last_worked(db, tech.id) == _at(10, 0, day=18)


def test_last_worked_is_none_for_a_technician_who_has_never_tracked_time(db):
    tech = _seed_user(db)
    assert labor_summary.last_worked(db, tech.id) is None


def test_last_worked_only_considers_the_named_technician(db):
    mine = _seed_user(db)
    theirs = _seed_user(db, first_name="Marisol", last_name="Chen")
    work_order = _seed_work_order(db, created_by=mine, assigned_to=mine)
    _seed_session(db, work_order, theirs, started_at=_at(9, 0), ended_at=_at(10, 0))

    assert labor_summary.last_worked(db, mine.id) is None


# --- the batched timesheet range aggregate ---------------------------------


def test_crew_range_summaries_include_every_requested_day(db):
    tech = _seed_user(db)

    result = labor_summary.crew_range_summaries(
        db, [tech.id], date(2026, 8, 17), date(2026, 8, 19), now=_at(18, 0)
    )

    assert [summary.day for summary in result[tech.id]] == [
        date(2026, 8, 17),
        date(2026, 8, 18),
        date(2026, 8, 19),
    ]
    assert all(summary.total_minutes == 0 for summary in result[tech.id])


def test_crew_range_summaries_split_a_session_across_days(db):
    tech = _seed_user(db)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    # 11 PM Aug 17 through 1 AM Aug 18 Central.
    _seed_session(
        db,
        work_order,
        tech,
        started_at=datetime(2026, 8, 18, 4, 0, tzinfo=timezone.utc),
        ended_at=datetime(2026, 8, 18, 6, 0, tzinfo=timezone.utc),
    )

    day17, day18 = labor_summary.crew_range_summaries(
        db, [tech.id], date(2026, 8, 17), date(2026, 8, 18), now=_at(18, 0)
    )[tech.id]

    assert (day17.closed_minutes, day18.closed_minutes) == (60, 60)
    assert (len(day17.timeline), len(day18.timeline)) == (1, 1)


def test_crew_range_summaries_preserve_running_session_anchors(db):
    tech = _seed_user(db)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    _seed_session(db, work_order, tech, started_at=_at(17, 0))

    summary = labor_summary.crew_range_summaries(
        db, [tech.id], DAY, DAY, now=_at(18, 0)
    )[tech.id][0]

    assert summary.running is not None
    assert summary.running_minutes == 60


def test_crew_range_summaries_bucket_adjustments_by_created_day(db):
    tech = _seed_user(db)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR, first_name="Sam")
    work_order = _seed_work_order(db, created_by=supervisor, assigned_to=tech)
    day18_start, _ = labor_day.day_bounds(date(2026, 8, 18))
    _seed_adjustment(
        db,
        work_order,
        tech,
        minutes=30,
        recorded_by=supervisor,
        created_at=day18_start + timedelta(hours=2),
    )

    day17, day18, day19 = labor_summary.crew_range_summaries(
        db, [tech.id], date(2026, 8, 17), date(2026, 8, 19), now=_at(18, 0)
    )[tech.id]

    assert [day17.adjustment_minutes, day18.adjustment_minutes, day19.adjustment_minutes] == [
        0,
        30,
        0,
    ]
    assert day18.adjustments[0].recorded_by_name == supervisor.full_name


def test_crew_range_summaries_match_the_existing_one_day_aggregate(db):
    tech = _seed_user(db)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    _seed_session(db, work_order, tech, started_at=_at(13, 0), ended_at=_at(15, 0))

    expected = labor_summary.day_summary(db, tech.id, DAY, now=_at(18, 0))
    actual = labor_summary.crew_range_summaries(
        db, [tech.id], DAY, DAY, now=_at(18, 0)
    )[tech.id][0]

    assert actual == expected


def test_crew_range_summaries_of_an_empty_crew_is_an_empty_dict(db):
    assert (
        labor_summary.crew_range_summaries(
            db, [], date(2026, 8, 17), date(2026, 8, 18), now=_at(18, 0)
        )
        == {}
    )
