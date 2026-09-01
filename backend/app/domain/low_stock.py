"""Low-stock policy: is an item low, and did this write make it low.

Layer: pure domain (no SQLAlchemy, no FastAPI, no models). Every
function takes numbers and returns a bool, which is what makes the one
interesting rule -- the *edge*, not the state -- testable without a
database.

The whole feature rests on a single idea: a push fires when an item was
not low before a write and is low after it. Because a threshold edit is
also a write with a before and an after, raising a threshold past the
current count is the same event as dispensing down past a fixed one, and
falls out of the same comparison rather than needing a second code path.
That is why there is no armed-state column anywhere in this feature.
"""

from decimal import Decimal

# The threshold every item starts at. Written here and in the Alembic
# migration's `server_default`, and nowhere else -- a third copy is how
# the database and the application drift apart.
DEFAULT_LOW_STOCK_THRESHOLD = 6

# Thresholds are whole numbers of at least one. There is deliberately no
# "0 = never alert" mute: stock cannot go below zero, so a zero threshold
# would be an invisible off-switch rather than a threshold.
MIN_LOW_STOCK_THRESHOLD = 1


def is_low(quantity: Decimal, threshold: int) -> bool:
    """Whether `quantity` is at or below `threshold`.

    `<=`, not `<`: "six or fewer" is the alert that was asked for, so an
    item sitting exactly on its threshold is already low. A negative
    count (Scan / Stock records real usage past the recorded balance) is
    low for the same reason.
    """
    return Decimal(quantity) <= Decimal(threshold)


def crossed_into_low(
    *,
    quantity_before: Decimal,
    threshold_before: int,
    quantity_after: Decimal,
    threshold_after: int,
) -> bool:
    """Whether this write is the moment the item BECAME low.

    The push predicate, and the reason there is no armed-state column: an
    item that was already low stays silent because the before-state is
    already `True`, and it re-arms by being restocked, with nothing
    persisted in between.

    Taking a before *and* after threshold is what folds the retune case
    in. Raising a threshold from 6 to 20 over a count of 10 is the same
    false-to-true edge as dispensing from 10 to 5 against a fixed 6, so
    both callers -- the stock services and the threshold route -- ask the
    same question.
    """
    return not is_low(quantity_before, threshold_before) and is_low(
        quantity_after, threshold_after
    )


def membership_changed(
    *,
    quantity_before: Decimal,
    threshold_before: int,
    quantity_after: Decimal,
    threshold_after: int,
) -> bool:
    """Whether the item entered OR left the low-stock set.

    Deliberately wider than `crossed_into_low`: the Low Stock page has to
    drop a row when an item is restocked back above its threshold, and a
    push-shaped predicate would leave that row on screen until the next
    page activation.
    """
    return is_low(quantity_before, threshold_before) != is_low(
        quantity_after, threshold_after
    )
