"""The Hours payload: population, per-day clipping, tallies (spec §6).

Clocked minutes only (§8) -- nothing here reads a labor session or a billed
number. Day boundaries come from `domain.labor_day`, so the DST case is a
test of the reuse, not of re-derived arithmetic.
"""
import os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, datetime, timedelta, timezone

from app.domain import labor_day
from app.models import AttendancePunch, User
from app.services import attendance_week
from app.services import auth as auth_service


def _user(db, role="technician", first="Ann", last="Lee"):
    user = User(username=f"u-{uuid.uuid4().hex[:10]}",
                password_hash=auth_service.hash_password("hunter2"),
                role=role, first_name=first, last_name=last)
    db.add(user); db.flush()
    return user


def _punch(db, user, started_at, ended_at=None, needs_review=False):
    punch = AttendancePunch(id=uuid.uuid4(), user_id=user.id, started_at=started_at,
                            ended_at=ended_at, start_source="manual",
                            end_source=None if ended_at is None else "manual",
                            needs_review=needs_review)
    db.add(punch); db.flush()
    return punch


# Monday 2026-09-14 08:00 Central == 13:00 UTC (CDT).
MONDAY = date(2026, 9, 14)
NOW = datetime(2026, 9, 20, 23, 0, tzinfo=timezone.utc)


def _row_for(payload, user):
    return next(row for row in payload.rows if row.user.id == user.id)


def test_a_closed_punch_lands_on_its_own_day(db):
    user = _user(db)
    _punch(db, user, datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc),
           datetime(2026, 9, 14, 21, 0, tzinfo=timezone.utc))
    db.commit()

    payload = attendance_week.week_payload(db, week_start=MONDAY, now=NOW)

    row = _row_for(payload, user)
    monday = next(day for day in row.days if day.date == MONDAY)
    assert monday.clocked_minutes == 480
    assert row.total_minutes == 480
    assert len(monday.punches) == 1
    assert monday.punches[0].carried is False
    assert monday.punches[0].open is False


def test_a_cross_midnight_punch_carries_into_the_next_day(db):
    user = _user(db)
    # 10 PM Central Monday -> 2 AM Central Tuesday: 2h Monday, 2h Tuesday.
    _punch(db, user, datetime(2026, 9, 15, 3, 0, tzinfo=timezone.utc),
           datetime(2026, 9, 15, 7, 0, tzinfo=timezone.utc))
    db.commit()

    row = _row_for(attendance_week.week_payload(db, week_start=MONDAY, now=NOW), user)
    by_date = {day.date: day for day in row.days}
    assert by_date[MONDAY].clocked_minutes == 120
    assert by_date[MONDAY].punches[0].carried is False
    assert by_date[MONDAY + timedelta(days=1)].clocked_minutes == 120
    assert by_date[MONDAY + timedelta(days=1)].punches[0].carried is True
    assert row.total_minutes == 240


def test_an_open_punch_counts_to_now_and_is_flagged(db):
    user = _user(db)
    _punch(db, user, NOW - timedelta(hours=2))
    db.commit()

    row = _row_for(attendance_week.week_payload(db, week_start=MONDAY, now=NOW), user)
    today = next(day for day in row.days if day.date == labor_day.central_date_of(NOW))
    assert today.clocked_minutes == 120
    assert today.punches[0].open is True
    assert today.has_open is True


def test_needs_review_propagates_to_the_day(db):
    user = _user(db)
    _punch(db, user, datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc),
           datetime(2026, 9, 14, 21, 0, tzinfo=timezone.utc), needs_review=True)
    db.commit()

    row = _row_for(attendance_week.week_payload(db, week_start=MONDAY, now=NOW), user)
    monday = next(day for day in row.days if day.date == MONDAY)
    assert monday.needs_review is True
    assert monday.punches[0].needs_review is True


def test_a_legacy_punch_past_midnight_flags_the_day_not_the_punch(db):
    user = _user(db)
    _punch(db, user, datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc),
           datetime(2026, 9, 15, 18, 0, tzinfo=timezone.utc))
    db.commit()

    row = _row_for(attendance_week.week_payload(db, week_start=MONDAY, now=NOW), user)
    monday = next(day for day in row.days if day.date == MONDAY)
    assert monday.needs_review is True
    assert monday.punches[0].crosses_midnight is True
    assert monday.punches[0].needs_review is False


def test_live_crew_appear_with_zero_hours(db):
    user = _user(db, role="technician")
    db.commit()

    payload = attendance_week.week_payload(db, week_start=MONDAY, now=NOW)

    row = _row_for(payload, user)
    assert row.total_minutes == 0
    assert len(row.days) == 7
    assert all(day.clocked_minutes == 0 for day in row.days)


def test_an_admin_who_punched_is_included_though_not_crew(db):
    admin = _user(db, role="admin", first="Dee", last="Ops")
    _punch(db, admin, datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc),
           datetime(2026, 9, 14, 14, 0, tzinfo=timezone.utc))
    db.commit()

    payload = attendance_week.week_payload(db, week_start=MONDAY, now=NOW)

    assert _row_for(payload, admin).total_minutes == 60


def test_an_archived_user_without_punches_is_absent(db):
    gone = _user(db, first="Old", last="Hand")
    gone.archived_at = NOW
    db.commit()

    payload = attendance_week.week_payload(db, week_start=MONDAY, now=NOW)

    assert all(row.user.id != gone.id for row in payload.rows)


def test_rows_sort_by_name_and_totals_add_up(db):
    zed = _user(db, first="Zed", last="Aaron")
    amy = _user(db, first="Amy", last="Zephyr")
    _punch(db, zed, datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc),
           datetime(2026, 9, 14, 14, 0, tzinfo=timezone.utc))
    _punch(db, amy, datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc),
           datetime(2026, 9, 14, 15, 0, tzinfo=timezone.utc))
    db.commit()

    payload = attendance_week.week_payload(db, week_start=MONDAY, now=NOW)

    names = [f"{row.user.first_name} {row.user.last_name}" for row in payload.rows]
    assert names.index("Amy Zephyr") < names.index("Zed Aaron")
    assert payload.total_minutes == 180
    assert next(t for t in payload.totals_by_day if t.date == MONDAY).minutes == 180


def test_the_spring_forward_week_is_167_hours(db):
    # 2026-03-08 is the US spring-forward Sunday; its week starts 2026-03-02.
    payload = attendance_week.week_payload(
        db, week_start=date(2026, 3, 2),
        now=datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc))

    assert payload.week_hours == 167
    assert payload.week_start == date(2026, 3, 2)
    assert payload.week_end == date(2026, 3, 8)


# --- The midnight cap on the read (M1/M2) ---------------------------------

def test_a_punch_past_midnight_reads_closed_and_flagged_before_any_sweep(db):
    user = _user(db)
    _punch(db, user, datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc))   # 7:00 AM CDT Mon
    db.commit()
    row = _row_for(attendance_week.week_payload(db, week_start=MONDAY, now=NOW), user)
    monday = row.days[0]
    assert monday.clocked_minutes == 17 * 60
    assert monday.needs_review is True and monday.has_open is False
    assert monday.punches[0].end_source == "auto_clock_out"
    assert monday.punches[0].ended_at == datetime(2026, 9, 15, 5, 0, tzinfo=timezone.utc)
    assert row.days[1].clocked_minutes == 0
    assert db.get(AttendancePunch, monday.punches[0].id).ended_at is None   # read wrote nothing


def test_a_forgotten_sunday_punch_stays_on_sunday(db):
    user = _user(db)
    _punch(db, user, datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc))   # 7:00 AM CDT Sun
    db.commit()
    later = datetime(2026, 9, 21, 18, 0, tzinfo=timezone.utc)
    this_week = _row_for(attendance_week.week_payload(db, week_start=MONDAY, now=later), user)
    next_week = _row_for(attendance_week.week_payload(
        db, week_start=MONDAY + timedelta(days=7), now=later), user)
    assert this_week.days[6].clocked_minutes == 17 * 60
    assert next_week.days[0].clocked_minutes == 0
    assert next_week.days[0].punches == []


# --- Lunch and paid (L1-L3) -----------------------------------------------

def _closed(db, user, start, hours, waived=False):
    punch = _punch(db, user, start, start + timedelta(hours=hours))
    punch.lunch_waived = waived
    db.flush()
    return punch


MON_7AM = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)


def test_lunch_comes_off_a_long_day_and_not_a_short_one(db):
    user = _user(db)
    _closed(db, user, MON_7AM, 8)
    _closed(db, user, MON_7AM + timedelta(days=1), 5)
    db.commit()
    week = attendance_week.week_payload(db, week_start=MONDAY, now=NOW)
    row = _row_for(week, user)
    mon, tue = row.days[0], row.days[1]
    assert (mon.clocked_minutes, mon.lunch_minutes, mon.paid_minutes) == (480, 30, 450)
    assert (tue.lunch_minutes, tue.paid_minutes) == (0, 300)
    assert row.total_minutes == 780 and row.paid_minutes == 750
    assert week.totals_by_day[0].paid_minutes >= 450
    assert week.paid_minutes == sum(t.paid_minutes for t in week.totals_by_day)


def test_a_waiver_on_any_punch_waives_the_day(db):
    user = _user(db)
    _closed(db, user, MON_7AM, 4)
    _closed(db, user, MON_7AM + timedelta(hours=5), 4, waived=True)
    db.commit()
    mon = _row_for(attendance_week.week_payload(db, week_start=MONDAY, now=NOW), user).days[0]
    assert mon.lunch_waived is True
    assert (mon.lunch_minutes, mon.paid_minutes) == (0, 480)


def test_a_carried_punchs_waiver_does_not_waive_the_next_day(db):
    user = _user(db)
    # Legacy 10 PM Mon -> 6 AM Tue, waived; then a normal 8-hour Tuesday.
    _closed(db, user, datetime(2026, 9, 15, 3, 0, tzinfo=timezone.utc), 8, waived=True)
    _closed(db, user, datetime(2026, 9, 15, 13, 0, tzinfo=timezone.utc), 8)
    db.commit()
    tue = _row_for(attendance_week.week_payload(db, week_start=MONDAY, now=NOW), user).days[1]
    assert tue.lunch_waived is False and tue.lunch_minutes == 30
