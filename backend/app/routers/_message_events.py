"""The one call every chat-writing route makes after its write.

Layer: routers (shared helper), alongside `_attendance_events.py`.

Targeted, unlike every other emission: only the conversation's members are
woken. The envelope carries the conversation id and never any message text.
"""

import logging
from typing import Iterable

from app.domain import realtime as realtime_policy
from app.logging_config import current_request_id
from app.services import realtime as realtime_service

logger = logging.getLogger(__name__)


def emit_message_changed(conversation_id, user_ids: Iterable) -> None:
    """Tell each member's open screens that `conversation_id` changed.

    Best-effort by contract: a dropped envelope costs one stale panel until
    the next open and must never fail a durable write.
    """
    realtime_service.emit(
        realtime_policy.build_envelope(
            event_type=realtime_policy.EVENT_MESSAGE_CHANGED,
            entity_id=conversation_id,
            request_id=current_request_id(),
        ),
        user_ids=user_ids,
    )
