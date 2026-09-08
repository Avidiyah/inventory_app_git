"""HTTP routes for operational User Requests.

TechFM OA and above own the queue, with one deliberate exception: filing a catalogue
request is open to any authenticated session, because the Technician who
cannot find a material on the floor is exactly the person who has to report
it. Every other operation here stays TechFM OA+.
"""

from decimal import Decimal
from typing import Optional
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth_deps import get_current_user, require_min_role
from app.database import get_db
from app.domain import roles
from app.domain.errors import DomainError, WorkOrderNotFoundError
from app.models import User, UserRequest, WorkOrder
from app.routers._errors import to_http
from app.routers._stock_events import emit_user_request_changed, flush_stock_events
from app.schemas.user_requests import (
    CatalogueRequestCreate,
    CatalogueRequestFulfill,
    MaterialRequestCreate,
    UserRequestResponse,
    UserRequestUpdate,
)
from app.services import items as items_service
from app.services import material_requests as material_service
from app.services import notifications as notifications_service
from app.services import user_requests as request_service
from app.services import work_orders as wo_service


router = APIRouter(prefix="/user-requests", tags=["user-requests"])


def build_response(
    request: UserRequest,
    *,
    skipped: Optional[list[str]] = None,
    item_quantity: Optional[Decimal] = None,
    updated: bool = False,
) -> UserRequestResponse:
    fallback_number = (request.details or {}).get("work_order_number")
    on_hand = item_quantity if item_quantity is not None else (
        request.item.quantity if request.item else None
    )
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
        item_quantity=on_hand,
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
        updated=updated,
    )


_response = build_response


_LIST_STATUSES = ("open", "stocked", "resolved")
_LIST_TYPES = (
    request_service.REQUEST_MATERIAL,
    request_service.REQUEST_CATALOGUE,
    request_service.REQUEST_INVENTORY_RECOUNT,
    request_service.REQUEST_MISSING_ITEM_PRICE,
)


@router.get("/", response_model=list[UserRequestResponse])
def list_user_requests(
    status: str = Query("open"),
    type: Optional[str] = Query(None),
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
):
    """List queue-visible requests, optionally one type. Plain `str` with a
    manual check rather than `Literal`: the User Requests tabs send both
    params on every load, and the manual check gives one 422 shape for both."""
    if status not in _LIST_STATUSES:
        raise HTTPException(status_code=422, detail="status must be open, stocked, or resolved")
    if type is not None and type not in _LIST_TYPES:
        raise HTTPException(status_code=422, detail="unknown request type")
    return [
        build_response(row)
        for row in request_service.list_user_requests(db, status=status, request_type=type)
    ]


@router.get(
    "/counts",
    response_model=dict[str, dict[str, int]],
    responses={403: {"description": "Requires the TechFM OA role or above."}},
)
def list_request_counts(
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
):
    """`{request_type: {"open": n, "stocked": n}}` for the tab labels."""
    return material_service.open_counts(db)


@router.post("/material-request", response_model=UserRequestResponse, status_code=201)
def create_material_request(
    payload: MaterialRequestCreate,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """File a request for a catalogue item the shelf does not have.

    Open to any authenticated session, scoped by the same visible-work-order
    reader the Work Orders page uses (SEC-021 applied from day one): a
    Technician can only file against a job they are assigned to, and an
    invisible or archived work order is 404, not 403. On-hand is read for
    the response only -- never a gate.
    """
    try:
        work_order = wo_service.get_visible_work_order(db, payload.work_order_id, user)
        item = material_service.lock_live_item(db, payload.item_id)
        request, created = material_service.create_or_update(
            db,
            item_id=item.id,
            work_order=work_order,
            quantity=payload.quantity,
            product_link=payload.product_link,
            note=payload.note,
            created_by_id=user.id,
            origin=material_service.ORIGIN_REQUEST_CARD,
        )
        db.commit()
        on_hand = item.quantity
        request = request_service.get_user_request(db, request.id)
        if created:
            notifications_service.notify_material_request_filed(
                db, background, item_name=item.name, work_order_number=work_order.number
            )
        emit_user_request_changed(request.id)
        return build_response(request, item_quantity=on_hand, updated=not created)
    except DomainError as exc:
        raise to_http(exc)


@router.post("/catalogue-request", response_model=UserRequestResponse, status_code=201)
def create_catalogue_request(
    payload: CatalogueRequestCreate,
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

    request = request_service.create_catalogue_request(
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
    """Other open catalogue requests naming the same material.

    A proposal for a TechFM OA or Admin to confirm before a fulfilment cascades to them,
    never an action in itself.
    """
    try:
        request = request_service.get_user_request(db, request_id)
        return [
            _response(row)
            for row in request_service.find_sibling_catalogue_requests(db, request)
        ]
    except DomainError as exc:
        raise to_http(exc)


@router.post(
    "/{request_id}/fulfill",
    response_model=UserRequestResponse,
    responses={403: {"description": "Requires the admin role or above."}},
)
def fulfill_catalogue_request(
    request_id: uuid.UUID,
    payload: CatalogueRequestFulfill,
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

        request, skipped = request_service.fulfill_catalogue_request(
            db,
            request_id,
            item_id=item_id,
            sibling_ids=payload.sibling_ids,
            resolved_by_id=user.id,
        )
        emit_user_request_changed(request_id)
        return _response(request, skipped=skipped)
    except DomainError as exc:
        raise to_http(exc)


@router.post(
    "/{request_id}/mark-stocked",
    response_model=UserRequestResponse,
    responses={403: {"description": "Requires the TechFM OA role or above."}},
)
def mark_request_stocked(
    request_id: uuid.UUID,
    background: BackgroundTasks,
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
):
    """Staff counted the shelf and the item is really there: fire the crew's
    stocked notification without faking a stock transaction. Same service
    transition and same flush as the automatic edge."""
    try:
        material_service.mark_stocked(db, request_id, actor_id=user.id)
        db.commit()
        flush_stock_events(db, background)
        return build_response(request_service.get_user_request(db, request_id))
    except DomainError as exc:
        raise to_http(exc)


@router.post("/{request_id}/cancel", response_model=UserRequestResponse)
def cancel_material_request(
    request_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The filer withdraws their own open request (403 for anyone else, 409
    once it is stocked or resolved)."""
    try:
        material_service.cancel(db, request_id, actor_id=user.id)
        db.commit()
        emit_user_request_changed(request_id)
        return build_response(request_service.get_user_request(db, request_id))
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
        emit_user_request_changed(request_id)
        return _response(request)
    except DomainError as exc:
        raise to_http(exc)
