"""HTTP routes for the attendance punch.

Layer: routers (FastAPI). Thin handlers only, mirroring `routers/hub.py`.

Every route here is **self-scoped**: the caller punches their own clock and
reads their own state, so the gate is `get_current_user` with no minimum
role -- an Admin has a shift too. The Admin+ reads and the audited writes are
separate endpoints in later phases (4).

`GET /attendance/me` is side-effect-free: no sweep, no row locks, unlike
`GET /hub`. That is what will let the live roster poll it safely in P4.

Every write here emits `attendance.changed` (audience Admin) so the Admin
roster does not wait out its 60-second poll. Best-effort, after the write.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth_deps import get_current_user
from app.database import get_db
from app.domain.errors import DomainError
from app.models import User
from app.routers._attendance_events import emit_attendance_changed
from app.routers._errors import to_http
from app.schemas.attendance import (
    AttendanceMeResponse,
    AttendancePunchResponse,
    SelfCloseRequest,
)
from app.services import attendance as attendance_service

router = APIRouter(prefix="/attendance", tags=["attendance"])


@router.get("/me", response_model=AttendanceMeResponse)
def get_attendance_me(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The Home tab's punch state: the open punch (if any) and today's
    clocked minutes."""
    return AttendanceMeResponse.model_validate(
        attendance_service.me_payload(db, user=user)
    )


@router.post("/punch-in", response_model=AttendancePunchResponse)
def punch_in(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start a shift. 409 when one is already open (D4) -- the client reads
    the blocking punch back from `GET /attendance/me` and offers the
    self-close (D5) when it is stale."""
    try:
        punch = attendance_service.punch_in(db, user=user)
    except DomainError as exc:
        raise to_http(exc) from exc
    emit_attendance_changed()
    return punch


@router.post("/punch-out", response_model=AttendancePunchResponse)
def punch_out(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """End the shift, force-stopping any running work-order clock (D3)."""
    try:
        punch = attendance_service.punch_out(db, user=user)
    except DomainError as exc:
        raise to_http(exc) from exc
    emit_attendance_changed()
    return punch


@router.post("/self-close", response_model=AttendancePunchResponse)
def self_close(
    payload: SelfCloseRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Close a forgotten punch at a stated time (D5). The result is flagged
    `needs_review` -- an estimate, labelled as one."""
    try:
        punch = attendance_service.self_close(
            db, user=user, ended_at=payload.ended_at)
    except DomainError as exc:
        raise to_http(exc) from exc
    emit_attendance_changed()
    return punch
