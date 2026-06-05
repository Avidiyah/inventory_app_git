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

from app.domain.errors import (
    DuplicateBarcodeError,
    ItemHasTransactionsError,
    ItemNotFoundError,
)
from app.models import Item, Transaction


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


def update_item(
    db: Session,
    item_id: uuid.UUID,
    *,
    barcode: str | None = None,
    name: str | None = None,
    location: str | None = None,
) -> Item:
    """Edit any of `barcode`, `name`, `location` on an existing item.
    Only fields passed as non-`None` are written; the schema guarantees
    at least one is set. Raises `ItemNotFoundError` if the id is
    unknown, or `DuplicateBarcodeError` if a new barcode collides with
    another item. Quantity is intentionally not editable here — direct
    corrections go through `services.transactions.apply_correction`.
    """
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise ItemNotFoundError("Item not found.")
    if barcode is not None:
        item.barcode = barcode
    if name is not None:
        item.name = name
    if location is not None:
        item.location = location
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateBarcodeError(
            "An item with this barcode already exists."
        ) from exc
    db.refresh(item)
    return item


def delete_item(db: Session, item_id: uuid.UUID) -> None:
    """Hard-delete an item. Refuses if any transactions reference it
    (`ItemHasTransactionsError`, → 400) so the audit trail is never
    orphaned; the `transactions.item_id` FK is also `ON DELETE RESTRICT`
    as a belt-and-braces guarantee at the DB level."""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise ItemNotFoundError("Item not found.")
    has_txn = (
        db.query(Transaction.id).filter(Transaction.item_id == item_id).first()
        is not None
    )
    if has_txn:
        raise ItemHasTransactionsError(
            "Cannot delete an item with transaction history."
        )
    db.delete(item)
    db.commit()
