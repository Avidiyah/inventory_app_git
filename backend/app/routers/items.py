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

from app.database import get_db
from app.domain.errors import DomainError
from app.routers._errors import to_http
from app.schemas.items import ItemCreate, ItemResponse, ItemNotesUpdate
from app.services import items as items_service
from app.services import notes as notes_service

router = APIRouter(prefix="/items", tags=["items"])


@router.post("/", response_model=ItemResponse, status_code=201)
def create_item(payload: ItemCreate, db: Session = Depends(get_db)):
    """Create an item. 400 on duplicate barcode."""
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


@router.get("/", response_model=list[ItemResponse])
def list_items(db: Session = Depends(get_db)):
    """Return every item, newest first. No filtering or pagination."""
    return items_service.list_items(db)


@router.get("/{barcode}", response_model=ItemResponse)
def get_item_by_barcode(barcode: str, db: Session = Depends(get_db)):
    """Lookup by barcode for the scan/entry flow. 404 if unknown."""
    try:
        return items_service.get_item_by_barcode(db, barcode)
    except DomainError as exc:
        raise to_http(exc)


@router.patch("/{item_id}/notes", response_model=ItemResponse)
def update_item_notes(
    item_id: uuid.UUID,
    payload: ItemNotesUpdate,
    db: Session = Depends(get_db),
):
    """Replace the JSONB `notes` dict wholesale. Notes whitelist is
    enforced by `ItemNotesUpdate`'s field validator; 404 if the item
    does not exist."""
    try:
        return notes_service.replace_notes(db, item_id, payload.notes)
    except DomainError as exc:
        raise to_http(exc)


@router.delete("/{item_id}", status_code=204)
def delete_item(item_id: uuid.UUID, db: Session = Depends(get_db)):
    """Hard-delete an item. 404 if unknown."""
    try:
        items_service.delete_item(db, item_id)
    except DomainError as exc:
        raise to_http(exc)
