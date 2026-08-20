"""HTTP routes for the User Hub.

Layer: routers (FastAPI). Thin handlers only, mirroring
`app/routers/tools.py`. Payloads stack by rank rather than branching by
role, so each route carries exactly one declarative gate and `auth_deps.py`
stays the only place a role 403 is raised:

- `GET /hub`             any authenticated  -- the personal block
- `GET /hub/crew`        supervisor+        -- the crew board (this phase)
- `GET /hub/admin`       techfm_oa+         -- later phase
- `GET /hub/timesheets`  supervisor+        -- later phase

**Neither `GET /hub` nor `GET /hub/crew` is side-effect-free.** Both sweep
over-cap sessions before reading and therefore commit when they find one --
`GET /hub` the caller's own, `GET /hub/crew` each crew member's individually
(spec §3.5 assigns the global sweep to `GET /hub/admin` only and is silent on
`/hub/crew`; scoping the crew sweep to exactly the people it reads follows
the same reasoning `GET /hub` already applies to itself). This follows
existing precedent rather than inventing it -- `get_work_order` already both
sweeps sessions and self-heals orphaned material lines on a read -- and the
sweep is idempotent under a row lock, so two tabs loading at once cannot
double-close a session.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth_deps import get_current_user, require_min_role
from app.database import get_db
from app.domain import roles
from app.models import User
from app.schemas.hub import HubClock, HubCrewResponse, HubResponse
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
