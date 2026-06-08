"""Item CRUD service.

Layer: services. Called by `app/routers/items.py`. Translates
SQLAlchemy integrity violations into the domain vocabulary
(`DuplicateBarcodeError`, `ItemNotFoundError`) so routers never have
to know about the database driver's exception classes.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.errors import (
    DuplicateBarcodeError,
    ItemNotFoundError,
)
from app.models import Item


def create_item(
    db: Session,
    *,
    barcode: str,
    name: str,
    quantity: Decimal,
    location: str,
    price: Decimal | None = None,
    product_link: str | None = None,
) -> Item:
    """Insert a new item. Raises `DuplicateBarcodeError` if the
    `barcode` UNIQUE constraint fires."""
    new_item = Item(
        barcode=barcode,
        name=name,
        quantity=quantity,
        location=location,
        price=price,
        product_link=product_link,
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
    """Return every live item, newest first. Archived (soft-deleted)
    items are excluded. The full table is small enough that pagination
    is unnecessary at this stage."""
    return (
        db.query(Item)
        .filter(Item.archived_at.is_(None))
        .order_by(Item.created_at.desc())
        .all()
    )


def get_item_by_barcode(db: Session, barcode: str) -> Item:
    """Lookup used by the scan/entry flow. Archived (soft-deleted) items
    are treated as not found, so a deleted item cannot be scanned into a
    new transaction. Raises `ItemNotFoundError` rather than returning
    `None` so the router can translate via the standard `to_http` table."""
    item = (
        db.query(Item)
        .filter(Item.barcode == barcode, Item.archived_at.is_(None))
        .first()
    )
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
    price: Decimal | None = None,
    product_link: str | None = None,
) -> Item:
    """Edit any of `barcode`, `name`, `location`, `price`, or `product_link` on an existing item.
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
    if price is not None:
        item.price = price
    if product_link is not None:
        item.product_link = product_link
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
    """Archive (soft-delete) an item by setting `archived_at`. The row is
    deliberately NOT removed: the history view reads each transaction's
    item name/barcode/price through a live join
    (`services.history.list_history`), so a hard delete would orphan or
    hide those rows. Archiving keeps the audit trail fully intact while
    hiding the item from `list_items` and barcode lookups. Raises
    `ItemNotFoundError` if the id is unknown. Idempotent: archiving an
    already-archived item simply refreshes the timestamp."""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise ItemNotFoundError("Item not found.")
    item.archived_at = datetime.now(timezone.utc)
    db.commit()
