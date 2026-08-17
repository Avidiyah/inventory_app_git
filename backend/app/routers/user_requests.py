"""HTTP routes for operational User Requests.

TechFM OA and above own the queue, with one deliberate exception: filing an item
request is open to any authenticated session, because the Technician who
cannot find a material on the floor is exactly the person who has to report
it. Every other operation here stays TechFM OA+.
"""

from typing import Literal, Optional
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth_deps import get_current_user, require_min_role
from app.database import get_db
from app.domain import roles
from app.domain.errors import DomainError, WorkOrderNotFoundError
from app.models import User, UserRequest, WorkOrder
from app.routers._errors import to_http
from app.schemas.user_requests import (
    ItemRequestCreate,
    ItemRequestFulfill,
    UserRequestResponse,
    UserRequestUpdate,
)
from app.services import items as items_service
from app.services import user_requests as request_service


router = APIRouter(prefix="/user-requests", tags=["user-requests"])


def _response(
    request: UserRequest, *, skipped: Optional[list[str]] = None
) -> UserRequestResponse:
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
        work_order_archived=bool(
            request.work_order is not None
            and request.work_order.archived_at is not None
        ),
        skipped=skipped or [],
    )


@router.get("/", response_model=list[UserRequestResponse])
def list_user_requests(
    status: Optional[Literal["open", "resolved"]] = Query("open"),
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
):
    """List queue-visible requests. Omit ``status`` only through an internal
    call; the browser uses ``open`` or ``resolved`` queues explicitly."""
    return [_response(row) for row in request_service.list_user_requests(db, status=status)]


@router.post("/item-request", response_model=UserRequestResponse, status_code=201)
def create_item_request(
    payload: ItemRequestCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """File a request for a material with no catalogue row.

    The one route on this router open to any authenticated session -- the same
    shape as ``POST /transactions/``, which is also gated by what the caller is
    doing rather than by rank. TechFM OA+ still owns reading and resolving the
    queue.
    """
    number = None
    if payload.work_order_id is not None:
        work_order = (
            db.query(WorkOrder)
            .filter(
                WorkOrder.id == payload.work_order_id,
                WorkOrder.archived_at.is_(None),
            )
            .first()
        )
        if work_order is None:
            raise to_http(WorkOrderNotFoundError("Work order not found."))
        number = work_order.number

    request = request_service.create_item_request(
        db,
        searched_text=payload.searched_text,
        quantity=payload.quantity,
        note=payload.note,
        work_order_id=payload.work_order_id,
        work_order_number=number,
        source=payload.source,
        created_by_id=user.id,
    )
    db.commit()
    return _response(request_service.get_user_request(db, request.id))


@router.get(
    "/{request_id}/siblings",
    response_model=list[UserRequestResponse],
    responses={403: {"description": "Requires the admin role or above."}},
)
def list_request_siblings(
    request_id: uuid.UUID,
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
):
    """Other open item requests naming the same material.

    A proposal for a TechFM OA or Admin to confirm before a fulfilment cascades to them,
    never an action in itself.
    """
    try:
        request = request_service.get_user_request(db, request_id)
        return [
            _response(row)
            for row in request_service.find_sibling_item_requests(db, request)
        ]
    except DomainError as exc:
        raise to_http(exc)


@router.post(
    "/{request_id}/fulfill",
    response_model=UserRequestResponse,
    responses={403: {"description": "Requires the admin role or above."}},
)
def fulfill_item_request(
    request_id: uuid.UUID,
    payload: ItemRequestFulfill,
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
):
    """Create or link the item, log it retroactively on every live work order
    across this request and its confirmed siblings, and resolve them all.

    Item creation runs first and through ``items_service.create_item`` so
    barcode uniqueness and the archived-holder conflict keep their existing
    behavior rather than being reimplemented here.
    """
    try:
        item_id = payload.item_id
        if payload.new_item is not None:
            item = items_service.create_item(db, **payload.new_item.model_dump())
            item_id = item.id

        request, skipped = request_service.fulfill_item_request(
            db,
            request_id,
            item_id=item_id,
            sibling_ids=payload.sibling_ids,
            resolved_by_id=user.id,
        )
        return _response(request, skipped=skipped)
    except DomainError as exc:
        raise to_http(exc)


@router.patch("/{request_id}", response_model=UserRequestResponse)
def update_user_request(
    request_id: uuid.UUID,
    payload: UserRequestUpdate,
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
):
    """Move a request through the queue and/or correct how it reads.

    Both jobs share one route because they share one row. Wording is applied
    first so a single call that edits and resolves ends up with the edit
    reflected in the resolved record.
    """
    try:
        request = None
        if payload.message is not None or payload.details is not None:
            request = request_service.update_user_request_fields(
                db,
                request_id,
                message=payload.message,
                details_patch=payload.details,
            )
        if payload.status is not None:
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
