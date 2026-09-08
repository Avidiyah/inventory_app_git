"""The one call every stock-writing route makes after its commit.

Layer: routers (shared helper), alongside `_errors.py` and `_uploads.py`.
It exists so the three routers that move stock -- transactions, mass
stages, work orders -- each add exactly one line instead of several, and so
the swallow-and-log contract is written once.

Two buffers drain here, filled by two thin services that import nothing
from `app.services`: `services.low_stock` (crossings of an item's
threshold) and `services.material_requests` (requests that just became
`stocked`). Each branch has its own try/except so a failure in one costs
that branch's push and never the other's.

Why the drain lives here rather than in a service: emitting realtime
invalidations from the router is the convention this repo already follows
(`routers/work_orders.py::_emit_status_changed`), and pulling
`services.realtime` into a service that `services.notifications` imports
would close an import ring.
"""

import logging
import uuid
from typing import Optional

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.domain import realtime as realtime_policy
from app.logging_config import current_request_id
from app.services import low_stock as low_stock_service
from app.services import material_requests as material_requests_service
from app.services import notifications as notifications_service
from app.services import realtime as realtime_service

logger = logging.getLogger(__name__)


def emit_low_stock_changed(item_id: Optional[uuid.UUID]) -> None:
    """Invalidate the Low Stock page for one item. Best-effort by contract."""
    realtime_service.emit(
        realtime_policy.build_envelope(
            event_type=realtime_policy.EVENT_ITEM_LOW_STOCK_CHANGED,
            entity_id=item_id,
            request_id=current_request_id(),
        )
    )


def emit_user_request_changed(request_id: Optional[uuid.UUID]) -> None:
    """Tell every connected client one User Request moved. Subscribers -- the
    Hub dashboard, the User Requests page, an open work-order card -- refetch
    through REST, which re-applies visibility. Best-effort by contract."""
    realtime_service.emit(
        realtime_policy.build_envelope(
            event_type=realtime_policy.EVENT_USER_REQUEST_CHANGED,
            entity_id=request_id,
            request_id=current_request_id(),
        )
    )


def flush_stock_events(db: Session, background: BackgroundTasks) -> None:
    """Drain this request's crossings and stocked facts, push what should be
    pushed, and invalidate what changed.

    Call once, on the success path, after the service returned -- the
    durable write has committed by then, which is what makes swallowing
    correct rather than lazy. A failure here costs a notification; raising
    would cost the user a save that actually succeeded.
    """
    try:
        crossings = low_stock_service.drain()
        if crossings:
            notifications_service.notify_item_low_stock(db, background, crossings=crossings)
            for crossing in crossings:
                emit_low_stock_changed(crossing.item_id)
    except Exception:  # noqa: BLE001 - best-effort by contract
        logger.exception("low-stock notification failed")

    try:
        facts = material_requests_service.drain()
        if facts:
            notifications_service.notify_material_request_stocked(db, background, facts=facts)
            for fact in facts:
                emit_user_request_changed(fact.request_id)
    except Exception:  # noqa: BLE001 - best-effort by contract
        logger.exception("material-request stocked notification failed")
