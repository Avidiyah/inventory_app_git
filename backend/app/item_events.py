"""The one emitter of `item.low_stock.changed` (W6).

Same shape as `request_events.py`: `after_flush` notes the id of every
`Item` inserted or really changed that is low before or after the write,
`after_commit` emits one envelope per noted id, a rollback forgets them.
So the Low Stock page hears a dispense, restock, correction, edit, create
or archive of any item it lists or should list, and nothing else.

"Low" is quantity against threshold only. The archived flag is ignored on
purpose: archiving a low item emits (the row must leave the page), and an
event for an already-archived item costs one harmless refetch.

Known ceilings: a core-SQL write to `items` (none exists in `app/` as of
2026-11-23) bypasses the session and so this listener; and a savepoint
rolled back inside a transaction that then commits still emits its ids.
"""

import logging

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.domain import realtime as realtime_policy
from app.domain.low_stock import is_low
from app.logging_config import current_request_id
from app.models import Item
from app.services import realtime as realtime_service

logger = logging.getLogger(__name__)
_PENDING = "item_events"


def _before(item, name):
    """The value `name` had before this flush (history is still present in
    `after_flush`); the current value when it did not change."""
    deleted = inspect(item).attrs[name].history.deleted
    return deleted[0] if deleted else getattr(item, name)


def _touches_low_stock(session, item):
    if is_low(item.quantity, item.low_stock_threshold):
        return True
    if item in session.new:
        return False
    return is_low(_before(item, "quantity"), _before(item, "low_stock_threshold"))


@event.listens_for(Session, "after_flush")
def _note_items(session, flush_context):
    ids = {
        obj.id
        for obj in (*session.new, *session.dirty)
        if isinstance(obj, Item)
        and (obj in session.new or session.is_modified(obj))
        and _touches_low_stock(session, obj)
    }
    if ids:
        session.info.setdefault(_PENDING, set()).update(ids)


@event.listens_for(Session, "after_soft_rollback")
def _forget_items(session, previous_transaction):
    session.info.pop(_PENDING, None)


@event.listens_for(Session, "after_commit")
def _emit_items(session):
    for item_id in session.info.pop(_PENDING, ()):
        try:
            realtime_service.emit(
                realtime_policy.build_envelope(
                    event_type=realtime_policy.EVENT_ITEM_LOW_STOCK_CHANGED,
                    entity_id=item_id,
                    request_id=current_request_id(),
                )
            )
        except Exception:  # noqa: BLE001 - best-effort by contract
            logger.exception("item.low_stock.changed emit failed")
