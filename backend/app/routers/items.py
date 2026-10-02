"""HTTP routes for the `/items` resource.

Layer: routers (FastAPI). Thin handlers only -- each one parses
the request via a Pydantic schema, delegates to a function in
`app.services.items` or `app.services.notes`, and converts any
`DomainError` to an `HTTPException` through the shared `to_http`
translator. No business logic, no database queries, no exception
type-checking beyond the single `DomainError` catch.

Mounted by `app/main.py` under the root prefix.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.auth_deps import get_current_user, require_min_role
from app.database import get_db
from app.domain import roles
from app.domain.errors import DomainError
from app.models import Item, User
from app.routers._errors import to_http
from app.routers._stock_events import emit_low_stock_changed, flush_stock_events
from app.schemas.items import (
    ItemBarcodesUpdate,
    ItemCreate,
    ItemNotesUpdate,
    ItemResponse,
    ItemUpdate,
    LowStockItemResponse,
    LowStockThresholdUpdate,
)
from app.services import barcode_labels as barcode_labels_service
from app.services import dispense_export_xlsx
from app.services import inventory_export_xlsx, work_order_report_xlsx
from app.services import items as items_service
from app.services import notes as notes_service

router = APIRouter(prefix="/items", tags=["items"])


def _item_response(item: Item, role: str) -> ItemResponse:
    """Serialise an item, redacting the cost-sensitive `price` and
    `product_link` for anyone below TechFM OA. This is the authoritative
    gate (the frontend only hides the columns): a Supervisor or
    Technician hitting `GET /items/` directly still gets `null` for
    both fields."""
    resp = ItemResponse.model_validate(item)
    # The additional barcodes are an ORM relationship of `ItemBarcode`
    # objects, so `from_attributes` cannot coerce them to `list[str]` --
    # flatten to their codes here. Ordered oldest-first for a stable
    # display (the relationship default order is insertion order).
    resp.barcodes = [b.code for b in item.alt_barcodes]
    if not roles.role_at_least(role, roles.ROLE_TECHFM_OA):
        resp.price = None
        resp.product_link = None
    return resp


def _low_stock_response(
    item: Item,
    role: str,
    dispensed: Decimal,
    last_dispensed_at: Optional[datetime],
) -> LowStockItemResponse:
    """`_item_response` plus the 7-day figure and the recency stamp.

    Reuses the base serializer rather than re-deriving it so the
    price/product-link redaction cannot drift between the two -- a second
    hand-written copy is exactly how a Supervisor ends up seeing a price
    on one page and not another.
    """
    base = _item_response(item, role)
    return LowStockItemResponse(
        **base.model_dump(),
        dispensed_last_7_days=dispensed,
        last_dispensed_at=last_dispensed_at,
    )


@router.post(
    "/",
    response_model=ItemResponse,
    status_code=201,
)
def create_item(
    payload: ItemCreate,
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
):
    """Create an item. TechFM OA+ only. 400 on a live duplicate barcode;
    409 when the barcode is held only by an archived item (the client
    confirms and retries with `override_archived` to free it)."""
    try:
        item = items_service.create_item(
            db,
            barcode=payload.barcode,
            name=payload.name,
            quantity=payload.quantity,
            location=payload.location,
            price=payload.price,
            product_link=payload.product_link,
            override_archived=payload.override_archived,
        )
        # An item can be born below its threshold. That is not a crossing
        # -- there is no before-state -- so it lists without pushing, but
        # the page still has to learn about the new row.
        emit_low_stock_changed(item.id)
        return _item_response(item, user.role)
    except DomainError as exc:
        raise to_http(exc)


@router.get(
    "/",
    response_model=list[ItemResponse],
)
def list_items(
    q: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return live items, optionally filtered by a literal name/barcode
    substring. Any logged-in user. `price` / `product_link` are redacted for
    below-TechFM-OA callers."""
    return [
        _item_response(item, user.role)
        for item in items_service.list_items(db, search=q)
    ]


@router.get(
    "/low-stock",
    response_model=list[LowStockItemResponse],
    dependencies=[Depends(require_min_role(roles.ROLE_TECHFM_OA))],
)
def list_low_stock(
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
):
    """Every live item at or below its own low-stock threshold, deepest
    below first, with the quantity dispensed in the last 7 days.

    TechFM OA+ -- the same rank that receives the low-stock push and can
    retune a threshold, so everyone who can see this can act on it.

    **This route MUST stay registered above `GET /items/{barcode}`.**
    That route's path parameter matches any single segment, so a
    later-registered literal is unreachable and answers 404 for a route
    that exists. Pinned by
    `test_low_stock_is_not_shadowed_by_the_barcode_lookup`.
    """
    return [
        _low_stock_response(item, user.role, dispensed, last_dispensed_at)
        for item, dispensed, last_dispensed_at in items_service.list_low_stock(db)
    ]


@router.get(
    "/export",
    responses={403: {"description": "Requires the TechFM OA role or above."}},
)
def export_inventory(
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
):
    """The item list plus every User Requests tab (all statuses) as one
    print-ready workbook. Registered above `GET /items/{barcode}` for the
    same shadowing reason as `/low-stock`."""
    now = datetime.now(timezone.utc)
    return Response(
        content=inventory_export_xlsx.export_xlsx(db, now=now),
        media_type=work_order_report_xlsx.XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition":
                f'attachment; filename="{inventory_export_xlsx.export_filename(now)}"'
        },
    )


def _xlsx_download(content: bytes, filename: str) -> Response:
    return Response(
        content=content,
        media_type=work_order_report_xlsx.XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/dispense-exports",
    responses={403: {"description": "Requires the TechFM OA role or above."}},
)
def create_dispense_export(
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
):
    """Weekly export: items dispensed since the previous export. Records
    the window, so the next export starts where this one ends."""
    content, filename = dispense_export_xlsx.create_export(
        db, user=user, now=datetime.now(timezone.utc))
    return _xlsx_download(content, filename)


@router.get(
    "/dispense-exports/latest",
    responses={
        403: {"description": "Requires the TechFM OA role or above."},
        404: {"description": "No weekly export has been run yet."},
    },
)
def reprint_dispense_export(
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
):
    """Reprint weekly: the latest weekly export's window, unchanged."""
    latest = dispense_export_xlsx.latest_export(db)
    if latest is None:
        raise HTTPException(status_code=404, detail="No weekly export has been run yet.")
    return _xlsx_download(*latest)


@router.get(
    "/labels",
    response_class=HTMLResponse,
    responses={403: {"description": "Requires the TechFM OA role or above."}},
)
def barcode_labels(
    q: Optional[str] = Query(None),
    barcode: list[str] = Query([]),
    location: Optional[str] = Query(None),
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
):
    """Print page of barcode labels: every item, a search result (`q`),
    chosen items (`barcode`, repeatable), or one `location`. Above
    `GET /items/{barcode}` for the same shadowing reason as `/low-stock`."""
    return barcode_labels_service.labels_html(
        db, search=q, barcodes=barcode, location=location)


@router.get(
    "/{barcode}",
    response_model=ItemResponse,
)
def get_item_by_barcode(
    barcode: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Lookup by barcode for the scan/entry flow. Any logged-in user.
    404 if unknown. `price` / `product_link` are redacted for below-TechFM-OA
    callers."""
    try:
        item = items_service.get_item_by_barcode(db, barcode)
        return _item_response(item, user.role)
    except DomainError as exc:
        raise to_http(exc)


@router.patch(
    "/{item_id}/notes",
    response_model=ItemResponse,
    dependencies=[Depends(require_min_role(roles.ROLE_SUPERVISOR))],
)
def update_item_notes(
    item_id: uuid.UUID,
    payload: ItemNotesUpdate,
    user: User = Depends(require_min_role(roles.ROLE_SUPERVISOR)),
    db: Session = Depends(get_db),
):
    """Replace the JSONB `notes` dict wholesale. Supervisor or above
    (notes are an operational field, distinct from the TechFM-OA-gated
    structural edits). Notes whitelist is enforced by
    `ItemNotesUpdate`'s field validator; 404 if the item does not exist.

    Routed through `_item_response` so a Supervisor saving notes does not
    receive the TechFM-OA-gated `price` / `product_link` in the echo."""
    try:
        item = notes_service.replace_notes(db, item_id, payload.notes)
        return _item_response(item, user.role)
    except DomainError as exc:
        raise to_http(exc)


@router.patch(
    "/{item_id}/barcodes",
    response_model=ItemResponse,
)
def update_item_barcodes(
    item_id: uuid.UUID,
    payload: ItemBarcodesUpdate,
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
):
    """Replace the item's *additional* barcodes wholesale. TechFM OA+
    only (same gate as the structural `PATCH /items/{item_id}` edit). The
    canonical `barcode` is unchanged -- it is edited via that route. 404 if
    the item does not exist; 400 if a submitted code is already in use by
    another live item or equals this item's own primary barcode; 409 if a
    submitted code is held only by an archived item (the client confirms and
    retries with `override_archived` to free it)."""
    try:
        item = items_service.replace_barcodes(
            db,
            item_id,
            payload.barcodes,
            override_archived=payload.override_archived,
        )
        return _item_response(item, user.role)
    except DomainError as exc:
        raise to_http(exc)


@router.patch(
    "/{item_id}/low-stock-threshold",
    response_model=ItemResponse,
    dependencies=[Depends(require_min_role(roles.ROLE_TECHFM_OA))],
)
def update_low_stock_threshold(
    item_id: uuid.UUID,
    payload: LowStockThresholdUpdate,
    background: BackgroundTasks,
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
):
    """Retune when this item starts warning. TechFM OA+ only.

    Raising the threshold past the current count is a crossing and pushes
    exactly like a dispense would: the item is newly low, and which write
    made it low is not something the crew needs to distinguish. 404 if the
    item is unknown or archived; 422 below the minimum of 1.
    """
    try:
        item = items_service.set_low_stock_threshold(
            db, item_id, threshold=payload.low_stock_threshold
        )
        flush_stock_events(db, background)
        return _item_response(item, user.role)
    except DomainError as exc:
        raise to_http(exc)


@router.patch(
    "/{item_id}",
    response_model=ItemResponse,
)
def update_item(
    item_id: uuid.UUID,
    payload: ItemUpdate,
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
):
    """Partially edit barcode, name, location, price, and/or product link.
    TechFM OA+ only. Only the fields present in the request body are
    written; an explicit `null` clears `price` / `product_link`. 404 if the
    item does not exist; 400 on a live duplicate barcode; 409 when the new
    barcode is held only by an archived item (the client confirms and
    retries with `override_archived` to free it). Quantity is not editable
    here — corrections go through `POST /transactions/adjust`."""
    try:
        # `exclude_unset` forwards only the fields the client actually sent,
        # so an omitted field is left untouched while an explicit `null`
        # reaches the service and clears the nullable column.
        item = items_service.update_item(
            db,
            item_id,
            performed_by_id=user.id,
            **payload.model_dump(exclude_unset=True),
        )
        return _item_response(item, user.role)
    except DomainError as exc:
        raise to_http(exc)


@router.delete(
    "/{item_id}",
    status_code=204,
    dependencies=[Depends(require_min_role(roles.ROLE_TECHFM_OA))],
)
def delete_item(item_id: uuid.UUID, db: Session = Depends(get_db)):
    """Soft-delete (archive) an item. TechFM OA+ only. 404 if unknown."""
    try:
        items_service.delete_item(db, item_id)
        # Archiving removes the row from the list as surely as a restock
        # would.
        emit_low_stock_changed(item_id)
    except DomainError as exc:
        raise to_http(exc)
