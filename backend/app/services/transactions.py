"""Transaction (stock/dispense) write service.

Layer: services. The most safety-critical write in the system: it
must adjust an item's `quantity` and insert a `transactions` row as
a single atomic unit, while preventing two concurrent dispenses
from both reading the same `current` value and each subtracting
their full amount.

Concurrency model: `SELECT ... FOR UPDATE` on the item row. Any
other writer attempting the same operation blocks until this
transaction commits, so the read–modify–write of `quantity` is
serialised per item. Stock-ins use `domain.quantity.apply_delta`; a Scan / Stock
dispense may cross below zero only while atomically raising a recount request.
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
    RoleManagementError,
    TransactionNotFoundError,
    TransactionVoidError,
)
from app.domain.billing import validate_billable_quantity
from app.domain import roles
from app.domain.quantity import apply_delta, reverse_delta
from app.models import Item, Transaction, WorkOrderItem
from app.services import low_stock
from app.services import user_requests as request_service
from app.services import work_orders as wo_service


def apply_transaction(
    db: Session,
    *,
    item_id: uuid.UUID,
    transaction_type: str,
    quantity: Decimal,
    user_id: Optional[uuid.UUID],
    work_order_number: Optional[str],
    work_order_id: Optional[uuid.UUID] = None,
) -> Transaction:
    """Apply a stock/dispense and append the audit row.

    `work_order_id` links the standalone work order (the router resolves it from
    a scanned card or by find-or-create); `work_order_number` is the denormalized
    snapshot kept for History.

    Raises `ItemNotFoundError` if the item id is unknown. A Scan / Stock
    dispense is deliberately allowed to move the recorded count below zero:
    that preserves reversible ledger arithmetic while a linked open User
    Request tells TechFM OA+ that the physical stock needs to be re-counted. Other
    stock-moving services retain the shared no-overdraft domain rule.
    """
    item = (
        db.query(Item)
        .filter(Item.id == item_id)
        .with_for_update()
        .first()
    )
    if not item:
        raise ItemNotFoundError("Item not found.")

    quantity_before = item.quantity
    recount_required = False
    shortage_quantity = Decimal(0)
    if transaction_type == "dispense":
        # Scan / Stock records real usage even when the expected app count is
        # short. Keeping the negative balance makes a later void the exact
        # inverse (adding the full transaction quantity restores the original
        # count); the User Request is the visible operational exception.
        item.quantity = quantity_before - quantity
        available = max(quantity_before, Decimal(0))
        shortage_quantity = max(quantity - available, Decimal(0))
        recount_required = shortage_quantity > 0
    else:
        item.quantity = apply_delta(quantity_before, transaction_type, quantity)

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
        work_order_id=work_order_id,
        reason=None,
    )
    db.add(new_txn)

    # Reflect a stock-out on the work order's materials list, the same as the
    # Work Orders page button. Only a dispense against a real work order creates a
    # line -- a stock-in (restocking) is not "material used" and stays ledger-only.
    if transaction_type == "dispense" and work_order_id is not None:
        db.flush()  # assign new_txn.id so the line can reference it
        wo_service.attach_dispense_line(
            db,
            work_order_id=work_order_id,
            item_id=item_id,
            quantity=quantity,
            transaction_id=new_txn.id,
            user_id=user_id,
        )

    if recount_required:
        # Assign the transaction id before creating its unique linked request.
        db.flush()
        request_service.create_inventory_recount_request(
            db,
            item_id=item_id,
            transaction_id=new_txn.id,
            work_order_id=work_order_id,
            work_order_number=work_order_number,
            created_by_id=user_id,
            recorded_quantity_before=quantity_before,
            dispensed_quantity=quantity,
            shortage_quantity=shortage_quantity,
        )

    # Recorded before the commit, while the row is loaded, and drained by
    # the router only after this returns -- so a rollback below never
    # leaves a phantom crossing behind.
    low_stock.record(item, quantity_before=quantity_before)
    db.commit()
    db.refresh(new_txn)
    # These response-only attributes are not columns: the durable source is the
    # linked User Request, while the scanner needs immediate feedback from this
    # one write.
    new_txn.recount_required = recount_required
    new_txn.item_quantity = item.quantity
    return new_txn


def void_transaction(
    db: Session,
    *,
    transaction_id: uuid.UUID,
    user_id: Optional[uuid.UUID],
    user_role: Optional[str] = None,
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

    # Supervisors retain the existing ability to void any ledger row. A
    # Technician may remove only a dispense they personally recorded against a
    # work order -- exactly the Scan / Stock mistake-recovery path, not an
    # elevation into History-wide correction powers.
    if user_role is not None and not roles.role_at_least(
        user_role, roles.ROLE_SUPERVISOR
    ):
        if (
            user_role != roles.ROLE_TECHNICIAN
            or txn.user_id != user_id
            or txn.transaction_type != "dispense"
            or txn.work_order_id is None
        ):
            raise RoleManagementError(
                "Technicians can only remove their own Scan / Stock entries."
            )

    # Stock-neutral rows (retroactive work-order backfill) never moved on-hand,
    # so undoing them must NOT move it either -- just soft-delete the row so it
    # leaves History. Skip the item lock + reversal entirely for them.
    if txn.affects_stock:
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

        quantity_before = item.quantity
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
        # Inside the branch on purpose: a stock-neutral retroactive row
        # never moved on-hand, so undoing it cannot change membership.
        low_stock.record(item, quantity_before=quantity_before)

    # Keep the work order's materials list in step with History: a line is the
    # aggregate of its work-order transactions, so voiding one reverses that row's
    # contribution. A `dispense` contributed +qty to the line; a reconciling
    # `adjust` from a line edit contributed -qty (its stored quantity is the signed
    # stock delta). Found by (work_order, item); the line drops out at zero. Only
    # work-order-linked rows qualify -- a correction carries no work_order_id.
    if txn.work_order_id is not None and txn.transaction_type in ("dispense", "adjust"):
        line = (
            db.query(WorkOrderItem)
            .filter(
                WorkOrderItem.work_order_id == txn.work_order_id,
                WorkOrderItem.item_id == txn.item_id,
            )
            .first()
        )
        if line is not None:
            if txn.transaction_type == "dispense":
                line.quantity = line.quantity - txn.quantity
            else:
                line.quantity = line.quantity + txn.quantity
            if line.quantity <= 0:
                db.delete(line)

    txn.voided_at = datetime.now(timezone.utc)
    txn.voided_by_id = user_id
    request_service.resolve_for_transaction(
        db,
        transaction_id=txn.id,
        resolved_by_id=user_id,
    )
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

    A correction also resolves any open `inventory_recount` request for the
    item, in the same commit. That is deliberately global rather than scoped to
    the User Requests page: the request asks "please re-count this", and an
    `adjust` answers it whichever screen it came from — this path backs both
    Correct Count on Find Item and the recount card's inline fix.

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

    quantity_before = item.quantity
    delta = new_quantity - quantity_before
    if delta == 0:
        raise NoChangeError("No change to apply.")

    item.quantity = apply_delta(quantity_before, "adjust", delta)

    new_txn = Transaction(
        item_id=item_id,
        user_id=user_id,
        transaction_type="adjust",
        quantity=delta,
        work_order_number=None,
        reason=reason,
    )
    db.add(new_txn)
    # Same commit as the stock write, under the same row lock the recount
    # request was raised beneath, so the queue can never disagree with the
    # count it is complaining about.
    request_service.resolve_recount_requests(
        db, item_id=item_id, resolved_by_id=user_id
    )
    low_stock.record(item, quantity_before=quantity_before)
    db.commit()
    db.refresh(new_txn)
    return new_txn
