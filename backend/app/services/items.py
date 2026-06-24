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
    ArchivedBarcodeConflictError,
    DuplicateBarcodeError,
    ItemNotFoundError,
)
from app.models import Item, ItemBarcode, MassStageItem, Transaction


def _barcode_holder(
    db: Session, code: str, *, exclude_item_id: uuid.UUID | None = None
) -> Item | None:
    """Return the item currently claiming `code` -- as a primary
    `items.barcode` OR an additional `item_barcodes.code` -- other than
    `exclude_item_id`, or `None` if the code is free.

    This is the single home for the cross-table uniqueness rule. The DB
    UNIQUE constraints only guard primary-vs-primary and alt-vs-alt; the
    primary-vs-alt overlap (and the "another item already has this") check
    cannot be expressed as a single-column constraint, so it lives here.
    Unlike a barcode lookup, this DELIBERATELY includes archived items:
    a soft-deleted item still owns its codes, and the caller
    (`_ensure_barcode_free`) decides whether that is a hard duplicate (live
    holder) or a recoverable archived conflict. `exclude_item_id` lets an
    item keep/move its own codes without self-colliding."""
    primary_q = db.query(Item).filter(Item.barcode == code)
    if exclude_item_id is not None:
        primary_q = primary_q.filter(Item.id != exclude_item_id)
    holder = primary_q.first()
    if holder is not None:
        return holder

    alt_q = (
        db.query(Item)
        .join(ItemBarcode, ItemBarcode.item_id == Item.id)
        .filter(ItemBarcode.code == code)
    )
    if exclude_item_id is not None:
        alt_q = alt_q.filter(Item.id != exclude_item_id)
    return alt_q.first()


def _item_has_history(db: Session, item: Item) -> bool:
    """Does `item` have any audit references that must outlive it -- a
    `transactions` row (the ledger / billing trail) or a `mass_stage_items`
    row (a staging plan)? Both FKs are effectively RESTRICT, and the
    history view resolves an item's name/barcode/price via a live join, so
    an item with either cannot be hard-deleted without orphaning records."""
    if db.query(Transaction.id).filter(Transaction.item_id == item.id).first():
        return True
    return (
        db.query(MassStageItem.id).filter(MassStageItem.item_id == item.id).first()
        is not None
    )


def _retire_barcode(item: Item) -> str:
    """A unique, clearly-retired replacement for an archived item's primary
    `barcode`, used to free its code for a live item without dropping the
    row the History join still reads. The item id (the PK, globally unique)
    guarantees the replacement can never collide with a real code; the
    original code stays up front so History stays recognisable."""
    return f"{item.barcode} (retired {item.id})"


def _free_archived_holder(db: Session, holder: Item, code: str) -> None:
    """Release `code` from an archived `holder` so a live item can claim it.

    Two paths, decided by whether the holder has history:
    - No history -> nothing to preserve, so purge the whole archived item
      (its `item_barcodes` cascade away with the row). This clears the
      clutter the user is trying to consolidate.
    - Has history -> the audit trail wins: keep the archived shell so the
      History join still resolves, and release only the conflicting code --
      retire the primary `barcode` if `code` is it, else drop the matching
      additional-barcode row.

    Flushes so the code is actually free before the caller re-applies it."""
    if _item_has_history(db, holder):
        if holder.barcode == code:
            holder.barcode = _retire_barcode(holder)
        else:
            for bc in list(holder.alt_barcodes):
                if bc.code == code:
                    holder.alt_barcodes.remove(bc)
                    break
    else:
        db.delete(holder)
    db.flush()


def _ensure_barcode_free(
    db: Session,
    code: str,
    *,
    exclude_item_id: uuid.UUID | None = None,
    override_archived: bool = False,
) -> None:
    """Enforce the cross-table uniqueness rule for `code`, distinguishing a
    live holder from an archived one:

    - free            -> returns, the caller may apply the code.
    - live holder     -> `DuplicateBarcodeError` (a hard 400 duplicate).
    - archived holder -> `ArchivedBarcodeConflictError` (a 409 the user can
                         confirm) unless `override_archived` is set, in which
                         case the holder is freed via `_free_archived_holder`
                         and the caller may apply the code.

    `override_archived` NEVER bypasses a live holder -- only an archived
    one -- so a confirmed reuse can still not steal a code in active use."""
    holder = _barcode_holder(db, code, exclude_item_id=exclude_item_id)
    if holder is None:
        return
    if holder.archived_at is None:
        raise DuplicateBarcodeError("An item with this barcode already exists.")
    if not override_archived:
        raise ArchivedBarcodeConflictError(
            "This barcode belongs to a deleted item."
        )
    _free_archived_holder(db, holder, code)


def create_item(
    db: Session,
    *,
    barcode: str,
    name: str,
    quantity: Decimal,
    location: str,
    price: Decimal | None = None,
    product_link: str | None = None,
    override_archived: bool = False,
) -> Item:
    """Insert a new item. Raises `DuplicateBarcodeError` if the barcode is
    taken by a *live* item -- either as its primary barcode (the
    `items.barcode` UNIQUE constraint) or as an additional code (the
    cross-table pre-check, which a single UNIQUE constraint cannot cover).
    If the barcode is held only by an *archived* item, raises
    `ArchivedBarcodeConflictError` so the caller can confirm reuse; passing
    `override_archived=True` frees that archived holder first (see
    `_free_archived_holder`)."""
    _ensure_barcode_free(db, barcode, override_archived=override_archived)
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


# Sentinel marking "caller did not pass this field" — distinct from a
# caller explicitly passing `None` to clear a nullable column. The router
# forwards only the fields the client actually sent (via
# `ItemUpdate.model_dump(exclude_unset=True)`), so an omitted field keeps
# this default and is left untouched, while an explicit `None` reaches the
# function and clears the column.
_UNSET = object()


def update_item(
    db: Session,
    item_id: uuid.UUID,
    *,
    barcode=_UNSET,
    name=_UNSET,
    location=_UNSET,
    price=_UNSET,
    product_link=_UNSET,
    override_archived: bool = False,
) -> Item:
    """Partially edit `barcode`, `name`, `location`, `price`, or
    `product_link` on an existing item. Only the fields the caller passes
    are written; an omitted field (left as `_UNSET`) is untouched, while an
    explicit `None` for the nullable `price` / `product_link` columns
    clears them. `barcode` / `name` / `location` are NOT NULL and the
    schema rejects a null/blank for them before they reach here. Raises
    `ItemNotFoundError` if the id is unknown, `DuplicateBarcodeError` if a
    new barcode collides with a *live* item, or
    `ArchivedBarcodeConflictError` if it collides only with an *archived*
    one (pass `override_archived=True` to free that holder and proceed).
    Quantity is intentionally not editable here — direct corrections go
    through `services.transactions.apply_correction`.
    """
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise ItemNotFoundError("Item not found.")
    if barcode is not _UNSET:
        # Cross-table pre-check: the new primary must not collide with
        # another item's primary OR with any item's additional code (the
        # `items.barcode` UNIQUE constraint only catches the former). A live
        # collision is a hard duplicate; an archived one is a confirmable
        # conflict that `override_archived` resolves by freeing the holder.
        if barcode != item.barcode:
            _ensure_barcode_free(
                db,
                barcode,
                exclude_item_id=item_id,
                override_archived=override_archived,
            )
        item.barcode = barcode
    if name is not _UNSET:
        item.name = name
    if location is not _UNSET:
        item.location = location
    if price is not _UNSET:
        item.price = price
    if product_link is not _UNSET:
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
    db: Session,
    item_id: uuid.UUID,
    codes: Sequence[str],
    *,
    override_archived: bool = False,
) -> Item:
    """Replace an item's *additional* barcodes wholesale with `codes`.

    Mirrors `services.notes.replace_notes`: the caller (router) has
    already trimmed, de-duplicated, and dropped blanks via
    `ItemBarcodesUpdate`. The item's canonical `barcode` is untouched --
    only the `item_barcodes` child rows are swapped.

    Each code is validated against the cross-table uniqueness rule before
    anything is written: it must not be in use by another *live* item
    (primary or additional) and must not equal this item's own primary
    barcode (which would be a redundant duplicate). A live collision raises
    `DuplicateBarcodeError` and leaves the existing codes intact. A code
    held only by an *archived* item raises `ArchivedBarcodeConflictError`
    unless `override_archived=True`, which frees that archived holder
    (purged if it has no history, else its conflicting code released) before
    the code is appended. Raises `ItemNotFoundError` if the id is unknown."""
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
        if code == item.barcode:
            raise DuplicateBarcodeError(f"Barcode '{code}' is already in use.")
        # A live holder is a hard duplicate; an archived one is a confirmable
        # conflict that `override_archived` frees before we append the code.
        _ensure_barcode_free(
            db, code, exclude_item_id=item_id, override_archived=override_archived
        )

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
