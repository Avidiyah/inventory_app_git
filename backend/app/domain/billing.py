"""Pure billing rules.

Layer: pure domain (no FastAPI, no SQLAlchemy, no Pydantic). Holds the
single rule that validates an Admin's billable-quantity override before
the service writes it, so it can be unit-tested without a database.

A billable-quantity override answers "how many of this row's units do we
actually charge the customer for?". It is a billing annotation only and
never moves stock (`Item.quantity`).
"""

from decimal import Decimal
from typing import Optional

from app.domain.errors import BillingQuantityError

# Transaction types that represent units that can be charged. `adjust`
# rows are stock corrections (a signed delta, possibly negative), not a
# customer charge, so a billable override on them is meaningless.
_BILLABLE_TYPES = ("stock", "dispense")


def validate_billable_quantity(
    transaction_type: str,
    quantity: Decimal,
    billable: Optional[Decimal],
) -> Optional[Decimal]:
    """Validate and normalise a billable-quantity override.

    `billable` is the Admin's requested charge count, or `None` to clear
    the override (charge the full `quantity` again). Returns the value to
    persist (`None` to clear).

    Rules:
    - `None` always passes through (clearing an override is always valid).
    - Only `stock` / `dispense` rows may carry an override; an `adjust`
      correction cannot be billed.
    - The override cannot be negative.
    - The override cannot exceed the units actually recorded (`quantity`);
      you can decline to charge for some, but never invent extra.

    Raises `BillingQuantityError` (maps to 400) on any violation.
    """
    if billable is None:
        return None
    if transaction_type not in _BILLABLE_TYPES:
        raise BillingQuantityError(
            "Only stock and dispense rows can have their billed amount adjusted."
        )
    if billable < 0:
        raise BillingQuantityError("Billed quantity cannot be negative.")
    if billable > quantity:
        raise BillingQuantityError(
            f"Billed quantity can't exceed the {quantity} actually recorded."
        )
    return billable
