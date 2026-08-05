"""Admin/Owner HTTP routes for operational User Requests."""

from typing import Literal, Optional
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth_deps import require_min_role
from app.database import get_db
from app.domain import roles
from app.domain.errors import DomainError
from app.models import User, UserRequest
from app.routers._errors import to_http
from app.schemas.user_requests import UserRequestResponse, UserRequestUpdate
from app.services import user_requests as request_service


router = APIRouter(prefix="/user-requests", tags=["user-requests"])


def _response(request: UserRequest) -> UserRequestResponse:
    fallback_number = (request.details or {}).get("work_order_number")
    return UserRequestResponse(
        id=request.id,
        request_type=request.request_type,
        status=request.status,
        message=request.message,
        item_id=request.item_id,
        item_name=request.item.name if request.item else None,
        item_barcode=request.item.barcode if request.item else None,
        item_price=request.item.price if request.item else None,
        item_product_link=request.item.product_link if request.item else None,
        transaction_id=request.transaction_id,
        work_order_id=request.work_order_id,
        work_order_number=(
            request.work_order.number if request.work_order else fallback_number
        ),
        created_by_id=request.created_by_id,
        created_by_name=request.creator.full_name if request.creator else None,
        details=request.details or {},
        created_at=request.created_at,
        resolved_at=request.resolved_at,
        resolved_by_id=request.resolved_by_id,
        resolved_by_name=request.resolver.full_name if request.resolver else None,
        resolution_note=request.resolution_note,
    )


@router.get("/", response_model=list[UserRequestResponse])
def list_user_requests(
    status: Optional[Literal["open", "resolved"]] = Query("open"),
    user: User = Depends(require_min_role(roles.ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """List Admin-visible requests. Omit ``status`` only through an internal
    call; the browser uses ``open`` or ``resolved`` queues explicitly."""
    return [_response(row) for row in request_service.list_user_requests(db, status=status)]


@router.patch("/{request_id}", response_model=UserRequestResponse)
def update_user_request(
    request_id: uuid.UUID,
    payload: UserRequestUpdate,
    user: User = Depends(require_min_role(roles.ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    try:
        request = request_service.update_user_request(
            db,
            request_id,
            status=payload.status,
            resolution_note=payload.resolution_note,
            resolved_by_id=user.id,
        )
        return _response(request)
    except DomainError as exc:
        raise to_http(exc)
