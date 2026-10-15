"""One crew member's week, one row per day: completed work orders, charged
labor, clocked time. Spec: 2026-10-15-user-profile-week-design.md.

Layer: services. Read-only and side-effect-free -- no sweep, no row locks,
no commit (D8); an open labor session is clipped at the cap on read.

Composition only, no new maths: the clocked column is the target's row of
`attendance_week.week_payload`, the charged column is
`labor_summary.crew_range_summaries` collapsed per work order per day, and
the completed column is one query bucketed by `labor_day.central_date_of`.
Wall-clock minutes throughout; never `billed_labor_minutes` (D9).

ponytail: whole-population attendance read; add a `user_ids` filter to
`attendance_week._population` if the roster grows past ~100.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.domain import labor_day, roles
from app.domain.errors import PersonNotProfilableError, UserNotFoundError
from app.models import User, WorkOrder, WorkOrderTechnician
from app.services import attendance_week, labor_summary

PROFILABLE_ROLES: tuple[str, ...] = (
    *roles.WORK_ORDER_TECHNICIAN_ROLES, roles.ROLE_TECHFM_OA, roles.ROLE_ADMIN,
)


@dataclass(frozen=True)
class PersonCompleted:
    work_order_id: uuid.UUID
    number: str
    location: str | None
    completed_at: datetime
    status: str
    archived: bool


@dataclass(frozen=True)
class PersonChargedSpan:
    started_at: datetime
    ended_at: datetime | None


@dataclass(frozen=True)
class PersonCharged:
    work_order_id: uuid.UUID
    number: str
    minutes: int
    auto_closed: bool
    running: bool
    spans: list[PersonChargedSpan]


@dataclass(frozen=True)
class PersonDay:
    date: date
    clocked_minutes: int
    lunch_minutes: int
    paid_minutes: int
    charged_minutes: int
    adjustment_minutes: int
    completed_count: int
    needs_review: bool
    has_open: bool
    completed: list[PersonCompleted]
    charged: list[PersonCharged]
    adjustments: list[labor_summary.Adjustment]
    punches: list[attendance_week.WeekPunch]


@dataclass(frozen=True)
class PersonWeek:
    user: User
    archived: bool
    week_start: date
    week_end: date
    server_now: datetime
    days: list[PersonDay]
    total_clocked_minutes: int
    total_paid_minutes: int
    total_charged_minutes: int
    total_adjustment_minutes: int
    total_completed: int
    reviewable: bool


def _collapse_charged(timeline: list[labor_summary.TimelineEntry]) -> list[PersonCharged]:
    """One line per work order per day, in first-seen order."""
    by_wo: dict[uuid.UUID, PersonCharged] = {}
    for entry in timeline:
        prior = by_wo.get(entry.work_order_id)
        by_wo[entry.work_order_id] = PersonCharged(
            work_order_id=entry.work_order_id,
            number=entry.number,
            minutes=(prior.minutes if prior else 0) + entry.minutes,
            auto_closed=(prior.auto_closed if prior else False) or entry.auto_closed,
            running=(prior.running if prior else False) or entry.ended_at is None,
            spans=[*(prior.spans if prior else []),
                   PersonChargedSpan(entry.started_at, entry.ended_at)],
        )
    return list(by_wo.values())


def _completed_by_day(
    db: Session, user_id: uuid.UUID, window_start: datetime, window_end: datetime
) -> dict[date, list[PersonCompleted]]:
    rows = (
        db.query(WorkOrder)
        .join(WorkOrderTechnician, WorkOrderTechnician.work_order_id == WorkOrder.id)
        .filter(
            WorkOrderTechnician.technician_id == user_id,
            WorkOrder.completed_at.isnot(None),
            WorkOrder.completed_at >= window_start,
            WorkOrder.completed_at < window_end,
        )
        .order_by(WorkOrder.completed_at)
        .all()
    )
    buckets: dict[date, list[PersonCompleted]] = {}
    for work_order in rows:
        completed_at = labor_day.as_utc(work_order.completed_at)
        buckets.setdefault(labor_day.central_date_of(completed_at), []).append(
            PersonCompleted(
                work_order_id=work_order.id, number=work_order.number,
                location=work_order.location, completed_at=completed_at,
                status=work_order.status, archived=work_order.archived_at is not None,
            )
        )
    return buckets


def week_payload(
    db: Session, *, user_id: uuid.UUID, week_start: date, now: datetime
) -> PersonWeek:
    """`week_start` is a Monday already resolved by
    `work_order_report.resolve_week`. Raises `UserNotFoundError` (404) and
    `PersonNotProfilableError` (403, Owner target) here, not at the
    route, so no future caller can skip the check."""
    person = db.get(User, user_id)
    if person is None:
        raise UserNotFoundError("User not found.")
    if person.role not in PROFILABLE_ROLES:
        raise PersonNotProfilableError("Only crew accounts have a profile.")

    week_end = week_start + timedelta(days=6)
    window_start, _ = labor_day.day_bounds(week_start)
    _, window_end = labor_day.day_bounds(week_end)
    days = [week_start + timedelta(days=i) for i in range(7)]

    clocked = attendance_week.week_payload(db, week_start=week_start, now=now)
    row = next((r for r in clocked.rows if r.user.id == user_id), None)
    clocked_by_day = {d.date: d for d in row.days} if row else {}
    summaries = labor_summary.crew_range_summaries(
        db, [user_id], week_start, week_end, now=now, cap_running=True,
    ).get(user_id, [])
    summary_by_day = {s.day: s for s in summaries}
    completed_by_day = _completed_by_day(db, user_id, window_start, window_end)

    out: list[PersonDay] = []
    for day in days:
        clocked_day = clocked_by_day.get(day)
        summary = summary_by_day.get(day, labor_summary.DaySummary(day=day))
        completed = completed_by_day.get(day, [])
        out.append(PersonDay(
            date=day,
            clocked_minutes=clocked_day.clocked_minutes if clocked_day else 0,
            lunch_minutes=clocked_day.lunch_minutes if clocked_day else 0,
            paid_minutes=clocked_day.paid_minutes if clocked_day else 0,
            charged_minutes=summary.closed_minutes + summary.running_minutes,
            adjustment_minutes=summary.adjustment_minutes,
            completed_count=len(completed),
            needs_review=bool(clocked_day and clocked_day.needs_review)
                or any(e.needs_review for e in summary.timeline),
            has_open=bool(clocked_day and clocked_day.has_open),
            completed=completed,
            charged=_collapse_charged(summary.timeline),
            adjustments=list(summary.adjustments),
            punches=list(clocked_day.punches) if clocked_day else [],
        ))

    return PersonWeek(
        user=person,
        archived=person.archived_at is not None,
        week_start=week_start,
        week_end=week_end,
        server_now=now,
        days=out,
        total_clocked_minutes=sum(d.clocked_minutes for d in out),
        total_paid_minutes=sum(d.paid_minutes for d in out),
        total_charged_minutes=sum(d.charged_minutes for d in out),
        total_adjustment_minutes=sum(d.adjustment_minutes for d in out),
        total_completed=sum(d.completed_count for d in out),
        reviewable=any(d.needs_review for d in out),
    )
