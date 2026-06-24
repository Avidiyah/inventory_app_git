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

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth_deps import get_current_user, require_min_role
from app.database import get_db
from app.domain import roles
from app.domain.errors import DomainError
from app.models import Item, User
from app.routers._errors import to_http
from app.schemas.items import (
    ItemBarcodesUpdate,
    ItemCreate,
    ItemNotesUpdate,
    ItemResponse,
    ItemUpdate,
)
from app.services import items as items_service
from app.services import notes as notes_service

router = APIRouter(prefix="/items", tags=["items"])


def _item_response(item: Item, role: str) -> ItemResponse:
    """Serialise an item, redacting the cost-sensitive `price` and
    `product_link` for anyone below Admin. This is the authoritative
    gate (the frontend only hides the columns): a Supervisor or
    Technician hitting `GET /items/` directly still gets `null` for
    both fields."""
    resp = ItemResponse.model_validate(item)
    # The additional barcodes are an ORM relationship of `ItemBarcode`
    # objects, so `from_attributes` cannot coerce them to `list[str]` --
    # flatten to their codes here. Ordered oldest-first for a stable
    # display (the relationship default order is insertion order).
    resp.barcodes = [b.code for b in item.alt_barcodes]
    if not roles.role_at_least(role, roles.ROLE_ADMIN):
        resp.price = None
        resp.product_link = None
    return resp


@router.post(
    "/",
    response_model=ItemResponse,
    status_code=201,
)
def create_item(
    payload: ItemCreate,
    user: User = Depends(require_min_role(roles.ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """Create an item. Owner/Admin only. 400 on a live duplicate barcode;
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
        return _item_response(item, user.role)
    except DomainError as exc:
        raise to_http(exc)


@router.get(
    "/",
    response_model=list[ItemResponse],
)
def list_items(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return every item, newest first. Any logged-in user (this is the
    Technician item-lookup feed). No filtering or pagination. `price` /
    `product_link` are redacted for non-Admin callers."""
    return [_item_response(item, user.role) for item in items_service.list_items(db)]


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
    404 if unknown. `price` / `product_link` are redacted for non-Admin
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
    (notes are an operational field, distinct from the Admin-only
    structural edits). Notes whitelist is enforced by
    `ItemNotesUpdate`'s field validator; 404 if the item does not exist.

    Routed through `_item_response` so a Supervisor saving notes does not
    receive the Admin-only `price` / `product_link` in the echo."""
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
    user: User = Depends(require_min_role(roles.ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """Replace the item's *additional* barcodes wholesale. Owner/Admin
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
    "/{item_id}",
    response_model=ItemResponse,
)
def update_item(
    item_id: uuid.UUID,
    payload: ItemUpdate,
    user: User = Depends(require_min_role(roles.ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """Partially edit barcode, name, location, price, and/or product link.
    Owner/Admin only. Only the fields present in the request body are
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
            **payload.model_dump(exclude_unset=True),
        )
        return _item_response(item, user.role)
    except DomainError as exc:
        raise to_http(exc)


@router.delete(
    "/{item_id}",
    status_code=204,
    dependencies=[Depends(require_min_role(roles.ROLE_ADMIN))],
)
def delete_item(item_id: uuid.UUID, db: Session = Depends(get_db)):
    """Soft-delete (archive) an item. Owner/Admin only. 404 if unknown."""
    try:
        items_service.delete_item(db, item_id)
    except DomainError as exc:
        raise to_http(exc)
