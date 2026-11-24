"""Admin+ "Message many": one text delivered as a separate direct message to
each picked person, so every recipient sees an ordinary one-to-one chat.

Layer: services. Split from `services/messages.py` (at the 500-line rule); it
reuses that module's direct-chat get-or-create and read-mark helpers.
"""

import uuid

from sqlalchemy.orm import Session

from app.domain import messages as rules
from app.domain.errors import GroupPermissionError, InvalidMessageError
from app.models import User
from app.models_messages import Message
from app.services import messages as chats


def broadcast(db: Session, user: User, user_ids, body: str) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """`(conversation_id, recipient_id)` per person, in the order given.

    Every id is checked before anything is written; the messages commit together.
    """
    if not rules.can_broadcast(user.role):
        raise GroupPermissionError("Only an Admin or Owner can message many people at once.")
    body = rules.clean_body(body)
    ids = [i for i in dict.fromkeys(chats._uuid(v) for v in user_ids) if i is not None and i != user.id]
    if not ids:
        raise InvalidMessageError("Pick at least one person.")
    active = {
        u.id for u in db.query(User.id).filter(User.id.in_(ids), User.archived_at.is_(None))
    }
    if len(active) != len(ids):
        raise InvalidMessageError("Someone on the list is unknown or archived.")

    pairs = [(chats.get_or_create_direct(db, user, rid), rid) for rid in ids]
    now = chats._now()
    for conv, _ in pairs:
        message = Message(conversation_id=conv.id, sender_id=user.id, body=body, created_at=now)
        db.add(message)
        db.flush()
        conv.last_message_at = now
        chats._advance_mark(db, conv.id, user.id, message.id)
    db.commit()
    return [(conv.id, rid) for conv, rid in pairs]
