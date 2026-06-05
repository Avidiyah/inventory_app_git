"""Transaction (stock/dispense) write service.

Layer: services. The most safety-critical write in the system: it
must adjust an item's `quantity` and insert a `transactions` row as
a single atomic unit, while preventing two concurrent dispenses
from both reading the same `current` value and each subtracting
their full amount.

Concurrency model: `SELECT ... FOR UPDATE` on the item row. Any
other writer attempting the same operation blocks until this
transaction commits, so the read–modify–write of `quantity` is
serialised per item. The actual arithmetic and the overdraft check
live in `app.domain.quantity.apply_delta`.
"""

import uuid
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.domain.errors import ItemNotFoundError, NoChangeError
from app.domain.quantity import apply_delta
from app.models import Item, Transaction


def apply_transaction(
    db: Session,
    *,
    item_id: uuid.UUID,
    transaction_type: str,
    quantity: Decimal,
    user_id: Optional[uuid.UUID],
    work_order_number: Optional[str],
) -> Transaction:
    """Apply a stock/dispense and append the audit row.

    Raises `ItemNotFoundError` if the item id is unknown, and
    `NegativeQuantityError` (from `apply_delta`) if a dispense
    would drive stock below zero. Both bubble up to the router via
    `to_http`. On `NegativeQuantityError` the implicit transaction
    is rolled back by SQLAlchemy when the exception propagates,
    leaving the database untouched.
    """
    item = (
        db.query(Item)
        .filter(Item.id == item_id)
        .with_for_update()
        .first()
    )
    if not item:
        raise ItemNotFoundError("Item not found.")

    item.quantity = apply_delta(item.quantity, transaction_type, quantity)

    new_txn = Transaction(
        item_id=item_id,
        user_id=user_id,
        transaction_type=transaction_type,
        quantity=quantity,
        work_order_number=work_order_number,
        reason=None,
    )
    db.add(new_txn)
    db.commit()
    db.refresh(new_txn)
    return new_txn


def apply_correction(
    db: Session,
    *,
    item_id: uuid.UUID,
    new_quantity: Decimal,
    reason: str,
    user_id: Optional[uuid.UUID],
) -> Transaction:
    """Set an item's `quantity` to `new_quantity` and append an "adjust"
    audit row recording the signed delta and the reason.

    Reuses the same `SELECT ... FOR UPDATE` row lock as
    `apply_transaction`, so concurrent corrections / stocks / dispenses
    serialise per item and never lose updates. The audit row stores
    the *delta* (so history rows have a uniform "what was applied to
    stock" reading); the UI surfaces the absolute new value via the
    item's updated quantity.

    Raises `ItemNotFoundError` if the id is unknown, `NoChangeError`
    if `new_quantity` equals the current quantity (no audit row is
    created for a no-op), and `NegativeQuantityError` if `new_quantity`
    is negative — `CorrectionCreate` blocks that at the Pydantic layer
    too, but we re-check here as a domain invariant.
    """
    item = (
        db.query(Item)
        .filter(Item.id == item_id)
        .with_for_update()
        .first()
    )
    if not item:
        raise ItemNotFoundError("Item not found.")

    delta = new_quantity - item.quantity
    if delta == 0:
        raise NoChangeError("No change to apply.")

    item.quantity = apply_delta(item.quantity, "adjust", delta)

    new_txn = Transaction(
        item_id=item_id,
        user_id=user_id,
        transaction_type="adjust",
        quantity=delta,
        work_order_number=None,
        reason=reason,
    )
    db.add(new_txn)
    db.commit()
    db.refresh(new_txn)
    return new_txn
