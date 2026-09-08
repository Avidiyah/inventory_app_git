"""Material Request policy: the two stock edges a request lives on.

Layer: pure domain (no SQLAlchemy, no FastAPI, no models). Same shape as
`domain/low_stock.py`: the interesting rule is an *edge*, not a state, so
it is a comparison of a before and an after and needs no armed-state
column anywhere.

A Material Request says "a catalogue item the shelf does not have". It
becomes `stocked` the moment any write takes the item's on-hand from
`<= 0` to `> 0`, and falls back to `open` on the reverse move. Which
write did it -- Add Stock, an upward correction, a voided dispense, a
Mass Stage return, a work-order line reversal -- is irrelevant here; the
eight stock-writing sites all ask the same two questions.

The vocabulary lives here rather than in `services/user_requests.py` so
that `services/material_requests.py` can import it without importing
anything from `app.services`, which is the import-ring discipline
`services/low_stock.py` established.
"""

from decimal import Decimal

REQUEST_MATERIAL = "material_request"

STATUS_OPEN = "open"
STATUS_STOCKED = "stocked"
STATUS_RESOLVED = "resolved"


def restocked(quantity_before: Decimal, quantity_after: Decimal) -> bool:
    """Whether this write is the moment the item came back onto the shelf.

    `<= 0` before, not `== 0`: Scan / Stock records real usage past the
    recorded balance, so an item can sit at -3 and a restock to +2 is
    still the edge the crew is waiting for.
    """
    return Decimal(quantity_before) <= 0 and Decimal(quantity_after) > 0


def went_out(quantity_before: Decimal, quantity_after: Decimal) -> bool:
    """The reverse edge: a stocked item ran out again before the crew
    added it. Sends a `stocked` request back to `open` so the Hub row and
    the Materials line stop promising something the shelf no longer has."""
    return Decimal(quantity_before) > 0 and Decimal(quantity_after) <= 0
