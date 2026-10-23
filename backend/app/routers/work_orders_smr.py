"""SMR27 audit routes (spec docs/superpowers/specs/2026-10-23-smr-audit-workflow-design.md).

Mounted under `/work-orders/smr`, declared on its own router so the
`/work-orders/{work_order_id}` catch-all never swallows `smr`. Import and
export are Owner-only; the tile list is Admin+."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.auth_deps import require_min_role
from app.database import get_db
from app.domain import roles
from app.domain.errors import DomainError
from app.models import User
from app.routers._errors import to_http
from app.routers._uploads import MAX_CSV_UPLOAD_BYTES, read_capped
from app.schemas.work_orders_smr import SmrImportResult, SmrTilesResponse
from app.services import work_orders_smr as smr_service

router = APIRouter(prefix="/work-orders/smr", tags=["work-orders-smr"])


def _forbidden(role: str) -> dict:
    return {403: {"description": f"Requires {roles.ROLE_LABELS[role]} or above."}}


@router.post(
    "/import",
    response_model=SmrImportResult,
    responses={**_forbidden(roles.ROLE_OWNER), 413: {"description": "CSV exceeds the upload size cap."}},
)
def import_smr(
    file: UploadFile = File(...),
    user: User = Depends(require_min_role(roles.ROLE_OWNER)),
    db: Session = Depends(get_db),
) -> SmrImportResult:
    """Import the SMR27 vendor sheet (Owner). Sync `def` for the same reason
    the mass import is: one long transaction belongs in the threadpool. The
    role gate is a dependency, so it answers before the body is read."""
    data = read_capped(file, limit=MAX_CSV_UPLOAD_BYTES, what="CSV file")
    try:
        return smr_service.import_smr(db, csv_bytes=data, user=user)
    except DomainError as exc:
        raise to_http(exc)


@router.get("", response_model=SmrTilesResponse, responses=_forbidden(roles.ROLE_ADMIN))
def list_smr_tiles(
    user: User = Depends(require_min_role(roles.ROLE_ADMIN)),
    db: Session = Depends(get_db),
) -> SmrTilesResponse:
    """Every SMR order as a tile with before / after / delta totals (Admin+).
    Unpaginated: the audit is a few hundred rows."""
    return smr_service.list_smr_tiles(db)
