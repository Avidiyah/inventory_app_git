"""The performance window: one week or one month to date, scored per person.

Layer: services. Read-only and **side-effect-free** -- no sweep, no row
locks, no commit -- so the Leaderboards tab may refetch it as often as it
likes. Every rule lives in `domain.performance`; this module is SQL and
assembly.

Punches come from `attendance_week.week_payload`, one call per Monday the
window touches, so the clocked number here is the Hours grid's number.
Sessions and hand-keyed labor come from `labor_summary.crew_range_summaries`
over the whole range. Billed dollars come from work orders **completed** in
the window: each order's real labor charge (`work_orders_smr.labor_split`,
Skilled-Technician lines left out) is split among its technicians by their
labor minutes. An order with one flawed job clock earns nothing for anyone
until that clock is fixed (spec, 2026-10-29).
"""

import calendar
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy.orm import Session, joinedload

from app.domain import attendance, labor_day, performance
from app.domain import work_orders as wo
from app.domain import work_orders_smr as smr
from app.domain.errors import ReportWeekError
from app.models import User, WorkOrder
from app.services import attendance_week, labor_summary, work_order_report

_CENT = Decimal("0.01")


@dataclass(frozen=True)
class PersonRow(performance.PersonScore):
    """One scored person with the row's user: the score's fields, plus `user`."""
    user: User = None  # type: ignore[assignment]  # always set; default only for dataclass ordering


@dataclass(frozen=True)
class PerformanceWindow:
    window: str
    start: date
    end: date
    to_date: bool
    server_now: datetime
    weights: dict[str, int]
    floor_minutes: int
    rows: list[PersonRow]


def resolve_window(window: str, start: Optional[date], now: datetime) -> tuple[date, date, bool]:
    """`(first day, last day, still filling)` for the window the request names.

    Week: the Monday contract of `work_order_report.resolve_week`. Month: the
    first of a month no later than the current Central one; absent means the
    month in progress. A past month runs to its last day; the current one
    runs to today."""
    if window == "week":
        monday = work_order_report.resolve_week(start, now)
        return monday, monday + timedelta(days=6), False
    today = labor_day.central_date_of(now)
    first = today.replace(day=1) if start is None else start
    if first.day != 1:
        raise ReportWeekError("start must be the first of a month (YYYY-MM-DD).")
    if first > today:
        raise ReportWeekError("start cannot be in the future.")
    last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
    return first, min(last, today), last > today


def _mondays(start: date, end: date) -> list[date]:
    monday = labor_day.week_bounds_containing(start)[0]
    out = []
    while monday <= end:
        out.append(monday)
        monday += timedelta(days=7)
    return out


def _session_reason(session, now: datetime) -> Optional[str]:
    """Why a work order's session makes the order untrusted, or None."""
    running_past_cap = session.ended_at is None and wo.session_needs_review(
        session.started_at, session.ended_at, auto_closed_at=None, reviewed_at=None, now=now)
    if session.auto_closed_at is not None or running_past_cap:
        return performance.SESSION_AUTO_CLOSED
    if performance.session_is_over_cap(session):
        return performance.SESSION_OVER_CAP
    return None


def _billed_shares(
    db: Session, start: date, end: date, now: datetime,
) -> tuple[dict[uuid.UUID, Decimal], dict[uuid.UUID, list[tuple[str, str]]]]:
    """Per technician: dollars credited, and the orders left out with why."""
    window_start, _ = labor_day.day_bounds(start)
    _, window_end = labor_day.day_bounds(end)
    orders = (
        db.query(WorkOrder)
        .options(joinedload(WorkOrder.labor_entries), joinedload(WorkOrder.labor_sessions))
        .filter(WorkOrder.completed_at.isnot(None),
                WorkOrder.completed_at >= window_start,
                WorkOrder.completed_at < window_end)
        .all()
    )
    dollars: dict[uuid.UUID, Decimal] = {}
    excluded: dict[uuid.UUID, list[tuple[str, str]]] = {}
    for order in orders:
        real = [e for e in order.labor_entries if not smr.is_skilled(e)]
        technicians = {e.technician_id for e in real}
        reason = next((r for r in (_session_reason(s, now) for s in order.labor_sessions) if r), None)
        if reason:
            for tech_id in technicians | {s.technician_id for s in order.labor_sessions}:
                excluded.setdefault(tech_id, []).append((order.number, reason))
            continue
        split = smr.labor_split(order.labor_entries)
        if split.real_minutes == 0:
            continue
        charge = wo.labor_charge(split.real_minutes)
        for tech_id in technicians:
            minutes = sum(e.minutes for e in real if e.technician_id == tech_id)
            dollars[tech_id] = dollars.get(tech_id, Decimal(0)) + charge * minutes / split.real_minutes
    return ({k: v.quantize(_CENT, rounding=ROUND_HALF_UP) for k, v in dollars.items()}, excluded)


def window_payload(db: Session, *, window: str, start: Optional[date], now: datetime) -> PerformanceWindow:
    first, last, to_date = resolve_window(window, start, now)
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]

    # Punches: the Hours grid's own read, one Monday at a time, clipped to the window.
    people: dict[uuid.UUID, User] = {}
    punch_days: dict[uuid.UUID, dict[date, attendance_week.WeekDay]] = {}
    for monday in _mondays(first, last):
        clocked = attendance_week.week_payload(db, week_start=monday, now=now)
        for row in clocked.rows:
            people[row.user.id] = row.user
            per_day = punch_days.setdefault(row.user.id, {})
            for day in row.days:
                if first <= day.date <= last:
                    per_day[day.date] = day

    dollars, excluded_orders = _billed_shares(db, first, last, now)
    for tech_id in set(dollars) | set(excluded_orders):
        if tech_id not in people:
            user = db.get(User, tech_id)
            if user is not None:
                people[tech_id] = user

    summaries = (
        labor_summary.crew_range_summaries(db, list(people), first, last, now=now, cap_running=True)
        if people else {}
    )
    bounds = {day: labor_day.day_bounds(day) for day in days}

    inputs: list[performance.PersonInput] = []
    for user_id, user in people.items():
        by_day = {s.day: s for s in summaries.get(user_id, [])}
        clocked = sessions = adjustments = counted = active = 0
        reasons: dict[str, int] = {}
        for day in days:
            punch_day = punch_days.get(user_id, {}).get(day)
            summary = by_day.get(day)
            punches = punch_day.punches if punch_day else []
            timeline = summary.timeline if summary else []
            day_clocked = punch_day.clocked_minutes if punch_day else 0
            day_sessions = (summary.closed_minutes + summary.running_minutes) if summary else 0
            day_adjust = summary.adjustment_minutes if summary else 0
            if not (day_clocked or day_sessions or day_adjust):
                continue
            active += 1
            outside = attendance.minutes_charged_outside_shift(
                sessions=[(e.started_at, wo.capped_session_end(e.started_at, e.ended_at, now=now))
                          for e in timeline],
                punches=[(p.started_at, p.ended_at) for p in punches],
                window=bounds[day], now=now)
            exclusions = performance.day_exclusions(
                punches=punches, timeline=timeline, clocked_minutes=day_clocked,
                charged_minutes=day_sessions + day_adjust, outside_shift_minutes=outside, now=now)
            if exclusions:
                for code in exclusions:
                    reasons[code] = reasons.get(code, 0) + 1
                continue
            counted += 1
            clocked += day_clocked
            sessions += day_sessions
            adjustments += day_adjust
        # An idle window is not a row: the week read lists every live crew
        # member at zero hours, and nobody is ranked, or greyed, for absence.
        if not (active or user_id in dollars or user_id in excluded_orders):
            continue
        inputs.append(performance.PersonInput(
            user_id=user_id, clocked_minutes=clocked, session_minutes=sessions,
            adjustment_minutes=adjustments, billed_dollars=dollars.get(user_id, Decimal(0)),
            counted_days=counted, active_days=active, day_reasons=reasons,
            excluded_orders=excluded_orders.get(user_id, [])))

    scored = performance.score_rows(inputs, window=window)
    return PerformanceWindow(
        window=window, start=first, end=last, to_date=to_date, server_now=now,
        weights=dict(performance.WEIGHTS), floor_minutes=performance.FLOOR_MINUTES[window],
        rows=[PersonRow(user=people[s.user_id], **vars(s)) for s in scored],
    )
