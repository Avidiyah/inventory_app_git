"""Charged against clocked: one week, per person per day.

Layer: services. Read-only and **side-effect-free** (spec §4) -- no sweep, no
row locks, no commit -- so the Timesheets tab may refetch it as often as it
likes, and P4b's live layer may poll it.

This is the one module that holds two of spec §8's three numbers at once, so
it is the one place they could be blurred. Three rules keep them apart:

- **Clocked** comes from `attendance_week.week_payload` and is passed through
  untouched. That module stays clocked-only; nothing here recomputes a pay
  number.
- **Tracked** is real wall-clock on jobs, from labor sessions, with a running
  session clipped at the 12-hour cap by `work_orders.capped_session_end`
  rather than by a sweep.
- **Billed is absent.** `billed_labor_minutes` rounds a *work order's
  combined* labor, across people and days; there is no per-person-per-day
  billed number, and inventing one would put an approximation of an invoice
  under a column labelled like a fact.

`delta_minutes` is `clocked - tracked` floored at zero: "on shift, not on a
job". `outside_shift_minutes` is the other direction -- charged time no punch
covers, which §9 allows and flags. Both can be non-zero on the same day.

A hand-entered labor adjustment has no start and no stop, so it is not
wall-clock: it rides in `adjustment_minutes` and is never added into tracked
or differenced into delta.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.domain import attendance, labor_day
from app.domain import work_orders as wo
from app.models import User
from app.services import attendance_week, labor_summary


@dataclass(frozen=True)
class CompareDay:
    date: date
    clocked_minutes: int
    tracked_minutes: int
    delta_minutes: int
    outside_shift_minutes: int
    adjustment_minutes: int
    needs_review: bool
    has_open: bool
    punches: list[attendance_week.WeekPunch]


@dataclass(frozen=True)
class CompareRow:
    user: User
    days: list[CompareDay]
    total_minutes: int          # clocked; the name the Hours grid already uses
    tracked_minutes: int
    delta_minutes: int


@dataclass(frozen=True)
class CompareWeek:
    week_start: date
    week_end: date
    server_now: datetime
    days: list[date]
    rows: list[CompareRow]
    totals_by_day: list[attendance_week.DayTotal]
    total_minutes: int
    tracked_minutes: int
    delta_minutes: int
    week_hours: int


def week_payload(db: Session, *, week_start: date, now: datetime) -> CompareWeek:
    """The comparison for the Central week beginning `week_start` (a Monday).

    `week_start` is resolved by `work_order_report.resolve_week` at the route,
    exactly as the Hours read resolves it -- the two sub-tabs share one week
    by construction, not by two agreeing implementations.
    """
    clocked = attendance_week.week_payload(db, week_start=week_start, now=now)
    user_ids = [row.user.id for row in clocked.rows]
    summaries: dict[uuid.UUID, list[labor_summary.DaySummary]] = (
        labor_summary.crew_range_summaries(
            db, user_ids, clocked.week_start, clocked.week_end,
            now=now, cap_running=True,
        )
        if user_ids
        else {}
    )
    bounds = {day: labor_day.day_bounds(day) for day in clocked.days}

    rows: list[CompareRow] = []
    week_tracked = 0
    week_delta = 0
    for row in clocked.rows:
        by_day = {
            summary.day: summary for summary in summaries.get(row.user.id, [])
        }
        days: list[CompareDay] = []
        row_tracked = 0
        row_delta = 0
        for day in row.days:
            summary = by_day.get(day.date)
            tracked = (
                summary.closed_minutes + summary.running_minutes if summary else 0
            )
            outside = attendance.minutes_charged_outside_shift(
                sessions=[
                    (
                        entry.started_at,
                        wo.capped_session_end(
                            entry.started_at, entry.ended_at, now=now
                        ),
                    )
                    for entry in (summary.timeline if summary else [])
                ],
                punches=[
                    (punch.started_at, punch.ended_at) for punch in day.punches
                ],
                window=bounds[day.date],
                now=now,
            )
            delta = max(0, day.clocked_minutes - tracked)
            row_tracked += tracked
            row_delta += delta
            days.append(
                CompareDay(
                    date=day.date,
                    clocked_minutes=day.clocked_minutes,
                    tracked_minutes=tracked,
                    delta_minutes=delta,
                    outside_shift_minutes=outside,
                    adjustment_minutes=(
                        summary.adjustment_minutes if summary else 0
                    ),
                    needs_review=day.needs_review,
                    has_open=day.has_open,
                    punches=day.punches,
                )
            )
        week_tracked += row_tracked
        week_delta += row_delta
        rows.append(
            CompareRow(
                user=row.user,
                days=days,
                total_minutes=row.total_minutes,
                tracked_minutes=row_tracked,
                delta_minutes=row_delta,
            )
        )

    return CompareWeek(
        week_start=clocked.week_start,
        week_end=clocked.week_end,
        server_now=clocked.server_now,
        days=clocked.days,
        rows=rows,
        totals_by_day=clocked.totals_by_day,
        total_minutes=clocked.total_minutes,
        tracked_minutes=week_tracked,
        delta_minutes=week_delta,
        week_hours=clocked.week_hours,
    )
