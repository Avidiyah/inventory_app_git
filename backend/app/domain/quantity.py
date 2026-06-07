"""Pure stock/dispense arithmetic.

Layer: pure domain (no SQLAlchemy, no FastAPI, no models).

This module owns the single most important business rule in the
system: a dispense may never leave an item with negative stock.
Keeping the rule here — rather than inside the transaction route
handler — means it can be exercised by plain unit tests with no
database and reused by any future caller (bulk importer, scheduled
job, CLI tool) without dragging in HTTP machinery.

Called by `app/services/transactions.py::apply_transaction`, which
holds the SELECT ... FOR UPDATE row lock around this call.
"""

from decimal import Decimal
from typing import Literal

from app.domain.errors import NegativeQuantityError


def apply_delta(
    current: Decimal,
    transaction_type: Literal["stock", "dispense", "adjust"],
    quantity: Decimal,
) -> Decimal:
    """Return the new item quantity after applying a transaction.

    - `stock` adds `quantity` (positive) to `current`.
    - `dispense` subtracts `quantity` (positive) from `current`; if the
      result would be negative, raises `NegativeQuantityError` carrying
      both numbers.
    - `adjust` adds `quantity` as a *signed* delta (the caller has
      already computed `new_quantity - current` under FOR UPDATE). The
      same overdraft check applies: if the result is below zero, raises
      `NegativeQuantityError`.

    Inputs are assumed already validated by the Pydantic / service
    layer: for stock/dispense, `quantity` is a positive `Decimal`; for
    adjust, `quantity` may be any non-zero `Decimal`. We deliberately
    do NOT re-validate here — that is a boundary concern, not a
    domain concern.
    """
    if transaction_type == "stock":
        return current + quantity

    if transaction_type == "adjust":
        new_quantity = current + quantity
        if new_quantity < 0:
            raise NegativeQuantityError(current=current, requested=-quantity)
        return new_quantity

    new_quantity = current - quantity
    if new_quantity < 0:
        raise NegativeQuantityError(current=current, requested=quantity)
    return new_quantity


def reverse_delta(
    current: Decimal,
    transaction_type: Literal["stock", "dispense", "adjust"],
    quantity: Decimal,
) -> Decimal:
    """Return the item quantity after *undoing* a previously-applied
    transaction -- used when a mis-clicked transaction is voided.

    Reversing is just applying the opposite operation, so it reuses
    `apply_delta` (and inherits its overdraft check):

    - undo `stock` -> subtract the stocked amount (`dispense`).
    - undo `dispense` -> add the dispensed amount back (`stock`).
    - undo `adjust` -> apply the negated signed delta.

    Like `apply_delta`, this raises `NegativeQuantityError` if the undo
    would drive stock below zero (e.g. voiding a stock-in whose units
    have since been dispensed). The caller is expected to translate that
    into a user-facing "can't void" message under the item row lock.
    """
    if transaction_type == "stock":
        return apply_delta(current, "dispense", quantity)
    if transaction_type == "dispense":
        return apply_delta(current, "stock", quantity)
    # adjust: the stored quantity is the signed delta already applied;
    # undo by applying its negation through the same signed-delta path.
    return apply_delta(current, "adjust", -quantity)
