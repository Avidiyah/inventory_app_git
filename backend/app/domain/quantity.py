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
    transaction_type: Literal["stock", "dispense"],
    quantity: Decimal,
) -> Decimal:
    """Return the new item quantity after applying a transaction.

    - `stock` adds `quantity` to `current`.
    - `dispense` subtracts `quantity`; if the result would be
      negative, raises `NegativeQuantityError` carrying both numbers.

    Inputs are assumed already validated by the Pydantic layer:
    `quantity` is a positive `Decimal` and `transaction_type` is one
    of the two literals. We deliberately do NOT re-validate here —
    that is a boundary concern, not a domain concern.
    """
    if transaction_type == "stock":
        return current + quantity

    new_quantity = current - quantity
    if new_quantity < 0:
        raise NegativeQuantityError(current=current, requested=quantity)
    return new_quantity
