"""The one call every stock-writing route makes about low stock.

Layer: routers (shared helper), alongside `_errors.py` and `_uploads.py`.
It exists so the three routers that move stock -- transactions, mass
stages, work orders -- each add exactly one line instead of three, and so
the swallow-and-log contract is written once.

Why the drain lives here rather than in a service: emitting realtime
invalidations from the router is the convention this repo already follows
(`routers/work_orders.py::_emit_status_changed`), and pulling
`services.realtime` into a service that `services.notifications` imports
would close an import ring. The buffer module underneath
(`services.low_stock`) deliberately imports nothing from `app.services`
for the same reason.
"""

import logging
import uuid
from typing import Optional

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.domain import realtime as realtime_policy
from app.logging_config import current_request_id
from app.services import low_stock as low_stock_service
from app.services import notifications as notifications_service
from app.services import realtime as realtime_service

logger = logging.getLogger(__name__)


def emit_low_stock_changed(item_id: Optional[uuid.UUID]) -> None:
    """Invalidate the Low Stock page for one item.

    Best-effort by contract, exactly like the work-order emitters:
    ``emit`` is total and its boolean result is deliberately ignored so a
    full handoff can never fail a durable write.
    """
    realtime_service.emit(
        realtime_policy.build_envelope(
            event_type=realtime_policy.EVENT_ITEM_LOW_STOCK_CHANGED,
            entity_id=item_id,
            request_id=current_request_id(),
        )
    )


def flush_low_stock(db: Session, background: BackgroundTasks) -> None:
    """Drain this request's crossings, push the ones that crossed, and
    invalidate every item whose membership changed.

    Call once, on the success path, after the service returned -- the
    durable write has committed by then, which is what makes swallowing
    correct rather than lazy. A failure here costs a notification; raising
    would cost the user a save that actually succeeded.

    Draining on the failure path is neither needed nor wanted: the request
    context dies with the request, taking its buffer with it.
    """
    try:
        crossings = low_stock_service.drain()
        if not crossings:
            return
        notifications_service.notify_item_low_stock(db, background, crossings=crossings)
        for crossing in crossings:
            emit_low_stock_changed(crossing.item_id)
    except Exception:  # noqa: BLE001 - best-effort by contract
        logger.exception("low-stock notification failed")
