"""Item CRUD service.

Layer: services. Called by `app/routers/items.py`. Translates
SQLAlchemy integrity violations into the domain vocabulary
(`DuplicateBarcodeError`, `ItemNotFoundError`) so routers never have
to know about the database driver's exception classes.
"""

import uuid
from decimal import Decimal
from typing import Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.errors import DuplicateBarcodeError, ItemNotFoundError
from app.models import Item


def create_item(
    db: Session,
    *,
    barcode: str,
    name: str,
    quantity: Decimal,
    location: str,
) -> Item:
    """Insert a new item. Raises `DuplicateBarcodeError` if the
    `barcode` UNIQUE constraint fires."""
    new_item = Item(
        barcode=barcode,
        name=name,
        quantity=quantity,
        location=location,
    )
    db.add(new_item)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateBarcodeError("An item with this barcode already exists.") from exc
    db.refresh(new_item)
    return new_item


def list_items(db: Session) -> Sequence[Item]:
    """Return every item, newest first. The full table is small
    enough that pagination is unnecessary at this stage."""
    return db.query(Item).order_by(Item.created_at.desc()).all()


def get_item_by_barcode(db: Session, barcode: str) -> Item:
    """Lookup used by the scan/entry flow. Raises `ItemNotFoundError`
    rather than returning `None` so the router can translate via the
    standard `to_http` table."""
    item = db.query(Item).filter(Item.barcode == barcode).first()
    if not item:
        raise ItemNotFoundError("Item not found.")
    return item


def delete_item(db: Session, item_id: uuid.UUID) -> None:
    """Hard-delete an item. Cascade rules on `transactions.item_id`
    are defined in the model; this function only enforces the
    "must exist" precondition."""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise ItemNotFoundError("Item not found.")
    db.delete(item)
    db.commit()
