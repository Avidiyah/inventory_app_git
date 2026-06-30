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


def validate_billable_value(
    quantity: Decimal,
    billable: Optional[Decimal],
) -> Optional[Decimal]:
    """The numeric core of a billable-quantity override, with no row-type
    opinion -- shared by the per-transaction (History) and per-line (work
    order) overrides.

    `billable` is the requested charge count, or `None` to clear the override
    (charge the full `quantity` again). Rules:
    - `None` always passes (clearing is always valid).
    - The override cannot be negative.
    - The override cannot exceed the units actually recorded (`quantity`); you
      can decline to charge for some, but never invent extra.

    Raises `BillingQuantityError` (maps to 400) on any violation.
    """
    if billable is None:
        return None
    if billable < 0:
        raise BillingQuantityError("Billed quantity cannot be negative.")
    if billable > quantity:
        raise BillingQuantityError(
            f"Billed quantity can't exceed the {quantity} actually recorded."
        )
    return billable


def validate_billable_quantity(
    transaction_type: str,
    quantity: Decimal,
    billable: Optional[Decimal],
) -> Optional[Decimal]:
    """Validate a per-transaction billable override (History page).

    Same as `validate_billable_value`, plus the rule that only `stock` /
    `dispense` rows may carry an override -- an `adjust` correction is a signed
    stock delta, not a customer charge. Raises `BillingQuantityError`.
    """
    if billable is None:
        return None
    if transaction_type not in _BILLABLE_TYPES:
        raise BillingQuantityError(
            "Only stock and dispense rows can have their billed amount adjusted."
        )
    return validate_billable_value(quantity, billable)
