"""The Admin live roster: who is on shift right now, and who is charging.

Layer: services. Read-only and **side-effect-free** (spec §4) -- no sweep, no
row locks, no commit -- which is what lets the Charged vs clocked sub-tab
poll it on the hub's existing 60-second safety timer.

Clocked only, again: nothing here produces a pay number or a billed one. It
answers "is this person at work, and do they have a reason to be charging",
and every rule behind that answer lives in `domain.attendance`.

**The one rule this module adds to the state machine:** an open labor session
past `work_orders.LABOR_SESSION_MAX_MINUTES` is *not* charging. A clock
nobody stopped would otherwise read green forever, which is the exact failure
the roster exists to catch. `work_orders.capped_session_end` decides it --
the same function the week read uses -- so the two surfaces cannot disagree
about a forgotten clock, and the abandoned session's capped end becomes the
idle anchor rather than the last *closed* session, which would read older
than it is.

Bounded queries, not N+1: one population read, one open-punch read, one
running-session read, one grouped `max(ended_at)`, one work-order number
lookup. None of them grows with the week, and a crew is tens of people.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.domain import attendance, labor_day, roles
from app.domain import work_orders as wo
from app.models import AttendancePunch, User, WorkOrder, WorkOrderLaborSession
from app.services import attendance as attendance_service


@dataclass(frozen=True)
class RosterEntry:
    """One card. `idle_since` and `charging_since` are the two instants the
    browser ticks from -- exactly one of them is set on an on-shift entry,
    and neither on an absent one."""

    user: User
    state: str
    punch_started_at: Optional[datetime]
    idle_since: Optional[datetime]
    idle_minutes: int
    charging_since: Optional[datetime]
    work_order_number: Optional[str]


@dataclass(frozen=True)
class LiveRoster:
    """`idle_red_minutes` rides along so the client can recolour a card
    between polls without a second copy of the threshold."""

    server_now: datetime
    idle_red_minutes: int
    on_shift: list[RosterEntry]
    absent: list[RosterEntry]
    on_shift_count: int
    charging_count: int
    idle_count: int


# Red first: the strip is read top-down by somebody looking for a problem.
_STATE_ORDER = {
    attendance.STATE_RED: 0,
    attendance.STATE_YELLOW: 1,
    attendance.STATE_GREEN: 2,
}


def _population(db: Session) -> list[User]:
    """Live Supervisors and Technicians only (spec §6). An Admin who punches
    in accrues hours in the Hours grid and is deliberately not colour-judged
    here -- the roster is about the crew on the ground."""
    return (
        db.query(User)
        .filter(
            User.role.in_(roles.WORK_ORDER_TECHNICIAN_ROLES),
            User.archived_at.is_(None),
        )
        .all()
    )


def roster(db: Session, *, now: Optional[datetime] = None) -> LiveRoster:
    now = now or datetime.now(timezone.utc)
    moment = labor_day.as_utc(now)
    people = _population(db)
    ids = [person.id for person in people]
    if not ids:
        return LiveRoster(
            server_now=now, idle_red_minutes=attendance.IDLE_RED_MINUTES,
            on_shift=[], absent=[], on_shift_count=0, charging_count=0,
            idle_count=0,
        )

    punches = {
        punch.user_id: punch
        for punch in attendance_service.live_punches(db)
        .filter(
            AttendancePunch.user_id.in_(ids),
            AttendancePunch.ended_at.is_(None),
        )
        .all()
    }
    running = {
        session.technician_id: session
        for session in db.query(WorkOrderLaborSession)
        .filter(
            WorkOrderLaborSession.technician_id.in_(ids),
            WorkOrderLaborSession.ended_at.is_(None),
        )
        .all()
    }
    last_closed = dict(
        db.query(
            WorkOrderLaborSession.technician_id,
            func.max(WorkOrderLaborSession.ended_at),
        )
        .filter(
            WorkOrderLaborSession.technician_id.in_(ids),
            WorkOrderLaborSession.ended_at.is_not(None),
        )
        .group_by(WorkOrderLaborSession.technician_id)
        .all()
    )
    numbers = (
        dict(
            db.query(WorkOrder.id, WorkOrder.number)
            .filter(
                WorkOrder.id.in_(
                    [session.work_order_id for session in running.values()]
                )
            )
            .all()
        )
        if running
        else {}
    )

    on_shift: list[RosterEntry] = []
    absent: list[RosterEntry] = []
    for person in people:
        punch = punches.get(person.id)
        if punch is None:
            absent.append(RosterEntry(
                user=person, state=attendance.STATE_GRAY, punch_started_at=None,
                idle_since=None, idle_minutes=0, charging_since=None,
                work_order_number=None,
            ))
            continue

        session = running.get(person.id)
        charging = False
        anchor = last_closed.get(person.id)
        if session is not None:
            effective_end = wo.capped_session_end(
                session.started_at, None, now=moment
            )
            charging = effective_end >= moment
            if not charging:
                # The forgotten clock's effective stop: the instant a sweep
                # would have written. Without it the abandoned session leaves
                # idle anchored on the last *closed* one, reading hours older
                # than the person actually is.
                anchor = (
                    effective_end if anchor is None
                    else max(labor_day.as_utc(anchor), effective_end)
                )

        state = attendance.shift_state(
            punch_started_at=punch.started_at, labor_running=charging,
            last_labor_ended_at=anchor, now=moment,
        )
        on_shift.append(RosterEntry(
            user=person,
            state=state,
            punch_started_at=punch.started_at,
            idle_since=None if charging else attendance.idle_anchor(
                punch_started_at=punch.started_at, last_labor_ended_at=anchor,
            ),
            idle_minutes=0 if charging else attendance.idle_minutes(
                punch_started_at=punch.started_at, last_labor_ended_at=anchor,
                now=moment,
            ),
            charging_since=session.started_at if charging else None,
            work_order_number=(
                numbers.get(session.work_order_id) if charging else None
            ),
        ))

    # Red, then yellow, then green; longest idle first inside a colour; name
    # to break a tie, so two equal rows do not swap places between polls.
    on_shift.sort(
        key=lambda e: (_STATE_ORDER[e.state], -e.idle_minutes, e.user.full_name)
    )
    absent.sort(key=lambda e: e.user.full_name)
    charging_count = sum(
        1 for entry in on_shift if entry.state == attendance.STATE_GREEN
    )
    return LiveRoster(
        server_now=now,
        idle_red_minutes=attendance.IDLE_RED_MINUTES,
        on_shift=on_shift,
        absent=absent,
        on_shift_count=len(on_shift),
        charging_count=charging_count,
        idle_count=len(on_shift) - charging_count,
    )
