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
