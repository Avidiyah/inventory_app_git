"""Composes the User Hub's payloads.

Layer: services. Called by `app/routers/hub.py`. Owns no rules of its own --
day arithmetic is `domain.labor_day`, the labor aggregate is
`services.labor_summary`, tool custody is `services.tools`, and the cap
sweep is `services.work_orders`. This module's whole job is to run them in
the right order and hand back one object the router can serialise, so the
router stays the thin translation layer every other one in this app is.

The module now composes the personal block, the routed crew board, and the
same crew's timesheets. The Admin-wide payload remains a later phase.
"""

import csv
import io
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.domain import hub as hub_domain
from app.domain import labor_day
from app.domain import work_orders as wo
from app.domain.errors import TimesheetRangeInvalidError, TimesheetRangeTooLargeError
from app.models import User, WorkOrder, WorkOrderLaborSession, WorkOrderTechnician
from app.services import labor_summary
from app.services import tools as tools_service
from app.services import work_orders as work_orders_service

# Work-order statuses that read as "the crew is on it" -- a stale one has
# gone quiet while someone was supposed to be working. Created/Assigned
# haven't started, and Ready/Completed/Review are past the point a
# supervisor would call "stuck."
_STALE_ELIGIBLE_STATUSES = (wo.STATUS_IN_PROGRESS, wo.STATUS_ON_HOLD)

_STATUS_LABELS = {
    wo.STATUS_IN_PROGRESS: "In-Progress",
    wo.STATUS_ON_HOLD: "On Hold",
}

# Picker order. The spec names the first two; the other two are startable as
# well, so they follow in the order somebody would actually reach for them --
# what I am on, what I paused, what I have been given, what exists.
_STARTABLE_ORDER = (
    wo.STATUS_IN_PROGRESS,
    wo.STATUS_ON_HOLD,
    wo.STATUS_ASSIGNED,
    wo.STATUS_CREATED,
)


@dataclass(frozen=True)
class AssignedCounts:
    """A total and two subsets of it -- **not** three disjoint buckets.

    `assigned` is every non-archived work order the caller is an assigned
    technician on, whatever its status; the other two count members of that
    same set. So "8 assigned, 1 in progress, 2 ready" describes 8 work
    orders, not 11, and the tiles are labelled to match.
    """

    assigned: int
    in_progress: int
    ready_to_complete: int


@dataclass(frozen=True)
class StartableWorkOrder:
    """One option in the `Start on...` picker.

    Carries the raw place fields rather than a composed string: there is no
    server-side location composer, and `static/views/workOrders.js::placeMeta`
    already owns that formatting for every card in the app. One composer, one
    spelling of an address.
    """

    work_order_id: uuid.UUID
    number: str
    status: str
    community: Optional[str]
    building_number: Optional[str]
    unit_number: Optional[str]
    location: Optional[str]


@dataclass(frozen=True)
class ToolOut:
    tool_id: uuid.UUID
    name: str
    barcode: str
    quantity: Decimal
    since: Optional[datetime]


@dataclass(frozen=True)
class HubPayload:
    user: User
    server_now: datetime
    day: date
    counts: AssignedCounts
    clock: labor_summary.DaySummary
    startable: list[StartableWorkOrder]
    tools_out: list[ToolOut]


def _assigned_work_orders(db: Session, user_id: uuid.UUID) -> list[WorkOrder]:
    """Every live work order this person is an assigned technician on.

    Assignment lives in two places -- the legacy singular `assigned_to_id`
    column and plural `work_order_technicians` rows -- and both are still
    populated, so both are matched. This is the same `or_` pair
    `_scoped_to_user` uses for a Technician's list, kept identical on purpose:
    the hub's count and the Work Orders page must never disagree about what
    somebody has been given.

    Loaded into Python rather than counted in SQL because the same rows feed
    three counts and the picker, and a technician's assignment list is tens of
    rows, not thousands.
    """
    return (
        db.query(WorkOrder)
        .filter(
            WorkOrder.archived_at.is_(None),
            or_(
                WorkOrder.assigned_to_id == user_id,
                WorkOrder.technician_assignments.any(
                    WorkOrderTechnician.technician_id == user_id
                ),
            ),
        )
        .order_by(WorkOrder.number)
        .all()
    )


def _assigned_counts(work_orders: list[WorkOrder]) -> AssignedCounts:
    """A total and two subsets of `work_orders` -- shared by `personal_hub`
    and each crew card in `crew_hub`, so the two surfaces can never disagree
    about what "assigned" means for the same person."""
    return AssignedCounts(
        assigned=len(work_orders),
        in_progress=sum(1 for w in work_orders if w.status == wo.STATUS_IN_PROGRESS),
        ready_to_complete=sum(
            1 for w in work_orders if w.status == wo.STATUS_READY_TO_COMPLETE
        ),
    )


def personal_hub(db: Session, user: User) -> HubPayload:
    """The `GET /hub` payload: what am I responsible for, and how long have I
    been working.

    **Not side-effect-free**, and deliberately so: the caller's stale clock is
    swept before anything is read (`sweep_stale_sessions`), so a session
    forgotten on Tuesday does not show up on Wednesday as a twenty-hour
    running total spanning two days. The cost is bounded to at most one row by
    the partial unique index, and it follows existing precedent --
    `get_work_order` already both sweeps sessions and heals orphaned material
    lines on a read.

    One `now` is taken after the sweep and used for the day, the aggregate,
    and the client's clock-skew anchor, so every number in the response
    describes the same instant.
    """
    now = datetime.now(timezone.utc)
    work_orders_service.sweep_stale_sessions(
        db, technician_id=user.id, now=now
    )
    day = labor_day.central_date_of(now)

    mine = _assigned_work_orders(db, user.id)
    counts = _assigned_counts(mine)

    startable = [
        StartableWorkOrder(
            work_order_id=w.id,
            number=w.number,
            status=w.status,
            community=w.community,
            building_number=w.building_number,
            unit_number=w.unit_number,
            location=w.location,
        )
        for w in sorted(
            (
                w
                for w in mine
                if w.status in work_orders_service.TRACKING_START_STATUSES
            ),
            key=lambda w: (_STARTABLE_ORDER.index(w.status), w.number or ""),
        )
    ]

    return HubPayload(
        user=user,
        server_now=now,
        day=day,
        counts=counts,
        clock=labor_summary.day_summary(db, user.id, day, now=now),
        startable=startable,
        tools_out=[
            ToolOut(
                tool_id=tool_id,
                name=name,
                barcode=barcode,
                quantity=quantity,
                since=since,
            )
            for tool_id, name, barcode, quantity, since in (
                tools_service.user_custody_detail(db, user.id)
            )
        ],
    )


# --- the crew payload (P3a) -------------------------------------------------


@dataclass(frozen=True)
class LedCounts:
    """A total and two subsets of the work orders this supervisor leads --
    same convention as `AssignedCounts`, for the same reason."""

    total: int
    in_progress: int
    ready_to_complete: int


@dataclass(frozen=True)
class CrewTechnician:
    """One card on the crew board."""

    user: User
    running_session: Optional[labor_summary.RunningSession]
    minutes_today: int
    assigned: int
    in_progress: int
    ready_to_complete: int
    last_worked: Optional[datetime]
    flags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AttentionItem:
    """One row in the "Needs attention" list. `detail` is a composed
    sentence -- spec §7's `/hub/crew` contract abbreviates this payload to
    exactly `{kind, subject, detail}`, so the server does the composing
    once rather than the frontend reassembling it from raw fields."""

    kind: str  # "technician" | "work_order"
    subject: str
    detail: str


@dataclass(frozen=True)
class HubCrewPayload:
    server_now: datetime
    led: LedCounts
    crew_on_clock: int
    crew_total: int
    crew_minutes_today: int
    technicians: list[CrewTechnician] = field(default_factory=list)
    attention: list[AttentionItem] = field(default_factory=list)


def _format_hm(total_minutes: float) -> str:
    minutes = max(0, round(total_minutes))
    hours, mins = divmod(minutes, 60)
    if not hours:
        return f"{mins} m"
    return f"{hours} h {mins} m"


def _last_activity_at(db: Session, work_order_id: uuid.UUID) -> Optional[datetime]:
    """The most recent instant any labor session touched this work order --
    a stop's `ended_at`, or a still-running session's own `started_at`, so an
    active clock always reads as recent regardless of how long ago it began.
    """
    return (
        db.query(
            func.max(
                func.coalesce(
                    WorkOrderLaborSession.ended_at, WorkOrderLaborSession.started_at
                )
            )
        )
        .filter(WorkOrderLaborSession.work_order_id == work_order_id)
        .scalar()
    )


def _stale_work_order_detail(
    status: str, last_activity_at: Optional[datetime], now: datetime
) -> str:
    label = _STATUS_LABELS.get(status, status)
    if last_activity_at is None:
        return f"{label}, no activity recorded"
    days = (now - last_activity_at).days
    unit = "day" if days == 1 else "days"
    return f"{label}, no activity for {days} {unit}"


def _led_work_orders(db: Session, supervisor_id: uuid.UUID) -> list[WorkOrder]:
    """Every live work order routed to this supervisor.

    This is the query half of D6's crew derivation, shared by the crew board
    and timesheets so their membership cannot drift.
    """
    return (
        db.query(WorkOrder)
        .options(joinedload(WorkOrder.technicians))
        .filter(
            WorkOrder.archived_at.is_(None),
            WorkOrder.supervisor_id == supervisor_id,
        )
        .all()
    )


def _crew_ids_from(
    led_work_orders: list[WorkOrder], supervisor_id: uuid.UUID
) -> set[uuid.UUID]:
    """Derive distinct crew ids from plural and legacy assignments (D6).

    The supervisor's own id is always removed (D13); their hours stay in the
    personal clock widget rather than a crew total they cannot reconcile.
    """
    crew_ids: set[uuid.UUID] = set()
    for work_order in led_work_orders:
        crew_ids.update(technician.id for technician in work_order.technicians)
        if work_order.assigned_to_id:
            crew_ids.add(work_order.assigned_to_id)
    crew_ids.discard(supervisor_id)
    return crew_ids


def crew_hub(db: Session, user: User, *, now: Optional[datetime] = None) -> HubCrewPayload:
    """The `GET /hub/crew` payload: who I lead, who is on the clock, and
    what needs a look.

    Crew membership (D6) is derived from routing, not a stored roster:
    distinct technicians on non-archived work orders where
    `supervisor_id == user.id`, matched through both the plural
    `work_order_technicians` table and the legacy singular `assigned_to_id`
    column -- the same `or_` pair `_assigned_work_orders` uses, so a
    technician who shows up on their own hub is never silently absent here.

    **Not side-effect-free**, deliberately narrower than `GET /hub/admin`'s
    global sweep (spec §3.5 is silent on `/hub/crew`, corrected here): this
    endpoint reads *other people's* running clocks, so each crew member's
    stale session is swept individually before anything is read. The write
    stays scoped to exactly what the endpoint returns.

    **The supervisor's own row is excluded** from the cards and from
    `crew_minutes_today` (D13) -- their own clock is already the widget
    above the tabs, and excluding it is what keeps the roll-up tile
    provably reconcilable against the cards below it.

    `now` is accepted rather than always read fresh so the attention
    thresholds (which key off the Central hour of day) are deterministic
    under test; the router does not pass it, so production always uses the
    real instant.
    """
    now = now or datetime.now(timezone.utc)
    day = labor_day.central_date_of(now)

    led_work_orders = _led_work_orders(db, user.id)
    led = LedCounts(
        total=len(led_work_orders),
        in_progress=sum(1 for w in led_work_orders if w.status == wo.STATUS_IN_PROGRESS),
        ready_to_complete=sum(
            1 for w in led_work_orders if w.status == wo.STATUS_READY_TO_COMPLETE
        ),
    )

    crew_ids = _crew_ids_from(led_work_orders, user.id)

    for technician_id in crew_ids:
        work_orders_service.sweep_stale_sessions(
            db, technician_id=technician_id, now=now
        )

    summaries = labor_summary.crew_day_summaries(db, list(crew_ids), day, now=now)
    crew_users = (
        {u.id: u for u in db.query(User).filter(User.id.in_(crew_ids)).all()}
        if crew_ids
        else {}
    )

    technicians: list[CrewTechnician] = []
    attention: list[AttentionItem] = []
    crew_on_clock = 0
    crew_minutes_today = 0

    for technician_id in sorted(crew_ids, key=lambda tid: crew_users[tid].full_name):
        technician = crew_users[technician_id]
        summary = summaries[technician_id]
        counts = _assigned_counts(_assigned_work_orders(db, technician_id))
        flags: list[str] = []

        if summary.running is not None:
            crew_on_clock += 1
            elapsed = (now - summary.running.started_at).total_seconds() / 60
            session_flag = hub_domain.session_flag(elapsed)
            if session_flag:
                flags.append(session_flag)
                attention.append(
                    AttentionItem(
                        kind="technician",
                        subject=technician.full_name,
                        detail=f"clock running {_format_hm(elapsed)}",
                    )
                )

        if hub_domain.is_assigned_idle(
            assigned_count=counts.assigned, minutes_today=summary.total_minutes, now=now
        ):
            flags.append(hub_domain.FLAG_ASSIGNED_IDLE)
            attention.append(
                AttentionItem(
                    kind="technician",
                    subject=technician.full_name,
                    detail=f"{counts.assigned} work orders assigned, no time tracked today",
                )
            )

        crew_minutes_today += summary.total_minutes
        technicians.append(
            CrewTechnician(
                user=technician,
                running_session=summary.running,
                minutes_today=summary.total_minutes,
                assigned=counts.assigned,
                in_progress=counts.in_progress,
                ready_to_complete=counts.ready_to_complete,
                last_worked=labor_summary.last_worked(db, technician_id),
                flags=flags,
            )
        )

    for w in led_work_orders:
        if w.status not in _STALE_ELIGIBLE_STATUSES:
            continue
        last_activity_at = _last_activity_at(db, w.id)
        if hub_domain.is_stale_work_order(last_activity_at=last_activity_at, now=now):
            attention.append(
                AttentionItem(
                    kind="work_order",
                    subject=f"WO {w.number}",
                    detail=_stale_work_order_detail(w.status, last_activity_at, now),
                )
            )

    return HubCrewPayload(
        server_now=now,
        led=led,
        crew_on_clock=crew_on_clock,
        crew_total=len(crew_ids),
        crew_minutes_today=crew_minutes_today,
        technicians=technicians,
        attention=attention,
    )


# --- the timesheet payload (P3b) -------------------------------------------

MAX_TIMESHEET_RANGE_DAYS = 92


@dataclass(frozen=True)
class TimesheetDay:
    """One grid cell plus the detail expanded from that same payload."""

    date: date
    tracked_minutes: int
    adjustment_minutes: int
    flags: list[str] = field(default_factory=list)
    sessions: list[labor_summary.TimelineEntry] = field(default_factory=list)
    adjustments: list[labor_summary.Adjustment] = field(default_factory=list)

    @property
    def total_minutes(self) -> int:
        """D15: every displayed total includes adjustments."""
        return self.tracked_minutes + self.adjustment_minutes


@dataclass(frozen=True)
class TimesheetRow:
    user: User
    days: list[TimesheetDay] = field(default_factory=list)
    total_minutes: int = 0


@dataclass(frozen=True)
class TimesheetDayTotal:
    date: date
    minutes: int


@dataclass(frozen=True)
class TimesheetRange:
    start: date
    end: date


@dataclass(frozen=True)
class HubTimesheetPayload:
    range: TimesheetRange
    rows: list[TimesheetRow] = field(default_factory=list)
    crew_totals_by_day: list[TimesheetDayTotal] = field(default_factory=list)


def timesheets_hub(
    db: Session,
    user: User,
    *,
    start: date,
    end: date,
    user_id: Optional[uuid.UUID] = None,
    now: Optional[datetime] = None,
) -> HubTimesheetPayload:
    """Compose the routed crew's timesheet cells for an inclusive range.

    P3b uses the exact same D6 membership as the crew board for every caller,
    including higher-ranked callers. P4 owns the later widening to an
    all-company scope. A ``user_id`` can only narrow that already-authorized
    set; an id outside it returns no rows without revealing whether it exists.

    Each in-scope technician is swept before reading so a forgotten clock is
    shown as the established 12-hour estimate, not unbounded running time.
    """
    if end < start:
        raise TimesheetRangeInvalidError()
    if (end - start).days + 1 > MAX_TIMESHEET_RANGE_DAYS:
        raise TimesheetRangeTooLargeError(MAX_TIMESHEET_RANGE_DAYS)

    now = now or datetime.now(timezone.utc)
    today = labor_day.central_date_of(now)
    crew_ids = _crew_ids_from(_led_work_orders(db, user.id), user.id)
    if user_id is not None:
        crew_ids.intersection_update({user_id})

    for technician_id in crew_ids:
        work_orders_service.sweep_stale_sessions(
            db, technician_id=technician_id, now=now
        )

    summaries = labor_summary.crew_range_summaries(
        db, list(crew_ids), start, end, now=now
    )
    crew_users = (
        {person.id: person for person in db.query(User).filter(User.id.in_(crew_ids)).all()}
        if crew_ids
        else {}
    )

    rows: list[TimesheetRow] = []
    totals_by_day: dict[date, int] = {}
    ordered_ids = sorted(
        crew_ids, key=lambda technician_id: crew_users[technician_id].full_name.casefold()
    )
    for technician_id in ordered_ids:
        assigned_count = _assigned_counts(
            _assigned_work_orders(db, technician_id)
        ).assigned
        days: list[TimesheetDay] = []
        for summary in summaries[technician_id]:
            flags: list[str] = []
            if summary.running is not None:
                flags.append(hub_domain.FLAG_RUNNING)
            if summary.day <= today and hub_domain.is_assigned_idle(
                assigned_count=assigned_count,
                minutes_today=summary.total_minutes,
                now=now,
            ):
                flags.append(hub_domain.FLAG_ASSIGNED_IDLE)

            timesheet_day = TimesheetDay(
                date=summary.day,
                tracked_minutes=summary.closed_minutes + summary.running_minutes,
                adjustment_minutes=summary.adjustment_minutes,
                flags=flags,
                sessions=summary.timeline,
                adjustments=summary.adjustments,
            )
            days.append(timesheet_day)
            totals_by_day[summary.day] = (
                totals_by_day.get(summary.day, 0) + timesheet_day.total_minutes
            )

        rows.append(
            TimesheetRow(
                user=crew_users[technician_id],
                days=days,
                total_minutes=sum(day.total_minutes for day in days),
            )
        )

    date_range = [
        start + timedelta(days=offset)
        for offset in range((end - start).days + 1)
    ]
    return HubTimesheetPayload(
        range=TimesheetRange(start=start, end=end),
        rows=rows,
        crew_totals_by_day=[
            TimesheetDayTotal(date=day, minutes=totals_by_day.get(day, 0))
            for day in date_range
        ],
    )


def _format_timesheet_hm(total_minutes: int) -> str:
    """Payroll-facing ``H:MM``; crew-board prose keeps its own formatter."""
    hours, minutes = divmod(max(0, round(total_minutes)), 60)
    return f"{hours}:{minutes:02d}"


def timesheet_csv(payload: HubTimesheetPayload) -> str:
    """Serialize the exact grid payload, including adjustment-aware totals."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    dates = [total.date for total in payload.crew_totals_by_day]
    writer.writerow(["Technician", *(day.isoformat() for day in dates), "Total"])
    for row in payload.rows:
        cells_by_day = {day.date: day for day in row.days}
        writer.writerow(
            [
                row.user.full_name,
                *(
                    _format_timesheet_hm(cells_by_day[day].total_minutes)
                    for day in dates
                ),
                _format_timesheet_hm(row.total_minutes),
            ]
        )
    writer.writerow(
        [
            "Crew total",
            *(
                _format_timesheet_hm(total.minutes)
                for total in payload.crew_totals_by_day
            ),
            _format_timesheet_hm(
                sum(total.minutes for total in payload.crew_totals_by_day)
            ),
        ]
    )
    return buffer.getvalue()
