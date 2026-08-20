"""Pure tool-custody rule.

Layer: pure domain (no SQLAlchemy, no FastAPI, no models).

A tool return can never exceed what the target user currently has checked
out for that tool. `outstanding` is the caller's already-computed net
(Sum(checkout) - Sum(return)) for the (tool, user) pair -- this module does
not know how to query it, mirroring how `domain.quantity.apply_delta` does
not know how to lock a row.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional, Sequence

from app.domain.errors import ToolReturnExceedsCheckedOutError


def validate_return(outstanding: Decimal, requested: Decimal) -> None:
    """Raise `ToolReturnExceedsCheckedOutError` if `requested` exceeds
    `outstanding`. Called by `services.tools.return_tool` before applying
    the on-hand quantity change."""
    if requested > outstanding:
        raise ToolReturnExceedsCheckedOutError(requested, outstanding)


def custody_since(
    events: Sequence[tuple[str, Decimal, datetime]],
) -> Optional[datetime]:
    """When the current unbroken custody spell began, or None if nothing is out.

    `events` are `(transaction_type, quantity, created_at)` for one
    `(tool, holder)` pair, in chronological order. Walks the running balance
    and remembers the checkout that lifted it off zero; a return that brings
    it back to zero ends the spell, so a tool taken out, returned, and taken
    out again reads "since" the second checkout rather than the first.

    A *partial* return does not end the spell -- the holder never gave the
    tool back. `adjust` rows are skipped for the same reason `tool_custody`
    excludes them: a Correct Count has no custody holder.
    """
    balance = Decimal("0")
    since: Optional[datetime] = None
    for transaction_type, quantity, created_at in events:
        if transaction_type == "checkout":
            if balance <= 0:
                since = created_at
            balance += quantity
        elif transaction_type == "return":
            balance -= quantity
            if balance <= 0:
                balance = Decimal("0")
                since = None
    return since
