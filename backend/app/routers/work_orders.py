"""HTTP routes for the `/work-orders` resource (the work order entity).

Layer: routers (FastAPI). Thin handlers: parse via a Pydantic schema, delegate
to `app.services.work_orders`, translate `DomainError` via `to_http`.

Most routes are open to any authenticated user but **server-scoped** (technician
-> assigned, supervisor -> created, admin/owner -> all). Creating a work order,
editing its attributes/assignee, and archiving are Supervisor+ (a technician may
only log/edit materials and flip status/mode on a work order assigned to them).
Out-of-scope, archived, or unknown work orders surface as 404.
"""

import uuid
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth_deps import get_current_user
from app.database import get_db
from app.domain import roles
from app.domain.errors import DomainError
from app.models import User, WorkOrder, WorkOrderItem
from app.routers._errors import to_http
from app.schemas.work_orders import (
    WorkOrderCard,
    WorkOrderCreate,
    WorkOrderDetail,
    WorkOrderItemBilling,
    WorkOrderItemCreate,
    WorkOrderItemDetail,
    WorkOrderItemUpdate,
    WorkOrderUpdate,
)
from app.services import work_orders as wo_service

router = APIRouter(prefix="/work-orders", tags=["work-orders"])

# Fields only a Supervisor+ may edit (identity / location / assignment). Status
# and entry_mode may be changed by any in-scope user (incl. an assigned tech).
_PRIVILEGED_FIELDS = {
    "number",
    "community",
    "building_number",
    "unit_number",
    "description",
    "assigned_to_id",
}


# --- response builders ---------------------------------------------------

def _effective_billable(line: WorkOrderItem) -> Decimal:
    """Units actually charged on a line: the override when set, else the full
    recorded quantity."""
    return line.quantity if line.billable_quantity is None else line.billable_quantity


def _line_detail(line: WorkOrderItem, *, include_price: bool) -> WorkOrderItemDetail:
    return WorkOrderItemDetail(
        id=line.id,
        item_id=line.item_id,
        item_name=line.item.name,
        item_barcode=line.item.barcode,
        item_quantity=line.item.quantity,
        quantity=line.quantity,
        mode=line.mode,
        # The line bills at the item's current price; both cost fields are
        # redacted below Admin.
        unit_price=line.item.price if include_price else None,
        billable_quantity=line.billable_quantity if include_price else None,
    )


def _card(work_order: WorkOrder) -> WorkOrderCard:
    return WorkOrderCard(
        id=work_order.id,
        number=work_order.number,
        community=work_order.community,
        building_number=work_order.building_number,
        unit_number=work_order.unit_number,
        description=work_order.description,
        status=work_order.status,
        entry_mode=work_order.entry_mode,
        created_by_id=work_order.created_by_id,
        assigned_to_id=work_order.assigned_to_id,
        assigned_to_username=work_order.assignee.username if work_order.assignee else None,
        item_count=len(work_order.items),
    )


def _materials_total(work_order: WorkOrder) -> Decimal:
    """Base materials charge (pre-mark-up): sum of each line's effective billable
    units times the item's current price."""
    total = Decimal(0)
    for line in work_order.items:
        price = line.item.price or Decimal(0)
        total += price * _effective_billable(line)
    return total


def _detail(work_order: WorkOrder, *, include_price: bool) -> WorkOrderDetail:
    return WorkOrderDetail(
        **_card(work_order).model_dump(),
        items=[_line_detail(line, include_price=include_price) for line in work_order.items],
        materials_total=_materials_total(work_order) if include_price else None,
    )


def _can_see_price(user: User) -> bool:
    """Cost fields (line unit price) are Admin/Owner only, mirroring item /
    history price redaction."""
    return roles.role_at_least(user.role, roles.ROLE_ADMIN)


# --- routes --------------------------------------------------------------

@router.get("/", response_model=list[WorkOrderCard])
def list_work_orders(
    status: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List the caller's work orders, newest-first. `status` filters by
    in_progress|completed; `q` is a case-insensitive number search. Any
    authenticated user; server-scoped."""
    try:
        return [
            _card(w)
            for w in wo_service.list_work_orders(db, user=user, status=status, search=q)
        ]
    except DomainError as exc:
        raise to_http(exc)


@router.post("/", response_model=WorkOrderDetail, status_code=201)
def create_work_order(
    payload: WorkOrderCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a work order (Supervisor+). Re-using an existing LIVE number opens
    that work order (fill-blanks), not an error. A number matching an *archived*
    work order returns 409 unless `restore_archived` is set, so the page can
    confirm the restore and re-submit."""
    if not roles.role_at_least(user.role, roles.ROLE_SUPERVISOR):
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action.")
    try:
        work_order = wo_service.create_work_order(
            db,
            user=user,
            number=payload.number,
            community=payload.community,
            building_number=payload.building_number,
            unit_number=payload.unit_number,
            description=payload.description,
            assigned_to_id=payload.assigned_to_id,
            restore_archived=payload.restore_archived,
        )
        # Re-fetch through the scoped loader so the response carries items/assignee.
        return _detail(
            wo_service.get_work_order(db, work_order.id, user=user),
            include_price=_can_see_price(user),
        )
    except DomainError as exc:
        raise to_http(exc)


@router.get("/{work_order_id}", response_model=WorkOrderDetail)
def get_work_order(
    work_order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Full work-order detail with logged materials. 404 if unknown, archived,
    or not visible to the caller."""
    try:
        return _detail(
            wo_service.get_work_order(db, work_order_id, user=user),
            include_price=_can_see_price(user),
        )
    except DomainError as exc:
        raise to_http(exc)


@router.patch("/{work_order_id}", response_model=WorkOrderDetail)
def update_work_order(
    work_order_id: uuid.UUID,
    payload: WorkOrderUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Edit a work order. Status / entry_mode are editable by any in-scope user;
    identity / location / assignment require Supervisor+. Server-scoped."""
    fields = payload.model_dump(exclude_unset=True)
    if _PRIVILEGED_FIELDS & fields.keys() and not roles.role_at_least(
        user.role, roles.ROLE_SUPERVISOR
    ):
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action.")
    try:
        work_order = wo_service.update_work_order(db, work_order_id, user=user, fields=fields)
        return _detail(
            wo_service.get_work_order(db, work_order.id, user=user),
            include_price=_can_see_price(user),
        )
    except DomainError as exc:
        raise to_http(exc)


@router.post("/{work_order_id}/archive", status_code=204)
def archive_work_order(
    work_order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Soft-archive a work order (Supervisor+, scoped)."""
    if not roles.role_at_least(user.role, roles.ROLE_SUPERVISOR):
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action.")
    try:
        wo_service.archive_work_order(db, work_order_id, user=user)
    except DomainError as exc:
        raise to_http(exc)


@router.post("/{work_order_id}/items", response_model=WorkOrderItemDetail, status_code=201)
def add_work_order_item(
    work_order_id: uuid.UUID,
    payload: WorkOrderItemCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Log a material using the work order's current entry mode (dispense moves
    stock; retroactive is stock-neutral). Re-adding an item replaces its
    quantity. Server-scoped; 400 if a dispense add overdraws stock."""
    try:
        line = wo_service.add_work_order_item(
            db, work_order_id, user=user, item_id=payload.item_id, quantity=payload.quantity
        )
        return _line_detail(line, include_price=_can_see_price(user))
    except DomainError as exc:
        raise to_http(exc)


@router.patch("/{work_order_id}/items/{wo_item_id}", response_model=WorkOrderItemDetail)
def update_work_order_item(
    work_order_id: uuid.UUID,
    wo_item_id: uuid.UUID,
    payload: WorkOrderItemUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Edit a logged material's quantity (dispense lines auto-correct stock)."""
    try:
        line = wo_service.update_work_order_item(
            db, work_order_id, wo_item_id, user=user, quantity=payload.quantity
        )
        return _line_detail(line, include_price=_can_see_price(user))
    except DomainError as exc:
        raise to_http(exc)


@router.patch(
    "/{work_order_id}/items/{wo_item_id}/billing",
    response_model=WorkOrderItemDetail,
)
def set_work_order_item_billing(
    work_order_id: uuid.UUID,
    wo_item_id: uuid.UUID,
    payload: WorkOrderItemBilling,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Set or clear a material line's billing override (Admin/Owner). The line is
    the billing unit for work-order materials, so this charges fewer units than
    were consumed (or none) without touching stock. `null` clears the override;
    `0` records but does not charge; a value up to the line quantity bills a
    partial count. 403 below Admin; 400 if the value exceeds the line quantity."""
    if not _can_see_price(user):
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action.")
    try:
        line = wo_service.set_work_order_item_billable(
            db, work_order_id, wo_item_id, user=user, billable_quantity=payload.billable_quantity
        )
        return _line_detail(line, include_price=True)
    except DomainError as exc:
        raise to_http(exc)


@router.delete("/{work_order_id}/items/{wo_item_id}", status_code=204)
def delete_work_order_item(
    work_order_id: uuid.UUID,
    wo_item_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove a logged material (dispense lines return stock; the linked History
    row is voided). Server-scoped."""
    try:
        wo_service.delete_work_order_item(db, work_order_id, wo_item_id, user=user)
    except DomainError as exc:
        raise to_http(exc)
