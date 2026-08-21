"""HTTP routes for the User Hub.

Layer: routers (FastAPI). Thin handlers only, mirroring
`app/routers/tools.py`. Payloads stack by rank rather than branching by
role, so each route carries exactly one declarative gate and `auth_deps.py`
stays the only place a role 403 is raised:

- `GET /hub`             any authenticated  -- the personal block
- `GET /hub/crew`        supervisor+        -- the crew board
- `GET /hub/admin`       techfm_oa+         -- the company-wide time summary
- `GET /hub/timesheets`  supervisor+        -- routed-crew timesheets

The personal, crew, and timesheet reads are not side-effect-free. They sweep
over-cap sessions before reading and therefore commit when they find one --
`GET /hub` the caller's own, `GET /hub/crew` each crew member's individually
(spec §3.5 assigns the global sweep to `GET /hub/admin` only and is silent on
`/hub/crew`; scoping the crew sweep to exactly the people it reads follows
the same reasoning `GET /hub` already applies to itself). This follows
existing precedent rather than inventing it -- `get_work_order` already both
sweeps sessions and self-heals orphaned material lines on a read -- and the
sweep is idempotent under a row lock, so two tabs loading at once cannot
double-close a session. Timesheets use the same per-crew-member sweep as the
crew board before reading their requested range.
"""

import re
import uuid
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.auth_deps import get_current_user, require_min_role
from app.database import get_db
from app.domain import labor_day, roles
from app.domain.errors import DomainError
from app.models import User
from app.routers._errors import to_http
from app.schemas.hub import HubAdminResponse, HubClock, HubCrewResponse, HubResponse, HubTimesheetResponse
from app.services import hub as hub_service

router = APIRouter(prefix="/hub", tags=["hub"])


@router.get("", response_model=HubResponse)
def get_hub(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The signed-in person's own block: counts, today's time, the clock,
    the `Start on...` picker, and tools they are holding.

    Open to every authenticated role, Admin included -- a supervisor can
    already start a clock on any work order they can see, so one with a
    running clock and nowhere to see it would be a regression.

    Built field by field rather than by `model_validate(payload)` because two
    names deliberately differ across the boundary: the service's `DaySummary`
    describes *a* day and is reused by the timesheet grid in a later phase,
    while this response is always about today and its fields say so. The
    nested models are all `from_attributes`, so the dataclasses below pass
    straight in.
    """
    payload = hub_service.personal_hub(db, user)
    clock = payload.clock
    return HubResponse(
        user=payload.user,
        server_now=payload.server_now,
        day=payload.day,
        clock=HubClock(
            running_session=clock.running,
            closed_minutes_today=clock.closed_minutes,
            running_minutes_today=clock.running_minutes,
            adjustment_minutes_today=clock.adjustment_minutes,
            adjustments=clock.adjustments,
        ),
        timeline=clock.timeline,
        counts=payload.counts,
        startable=payload.startable,
        tools_out=payload.tools_out,
    )


@router.get("/crew", response_model=HubCrewResponse)
def get_hub_crew(
    user: User = Depends(require_min_role(roles.ROLE_SUPERVISOR)),
    db: Session = Depends(get_db),
):
    """The crew board: who this supervisor leads, who is on the clock, and
    what needs a look.

    One declarative gate -- `auth_deps.py` stays the only place a role 403
    is raised. `model_validate` does the whole translation because every
    field in `HubCrewResponse` is `from_attributes` and the service's
    dataclasses pass straight through.
    """
    return HubCrewResponse.model_validate(hub_service.crew_hub(db, user))


@router.get("/admin", response_model=HubAdminResponse)
def get_hub_admin(
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
):
    """The company-wide time summary: today's tracked minutes for every
    active Supervisor and every active Technician, summed separately.

    One declarative gate, same pattern as `get_hub_crew` -- `auth_deps.py`
    stays the only place a role 403 is raised.
    """
    return HubAdminResponse.model_validate(hub_service.admin_hub(db, user))


def _default_range(now: datetime) -> tuple[date, date]:
    """The current Monday-Sunday Central calendar week (D12)."""
    return labor_day.week_bounds_containing(labor_day.central_date_of(now))


def _resolve_range(
    start: Optional[date], end: Optional[date], now: datetime
) -> tuple[date, date]:
    """Use an explicit pair, or default both halves together."""
    if start is not None and end is not None:
        return start, end
    return _default_range(now)


def _filename_slug(value: object) -> str:
    """A short filesystem-safe token, matching work-order exports."""
    return re.sub(r"[^a-z0-9]+", "-", str(value).strip().casefold()).strip("-")[:24]


def _timesheet_filename(
    payload: hub_service.HubTimesheetPayload, *, technician: Optional[User]
) -> str:
    stamp = f"{payload.range.start.isoformat()}_to_{payload.range.end.isoformat()}"
    if technician is not None:
        return f"timesheet_{stamp}_{_filename_slug(technician.full_name)}.csv"
    return f"timesheet_{stamp}.csv"


@router.get("/timesheets", response_model=HubTimesheetResponse)
def get_hub_timesheets(
    start: Optional[date] = Query(None),
    end: Optional[date] = Query(None),
    user_id: Optional[uuid.UUID] = Query(None),
    user: User = Depends(require_min_role(roles.ROLE_SUPERVISOR)),
    db: Session = Depends(get_db),
):
    """Return the caller's routed crew timesheets for an inclusive range."""
    now = datetime.now(timezone.utc)
    range_start, range_end = _resolve_range(start, end, now)
    try:
        payload = hub_service.timesheets_hub(
            db,
            user,
            start=range_start,
            end=range_end,
            user_id=user_id,
            now=now,
        )
    except DomainError as exc:
        raise to_http(exc) from exc
    return HubTimesheetResponse.model_validate(payload)


@router.get("/timesheets/export")
def export_hub_timesheets(
    start: Optional[date] = Query(None),
    end: Optional[date] = Query(None),
    user_id: Optional[uuid.UUID] = Query(None),
    user: User = Depends(require_min_role(roles.ROLE_SUPERVISOR)),
    db: Session = Depends(get_db),
):
    """Download the same scoped payload as payroll-friendly CSV (D14)."""
    now = datetime.now(timezone.utc)
    range_start, range_end = _resolve_range(start, end, now)
    try:
        payload = hub_service.timesheets_hub(
            db,
            user,
            start=range_start,
            end=range_end,
            user_id=user_id,
            now=now,
        )
    except DomainError as exc:
        raise to_http(exc) from exc

    technician = next(
        (
            row.user
            for row in payload.rows
            if user_id is not None and row.user.id == user_id
        ),
        None,
    )
    filename = _timesheet_filename(payload, technician=technician)
    return Response(
        content=hub_service.timesheet_csv(payload),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
