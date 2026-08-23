"""Composes the User Hub's payloads.

Layer: services. Called by `app/routers/hub.py`. Owns no rules of its own --
day arithmetic is `domain.labor_day`, the labor aggregate is
`services.labor_summary`, tool custody is `services.tools`, and the cap
sweep is `services.work_orders`. This module's whole job is to run them in
the right order and hand back one object the router can serialise, so the
router stays the thin translation layer every other one in this app is.

The module now composes the personal block, routed crew board, crew timesheets,
company-wide admin summary, and the lazy company-wide Graphs report.
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
from app.domain import receipt
from app.domain import roles
from app.domain import work_orders as wo
from app.domain.errors import TimesheetRangeInvalidError, TimesheetRangeTooLargeError
from app.models import User, UserRequest, WorkOrder, WorkOrderLaborSession, WorkOrderTechnician
from app.services import labor_summary
from app.services import tools as tools_service
from app.services import user_requests as user_requests_service
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
class PriorityCounts:
    """High-priority live-work-order counts for the Priorities card.

    `assigned` and `unassigned` share one denominator that differs by scope:
    a Technician's own assignments (personal_hub), a Supervisor's led work
    orders (crew_hub), or every live work order company-wide (admin_hub).
    `unassigned` is `None` for a Technician's card, which has no such number
    -- a Technician only ever sees what is assigned to them.
    """

    assigned: int
    unassigned: Optional[int] = None


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
    # The number on the "My Work Orders" tab label. Deliberately separate from
    # `counts.assigned`: that one is worker assignment only (it feeds the
    # Dashboard's own tiles and every crew card), while this counts exactly
    # what the tab lists -- routed to me *or* assigned to me. A Supervisor with
    # nothing but routed work has `counts.assigned == 0` and `mine_total > 0`,
    # which is precisely the disagreement that put "(0)" over a list of cards.
    mine_total: int
    counts: AssignedCounts
    priority: PriorityCounts
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


def _mine_total(db: Session, user_id: uuid.UUID) -> int:
    """How many live work orders sit behind the "My Work Orders" tab.

    Counted in SQL rather than by loading rows the way `_assigned_work_orders`
    does: this number feeds a tab label and nothing else, so there is no second
    consumer to justify hydrating entities.

    The predicate is imported from the list service rather than restated here
    -- `mine_predicate` is the single definition the tab's own card list also
    filters on, so the label and the cards behind it cannot drift apart.

    Note this is the *true* total, not the capped ten the tab renders. A
    Technician's tile count has always worked that way, and "(12)" over ten
    cards and a "View all" link is the honest reading of how much work the
    person has.
    """
    return (
        db.query(func.count(WorkOrder.id))
        .filter(
            WorkOrder.archived_at.is_(None),
            work_orders_service.mine_predicate(user_id),
        )
        .scalar()
        or 0
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
    priority = PriorityCounts(
        assigned=sum(1 for w in mine if wo.priority_bucket(w.priority) == wo.PRIORITY_HIGH)
    )

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
        mine_total=_mine_total(db, user.id),
        counts=counts,
        priority=priority,
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
    priority: PriorityCounts
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


def _priority_counts(work_orders: list[WorkOrder]) -> PriorityCounts:
    """Shared by `crew_hub` (already has `technicians` eager-loaded on each
    row via `_led_work_orders`'s `joinedload`) -- `admin_hub` cannot reuse
    this directly because hydrating every company-wide WorkOrder row with
    that join would be far more expensive than the narrow projection it uses
    instead (see `_company_wide_priority_counts`)."""
    high = [w for w in work_orders if wo.priority_bucket(w.priority) == wo.PRIORITY_HIGH]
    unassigned = sum(1 for w in high if w.assigned_to_id is None and not w.technicians)
    return PriorityCounts(assigned=len(high), unassigned=unassigned)


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
    priority = _priority_counts(led_work_orders)

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
        priority=priority,
        crew_on_clock=crew_on_clock,
        crew_total=len(crew_ids),
        crew_minutes_today=crew_minutes_today,
        technicians=technicians,
        attention=attention,
    )


# --- the admin payload (P4 slice 1: company-wide time summary) -------------


@dataclass(frozen=True)
class AdminPipelineCounts:
    """Company-wide, unscoped work-order status counts -- the "Work Order
    Pipeline" row (spec §5.4). Six columns, not seven: `on_hold` is a
    temporal pause on `in_progress`, not a pipeline stage of its own, and
    has no column here."""

    created: int
    assigned: int
    in_progress: int
    ready_to_complete: int
    completed: int
    review: int


def _pipeline_counts(db: Session) -> AdminPipelineCounts:
    rows = (
        db.query(WorkOrder.status, func.count(WorkOrder.id))
        .filter(WorkOrder.archived_at.is_(None))
        .group_by(WorkOrder.status)
        .all()
    )
    counts = dict(rows)
    return AdminPipelineCounts(
        created=counts.get(wo.STATUS_CREATED, 0),
        assigned=counts.get(wo.STATUS_ASSIGNED, 0),
        in_progress=counts.get(wo.STATUS_IN_PROGRESS, 0),
        ready_to_complete=counts.get(wo.STATUS_READY_TO_COMPLETE, 0),
        completed=counts.get(wo.STATUS_COMPLETED, 0),
        review=counts.get(wo.STATUS_REVIEW, 0),
    )


def _company_wide_priority_counts(db: Session) -> PriorityCounts:
    """Every live work order, unscoped -- the Admin+ mirror of `_priority_counts`.

    A narrow two-query projection rather than hydrating full `WorkOrder` rows
    with a `technicians` join (the way `_priority_counts` does for a
    supervisor's much smaller led set): company-wide, that join would be the
    most expensive read on this payload for no benefit, since only
    `priority`, `assigned_to_id`, and technician-assignment existence are
    needed.
    """
    rows = (
        db.query(WorkOrder.id, WorkOrder.priority, WorkOrder.assigned_to_id)
        .filter(WorkOrder.archived_at.is_(None))
        .all()
    )
    high_ids = {row.id for row in rows if wo.priority_bucket(row.priority) == wo.PRIORITY_HIGH}
    if not high_ids:
        return PriorityCounts(assigned=0, unassigned=0)
    technician_assigned_ids = {
        row.work_order_id
        for row in db.query(WorkOrderTechnician.work_order_id)
        .filter(WorkOrderTechnician.work_order_id.in_(high_ids))
        .distinct()
        .all()
    }
    unassigned = sum(
        1
        for row in rows
        if row.id in high_ids
        and row.assigned_to_id is None
        and row.id not in technician_assigned_ids
    )
    return PriorityCounts(assigned=len(high_ids), unassigned=unassigned)


@dataclass(frozen=True)
class AdminExceptionCounts:
    """The "Exceptions" tile group (spec §5.4) -- five open-work counts
    pulled from three different subsystems. `admin_review_queue` is not a
    new query: it is `AdminPipelineCounts.review`, the same live-status
    count the pipeline row already shows, surfaced a second time here
    because Exceptions is where an admin looks for open work, not for the
    full six-stage breakdown."""

    inventory_recounts: int
    missing_item_price: int
    item_requests: int
    admin_review_queue: int
    stale_work_orders: int


def _exception_counts(
    db: Session, now: datetime, pipeline: AdminPipelineCounts
) -> AdminExceptionCounts:
    rows = (
        db.query(UserRequest.request_type, func.count(UserRequest.id))
        .filter(UserRequest.status == user_requests_service.STATUS_OPEN)
        .group_by(UserRequest.request_type)
        .all()
    )
    open_counts = dict(rows)

    stale_eligible = (
        db.query(WorkOrder.id)
        .filter(
            WorkOrder.archived_at.is_(None),
            WorkOrder.status.in_(_STALE_ELIGIBLE_STATUSES),
        )
        .all()
    )
    stale_work_orders = sum(
        1
        for (work_order_id,) in stale_eligible
        if hub_domain.is_stale_work_order(
            last_activity_at=_last_activity_at(db, work_order_id), now=now
        )
    )

    return AdminExceptionCounts(
        inventory_recounts=open_counts.get(
            user_requests_service.REQUEST_INVENTORY_RECOUNT, 0
        ),
        missing_item_price=open_counts.get(
            user_requests_service.REQUEST_MISSING_ITEM_PRICE, 0
        ),
        item_requests=open_counts.get(user_requests_service.REQUEST_ITEM, 0),
        admin_review_queue=pipeline.review,
        stale_work_orders=stale_work_orders,
    )


@dataclass(frozen=True)
class AdminBilling:
    """The "Billing" tile group (spec §5.4). `materials_total`/`labor_total`
    are locked to the **current Central week** (D12) -- the receipt's own
    numbers (`domain.receipt`: billed labor minutes, 15% material mark-up),
    summed over every work order completed inside it. `avg_days_to_complete`
    and `completed_per_day` are not pinned by D12 (which only fixes the $
    figures' range) and instead look at the trailing 14 Central days -- long
    enough for a meaningful average and for the spec's 14-point sparkline; a
    single week would be too small a sample for either."""

    materials_total: Decimal
    labor_total: Decimal
    avg_days_to_complete: Optional[float]
    completed_per_day: list[int]
    legacy_live_count: Optional[int]

    @property
    def total(self) -> Decimal:
        return self.materials_total + self.labor_total


def _materials_and_labor(work_orders: list[WorkOrder]) -> tuple[Decimal, Decimal]:
    materials_total = Decimal(0)
    labor_total = Decimal(0)
    for work_order in work_orders:
        for line in work_order.items:
            charge = receipt.marked_material_charge(
                receipt.ReceiptLine(
                    name=line.item.name,
                    quantity=line.quantity,
                    billable_quantity=line.billable_quantity,
                    unit_price=line.item.price,
                )
            )
            if charge is not None:
                materials_total += charge
        labor_minutes = sum(entry.minutes for entry in work_order.labor_entries)
        labor_total += wo.labor_charge(labor_minutes)
    return materials_total, labor_total


def _billing(db: Session, now: datetime, user: User) -> AdminBilling:
    today = labor_day.central_date_of(now)
    week_start, week_end = labor_day.week_bounds_containing(today)
    week_window_start, _ = labor_day.day_bounds(week_start)
    _, week_window_end = labor_day.day_bounds(week_end)

    this_week = (
        db.query(WorkOrder)
        .filter(
            WorkOrder.completed_at.is_not(None),
            WorkOrder.completed_at >= week_window_start,
            WorkOrder.completed_at < week_window_end,
        )
        .all()
    )
    materials_total, labor_total = _materials_and_labor(this_week)

    trailing_days = [today - timedelta(days=offset) for offset in range(13, -1, -1)]
    trailing_start, _ = labor_day.day_bounds(trailing_days[0])
    _, trailing_end = labor_day.day_bounds(trailing_days[-1])
    trailing = (
        db.query(WorkOrder.created_at, WorkOrder.completed_at)
        .filter(
            WorkOrder.completed_at.is_not(None),
            WorkOrder.completed_at >= trailing_start,
            WorkOrder.completed_at < trailing_end,
        )
        .all()
    )
    per_day = {day: 0 for day in trailing_days}
    for created_at, completed_at in trailing:
        day = labor_day.central_date_of(completed_at)
        if day in per_day:
            per_day[day] += 1
    completed_per_day = [per_day[day] for day in trailing_days]
    avg_days_to_complete = (
        sum((c - cr).total_seconds() for cr, c in trailing) / len(trailing) / 86400
        if trailing
        else None
    )

    legacy_live_count = (
        work_orders_service.count_live_legacy_work_orders(db, user=user)
        if roles.role_at_least(user.role, roles.ROLE_OWNER)
        else None
    )

    return AdminBilling(
        materials_total=materials_total,
        labor_total=labor_total,
        avg_days_to_complete=avg_days_to_complete,
        completed_per_day=completed_per_day,
        legacy_live_count=legacy_live_count,
    )


@dataclass(frozen=True)
class OnClockEntry:
    """One row of the "On the clock now" list (spec §5.4) -- a currently
    running labor session, company-wide. `flag` reuses the crew board's own
    vocabulary (`hub_domain.FLAG_LONG_SESSION` / `FLAG_APPROACHING_CAP`) so
    the same icon-plus-word rendering rule (spec §8) applies here too."""

    technician_name: str
    work_order_number: str
    community: Optional[str]
    started_at: datetime
    elapsed_minutes: int
    flag: Optional[str]


def _on_the_clock(
    db: Session,
    now: datetime,
    users_by_id: dict[uuid.UUID, User],
    summaries_by_user_id: dict[uuid.UUID, labor_summary.DaySummary],
) -> list[OnClockEntry]:
    running = [
        (user_id, summary.running)
        for user_id, summary in summaries_by_user_id.items()
        if summary.running is not None
    ]
    work_order_ids = [session.work_order_id for _, session in running]
    communities = (
        dict(
            db.query(WorkOrder.id, WorkOrder.community)
            .filter(WorkOrder.id.in_(work_order_ids))
            .all()
        )
        if work_order_ids
        else {}
    )
    entries = [
        OnClockEntry(
            technician_name=users_by_id[user_id].full_name,
            work_order_number=session.number,
            community=communities.get(session.work_order_id),
            started_at=session.started_at,
            elapsed_minutes=elapsed_minutes,
            flag=hub_domain.session_flag(elapsed_minutes),
        )
        for user_id, session in running
        for elapsed_minutes in [int((now - session.started_at).total_seconds() // 60)]
    ]
    entries.sort(key=lambda e: e.elapsed_minutes, reverse=True)
    return entries


@dataclass(frozen=True)
class HubAdminPayload:
    """`GET /hub/admin`'s whole contract: today's tracked minutes, summed
    by account role across the whole company.

    Bucketed by account role, not by what work was clocked on -- a
    Supervisor's own hands-on hours count as Supervisor Time; a TechFM
    OA/Admin/Owner's hours (if any) land in neither bucket, since their own
    time is already the personal clock widget above the tabs.
    """

    server_now: datetime
    supervisor_minutes_today: int
    technician_minutes_today: int
    pipeline: AdminPipelineCounts
    priority: PriorityCounts
    on_the_clock: list[OnClockEntry]
    exceptions: AdminExceptionCounts
    billing: AdminBilling


def admin_hub(db: Session, user: User, *, now: Optional[datetime] = None) -> HubAdminPayload:
    """The `GET /hub/admin` payload: how much the company tracked today,
    split into Supervisor Time and Technician Time.

    **Not side-effect-free**, deliberately the widest sweep in the module:
    unscoped (no `technician_id`), so every over-cap running session in the
    company is closed before anything is summed. This is the call site the
    router module's own docstring already reserves for the global sweep
    (spec §3.5), and it is safe under concurrent callers for the same
    reason `crew_hub`'s per-member sweep is -- `sweep_stale_sessions` locks
    each work order `FOR UPDATE` before touching its sessions.
    """
    now = now or datetime.now(timezone.utc)
    day = labor_day.central_date_of(now)

    work_orders_service.sweep_stale_sessions(db, now=now)

    supervisors = (
        db.query(User)
        .filter(User.role == roles.ROLE_SUPERVISOR, User.archived_at.is_(None))
        .all()
    )
    technicians = (
        db.query(User)
        .filter(User.role == roles.ROLE_TECHNICIAN, User.archived_at.is_(None))
        .all()
    )

    supervisor_summaries = labor_summary.crew_day_summaries(
        db, [u.id for u in supervisors], day, now=now
    )
    technician_summaries = labor_summary.crew_day_summaries(
        db, [u.id for u in technicians], day, now=now
    )
    users_by_id = {u.id: u for u in supervisors + technicians}
    all_summaries = {**supervisor_summaries, **technician_summaries}
    pipeline = _pipeline_counts(db)
    priority = _company_wide_priority_counts(db)

    return HubAdminPayload(
        server_now=now,
        supervisor_minutes_today=sum(s.total_minutes for s in supervisor_summaries.values()),
        technician_minutes_today=sum(s.total_minutes for s in technician_summaries.values()),
        pipeline=pipeline,
        priority=priority,
        on_the_clock=_on_the_clock(db, now, users_by_id, all_summaries),
        exceptions=_exception_counts(db, now, pipeline),
        billing=_billing(db, now, user),
    )


# --- the admin graphs payload ------------------------------------------------


@dataclass(frozen=True)
class GraphStatus:
    key: str
    label: str


@dataclass(frozen=True)
class GraphDistribution:
    key: str
    label: str
    total: int
    counts: dict[str, int]


@dataclass(frozen=True)
class GraphDurationRange:
    start: date
    end: date


@dataclass(frozen=True)
class GraphDurationBucket:
    start: date
    end: date
    partial: bool
    circulating_avg_age_days: Optional[float]
    circulating_count: int
    closed_avg_days: Optional[float]
    closed_count: int


@dataclass(frozen=True)
class GraphDuration:
    range: GraphDurationRange
    buckets: list[GraphDurationBucket]


@dataclass(frozen=True)
class HubGraphsPayload:
    generated_at: datetime
    weeks: int
    statuses: list[GraphStatus]
    priority_high: GraphDistribution
    priority_medium: GraphDistribution
    communities: list[GraphDistribution]
    service_types: list[GraphDistribution]
    duration: GraphDuration


_GRAPH_STATUS_LABELS = {
    wo.STATUS_CREATED: "Created",
    wo.STATUS_ASSIGNED: "Assigned",
    wo.STATUS_IN_PROGRESS: "In-Progress",
    wo.STATUS_ON_HOLD: "On Hold",
    wo.STATUS_READY_TO_COMPLETE: "Ready to Complete",
    wo.STATUS_COMPLETED: "Completed",
    wo.STATUS_REVIEW: "Review",
}


def _empty_graph_counts() -> dict[str, int]:
    return {status: 0 for status in wo.ALL_STATUSES}


def _average_days(durations: list[float]) -> Optional[float]:
    return round(sum(durations) / len(durations), 2) if durations else None


def graphs_hub(
    db: Session, user: User, *, weeks: int, now: Optional[datetime] = None
) -> HubGraphsPayload:
    """Compose the lazy, company-wide Graphs-tab report.

    Live distributions read only non-archived rows. The duration series has
    two intentionally different measures: each bucket's circulating age is a
    historical snapshot, while close-out time uses ``archived_at`` for rows
    closed in that bucket. ``completed_at`` remains exclusive to the existing
    dashboard's "time to complete" metric.

    A restored work order has its ``archived_at`` cleared, so this can only
    report closure intervals still represented by the current row; it does
    not claim audit-grade historical close data.
    """
    del user  # Auth is the router's concern; this payload is company-wide.
    now = now or datetime.now(timezone.utc)
    periods = hub_domain.graph_week_ranges(now, weeks)
    statuses = [
        GraphStatus(key=status, label=_GRAPH_STATUS_LABELS[status])
        for status in wo.ALL_STATUSES
    ]

    community_counts = {key: _empty_graph_counts() for key in wo.ALL_COMMUNITY_FILTERS}
    service_counts: dict[str, dict[str, int]] = {}
    service_labels: dict[str, str] = {}
    priority_counts = {
        wo.PRIORITY_HIGH: _empty_graph_counts(),
        wo.PRIORITY_MEDIUM: _empty_graph_counts(),
    }
    live_rows = (
        db.query(
            WorkOrder.status,
            WorkOrder.community,
            WorkOrder.location,
            WorkOrder.service_type,
            WorkOrder.priority,
        )
        .filter(WorkOrder.archived_at.is_(None))
        .all()
    )
    for status, community, location, service_type, priority in live_rows:
        # A defensive unknown-status guard preserves an exhaustive response if
        # a legacy row predates today's validation vocabulary.
        if status not in wo.ALL_STATUSES:
            continue
        for key in wo.community_memberships(community, location):
            community_counts[key][status] += 1
        service_key, service_label = wo.normalize_service_type(service_type)
        service_counts.setdefault(service_key, _empty_graph_counts())[status] += 1
        prior_label = service_labels.get(service_key)
        if prior_label is None or service_label.casefold() < prior_label.casefold():
            service_labels[service_key] = service_label
        bucket = wo.priority_bucket(priority)
        if bucket in priority_counts:
            priority_counts[bucket][status] += 1

    priority_high = GraphDistribution(
        key=wo.PRIORITY_HIGH,
        label="High priority",
        total=sum(priority_counts[wo.PRIORITY_HIGH].values()),
        counts=priority_counts[wo.PRIORITY_HIGH],
    )
    priority_medium = GraphDistribution(
        key=wo.PRIORITY_MEDIUM,
        label="Medium priority",
        total=sum(priority_counts[wo.PRIORITY_MEDIUM].values()),
        counts=priority_counts[wo.PRIORITY_MEDIUM],
    )

    communities = [
        GraphDistribution(
            key=key,
            label=wo.COMMUNITY_LABELS[key],
            total=sum(community_counts[key].values()),
            counts=community_counts[key],
        )
        for key in wo.ALL_COMMUNITY_FILTERS
    ]
    service_types = [
        GraphDistribution(
            key=key,
            label=service_labels[key],
            total=sum(counts.values()),
            counts=counts,
        )
        for key, counts in service_counts.items()
    ]
    service_types.sort(key=lambda row: (-row.total, row.label.casefold()))

    first_start, _, _ = periods[0]
    _, last_end, _ = periods[-1]
    first_start_at = labor_day.day_bounds(first_start)[0]
    last_end_at = labor_day.day_bounds(last_end)[1]
    history_rows = (
        db.query(WorkOrder.created_at, WorkOrder.archived_at)
        .filter(WorkOrder.created_at.is_not(None))
        .filter(WorkOrder.created_at < last_end_at)
        .filter(or_(WorkOrder.archived_at.is_(None), WorkOrder.archived_at >= first_start_at))
        .all()
    )

    buckets: list[GraphDurationBucket] = []
    for start, end, partial in periods:
        start_at = labor_day.day_bounds(start)[0]
        end_at = labor_day.day_bounds(end)[1]
        snapshot_at = now if partial else end_at
        circulating = [
            (snapshot_at - labor_day.as_utc(created_at)).total_seconds() / 86400
            for created_at, archived_at in history_rows
            if labor_day.as_utc(created_at) <= snapshot_at
            and (archived_at is None or labor_day.as_utc(archived_at) > snapshot_at)
        ]
        closed = [
            (labor_day.as_utc(archived_at) - labor_day.as_utc(created_at)).total_seconds() / 86400
            for created_at, archived_at in history_rows
            if archived_at is not None
            and start_at <= labor_day.as_utc(archived_at) < end_at
        ]
        buckets.append(
            GraphDurationBucket(
                start=start,
                end=end,
                partial=partial,
                circulating_avg_age_days=_average_days(circulating),
                circulating_count=len(circulating),
                closed_avg_days=_average_days(closed),
                closed_count=len(closed),
            )
        )

    return HubGraphsPayload(
        generated_at=now,
        weeks=weeks,
        statuses=statuses,
        priority_high=priority_high,
        priority_medium=priority_medium,
        communities=communities,
        service_types=service_types,
        duration=GraphDuration(
            range=GraphDurationRange(start=first_start, end=last_end),
            buckets=buckets,
        ),
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
    """Compose the timesheet grid's cells for an inclusive range.

    P3b used the exact same D6 crew membership as the crew board for every
    caller, including higher-ranked ones. P4 widens that to an all-company
    scope (every live Supervisor and Technician, the same population
    `admin_hub`'s two time buckets sum) for a techfm_oa+ caller -- a
    Supervisor caller is unaffected and still sees only their own routed
    crew. A ``user_id`` can only narrow whichever set the caller is
    authorized to see; an id outside it returns no rows without revealing
    whether it exists.

    Each in-scope technician is swept before reading so a forgotten clock is
    shown as the established 12-hour estimate, not unbounded running time.
    """
    if end < start:
        raise TimesheetRangeInvalidError()
    if (end - start).days + 1 > MAX_TIMESHEET_RANGE_DAYS:
        raise TimesheetRangeTooLargeError(MAX_TIMESHEET_RANGE_DAYS)

    now = now or datetime.now(timezone.utc)
    today = labor_day.central_date_of(now)
    if roles.role_at_least(user.role, roles.ROLE_TECHFM_OA):
        crew_ids = {
            person.id
            for person in db.query(User)
            .filter(
                User.role.in_((roles.ROLE_SUPERVISOR, roles.ROLE_TECHNICIAN)),
                User.archived_at.is_(None),
            )
            .all()
        }
    else:
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
