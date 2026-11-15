"""The one emitter of `user_request.changed` (W5).

Rather than trust every route to remember, two session events cover every
writer -- routes, services, scripts:

- `after_flush` notes the id of each `UserRequest` inserted or really changed.
  The id is a client-side default, so a new row already has one here.
- `after_commit` emits one envelope per noted id, once the write is durable.
  `realtime.emit` works with no event loop (scripts, tests) and never raises;
  each emit is still guarded so one failure cannot cost the rest.

A rollback forgets the noted ids. Known ceiling: a savepoint rolled back
inside a transaction that then commits still emits its ids -- a harmless
extra invalidation, since subscribers refetch over REST.
"""

import logging

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.domain import realtime as realtime_policy
from app.logging_config import current_request_id
from app.models import UserRequest
from app.services import realtime as realtime_service

logger = logging.getLogger(__name__)
_PENDING = "request_events"


@event.listens_for(Session, "after_flush")
def _note_requests(session, flush_context):
    ids = {
        obj.id
        for obj in (*session.new, *session.dirty)
        if isinstance(obj, UserRequest) and (obj in session.new or session.is_modified(obj))
    }
    if ids:
        session.info.setdefault(_PENDING, set()).update(ids)


@event.listens_for(Session, "after_soft_rollback")
def _forget_requests(session, previous_transaction):
    session.info.pop(_PENDING, None)


@event.listens_for(Session, "after_commit")
def _emit_requests(session):
    for request_id in session.info.pop(_PENDING, ()):
        try:
            realtime_service.emit(
                realtime_policy.build_envelope(
                    event_type=realtime_policy.EVENT_USER_REQUEST_CHANGED,
                    entity_id=request_id,
                    request_id=current_request_id(),
                )
            )
        except Exception:  # noqa: BLE001 - best-effort by contract
            logger.exception("user_request.changed emit failed")
