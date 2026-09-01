"""The request-scoped buffer of low-stock crossings.

Layer: services, but deliberately the thinnest one in the app. This
module imports **nothing from `app.services`** and no ORM model. Three
services will import it (`transactions`, `mass_staging`, `work_orders`)
and one of those is imported by `services.notifications`; a service
import in the other direction would close that ring into a cycle.

**Why a buffer at all.** Stock moves in the middle of services that are
several frames below the router, some of them inside loops. Threading a
return value up through `load_item`'s allocation loop and
`work_orders`' line editing would touch far more code than the feature
is worth, and would still leave the next stock-writing service free to
forget. A buffer lets each mutation point say one true thing about the
item in front of it and lets exactly one place -- the router -- decide
what to do about it.

**Why a ContextVar, and why it is safe.** Each request runs in its own
copied context: an async handler in its task's context, a sync handler in
a fresh `copy_context()` per threadpool call. So a `set()` here is
visible for the rest of that request and invisible to every other, with
no explicit teardown. The buffer is only ever read back inside the same
handler invocation that filled it, which is the one direction context
copying guarantees.

**The invariant the call sites rely on:** `record` is called immediately
*before* the service's `db.commit()`, while the ORM object is loaded and
its values are cheap to read; `drain` is called by the router only after
the handler's success path. A service that raises between the two never
reaches the drain, and its buffered entry dies with the request context.
"""

import logging
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from app.domain import low_stock as policy
from app.domain.receipt import format_quantity

logger = logging.getLogger(__name__)

# A ceiling, not a budget. Every HTTP path drains, so this only bites a
# non-request caller (a script, an import job) that mutates stock in a
# loop and never drains -- there, an unbounded list is a slow leak and a
# dropped notification is not.
MAX_BUFFERED_CROSSINGS = 500


@dataclass(frozen=True)
class Crossing:
    """One item's low-stock membership change, as plain values.

    Everything a background task will need is already a `str` / `int` /
    `uuid` here. Keeping an ORM object instead is the single easiest way
    to break notifications, and it breaks them only in a real deployment:
    the request's session is closed before background tasks run, so a
    lazy attribute touched there raises `DetachedInstanceError` that no
    synchronous test would ever see.

    `pushes` is the narrow, edge-only question; membership merely
    *changing* is the wider one and is why an item leaving the low set is
    buffered at all.
    """

    item_id: uuid.UUID
    name: str
    quantity: str
    pushes: bool


_buffer: ContextVar[Optional[list]] = ContextVar("low_stock_buffer", default=None)


def record(item, *, quantity_before: Decimal, threshold_before: Optional[int] = None) -> None:
    """Note that `item` may have entered or left the low-stock set.

    Call immediately before the service's `db.commit()`, with
    `quantity_before` captured before the mutation. `threshold_before`
    defaults to the item's current threshold, which is correct for every
    stock write -- only the threshold route supplies it, and only because
    that route is the one write where the threshold itself moved.

    Buffers nothing when membership did not change, so the common case
    (a dispense that leaves a healthy item healthy) costs two
    comparisons and no allocation.
    """
    threshold_after = int(item.low_stock_threshold)
    if threshold_before is None:
        threshold_before = threshold_after

    quantity_after = Decimal(item.quantity)
    if not policy.membership_changed(
        quantity_before=quantity_before,
        threshold_before=threshold_before,
        quantity_after=quantity_after,
        threshold_after=threshold_after,
    ):
        return

    entries = _buffer.get()
    if entries is None:
        entries = []
        _buffer.set(entries)
    if len(entries) >= MAX_BUFFERED_CROSSINGS:
        logger.warning(
            "low-stock buffer full at %s entries; dropping further crossings",
            MAX_BUFFERED_CROSSINGS,
        )
        return

    entries.append(
        Crossing(
            item_id=item.id,
            name=item.name,
            quantity=format_quantity(quantity_after),
            pushes=policy.crossed_into_low(
                quantity_before=quantity_before,
                threshold_before=threshold_before,
                quantity_after=quantity_after,
                threshold_after=threshold_after,
            ),
        )
    )


def drain() -> list:
    """Take everything buffered so far and empty the buffer.

    Total by contract: called on paths that have already committed, and
    called again by tests for cleanup. Returning a new list (rather than
    the buffered one) means a caller holding the result cannot be
    surprised by a later `record`.
    """
    entries = _buffer.get()
    if not entries:
        return []
    taken = list(entries)
    entries.clear()
    return taken
