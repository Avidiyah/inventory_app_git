"""HTTP routes for the `/work-orders` resource (the work order entity).

Layer: routers (FastAPI). Thin handlers: parse via a Pydantic schema, delegate
to `app.services.work_orders`, translate `DomainError` via `to_http`.

Most routes are open to any authenticated user but **server-scoped** (technician
-> assigned, supervisor -> created/routed, admin/owner -> all). Editing a work
order's attributes/assignee and manual status rollback/On-Hold are Supervisor+;
notes and entry mode are available in-scope, and an assigned technician may Mark
Completed. Sending to Review remains Supervisor+.
Closing (the archive operation) is Admin+ and only valid from Review so the Admin
Review workflow is the sole UI entry point.
Out-of-scope, archived, or unknown work orders surface as 404.

There is no create route: work orders are import-only, so `POST /work-orders/
import` (Admin+) is the one way a work order enters the system. Everything else
here operates on an already-imported work order.
"""

import uuid
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.auth_deps import get_current_user, require_min_role
from app.database import get_db
from app.domain import roles
from app.domain import work_orders as wo
from app.domain.errors import DomainError
from app.models import User, WorkOrder, WorkOrderItem, WorkOrderLabor
from app.routers._errors import to_http
from app.schemas.work_orders import (
    WorkOrderCard,
    WorkOrderDetail,
    WorkOrderImportResult,
    WorkOrderItemBilling,
    WorkOrderItemCreate,
    WorkOrderItemDetail,
    WorkOrderItemUpdate,
    WorkOrderLaborCreate,
    WorkOrderLaborDetail,
    WorkOrderLaborUpdate,
    WorkOrderLookup,
    WorkOrderUpdate,
)
from app.services import work_orders as wo_service

router = APIRouter(prefix="/work-orders", tags=["work-orders"])

# Fields only a Supervisor+ may edit (identity / location / assignment). Notes
# and entry_mode are available in-scope; the route's dynamic status gate lets an
    # assigned technician set In-Progress or Mark Completed but reserves every
    # other manual status change for Supervisor+.
_PRIVILEGED_FIELDS = {
    "number",
    "community",
    "building_number",
    "unit_number",
    "description",
    "assigned_to_id",
    "assigned_to_ids",
    "supervisor_id",
    "location",
    "output_to",
    "vendor_assignee",
    "service_type",
    "schedule_date",
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
    technicians = wo_service.assigned_technicians(work_order)
    legacy_id = getattr(work_order, "assigned_to_id", None)
    technician_pairs = [
        (getattr(technician, "id", legacy_id if index == 0 else None), technician)
        for index, technician in enumerate(technicians)
    ]
    technician_pairs = [(tech_id, tech) for tech_id, tech in technician_pairs if tech_id]
    technician_ids = [tech_id for tech_id, _ in technician_pairs]
    technician_names = [technician.full_name for _, technician in technician_pairs]
    primary_pair = next(
        ((tech_id, tech) for tech_id, tech in technician_pairs if tech_id == legacy_id),
        technician_pairs[0] if technician_pairs else None,
    )
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
        assigned_to_id=primary_pair[0] if primary_pair else None,
        assigned_to_name=primary_pair[1].full_name if primary_pair else None,
        assigned_to_ids=technician_ids,
        assigned_to_names=technician_names,
        item_count=len(work_order.items),
        location=work_order.location,
        output_to=work_order.output_to,
        vendor_assignee=work_order.vendor_assignee,
        service_type=work_order.service_type,
        schedule_date=work_order.schedule_date,
        supervisor_id=work_order.supervisor_id,
        supervisor_name=work_order.supervisor.full_name if work_order.supervisor else None,
        legacy=work_order.legacy,
    )


def _materials_total(work_order: WorkOrder) -> Decimal:
    """Base materials charge (pre-mark-up): sum of each line's effective billable
    units times the item's current price."""
    total = Decimal(0)
    for line in work_order.items:
        price = line.item.price or Decimal(0)
        total += price * _effective_billable(line)
    return total


def _labor_detail(entry: WorkOrderLabor) -> WorkOrderLaborDetail:
    return WorkOrderLaborDetail(
        id=entry.id,
        technician_id=entry.technician_id,
        technician_name=entry.technician.full_name,
        minutes=entry.minutes,
    )


def _detail(work_order: WorkOrder, *, include_price: bool) -> WorkOrderDetail:
    labor_entries = list(getattr(work_order, "labor_entries", None) or ())
    labor_minutes = sum(entry.minutes for entry in labor_entries)
    return WorkOrderDetail(
        **_card(work_order).model_dump(),
        notes=work_order.notes,
        items=[_line_detail(line, include_price=include_price) for line in work_order.items],
        labor=[_labor_detail(entry) for entry in labor_entries],
        materials_total=_materials_total(work_order) if include_price else None,
        labor_minutes=labor_minutes,
        labor_billed_minutes=wo.billed_labor_minutes(labor_minutes),
        labor_rate=wo.LABOR_RATE if include_price else None,
        labor_total=wo.labor_charge(labor_minutes) if include_price else None,
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
    limit: Optional[int] = Query(None, ge=1),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List the caller's work orders, newest-first. `status` filters one live
    state including On-Hold; `q` is a case-insensitive number search;
    `limit` caps the result to the N newest (the page browses the 10 most recent
    by default and omits `limit` to show all / to search). Any authenticated user;
    server-scoped."""
    try:
        return [
            _card(w)
            for w in wo_service.list_work_orders(
                db, user=user, status=status, search=q, limit=limit
            )
        ]
    except DomainError as exc:
        raise to_http(exc)


@router.post("/import", response_model=WorkOrderImportResult)
async def import_work_orders(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Bulk-import work orders from the mass CSV export (Admin+). Each row
    find-or-creates by number (idempotent re-upload), stores the new-schema
    columns, and matches the vendor `ASSIGNED TO` name to a supervisor to route
    visibility. Returns a summary of created/opened/matched/skipped counts."""
    if not roles.role_at_least(user.role, roles.ROLE_ADMIN):
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action.")
    data = await file.read()
    try:
        summary = wo_service.import_work_orders(db, csv_bytes=data, user=user)
    except DomainError as exc:
        raise to_http(exc)
    return WorkOrderImportResult(**summary)


@router.get("/lookup", response_model=WorkOrderLookup)
def lookup_work_order(
    number: str = Query(..., min_length=1),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Report whether `number` names a work order the caller can see, and whether
    it is archived (Supervisor+).

    Declared before `/{work_order_id}` so "lookup" is not parsed as an id. This is
    the one read that sees through the archive: the list and detail routes hide
    archived work orders, which leaves a number that appears all over History with
    no visible work order. History uses this to offer a restore. A number the
    caller may not see reports `found=False`, same as the list would show."""
    if not roles.role_at_least(user.role, roles.ROLE_SUPERVISOR):
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action.")
    work_order = wo_service.lookup_work_order(db, number=number, user=user)
    if work_order is None:
        return WorkOrderLookup(found=False)
    return WorkOrderLookup(
        found=True,
        archived=work_order.archived_at is not None,
        id=work_order.id,
        number=work_order.number,
    )


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
    """Edit a work order. Notes and entry mode are available to an in-scope
    user, and an assigned technician may set In-Progress or Mark Completed.
    Manual rollback, On-Hold, Review, and identity/location/assignment require
    Supervisor+. Server-scoped."""
    fields = payload.model_dump(exclude_unset=True)
    if _PRIVILEGED_FIELDS & fields.keys() and not roles.role_at_least(
        user.role, roles.ROLE_SUPERVISOR
    ):
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action.")
    requested_status = fields.get("status")
    if requested_status is not None and not roles.role_at_least(
        user.role, roles.ROLE_SUPERVISOR
    ):
        if requested_status == wo.STATUS_IN_PROGRESS:
            # A technician may start pre-work, but must not use this allowance
            # to roll Completed/On-Hold/Review backward. Those transitions stay
            # inside the Supervisor+ Edit Details workflow.
            try:
                current = wo_service.get_work_order(db, work_order_id, user=user)
            except DomainError as exc:
                raise to_http(exc)
            if current.status not in (wo.STATUS_CREATED, wo.STATUS_ASSIGNED):
                raise HTTPException(status_code=403, detail="You do not have permission to perform this action.")
        elif requested_status != wo.STATUS_COMPLETED:
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
    user: User = Depends(require_min_role(roles.ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """Close a Review work order (Admin+, scoped) by soft-archiving it.

    The ordinary Work Orders page deliberately has no close action; the future
    Admin Review page is the intended caller for this existing endpoint.
    """
    try:
        wo_service.archive_work_order(db, work_order_id, user=user)
    except DomainError as exc:
        raise to_http(exc)


@router.post("/{work_order_id}/restore", response_model=WorkOrderDetail)
def restore_work_order(
    work_order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Un-archive a work order (Supervisor+, scoped), bringing it back onto the
    Work Orders page with its materials intact. The undo for `/archive`, and the
    only way back for an archived work order short of re-importing its CSV row --
    work orders are import-only, so it cannot simply be created again. 404 if
    unknown or not visible to the caller."""
    if not roles.role_at_least(user.role, roles.ROLE_SUPERVISOR):
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action.")
    try:
        work_order = wo_service.restore_work_order(db, work_order_id, user=user)
        return _detail(
            wo_service.get_work_order(db, work_order.id, user=user),
            include_price=_can_see_price(user),
        )
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


@router.post(
    "/{work_order_id}/labor",
    response_model=WorkOrderLaborDetail,
    status_code=201,
)
def add_work_order_labor(
    work_order_id: uuid.UUID,
    payload: WorkOrderLaborCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Record actual labor for an assigned technician.

    Technicians may record only themselves; Supervisor+ may record any assigned
    technician. The first entry starts pre-work, and billing rounds the combined
    work-order duration upward to the next 30 minutes.
    """
    try:
        return _labor_detail(
            wo_service.add_work_order_labor(
                db,
                work_order_id,
                user=user,
                technician_id=payload.technician_id,
                minutes=payload.minutes,
            )
        )
    except DomainError as exc:
        raise to_http(exc)


@router.patch(
    "/{work_order_id}/labor/{labor_id}",
    response_model=WorkOrderLaborDetail,
)
def update_work_order_labor(
    work_order_id: uuid.UUID,
    labor_id: uuid.UUID,
    payload: WorkOrderLaborUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Replace an in-scope labor entry's actual duration."""
    try:
        return _labor_detail(
            wo_service.update_work_order_labor(
                db,
                work_order_id,
                labor_id,
                user=user,
                minutes=payload.minutes,
            )
        )
    except DomainError as exc:
        raise to_http(exc)


@router.delete("/{work_order_id}/labor/{labor_id}", status_code=204)
def delete_work_order_labor(
    work_order_id: uuid.UUID,
    labor_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove an in-scope labor entry without rolling lifecycle status back."""
    try:
        wo_service.delete_work_order_labor(
            db, work_order_id, labor_id, user=user
        )
    except DomainError as exc:
        raise to_http(exc)
