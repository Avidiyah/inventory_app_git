"""The performance window: trusted days, billed shares, and the month contract.
Spec: docs/superpowers/specs/2026-10-29-performance-score-design.md."""
import os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.domain import performance as perf
from app.domain.errors import ReportWeekError
from app.models import AttendancePunch, User, WorkOrder, WorkOrderLabor, WorkOrderLaborSession
from app.services import auth as auth_service
from app.services import performance_score
from app.services import work_orders as wos


def _instant(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def make_technician(db, first="Ann", last="Lee"):
    user = User(username=f"u-{uuid.uuid4().hex[:10]}",
                password_hash=auth_service.hash_password("hunter2"),
                role="technician", first_name=first, last_name=last)
    db.add(user); db.flush()
    return user


def make_punch(db, user, started_at, ended_at, end_source="manual", needs_review=False):
    punch = AttendancePunch(
        id=uuid.uuid4(), user_id=user.id, started_at=_instant(started_at),
        ended_at=_instant(ended_at), start_source="manual", end_source=end_source,
        needs_review=needs_review)
    db.add(punch); db.flush()
    return punch


def make_order(db, tech, completed_at=None):
    order = wos.get_or_create_work_order(
        db, number=f"WO-{uuid.uuid4().hex[:6]}", created_by_id=tech.id, assigned_to_id=tech.id)
    order.completed_at = None if completed_at is None else _instant(completed_at)
    db.flush()
    return order


def make_session(db, tech, started_at, ended_at, order=None, auto_closed_at=None):
    order = order or make_order(db, tech)
    session = WorkOrderLaborSession(
        id=uuid.uuid4(), work_order_id=order.id, technician_id=tech.id,
        started_at=_instant(started_at), ended_at=_instant(ended_at),
        auto_closed_at=None if auto_closed_at is None else _instant(auto_closed_at))
    db.add(session); db.flush()
    return session


def make_labor(db, order, tech, minutes):
    entry = WorkOrderLabor(id=uuid.uuid4(), work_order_id=order.id,
                           technician_id=None if tech is None else tech.id, minutes=minutes,
                           recorded_by_id=None if tech is None else tech.id,
                           created_at=_instant("2026-09-14T22:00Z"))
    db.add(entry); db.flush()
    return entry


MONDAY = date(2026, 9, 14)
NOW = datetime(2026, 9, 17, 15, 0, tzinfo=timezone.utc)


def week(db, now=NOW):
    return performance_score.window_payload(db, window="week", start=MONDAY, now=now)


def row_for(payload, user):
    return next(r for r in payload.rows if r.user.id == user.id)


def test_week_counts_a_clean_day(db):
    tech = make_technician(db)
    make_punch(db, tech, "2026-09-14T13:00Z", "2026-09-14T21:00Z")
    make_session(db, tech, "2026-09-14T13:00Z", "2026-09-14T20:00Z")
    row = row_for(week(db), tech)
    assert (row.raw["efficiency"], row.raw["accuracy"]) == (88, 88)
    assert (row.counted_days, row.active_days) == (1, 1)
    assert row.clocked_minutes == 480


def test_idle_crew_members_are_not_listed(db):
    # The week read carries every live crew member at zero hours; an idle week
    # is not a row to rank or to grey out.
    idle = make_technician(db, "Idle")
    busy = make_technician(db, "Busy")
    make_punch(db, busy, "2026-09-14T13:00Z", "2026-09-14T21:00Z")
    ids = {r.user.id for r in week(db).rows}
    assert busy.id in ids and idle.id not in ids


def test_reviewed_estimate_stays_out(db):
    tech = make_technician(db)
    make_punch(db, tech, "2026-09-14T13:00Z", "2026-09-15T05:00Z",
               end_source="auto_clock_out", needs_review=False)
    row = row_for(week(db), tech)
    assert (row.counted_days, row.active_days) == (0, 1)
    assert row.day_reasons == {perf.PUNCH_ESTIMATED: 1}
    assert row.clocked_minutes == 0


def test_session_over_cap_flaws_every_day_it_touches(db):
    tech = make_technician(db)
    make_punch(db, tech, "2026-09-14T13:00Z", "2026-09-14T21:00Z")
    make_punch(db, tech, "2026-09-15T13:00Z", "2026-09-15T21:00Z")
    # 20:00 Mon Central (01:00Z Tue) -> 10:00 Tue Central: 14 hours.
    make_session(db, tech, "2026-09-15T01:00Z", "2026-09-15T15:00Z")
    row = row_for(week(db), tech)
    # The span is also off shift; reasons stack, and the cap reason names both days.
    assert row.day_reasons[perf.SESSION_OVER_CAP] == 2
    assert row.counted_days == 0


def test_off_shift_grace(db):
    tech = make_technician(db)
    make_punch(db, tech, "2026-09-14T13:00Z", "2026-09-14T21:00Z")
    make_session(db, tech, "2026-09-14T12:55Z", "2026-09-14T20:00Z")
    assert row_for(week(db), tech).counted_days == 1
    other = make_technician(db, "Bo")
    make_punch(db, other, "2026-09-14T13:00Z", "2026-09-14T21:00Z")
    make_session(db, other, "2026-09-14T12:54Z", "2026-09-14T20:00Z")
    row = row_for(week(db), other)
    assert row.day_reasons == {perf.CHARGED_OFF_SHIFT: 1}


def test_billed_split_by_labor_share(db):
    ann, bo = make_technician(db), make_technician(db, "Bo")
    order = make_order(db, ann, completed_at="2026-09-16T20:00Z")
    make_labor(db, order, ann, 90)
    make_labor(db, order, bo, 30)
    payload = week(db)
    assert row_for(payload, ann).raw["billed"] == Decimal("93.75")
    assert row_for(payload, bo).raw["billed"] == Decimal("31.25")


def test_billed_shares_skip_orders_with_no_real_minutes(db):
    ann = make_technician(db)
    order = make_order(db, ann, completed_at="2026-09-16T20:00Z")
    make_labor(db, order, None, 60)
    payload = week(db)
    assert all(r.raw["billed"] == 0 for r in payload.rows)


def test_flawed_order_credits_nobody(db):
    ann, bo = make_technician(db), make_technician(db, "Bo")
    order = make_order(db, ann, completed_at="2026-09-16T20:00Z")
    make_labor(db, order, ann, 60)
    make_labor(db, order, bo, 60)
    make_session(db, ann, "2026-09-16T08:00Z", "2026-09-16T20:00Z", order=order,
                 auto_closed_at="2026-09-16T20:00Z")
    payload = week(db)
    for tech in (ann, bo):
        row = row_for(payload, tech)
        assert row.raw["billed"] == 0
        assert row.excluded_orders == [(order.number, perf.SESSION_AUTO_CLOSED)]


def test_order_completed_outside_window_is_ignored(db):
    ann = make_technician(db)
    order = make_order(db, ann, completed_at="2026-09-21T20:00Z")
    make_labor(db, order, ann, 60)
    assert all(r.raw["billed"] == 0 for r in week(db).rows)


def test_month_window_in_the_past_runs_to_month_end():
    now = datetime(2026, 10, 29, 20, 0, tzinfo=timezone.utc)
    assert performance_score.resolve_window("month", date(2026, 9, 1), now) == (
        date(2026, 9, 1), date(2026, 9, 30), False)
    assert performance_score.resolve_window("month", None, now) == (
        date(2026, 10, 1), date(2026, 10, 29), True)
    with pytest.raises(ReportWeekError):
        performance_score.resolve_window("month", date(2026, 9, 2), now)
    with pytest.raises(ReportWeekError):
        performance_score.resolve_window("month", date(2026, 11, 1), now)
    assert performance_score.resolve_window("week", MONDAY, now) == (MONDAY, date(2026, 9, 20), False)


def test_month_payload_spans_the_whole_month(db):
    tech = make_technician(db)
    make_punch(db, tech, "2026-09-01T13:00Z", "2026-09-01T21:00Z")
    make_punch(db, tech, "2026-09-30T13:00Z", "2026-09-30T21:00Z")
    payload = performance_score.window_payload(
        db, window="month", start=date(2026, 9, 1), now=datetime(2026, 10, 29, tzinfo=timezone.utc))
    assert (payload.start, payload.end, payload.to_date) == (date(2026, 9, 1), date(2026, 9, 30), False)
    assert row_for(payload, tech).clocked_minutes == 960
    assert payload.floor_minutes == 60 * 60 and payload.weights == perf.WEIGHTS


def test_read_is_side_effect_free(db):
    tech = make_technician(db)
    punch = make_punch(db, tech, "2026-09-14T13:00Z", "2026-09-15T05:00Z",
                       end_source="auto_clock_out", needs_review=True)
    session = make_session(db, tech, "2026-09-14T13:00Z", "2026-09-15T01:00Z",
                           auto_closed_at="2026-09-15T01:00Z")
    week(db); week(db)
    assert not db.dirty
    assert db.get(AttendancePunch, punch.id).needs_review is True
    assert db.get(WorkOrderLaborSession, session.id).reviewed_at is None
