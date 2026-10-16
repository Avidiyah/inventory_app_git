"""Charged against clocked: one week, per person per day.

Layer: services. Read-only and **side-effect-free** (spec §4) -- no sweep, no
row locks, no commit -- so the Timesheets tab may refetch it as often as it
likes, and P4b's live layer may poll it.

This is the one module that holds two of spec §8's three numbers at once, so
it is the one place they could be blurred. Three rules keep them apart:

- **Clocked** comes from `attendance_week.week_payload`; each day is passed
  through untouched. That module stays clocked-only; nothing here recomputes
  a day's pay number. The *totals* are summed here, over unflagged days only.
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

`pending_review` marks a day whose numbers rest on a forgotten clock: a
flagged punch (`needs_review`, which a midnight close always is), or an
auto-closed session no Admin has accepted (`attendance.day_pending_review`).
Every total here -- row, day, week, CSV week column -- sets such a day aside
whole (spec 2026-10-16 U9); dropping only the suspect item would push the rest
of the shift into "uncharged" and misprice it the other way.
"""

import csv
import io
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.domain import attendance, labor_day
from app.domain import work_orders as wo
from app.models import User
from app.services import attendance_week, labor_summary


@dataclass(frozen=True)
class CompareDay:
    date: date
    clocked_minutes: int
    lunch_minutes: int
    lunch_waived: bool
    paid_minutes: int
    tracked_minutes: int
    delta_minutes: int
    outside_shift_minutes: int
    adjustment_minutes: int
    needs_review: bool
    has_open: bool
    pending_review: bool
    punches: list[attendance_week.WeekPunch]


@dataclass(frozen=True)
class CompareRow:
    user: User
    days: list[CompareDay]
    total_minutes: int          # clocked; the name the Hours grid already uses
    paid_minutes: int
    tracked_minutes: int
    delta_minutes: int
    adjustment_minutes: int = 0


@dataclass(frozen=True)
class CompareWeek:
    week_start: date
    week_end: date
    server_now: datetime
    days: list[date]
    rows: list[CompareRow]
    totals_by_day: list[attendance_week.DayTotal]
    total_minutes: int
    paid_minutes: int
    tracked_minutes: int
    delta_minutes: int
    week_hours: int
    labor_rate: Decimal         # the leaderboard's $/hour; billing's own rate
    # What "Mark all reviewed" would accept: flagged punches (midnight closes
    # included -- review sweeps them first) plus unaccepted auto-closed
    # sessions.
    reviewable_count: int


def week_payload(db: Session, *, week_start: date, now: datetime) -> CompareWeek:
    """The comparison for the Central week beginning `week_start` (a Monday).

    `week_start` is resolved by `work_order_report.resolve_week` at the route,
    exactly as the Hours read resolves it -- the leaderboard and Hours share one week
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
    totals_minutes = {day: 0 for day in clocked.days}
    totals_paid = {day: 0 for day in clocked.days}
    reviewable: set = set()
    for row in clocked.rows:
        by_day = {
            summary.day: summary for summary in summaries.get(row.user.id, [])
        }
        days: list[CompareDay] = []
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
            flagged_punches = {p.id for p in day.punches if p.needs_review}
            flagged_sessions = {
                (row.user.id, entry.work_order_id, entry.started_at)
                for entry in (summary.timeline if summary else [])
                if entry.needs_review
            }
            reviewable |= flagged_punches | flagged_sessions
            pending = attendance.day_pending_review(
                day.punches, summary.timeline if summary else [])
            days.append(
                CompareDay(
                    date=day.date,
                    clocked_minutes=day.clocked_minutes,
                    lunch_minutes=day.lunch_minutes,
                    lunch_waived=day.lunch_waived,
                    paid_minutes=day.paid_minutes,
                    tracked_minutes=tracked,
                    delta_minutes=delta,
                    outside_shift_minutes=outside,
                    adjustment_minutes=(
                        summary.adjustment_minutes if summary else 0
                    ),
                    needs_review=day.needs_review,
                    has_open=day.has_open,
                    pending_review=pending,
                    punches=day.punches,
                )
            )
        # The totals rule (spec U9): a pending day is shown, never added.
        counted = [day for day in days if not day.pending_review]
        rows.append(
            CompareRow(
                user=row.user,
                days=days,
                total_minutes=sum(d.clocked_minutes for d in counted),
                paid_minutes=sum(d.paid_minutes for d in counted),
                tracked_minutes=sum(d.tracked_minutes for d in counted),
                delta_minutes=sum(d.delta_minutes for d in counted),
                adjustment_minutes=sum(d.adjustment_minutes for d in counted),
            )
        )
        for day in counted:
            totals_minutes[day.date] += day.clocked_minutes
            totals_paid[day.date] += day.paid_minutes

    return CompareWeek(
        week_start=clocked.week_start,
        week_end=clocked.week_end,
        server_now=clocked.server_now,
        days=clocked.days,
        rows=rows,
        totals_by_day=[
            attendance_week.DayTotal(date=day, minutes=totals_minutes[day],
                                     paid_minutes=totals_paid[day])
            for day in clocked.days
        ],
        total_minutes=sum(r.total_minutes for r in rows),
        paid_minutes=sum(r.paid_minutes for r in rows),
        tracked_minutes=sum(r.tracked_minutes for r in rows),
        delta_minutes=sum(r.delta_minutes for r in rows),
        week_hours=clocked.week_hours,
        labor_rate=wo.LABOR_RATE,
        reviewable_count=len(reviewable),
    )


def _hm(total_minutes: int) -> str:
    """Payroll-facing `H:MM`, the convention the hub's exports already use."""
    hours, minutes = divmod(max(0, round(total_minutes)), 60)
    return f"{hours}:{minutes:02d}"


# Seven metric rows per person, always, in this order, then "Pending review".
# A fixed block is what makes the
# file parseable: a metric that appears only when non-zero turns every reader
# into a state machine.
_METRICS: tuple[tuple[str, str], ...] = (
    ("Clocked", "clocked_minutes"),
    ("Lunch", "lunch_minutes"),
    ("Paid", "paid_minutes"),
    ("Charged", "tracked_minutes"),
    ("Off job", "delta_minutes"),
    ("Charged outside shift", "outside_shift_minutes"),
    ("Adjustments", "adjustment_minutes"),
)
PENDING_LABEL = "Pending review"


def week_csv(payload: CompareWeek) -> str:
    """The comparison as payroll-friendly CSV: eight rows per person,
    seven day columns, a week column, then the same block for the company.

    One header row and nothing above it -- a title line is the first thing a
    spreadsheet import gets wrong.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(
        ["Person", "Metric", *(day.isoformat() for day in payload.days), "Week"]
    )

    company: dict[str, list[int]] = {
        label: [0] * len(payload.days) for label, _ in _METRICS
    }
    for row in payload.rows:
        by_date = {day.date: day for day in row.days}
        name = row.user.full_name
        pending = [day in by_date and by_date[day].pending_review
                   for day in payload.days]
        for label, field in _METRICS:
            cells = [getattr(by_date[day], field) if day in by_date else 0
                     for day in payload.days]
            # Every day is printed; only unflagged days reach the sums (U9).
            counted = [0 if flag else value for value, flag in zip(cells, pending)]
            for index, value in enumerate(counted):
                company[label][index] += value
            writer.writerow(
                [name, label, *(_hm(value) for value in cells), _hm(sum(counted))]
            )
        writer.writerow([name, PENDING_LABEL, *("yes" if flag else "" for flag in pending),
                         str(sum(pending)) if any(pending) else ""])

    for label, _ in _METRICS:
        cells = company[label]
        writer.writerow(
            ["Company total", label, *(_hm(value) for value in cells),
             _hm(sum(cells))]
        )
    return buffer.getvalue()
