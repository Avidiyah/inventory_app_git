"""Composes the User Hub's payloads.

Layer: services. Called by `app/routers/hub.py`. Owns no rules of its own --
day arithmetic is `domain.labor_day`, the labor aggregate is
`services.labor_summary`, tool custody is `services.tools`, and the cap
sweep is `services.work_orders`. This module's whole job is to run them in
the right order and hand back one object the router can serialise, so the
router stays the thin translation layer every other one in this app is.

Phase 1 builds the **personal block** only -- the payload behind `GET /hub`,
which every authenticated role receives, Admin included. That is not
symmetry for its own sake: `POST /tracking/start` is already open to
Supervisor+ on any visible work order, precisely so a supervisor who does
the work records it, and a supervisor with a running clock and nowhere to
see it would be a regression. The crew, admin, and timesheet payloads are
later phases.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.domain import labor_day
from app.domain import work_orders as wo
from app.models import User, WorkOrder, WorkOrderTechnician
from app.services import labor_summary
from app.services import tools as tools_service
from app.services import work_orders as work_orders_service

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
    work_orders_service.sweep_stale_sessions(db, technician_id=user.id)

    now = datetime.now(timezone.utc)
    day = labor_day.central_date_of(now)

    mine = _assigned_work_orders(db, user.id)
    counts = AssignedCounts(
        assigned=len(mine),
        in_progress=sum(1 for w in mine if w.status == wo.STATUS_IN_PROGRESS),
        ready_to_complete=sum(
            1 for w in mine if w.status == wo.STATUS_READY_TO_COMPLETE
        ),
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
