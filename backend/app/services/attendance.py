"""Attendance punches: the on-shift record and its coupling to the clock.

Layer: services. Owns every `attendance_punches` query; every *rule* lives in
`app.domain.attendance`, which is why the state machine is tested without a
database and this module is SQL plus assembly.

**The coupling lives here** (spec 3), in the caller of
`work_orders.start_labor_session`, not inside the ~2,600-line
`services/work_orders.py`. The dependency points one way: this module imports
work orders, work orders never imports this.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain import attendance, labor_day
from app.domain.errors import PunchAlreadyOpenError, PunchNotFoundError
from app.models import AttendancePunch, User
from app.services import work_orders as wo_service


@dataclass(frozen=True)
class OpenPunch:
    id: uuid.UUID
    started_at: datetime
    start_source: str
    stale: bool


@dataclass(frozen=True)
class AttendanceMe:
    """What the Home tab needs and nothing more. `clocked_minutes_today` is
    the *pay* number -- real wall-clock, never rounded to 30 (8)."""

    server_now: datetime
    day: date
    open_punch: Optional[OpenPunch]
    clocked_minutes_today: int


def open_punch_for(db: Session, user_id: uuid.UUID) -> Optional[AttendancePunch]:
    """This person's open punch, or None. The partial unique index permits
    exactly one, so this is a single indexed lookup."""
    return (
        db.query(AttendancePunch)
        .filter(AttendancePunch.user_id == user_id, AttendancePunch.ended_at.is_(None))
        .first()
    )


def _already_open(punch: AttendancePunch, *, now: datetime) -> PunchAlreadyOpenError:
    stale = attendance.is_stale(punch.started_at, now=now)
    started = labor_day.as_utc(punch.started_at).astimezone(labor_day.CENTRAL)
    # Hour formatted by hand: `%-I` is glibc-only and `%#I` is Windows-only,
    # and this app runs on both.
    when = f"{started:%a} {started.hour % 12 or 12}:{started:%M %p}"
    message = (
        f"You are still punched in from {when}. Close it on your Home tab "
        "before starting again."
        if stale
        else f"You are already punched in since {when}."
    )
    return PunchAlreadyOpenError(message, punch_id=punch.id,
                                 started_at=punch.started_at, stale=stale)


def punch_in(
    db: Session,
    *,
    user: User,
    now: Optional[datetime] = None,
    source: str = attendance.START_SOURCE_MANUAL,
) -> AttendancePunch:
    """Open a punch. Refuses when one is open (D4), returning it on the
    exception so the UI can drive D5's prompt.

    The `IntegrityError` arm is the race the partial unique index exists to
    win: two taps that both pass the pre-check, one insert, the loser
    re-reads and reports the same conflict.
    """
    now = now or datetime.now(timezone.utc)
    existing = open_punch_for(db, user.id)
    if existing is not None:
        raise _already_open(existing, now=now)

    punch = AttendancePunch(
        id=uuid.uuid4(), user_id=user.id, started_at=now, start_source=source
    )
    db.add(punch)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        winner = open_punch_for(db, user.id)
        if winner is None:
            raise
        raise _already_open(winner, now=now) from exc
    db.refresh(punch)
    return punch


def punch_out(
    db: Session, *, user: User, now: Optional[datetime] = None
) -> AttendancePunch:
    """Close the punch **and** force-stop any running labor session (D3).

    Labor first, deliberately: `stop_labor_session` writes the labor row at
    its own `now`, and closing the punch first would leave a charged minute
    landing after the shift ended -- the exact shape 9 flags as a warning
    rather than a refusal, and there is no reason to manufacture one here.
    """
    now = now or datetime.now(timezone.utc)
    punch = open_punch_for(db, user.id)
    if punch is None:
        raise PunchNotFoundError("You are not punched in.")

    running = wo_service.running_labor_session_for(db, user.id)
    if running is not None:
        wo_service.stop_labor_session(db, running.work_order_id, user=user)

    punch.ended_at = now
    punch.end_source = attendance.END_SOURCE_MANUAL
    db.commit()
    db.refresh(punch)
    return punch


def self_close(
    db: Session, *, user: User, ended_at: datetime, now: Optional[datetime] = None
) -> AttendancePunch:
    """D5: the technician closes their own stale punch at a stated time.

    Flagged `needs_review` and `end_source='self_reported'` -- an estimate,
    labelled as one, that an Admin corrects in P3. Without this, D3 and D4
    together would let Tuesday's clerical error stop Wednesday's jobs.
    """
    now = now or datetime.now(timezone.utc)
    punch = open_punch_for(db, user.id)
    if punch is None:
        raise PunchNotFoundError("You have no open punch to close.")
    attendance.validate_punch_window(punch.started_at, ended_at, now=now)
    punch.ended_at = labor_day.as_utc(ended_at)
    punch.end_source = attendance.END_SOURCE_SELF_REPORTED
    punch.needs_review = True
    db.commit()
    db.refresh(punch)
    return punch


def ensure_punch_for_labor_start(
    db: Session, *, user: User, now: Optional[datetime] = None
) -> AttendancePunch:
    """Called immediately before `work_orders.start_labor_session` (D3).

    A technician who ignores the punch button still produces a correct
    timesheet: starting a clock off-shift opens a punch tagged
    `auto_work_order`. A *stale* punch refuses instead, because charging a
    job against a shift that started two days ago is not a record anyone can
    pay from.
    """
    now = now or datetime.now(timezone.utc)
    existing = open_punch_for(db, user.id)
    if existing is not None:
        if attendance.is_stale(existing.started_at, now=now):
            raise _already_open(existing, now=now)
        return existing
    return punch_in(db, user=user, now=now,
                    source=attendance.START_SOURCE_AUTO_WORK_ORDER)


def me_payload(
    db: Session, *, user: User, now: Optional[datetime] = None
) -> AttendanceMe:
    """The Home tab's state. Side-effect-free: no sweep, no row locks (4)."""
    now = now or datetime.now(timezone.utc)
    today = labor_day.central_date_of(now)
    day_start, day_end = labor_day.day_bounds(today)

    punches = (
        db.query(AttendancePunch)
        .filter(
            AttendancePunch.user_id == user.id,
            AttendancePunch.started_at < day_end,
            or_(AttendancePunch.ended_at.is_(None),
                AttendancePunch.ended_at > day_start),
        )
        .all()
    )
    minutes = sum(
        labor_day.overlap_minutes(p.started_at, p.ended_at, day_start, day_end, now=now)
        for p in punches
    )
    open_row = next((p for p in punches if p.ended_at is None), None)
    return AttendanceMe(
        server_now=now,
        day=today,
        open_punch=None if open_row is None else OpenPunch(
            id=open_row.id,
            started_at=open_row.started_at,
            start_source=open_row.start_source,
            stale=attendance.is_stale(open_row.started_at, now=now),
        ),
        clocked_minutes_today=minutes,
    )
