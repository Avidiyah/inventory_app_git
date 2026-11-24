"""HTTP routes for the Owner's app-wide switches: `/feature-switches/...`.

Owner only. The SPA reads the current state off `/auth/me` (`smr_enabled`),
so there is no read route here."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth_deps import require_min_role
from app.database import get_db
from app.domain import roles
from app.services import feature_switches


class SwitchIn(BaseModel):
    enabled: bool


class SwitchOut(BaseModel):
    enabled: bool


router = APIRouter(prefix="/feature-switches", tags=["feature-switches"])


@router.put(
    "/smr",
    response_model=SwitchOut,
    dependencies=[Depends(require_min_role(roles.ROLE_OWNER))],
    responses={403: {"description": f"Requires the {roles.label(roles.ROLE_OWNER)} role."}},
)
def set_smr_switch(payload: SwitchIn, db: Session = Depends(get_db)):
    """Turn the SMR27 audit on or off for everyone."""
    return SwitchOut(enabled=feature_switches.set_enabled(db, feature_switches.SMR, payload.enabled))
