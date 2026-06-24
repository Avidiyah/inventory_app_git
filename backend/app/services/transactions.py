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
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.domain.errors import (
    ItemNotFoundError,
    NegativeQuantityError,
    NoChangeError,
    TransactionNotFoundError,
    TransactionVoidError,
)
from app.domain.billing import validate_billable_quantity
from app.domain.quantity import apply_delta, reverse_delta
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
        # Snapshot the price under the same row lock that guards the
        # quantity update, so History reflects the price at this moment
        # rather than the item's current price.
        unit_price=item.price,
        work_order_number=work_order_number,
        reason=None,
    )
    db.add(new_txn)
    db.commit()
    db.refresh(new_txn)
    return new_txn


def void_transaction(
    db: Session,
    *,
    transaction_id: uuid.UUID,
    user_id: Optional[uuid.UUID],
) -> None:
    """Void a mis-clicked transaction (soft delete) and reverse its
    effect on the item's stock.

    The row is NOT hard-deleted: it is stamped with `voided_at` (now)
    and `voided_by_id` (the acting user) so the audit trail is retained,
    but it disappears from the history view (which filters out voided
    rows). The item's `quantity` is adjusted by the opposite of the
    original delta -- under the same `SELECT ... FOR UPDATE` row lock the
    stock/dispense path uses -- so concurrent writes serialise per item.

    Raises:
    - `TransactionNotFoundError` if the id is unknown or the row has
      already been voided (it is no longer actionable from history).
    - `TransactionVoidError` if undoing the row would drive stock below
      zero (e.g. voiding a stock-in whose units were since dispensed);
      the operator should make a correction instead.
    """
    # Lock the transaction row itself so two concurrent voids of the same
    # transaction serialise here: the second blocks until the first commits,
    # then re-reads the row, sees `voided_at` set, and raises instead of
    # reversing the stock effect a second time.
    txn = (
        db.query(Transaction)
        .filter(Transaction.id == transaction_id)
        .with_for_update()
        .first()
    )
    if txn is None or txn.voided_at is not None:
        raise TransactionNotFoundError("Transaction not found.")

    # Lock the item row before the read-modify-write of its quantity, so
    # a void racing a stock/dispense/correction can never lose an update.
    item = (
        db.query(Item)
        .filter(Item.id == txn.item_id)
        .with_for_update()
        .first()
    )
    if item is None:
        # The item_id FK is RESTRICT, so a live transaction always has a
        # live item; this is a defensive guard, not an expected path.
        raise ItemNotFoundError("Item not found.")

    try:
        item.quantity = reverse_delta(
            item.quantity, txn.transaction_type, txn.quantity
        )
    except NegativeQuantityError as exc:
        # Translate the low-level overdraft into a void-specific message;
        # SQLAlchemy rolls back the (untouched) transaction on raise.
        raise TransactionVoidError(
            "Cannot void this entry — it would make the on-hand count "
            "negative. Make a correction instead."
        ) from exc

    txn.voided_at = datetime.now(timezone.utc)
    txn.voided_by_id = user_id
    db.commit()


def set_billable_quantity(
    db: Session,
    *,
    transaction_id: uuid.UUID,
    billable_quantity: Optional[Decimal],
) -> Transaction:
    """Set (or clear) a transaction's billing override.

    This is a pure billing annotation -- it records how many of the row's
    units to actually charge the customer for and NEVER touches
    `Item.quantity` (the items were physically used; only the invoice
    changes). `billable_quantity` of `None` clears the override (charge
    the full recorded quantity again); `0` records the row but charges
    nothing; any value up to the recorded quantity bills a partial count.

    No row lock is taken: unlike stock/dispense/void there is no
    read-modify-write of a shared counter, just a last-write-wins update
    of an annotation on this one row.

    Raises:
    - `TransactionNotFoundError` if the id is unknown or already voided
      (a voided row is not actionable from history).
    - `BillingQuantityError` (via `validate_billable_quantity`) if the
      override is negative, exceeds the recorded quantity, or targets an
      `adjust` (correction) row.
    """
    txn = (
        db.query(Transaction)
        .filter(Transaction.id == transaction_id)
        .first()
    )
    if txn is None or txn.voided_at is not None:
        raise TransactionNotFoundError("Transaction not found.")

    txn.billable_quantity = validate_billable_quantity(
        txn.transaction_type, txn.quantity, billable_quantity
    )
    db.commit()
    db.refresh(txn)
    return txn


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
