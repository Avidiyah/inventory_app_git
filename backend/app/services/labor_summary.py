"""One person's tracked labor for one Central calendar day.

Layer: services. Owns every session/labor aggregate query the hub reads;
every *rule* it applies lives in `app.domain.labor_day`. That split is what
lets the arithmetic be tested exhaustively without a database and leaves this
module with nothing but SQL and assembly.

Derived on read (spec D2): there is no snapshot table and no nightly job.
`work_order_labor_sessions` is already the audit record, and a supervisor
correcting a historical session therefore corrects every total derived from
it, retroactively and for free.

Three numbers come out of here and they are deliberately kept apart:

- `closed_minutes`  -- sessions with a real stop, clipped to the day.
- `running_minutes` -- the open clock's share of *this* day as of `now`.
- `adjustment_minutes` -- hand-entered `work_order_labor` rows with no
  session behind them (spec D5). Counted in the total (D15), never merged
  into tracked time.
"""

import uuid
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.domain import labor_day, list_limits
from app.models import (
    User,
    WorkOrder,
    WorkOrderLabor,
    WorkOrderLaborSession,
)
from app.services import _list_cap


@dataclass(frozen=True)
class TimelineEntry:
    """One block on the day's timeline strip.

    `minutes` is this session's share of *this* day, so a midnight crossing
    appears on both days with the two halves it actually contributed --
    which is why it is not simply `ended_at - started_at`.
    """

    work_order_id: uuid.UUID
    number: str
    started_at: datetime
    ended_at: Optional[datetime]
    auto_closed: bool
    minutes: int


@dataclass(frozen=True)
class RunningSession:
    """The caller's open clock, with the two anchors a live display needs.

    `started_at` is what the widget shows ("started 8:12 AM") and ticks
    *session* elapsed from. `day_counting_from` is what **today's total**
    ticks from -- the later of `started_at` and midnight. They differ only
    for a clock inherited from yesterday, and conflating them would report an
    hour of today's work for a session that has given today thirty minutes.
    """

    work_order_id: uuid.UUID
    number: str
    started_at: datetime
    day_counting_from: datetime


@dataclass(frozen=True)
class Adjustment:
    """A hand-entered labor row: minutes with no start, stop, or timeline
    block. Always shown on its own line, naming who recorded it."""

    minutes: int
    recorded_by_name: str
    work_order_number: str


@dataclass(frozen=True)
class DaySummary:
    day: date
    closed_minutes: int = 0
    running_minutes: int = 0
    adjustment_minutes: int = 0
    running: Optional[RunningSession] = None
    timeline: list[TimelineEntry] = field(default_factory=list)
    adjustments: list[Adjustment] = field(default_factory=list)

    @property
    def total_minutes(self) -> int:
        """The one number every hub surface shows for this day (spec D15)."""
        return self.closed_minutes + self.running_minutes + self.adjustment_minutes


def _sessions_touching_day(
    db: Session,
    technician_id: uuid.UUID,
    window_start: datetime,
    window_end: datetime,
) -> list[WorkOrderLaborSession]:
    """Every session of this person's that *overlaps* the window.

    Interval overlap, not a `started_at BETWEEN` filter: a session that began
    yesterday evening and ended this morning belongs to both days, and a range
    filter on the start alone would drop it from today entirely.
    """
    return (
        db.query(WorkOrderLaborSession)
        .options(joinedload(WorkOrderLaborSession.work_order))
        .filter(
            WorkOrderLaborSession.technician_id == technician_id,
            WorkOrderLaborSession.started_at < window_end,
            or_(
                WorkOrderLaborSession.ended_at.is_(None),
                WorkOrderLaborSession.ended_at > window_start,
            ),
        )
        .order_by(WorkOrderLaborSession.started_at)
        .all()
    )


def _adjustments_for_day(
    db: Session,
    technician_id: uuid.UUID,
    window_start: datetime,
    window_end: datetime,
) -> list[Adjustment]:
    """Labor rows with no session behind them, filed by when they were entered.

    The LEFT JOIN + `IS NULL` is the definition of "hand-entered": a stop
    writes its labor row and links it back through
    `work_order_labor_sessions.labor_id`, so an unlinked row is one a person
    typed. Filed under the Central date of `created_at` because that is the
    only date such a row carries -- see the spec's deferred-work list for why
    a Friday correction to Tuesday lands on Friday.
    """
    rows = (
        db.query(WorkOrderLabor, WorkOrder.number, User)
        .join(WorkOrder, WorkOrder.id == WorkOrderLabor.work_order_id)
        .outerjoin(
            WorkOrderLaborSession,
            WorkOrderLaborSession.labor_id == WorkOrderLabor.id,
        )
        .outerjoin(User, User.id == WorkOrderLabor.recorded_by_id)
        .filter(
            WorkOrderLabor.technician_id == technician_id,
            WorkOrderLaborSession.id.is_(None),
            WorkOrderLabor.created_at >= window_start,
            WorkOrderLabor.created_at < window_end,
        )
        .order_by(WorkOrderLabor.created_at)
        .all()
    )
    return [
        Adjustment(
            minutes=entry.minutes,
            recorded_by_name=(
                recorded_by.full_name if recorded_by is not None else "Name unavailable"
            ),
            work_order_number=number,
        )
        for entry, number, recorded_by in rows
    ]


def day_summary(
    db: Session,
    technician_id: uuid.UUID,
    day: date,
    *,
    now: datetime,
) -> DaySummary:
    """One person's tracked labor for one Central calendar day.

    `now` is injected rather than read here so the whole aggregate is
    deterministic under test and so a caller that reads several days shares
    one instant across all of them.

    Does **not** sweep stale sessions -- that is
    `services.work_orders.sweep_stale_sessions`, which the hub composer runs
    first. Keeping the repair out of the read means this function is
    side-effect-free and can be called for any day, including historical ones,
    without writing anything.
    """
    window_start, window_end = labor_day.day_bounds(day)

    closed_minutes = 0
    running_minutes = 0
    running: Optional[RunningSession] = None
    timeline: list[TimelineEntry] = []

    for session in _sessions_touching_day(db, technician_id, window_start, window_end):
        minutes = labor_day.overlap_minutes(
            session.started_at,
            session.ended_at,
            window_start,
            window_end,
            now=now,
        )
        is_running = session.ended_at is None
        if minutes <= 0 and not is_running:
            # Touched the boundary and earned nothing. Nothing to draw.
            continue

        number = session.work_order.number if session.work_order else ""
        timeline.append(
            TimelineEntry(
                work_order_id=session.work_order_id,
                number=number,
                started_at=labor_day.as_utc(session.started_at),
                ended_at=(
                    None if is_running else labor_day.as_utc(session.ended_at)
                ),
                auto_closed=session.auto_closed_at is not None,
                minutes=minutes,
            )
        )
        if is_running:
            running_minutes += minutes
            # At most one, by the partial unique index; the loop does not rely
            # on that, it just takes the latest.
            running = RunningSession(
                work_order_id=session.work_order_id,
                number=number,
                started_at=labor_day.as_utc(session.started_at),
                day_counting_from=max(
                    labor_day.as_utc(session.started_at), window_start
                ),
            )
        else:
            closed_minutes += minutes

    adjustments = _adjustments_for_day(db, technician_id, window_start, window_end)

    return DaySummary(
        day=day,
        closed_minutes=closed_minutes,
        running_minutes=running_minutes,
        adjustment_minutes=sum(a.minutes for a in adjustments),
        running=running,
        timeline=timeline,
        adjustments=adjustments,
    )


def crew_day_summaries(
    db: Session,
    technician_ids: list[uuid.UUID],
    day: date,
    *,
    now: datetime,
) -> dict[uuid.UUID, DaySummary]:
    """One `DaySummary` per technician, keyed by id.

    A loop over the existing `day_summary`, not a reimplementation -- N
    indexed lookups, N bounded by routing (a crew is tens of people, not
    thousands). The shared `now` keeps every technician's row anchored to
    the same instant, so a crew board never shows two people's clocks
    computed a second apart.
    """
    return {
        technician_id: day_summary(db, technician_id, day, now=now)
        for technician_id in technician_ids
    }


def crew_range_summaries(
    db: Session,
    technician_ids: list[uuid.UUID],
    start_day: date,
    end_day: date,
    *,
    now: datetime,
) -> dict[uuid.UUID, list[DaySummary]]:
    """Build every technician/day cell in an inclusive timesheet range.

    The work is intentionally two range-spanning queries, not one pair of
    queries per cell. Sessions are split with the same pure day arithmetic as
    :func:`day_summary`, and both result sets use the shared list ceiling.
    Every requested day is present, including zero-valued days.
    """
    if not technician_ids:
        return {}

    window_start, _ = labor_day.day_bounds(start_day)
    _, window_end = labor_day.day_bounds(end_day)
    days = [
        start_day + timedelta(days=offset)
        for offset in range((end_day - start_day).days + 1)
    ]
    buckets: dict[uuid.UUID, dict[date, DaySummary]] = {
        technician_id: {day: DaySummary(day=day) for day in days}
        for technician_id in technician_ids
    }

    sessions = _list_cap.capped(
        db.query(WorkOrderLaborSession)
        .options(joinedload(WorkOrderLaborSession.work_order))
        .filter(
            WorkOrderLaborSession.technician_id.in_(technician_ids),
            WorkOrderLaborSession.started_at < window_end,
            or_(
                WorkOrderLaborSession.ended_at.is_(None),
                WorkOrderLaborSession.ended_at > window_start,
            ),
        )
        .order_by(WorkOrderLaborSession.started_at)
        .limit(list_limits.fetch_limit())
        .all(),
        what="hub_timesheet_sessions",
    )

    for session in sessions:
        technician_bucket = buckets.get(session.technician_id)
        if technician_bucket is None:
            continue
        is_running = session.ended_at is None
        number = session.work_order.number if session.work_order else ""
        for day, minutes in labor_day.split_by_day(
            session.started_at, session.ended_at, now=now
        ):
            summary = technician_bucket.get(day)
            if summary is None:
                continue
            timeline_entry = TimelineEntry(
                work_order_id=session.work_order_id,
                number=number,
                started_at=labor_day.as_utc(session.started_at),
                ended_at=(
                    None if is_running else labor_day.as_utc(session.ended_at)
                ),
                auto_closed=session.auto_closed_at is not None,
                minutes=minutes,
            )
            running = summary.running
            if is_running:
                day_start, _ = labor_day.day_bounds(day)
                running = RunningSession(
                    work_order_id=session.work_order_id,
                    number=number,
                    started_at=labor_day.as_utc(session.started_at),
                    day_counting_from=max(
                        labor_day.as_utc(session.started_at), day_start
                    ),
                )
            technician_bucket[day] = replace(
                summary,
                closed_minutes=(
                    summary.closed_minutes + (0 if is_running else minutes)
                ),
                running_minutes=(
                    summary.running_minutes + (minutes if is_running else 0)
                ),
                running=running,
                timeline=[*summary.timeline, timeline_entry],
            )

    adjustments = _list_cap.capped(
        db.query(WorkOrderLabor, WorkOrder.number, User)
        .join(WorkOrder, WorkOrder.id == WorkOrderLabor.work_order_id)
        .outerjoin(
            WorkOrderLaborSession,
            WorkOrderLaborSession.labor_id == WorkOrderLabor.id,
        )
        .outerjoin(User, User.id == WorkOrderLabor.recorded_by_id)
        .filter(
            WorkOrderLabor.technician_id.in_(technician_ids),
            WorkOrderLaborSession.id.is_(None),
            WorkOrderLabor.created_at >= window_start,
            WorkOrderLabor.created_at < window_end,
        )
        .order_by(WorkOrderLabor.created_at)
        .limit(list_limits.fetch_limit())
        .all(),
        what="hub_timesheet_adjustments",
    )

    for labor_entry, number, recorded_by in adjustments:
        technician_bucket = buckets.get(labor_entry.technician_id)
        day = labor_day.central_date_of(labor_entry.created_at)
        if technician_bucket is None or day not in technician_bucket:
            continue
        summary = technician_bucket[day]
        adjustment = Adjustment(
            minutes=labor_entry.minutes,
            recorded_by_name=(
                recorded_by.full_name
                if recorded_by is not None
                else "Name unavailable"
            ),
            work_order_number=number,
        )
        technician_bucket[day] = replace(
            summary,
            adjustment_minutes=summary.adjustment_minutes + labor_entry.minutes,
            adjustments=[*summary.adjustments, adjustment],
        )

    return {
        technician_id: [buckets[technician_id][day] for day in days]
        for technician_id in technician_ids
    }


def last_worked(db: Session, technician_id: uuid.UUID) -> Optional[datetime]:
    """This person's most recent session `ended_at` -- nothing else (D11).

    Deliberately not a union across notes, materials, or transactions: the
    label this feeds is "Last worked," and the honest answer to that
    question is when they were last on a clock. A currently running session
    has no `ended_at` and is excluded by the `is_not(None)` filter, so a
    person mid-shift reads by their *previous* stop here -- the clock widget
    is what shows they are on the clock right now.
    """
    return db.query(func.max(WorkOrderLaborSession.ended_at)).filter(
        WorkOrderLaborSession.technician_id == technician_id,
        WorkOrderLaborSession.ended_at.is_not(None),
    ).scalar()
