"""The Admin Hours payload: one week of clocked time, per person per day.

Layer: services. Read-only and **side-effect-free** (spec §4) -- no sweep, no
row locks, no commit -- which is what will let P4's live sub-tab poll it.

Kept out of `services/attendance.py` on purpose: that module owns the punch
*writes* and their coupling to the work-order clock. This one owns the
week-shaped read, and P4 grows it with the charged column, the live roster,
and the CSV.

**Clocked only** (spec §8). Nothing here touches a labor session or
`billed_labor_minutes`. Mixing the three numbers is the likeliest way this
feature ships subtly wrong, so the module that produces the pay number does
not import the modules that produce the other two.

Every day boundary comes from `domain.labor_day`, so the week is the same
object `services.work_order_report.resolve_week` resolves rather than a
parallel definition free to drift -- and the DST week is correct because
`labor_day.day_bounds` already is.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.domain import labor_day, roles
from app.models import AttendancePunch, User


@dataclass(frozen=True)
class WeekPunch:
    """One punch, as it contributes to **one** day.

    A punch that crosses midnight appears twice -- once per day it touches --
    with `minutes` clipped to that day and `carried=True` on every day after
    the one it started on. Spec §9: the punch is owned by the day it started,
    so P3 offers its edit button only where `carried` is False.
    """

    id: uuid.UUID
    started_at: datetime
    ended_at: Optional[datetime]
    start_source: str
    end_source: Optional[str]
    needs_review: bool
    minutes: int
    carried: bool
    open: bool


@dataclass(frozen=True)
class WeekDay:
    date: date
    clocked_minutes: int
    needs_review: bool
    has_open: bool
    punches: list[WeekPunch]


@dataclass(frozen=True)
class WeekRow:
    user: User
    days: list[WeekDay]
    total_minutes: int


@dataclass(frozen=True)
class DayTotal:
    date: date
    minutes: int


@dataclass(frozen=True)
class AttendanceWeek:
    week_start: date
    week_end: date
    server_now: datetime
    days: list[date]
    rows: list[WeekRow]
    totals_by_day: list[DayTotal]
    total_minutes: int
    week_hours: int


def _week_days(week_start: date) -> list[date]:
    return [week_start + timedelta(days=offset) for offset in range(7)]


def _week_window(week_start: date) -> tuple[datetime, datetime]:
    """Half-open UTC bracket of the Central week: Monday 00:00 through the
    next Monday 00:00. Built the same way `work_order_report.week_window`
    builds it, from `labor_day.day_bounds`, so the two cannot drift."""
    start, _ = labor_day.day_bounds(week_start)
    _, end = labor_day.day_bounds(week_start + timedelta(days=6))
    return start, end


def _population(db: Session, window_start: datetime, window_end: datetime) -> list[User]:
    """Every live Supervisor and Technician, plus anyone else who punched
    inside the window.

    The first set is the crew the grid exists to pay and is present at zero
    hours, because an absent week is information. The second is spec §6's
    accepted consequence: an Admin who punches in accrues hours here even
    though the P4 roster never color-judges them.
    """
    crew = (
        db.query(User)
        .filter(
            User.role.in_(roles.WORK_ORDER_TECHNICIAN_ROLES),
            User.archived_at.is_(None),
        )
        .all()
    )
    punched_ids = {
        row[0]
        for row in db.query(AttendancePunch.user_id)
        .filter(
            AttendancePunch.started_at < window_end,
            or_(
                AttendancePunch.ended_at.is_(None),
                AttendancePunch.ended_at > window_start,
            ),
        )
        .distinct()
        .all()
    }
    extra_ids = punched_ids - {person.id for person in crew}
    extra = (
        db.query(User).filter(User.id.in_(extra_ids)).all() if extra_ids else []
    )
    return crew + extra


def _sort_key(person: User) -> str:
    return (person.full_name or "").casefold()


def week_payload(
    db: Session, *, week_start: date, now: datetime
) -> AttendanceWeek:
    """The Hours grid for the Central week beginning `week_start` (a Monday).

    `week_start` is already resolved by `work_order_report.resolve_week`, so
    a non-Monday never reaches here -- the 422 is raised at the route.
    """
    days = _week_days(week_start)
    window_start, window_end = _week_window(week_start)
    people = _population(db, window_start, window_end)
    by_id = {person.id: person for person in people}

    punches = (
        db.query(AttendancePunch)
        .filter(
            AttendancePunch.user_id.in_(list(by_id)),
            AttendancePunch.started_at < window_end,
            or_(
                AttendancePunch.ended_at.is_(None),
                AttendancePunch.ended_at > window_start,
            ),
        )
        .order_by(AttendancePunch.started_at)
        .all()
        if by_id
        else []
    )
    punches_by_user: dict[uuid.UUID, list[AttendancePunch]] = {
        person_id: [] for person_id in by_id
    }
    for punch in punches:
        punches_by_user[punch.user_id].append(punch)

    # Day bounds computed once for all seven days, not once per person-day.
    bounds = {day: labor_day.day_bounds(day) for day in days}
    totals_by_day: dict[date, int] = {day: 0 for day in days}
    rows: list[WeekRow] = []

    for person in sorted(people, key=_sort_key):
        week_days: list[WeekDay] = []
        row_total = 0
        for day in days:
            day_start, day_end = bounds[day]
            day_punches: list[WeekPunch] = []
            for punch in punches_by_user[person.id]:
                minutes = labor_day.overlap_minutes(
                    punch.started_at, punch.ended_at, day_start, day_end, now=now
                )
                if minutes == 0:
                    continue
                day_punches.append(
                    WeekPunch(
                        id=punch.id,
                        started_at=punch.started_at,
                        ended_at=punch.ended_at,
                        start_source=punch.start_source,
                        end_source=punch.end_source,
                        needs_review=bool(punch.needs_review),
                        minutes=minutes,
                        carried=labor_day.central_date_of(punch.started_at) < day,
                        open=punch.ended_at is None,
                    )
                )
            day_minutes = sum(entry.minutes for entry in day_punches)
            row_total += day_minutes
            totals_by_day[day] += day_minutes
            week_days.append(
                WeekDay(
                    date=day,
                    clocked_minutes=day_minutes,
                    needs_review=any(entry.needs_review for entry in day_punches),
                    has_open=any(entry.open for entry in day_punches),
                    punches=day_punches,
                )
            )
        rows.append(WeekRow(user=person, days=week_days, total_minutes=row_total))

    return AttendanceWeek(
        week_start=week_start,
        week_end=week_start + timedelta(days=6),
        server_now=now,
        days=days,
        rows=rows,
        totals_by_day=[DayTotal(date=day, minutes=totals_by_day[day]) for day in days],
        total_minutes=sum(totals_by_day.values()),
        # 167 or 169 across a DST transition. The grid's footer says so rather
        # than letting an Admin read a short week as missing hours.
        week_hours=round((window_end - window_start).total_seconds() / 3600),
    )
