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
from app.routers._errors import to_http
from app.schemas.items import ItemCreate, ItemResponse, ItemNotesUpdate
from app.services import items as items_service
from app.services import notes as notes_service

router = APIRouter(prefix="/items", tags=["items"])


@router.post(
    "/",
    response_model=ItemResponse,
    status_code=201,
    dependencies=[Depends(require_min_role(roles.ROLE_ADMIN))],
)
def create_item(payload: ItemCreate, db: Session = Depends(get_db)):
    """Create an item. Owner/Admin only. 400 on duplicate barcode."""
    try:
        return items_service.create_item(
            db,
            barcode=payload.barcode,
            name=payload.name,
            quantity=payload.quantity,
            location=payload.location,
        )
    except DomainError as exc:
        raise to_http(exc)


@router.get(
    "/",
    response_model=list[ItemResponse],
    dependencies=[Depends(get_current_user)],
)
def list_items(db: Session = Depends(get_db)):
    """Return every item, newest first. Any logged-in user (this is the
    Technician item-lookup feed). No filtering or pagination."""
    return items_service.list_items(db)


@router.get(
    "/{barcode}",
    response_model=ItemResponse,
    dependencies=[Depends(get_current_user)],
)
def get_item_by_barcode(barcode: str, db: Session = Depends(get_db)):
    """Lookup by barcode for the scan/entry flow. Any logged-in user.
    404 if unknown."""
    try:
        return items_service.get_item_by_barcode(db, barcode)
    except DomainError as exc:
        raise to_http(exc)


@router.patch(
    "/{item_id}/notes",
    response_model=ItemResponse,
    dependencies=[Depends(require_min_role(roles.ROLE_ADMIN))],
)
def update_item_notes(
    item_id: uuid.UUID,
    payload: ItemNotesUpdate,
    db: Session = Depends(get_db),
):
    """Replace the JSONB `notes` dict wholesale. Owner/Admin only. Notes
    whitelist is enforced by `ItemNotesUpdate`'s field validator; 404 if
    the item does not exist."""
    try:
        return notes_service.replace_notes(db, item_id, payload.notes)
    except DomainError as exc:
        raise to_http(exc)


@router.delete(
    "/{item_id}",
    status_code=204,
    dependencies=[Depends(require_min_role(roles.ROLE_ADMIN))],
)
def delete_item(item_id: uuid.UUID, db: Session = Depends(get_db)):
    """Hard-delete an item. Owner/Admin only. 404 if unknown."""
    try:
        items_service.delete_item(db, item_id)
    except DomainError as exc:
        raise to_http(exc)
