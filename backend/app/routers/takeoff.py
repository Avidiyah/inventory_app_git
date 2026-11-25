"""HTTP routes for Takeoff: predicted material per work order, and the office page.

Layer: routers (FastAPI). Thin handlers over `app.services.takeoff`. Line routes
are Team Lead+; the overview and purchases are TechFM OA+. Full paths, no prefix:
the line routes live under `/work-orders/{id}` and the page under `/takeoff`.
"""

import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.auth_deps import require_min_role
from app.database import get_db
from app.domain import roles
from app.domain.errors import DomainError
from app.models import User, WorkOrderTakeoffLine
from app.routers._errors import to_http
from app.routers.work_orders import _emit_status_changed, _forbidden
from app.schemas.takeoff import (
    TakeoffLineCreate,
    TakeoffLineOut,
    TakeoffLineUpdate,
    TakeoffOverview,
    TakeoffPurchaseSet,
)
from app.services import takeoff as takeoff_service

router = APIRouter(tags=["takeoff"])

_LEAD = Depends(require_min_role(roles.ROLE_SUPERVISOR))
_OA = Depends(require_min_role(roles.ROLE_TECHFM_OA))


def _out(line: WorkOrderTakeoffLine) -> TakeoffLineOut:
    return TakeoffLineOut(
        id=line.id, item_id=line.item_id, item_name=line.item.name, quantity=line.quantity
    )


@router.post(
    "/work-orders/{work_order_id}/takeoff",
    response_model=TakeoffLineOut,
    status_code=201,
    dependencies=[_LEAD],
    responses=_forbidden(roles.ROLE_SUPERVISOR),
)
def add_takeoff_line(
    work_order_id: uuid.UUID,
    payload: TakeoffLineCreate,
    user: User = Depends(require_min_role(roles.ROLE_SUPERVISOR)),
    db: Session = Depends(get_db),
):
    """Predict material for a work order. Re-adding an item adds to its line."""
    try:
        line = takeoff_service.add_line(
            db, work_order_id, user=user, item_id=payload.item_id, quantity=payload.quantity
        )
    except DomainError as exc:
        raise to_http(exc)
    _emit_status_changed(work_order_id)
    return _out(line)


@router.patch(
    "/work-orders/{work_order_id}/takeoff/{line_id}",
    response_model=TakeoffLineOut,
    dependencies=[_LEAD],
    responses=_forbidden(roles.ROLE_SUPERVISOR),
)
def update_takeoff_line(
    work_order_id: uuid.UUID,
    line_id: uuid.UUID,
    payload: TakeoffLineUpdate,
    user: User = Depends(require_min_role(roles.ROLE_SUPERVISOR)),
    db: Session = Depends(get_db),
):
    """Set a takeoff line's remaining quantity."""
    try:
        line = takeoff_service.update_line(
            db, work_order_id, line_id, user=user, quantity=payload.quantity
        )
    except DomainError as exc:
        raise to_http(exc)
    _emit_status_changed(work_order_id)
    return _out(line)


@router.delete(
    "/work-orders/{work_order_id}/takeoff/{line_id}",
    status_code=204,
    dependencies=[_LEAD],
    responses=_forbidden(roles.ROLE_SUPERVISOR),
)
def delete_takeoff_line(
    work_order_id: uuid.UUID,
    line_id: uuid.UUID,
    user: User = Depends(require_min_role(roles.ROLE_SUPERVISOR)),
    db: Session = Depends(get_db),
):
    """Remove a takeoff line."""
    try:
        takeoff_service.delete_line(db, work_order_id, line_id, user=user)
    except DomainError as exc:
        raise to_http(exc)
    _emit_status_changed(work_order_id)
    return Response(status_code=204)


@router.get(
    "/takeoff/",
    response_model=TakeoffOverview,
    dependencies=[_OA],
    responses=_forbidden(roles.ROLE_TECHFM_OA),
)
def takeoff_overview(db: Session = Depends(get_db)):
    """Need per service type and item across live work orders (TechFM OA+)."""
    return takeoff_service.overview(db)


@router.put(
    "/takeoff/purchases",
    status_code=204,
    dependencies=[_OA],
    responses=_forbidden(roles.ROLE_TECHFM_OA),
)
def set_takeoff_purchase(
    payload: TakeoffPurchaseSet,
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
):
    """Set how many of an item are on the way for one service type; 0 clears."""
    try:
        takeoff_service.set_purchase(
            db, user=user, item_id=payload.item_id,
            service_type_key=payload.service_type_key,
            service_type_label=payload.service_type_label,
            quantity=payload.quantity,
        )
    except DomainError as exc:
        raise to_http(exc)
    return Response(status_code=204)
