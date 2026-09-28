"""Charged against clocked: one week, per person per day (spec §8, §9).

The clocked half is `attendance_week`'s, passed through untouched -- the last
test in this file is the guard that says so. Everything else here is the
charged half and the two gaps between them.
"""
import os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, datetime, timezone

from app.models import (
    AttendancePunch,
    User,
    WorkOrder,
    WorkOrderLabor,
    WorkOrderLaborSession,
)
from app.services import attendance_compare, attendance_week
from app.services import auth as auth_service
from app.services import work_orders as wos


def _instant(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def make_technician(db, first="Ann", last="Lee"):
    user = User(username=f"u-{uuid.uuid4().hex[:10]}",
                password_hash=auth_service.hash_password("hunter2"),
                role="technician", first_name=first, last_name=last)
    db.add(user); db.flush()
    return user


def make_punch(db, user, started_at, ended_at=None):
    punch = AttendancePunch(
        id=uuid.uuid4(), user_id=user.id, started_at=_instant(started_at),
        ended_at=None if ended_at is None else _instant(ended_at),
        start_source="manual",
        end_source=None if ended_at is None else "manual",
        needs_review=False)
    db.add(punch); db.flush()
    return punch


def _work_order(db, tech):
    return wos.get_or_create_work_order(
        db, number=f"WO-{uuid.uuid4().hex[:8]}",
        created_by_id=tech.id, assigned_to_id=tech.id)


def make_session(db, tech, started_at, ended_at=None):
    session = WorkOrderLaborSession(
        id=uuid.uuid4(), work_order_id=_work_order(db, tech).id,
        technician_id=tech.id, started_at=_instant(started_at),
        ended_at=None if ended_at is None else _instant(ended_at))
    db.add(session); db.flush()
    return session


def make_running_session(db, tech, started_at):
    return make_session(db, tech, started_at)


def make_adjustment(db, tech, *, minutes, created_at):
    """A hand-entered labor row: no session points at it (spec D5)."""
    entry = WorkOrderLabor(
        id=uuid.uuid4(), work_order_id=_work_order(db, tech).id,
        technician_id=tech.id, minutes=minutes, recorded_by_id=tech.id,
        created_at=_instant(created_at))
    db.add(entry); db.flush()
    return entry


def reload_session(db, tech):
    return (db.query(WorkOrderLaborSession)
            .filter(WorkOrderLaborSession.technician_id == tech.id)
            .one())


def _row_for(payload, user):
    """The grid holds every live crew member, not only the seeded one."""
    return next(row for row in payload.rows if row.user.id == user.id)


MONDAY = date(2026, 9, 14)
NOW = datetime(2026, 9, 16, 15, 0, tzinfo=timezone.utc)


def test_a_day_on_shift_and_on_a_job_has_no_gap_in_either_direction(db):
    tech = make_technician(db)
    make_punch(db, tech, "2026-09-14T13:00Z", "2026-09-14T21:00Z")      # 8h
    make_session(db, tech, "2026-09-14T13:00Z", "2026-09-14T21:00Z")    # 8h
    week = attendance_compare.week_payload(db, week_start=MONDAY, now=NOW)

    monday = _row_for(week, tech).days[0]
    assert (monday.clocked_minutes, monday.tracked_minutes) == (480, 480)
    assert monday.delta_minutes == 0
    assert monday.outside_shift_minutes == 0


def test_delta_is_clocked_minus_tracked_and_means_on_shift_not_on_a_job(db):
    tech = make_technician(db)
    make_punch(db, tech, "2026-09-14T13:00Z", "2026-09-14T21:00Z")      # 8h
    make_session(db, tech, "2026-09-14T13:00Z", "2026-09-14T19:00Z")    # 6h
    week = attendance_compare.week_payload(db, week_start=MONDAY, now=NOW)

    row = _row_for(week, tech)
    assert row.days[0].delta_minutes == 120
    assert row.delta_minutes == 120
    assert week.delta_minutes == 120


def test_charging_outside_the_shift_is_flagged_and_never_makes_delta_negative(db):
    tech = make_technician(db)
    make_punch(db, tech, "2026-09-14T14:00Z", "2026-09-14T21:00Z")      # 7h
    make_session(db, tech, "2026-09-14T13:00Z", "2026-09-14T21:00Z")    # 8h
    week = attendance_compare.week_payload(db, week_start=MONDAY, now=NOW)

    monday = _row_for(week, tech).days[0]
    assert monday.delta_minutes == 0          # floored, never negative
    assert monday.outside_shift_minutes == 60


def test_both_gaps_can_be_non_zero_on_the_same_day(db):
    # An hour charged before punching in, and an idle hour after lunch.
    tech = make_technician(db)
    make_punch(db, tech, "2026-09-14T14:00Z", "2026-09-14T22:00Z")      # 8h
    make_session(db, tech, "2026-09-14T13:00Z", "2026-09-14T20:00Z")    # 7h
    week = attendance_compare.week_payload(db, week_start=MONDAY, now=NOW)

    monday = _row_for(week, tech).days[0]
    assert monday.outside_shift_minutes == 60
    assert monday.delta_minutes == 60


def test_an_adjustment_is_carried_beside_the_two_wall_clock_numbers(db):
    tech = make_technician(db)
    make_punch(db, tech, "2026-09-14T13:00Z", "2026-09-14T21:00Z")
    make_adjustment(db, tech, minutes=30, created_at="2026-09-14T15:00Z")
    week = attendance_compare.week_payload(db, week_start=MONDAY, now=NOW)

    monday = _row_for(week, tech).days[0]
    assert monday.adjustment_minutes == 30
    assert monday.tracked_minutes == 0        # no session, so no wall clock
    assert monday.delta_minutes == 480        # the whole shift reads as off-job


def test_a_forgotten_clock_is_capped_without_writing_anything(db):
    tech = make_technician(db)
    make_running_session(db, tech, "2026-09-14T13:00Z")
    later = datetime(2026, 9, 16, 13, 0, tzinfo=timezone.utc)

    week = attendance_compare.week_payload(db, week_start=MONDAY, now=later)
    tracked = sum(day.tracked_minutes for day in _row_for(week, tech).days)
    assert tracked == 720
    # side-effect-free (spec §4): the session is still open in the database
    db.expire_all()
    assert reload_session(db, tech).ended_at is None


def test_the_clocked_half_is_exactly_what_the_hours_grid_reads(db):
    # One source for the pay number. If these ever differ, two tabs of the
    # same tab disagree about payroll.
    tech = make_technician(db)
    make_punch(db, tech, "2026-09-14T13:00Z", "2026-09-14T21:00Z")
    clocked = attendance_week.week_payload(db, week_start=MONDAY, now=NOW)
    compared = attendance_compare.week_payload(db, week_start=MONDAY, now=NOW)

    assert compared.total_minutes == clocked.total_minutes
    assert [d.minutes for d in compared.totals_by_day] == [
        d.minutes for d in clocked.totals_by_day
    ]
    assert _row_for(compared, tech).days[0].punches == (
        _row_for(clocked, tech).days[0].punches
    )


# --- Pending review: days resting on a forgotten clock --------------------

def _monday(db, tech, now=NOW):
    week = attendance_compare.week_payload(db, week_start=MONDAY, now=now)
    return week, _row_for(week, tech).days[0]


def test_an_ordinary_day_is_not_pending(db):
    tech = make_technician(db)
    make_punch(db, tech, "2026-09-14T13:00Z", "2026-09-14T21:00Z")
    make_session(db, tech, "2026-09-14T13:00Z", "2026-09-14T21:00Z")
    week, monday = _monday(db, tech)
    assert monday.pending_review is False
    assert week.reviewable_count == 0


def test_an_unaccepted_auto_closed_session_makes_its_day_pending(db):
    tech = make_technician(db)
    session = make_session(db, tech, "2026-09-14T13:00Z", "2026-09-15T01:00Z")
    session.auto_closed_at = _instant("2026-09-15T02:00Z")
    db.flush()
    week, monday = _monday(db, tech)
    assert monday.pending_review is True
    # One session spanning two days is still one thing to review.
    assert week.reviewable_count == 1

    session.reviewed_at = _instant("2026-09-16T12:00Z")
    db.flush()
    week, monday = _monday(db, tech)
    assert monday.pending_review is False
    assert week.reviewable_count == 0


def test_a_running_clock_past_the_cap_is_pending_before_any_sweep(db):
    tech = make_technician(db)
    make_running_session(db, tech, "2026-09-14T13:00Z")
    week, monday = _monday(db, tech)
    assert monday.pending_review is True
    assert week.reviewable_count == 1


def test_a_self_reported_punch_makes_its_day_pending(db):
    tech = make_technician(db)
    punch = make_punch(db, tech, "2026-09-14T13:00Z", "2026-09-14T21:00Z")
    punch.needs_review = True
    db.flush()
    week, monday = _monday(db, tech)
    assert monday.pending_review is True
    assert week.reviewable_count == 1


def test_an_open_punch_from_an_earlier_day_is_pending_but_not_reviewable(db):
    tech = make_technician(db)
    make_punch(db, tech, "2026-09-14T13:00Z")
    week, monday = _monday(db, tech)
    assert monday.pending_review is True
    assert week.reviewable_count == 0


def test_todays_open_punch_is_an_ordinary_shift(db):
    tech = make_technician(db)
    make_punch(db, tech, "2026-09-16T13:00Z")
    week = attendance_compare.week_payload(db, week_start=MONDAY, now=NOW)
    wednesday = _row_for(week, tech).days[2]
    assert wednesday.has_open is True
    assert wednesday.pending_review is False


def test_mark_week_reviewed_accepts_every_estimate_but_the_open_punch(db):
    from app.models import AttendancePunchEdit
    from app.services import attendance as attendance_service

    admin = make_technician(db, "Ada", "Min")
    admin.role = "admin"
    tech = make_technician(db)
    punch = make_punch(db, tech, "2026-09-14T13:00Z", "2026-09-14T21:00Z")
    punch.needs_review = True
    make_running_session(db, tech, "2026-09-14T13:00Z")   # swept, then accepted
    other = make_technician(db, "Bo", "Diaz")
    make_punch(db, other, "2026-09-15T13:00Z")             # stale open punch
    db.commit()

    result = attendance_service.mark_week_reviewed(
        db, actor=admin, week_start=MONDAY, now=NOW)

    assert (result.punches, result.sessions) == (1, 1)
    db.expire_all()
    assert db.get(AttendancePunch, punch.id).needs_review is False
    audit = db.query(AttendancePunchEdit).filter_by(punch_id=punch.id).one()
    assert (audit.field, audit.reason) == ("needs_review", "Bulk reviewed")
    session = reload_session(db, tech)
    assert session.ended_at is not None and session.reviewed_at is not None

    week = attendance_compare.week_payload(db, week_start=MONDAY, now=NOW)
    assert week.reviewable_count == 0
    assert _row_for(week, tech).days[0].pending_review is False
    assert _row_for(week, other).days[1].pending_review is True
