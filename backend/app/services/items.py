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

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.errors import (
    DuplicateBarcodeError,
    ItemNotFoundError,
)
from app.models import Item, ItemBarcode


def _barcode_in_use(
    db: Session, code: str, *, exclude_item_id: uuid.UUID | None = None
) -> bool:
    """Is `code` already claimed -- as a primary `items.barcode` OR an
    additional `item_barcodes.code` -- by some item other than
    `exclude_item_id`?

    This is the single home for the cross-table uniqueness rule. The DB
    UNIQUE constraints only guard primary-vs-primary and alt-vs-alt; the
    primary-vs-alt overlap (and the "another item already has this") check
    cannot be expressed as a single-column constraint, so it lives here
    and callers translate a True result into `DuplicateBarcodeError`.
    `exclude_item_id` lets an item keep/move its own codes without
    self-colliding."""
    primary_q = db.query(Item.id).filter(Item.barcode == code)
    if exclude_item_id is not None:
        primary_q = primary_q.filter(Item.id != exclude_item_id)
    if db.query(primary_q.exists()).scalar():
        return True

    alt_q = db.query(ItemBarcode.id).filter(ItemBarcode.code == code)
    if exclude_item_id is not None:
        alt_q = alt_q.filter(ItemBarcode.item_id != exclude_item_id)
    return bool(db.query(alt_q.exists()).scalar())


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
    """Insert a new item. Raises `DuplicateBarcodeError` if the barcode is
    already taken -- either as another item's primary barcode (the
    `items.barcode` UNIQUE constraint) or as an additional code on some
    item (the cross-table pre-check, which a single UNIQUE constraint
    cannot cover)."""
    if _barcode_in_use(db, barcode):
        raise DuplicateBarcodeError("An item with this barcode already exists.")
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
    """Lookup used by the scan/entry flow. Resolves against the item's
    primary `barcode` OR any of its additional `item_barcodes` codes, so a
    scan of any label on the packaging finds the item. Archived
    (soft-deleted) items are treated as not found, so a deleted item
    cannot be scanned into a new transaction. Raises `ItemNotFoundError`
    rather than returning `None` so the router can translate via the
    standard `to_http` table.

    Codes are globally unique across both columns, so the OUTER JOIN can
    never return more than one live item for a given code."""
    item = (
        db.query(Item)
        .outerjoin(ItemBarcode, ItemBarcode.item_id == Item.id)
        .filter(
            Item.archived_at.is_(None),
            or_(Item.barcode == barcode, ItemBarcode.code == barcode),
        )
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
        # Cross-table pre-check: the new primary must not collide with
        # another item's primary OR with any item's additional code (the
        # `items.barcode` UNIQUE constraint only catches the former).
        if barcode != item.barcode and _barcode_in_use(
            db, barcode, exclude_item_id=item_id
        ):
            raise DuplicateBarcodeError(
                "An item with this barcode already exists."
            )
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


def replace_barcodes(
    db: Session, item_id: uuid.UUID, codes: Sequence[str]
) -> Item:
    """Replace an item's *additional* barcodes wholesale with `codes`.

    Mirrors `services.notes.replace_notes`: the caller (router) has
    already trimmed, de-duplicated, and dropped blanks via
    `ItemBarcodesUpdate`. The item's canonical `barcode` is untouched --
    only the `item_barcodes` child rows are swapped.

    Each code is validated against the cross-table uniqueness rule before
    anything is written: it must not be in use by another item (primary or
    additional) and must not equal this item's own primary barcode (which
    would be a redundant duplicate). Any violation raises
    `DuplicateBarcodeError` and leaves the existing codes intact. Raises
    `ItemNotFoundError` if the id is unknown."""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise ItemNotFoundError("Item not found.")

    existing = {bc.code: bc for bc in item.alt_barcodes}
    desired = list(codes)  # already trimmed / de-duplicated by the schema
    desired_set = set(desired)

    # Validate only the codes being *added* (a retained code is already
    # known-valid). Checking everything would false-positive on the item's
    # own retained alternates.
    for code in desired:
        if code in existing:
            continue
        if code == item.barcode or _barcode_in_use(
            db, code, exclude_item_id=item_id
        ):
            raise DuplicateBarcodeError(f"Barcode '{code}' is already in use.")

    # Diff rather than reassign the whole collection: deleting and
    # re-inserting a *retained* code in the same flush would collide on the
    # global UNIQUE(code) constraint (the INSERT can land before the
    # DELETE). Remove dropped codes, add new ones, leave retained rows be.
    for code, bc in existing.items():
        if code not in desired_set:
            item.alt_barcodes.remove(bc)  # delete-orphan deletes the row
    for code in desired:
        if code not in existing:
            item.alt_barcodes.append(ItemBarcode(code=code))

    db.commit()
    db.refresh(item)
    return item
