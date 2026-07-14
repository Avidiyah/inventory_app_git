"""Pure tool-custody rule.

Layer: pure domain (no SQLAlchemy, no FastAPI, no models).

A tool return can never exceed what the target user currently has checked
out for that tool. `outstanding` is the caller's already-computed net
(Sum(checkout) - Sum(return)) for the (tool, user) pair -- this module does
not know how to query it, mirroring how `domain.quantity.apply_delta` does
not know how to lock a row.
"""

from decimal import Decimal

from app.domain.errors import ToolReturnExceedsCheckedOutError


def validate_return(outstanding: Decimal, requested: Decimal) -> None:
    """Raise `ToolReturnExceedsCheckedOutError` if `requested` exceeds
    `outstanding`. Called by `services.tools.return_tool` before applying
    the on-hand quantity change."""
    if requested > outstanding:
        raise ToolReturnExceedsCheckedOutError(requested, outstanding)
