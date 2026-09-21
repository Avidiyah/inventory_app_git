"""The one call every punch-writing route makes after its write.

Layer: routers (shared helper), alongside `_errors.py` and `_stock_events.py`
-- which is the convention this repo already follows for emitting realtime
invalidations from the router rather than from a service.

It lives here rather than in either router because six routes across two
modules make the same call, and a second copy is how two surfaces end up
emitting two different event names.
"""

import logging

from app.domain import realtime as realtime_policy
from app.logging_config import current_request_id
from app.services import realtime as realtime_service

logger = logging.getLogger(__name__)


def emit_attendance_changed() -> None:
    """Invalidate the Admin roster and the comparison week after a punch
    write.

    Always `entity_id=None`: a punch changing is a membership change to
    *somebody's* on-shift state, not one card's field, so the recipient
    refetches rather than targeting a row -- the same reasoning
    `labor.session.changed` already uses.

    Best-effort by contract, like every other emission in this package: a
    dropped envelope costs one stale strip until the next 60-second poll and
    must never fail a durable write.
    """
    realtime_service.emit(
        realtime_policy.build_envelope(
            event_type=realtime_policy.EVENT_ATTENDANCE_CHANGED,
            entity_id=None,
            request_id=current_request_id(),
        )
    )
