"""Live messaging service: direct chats, Team-Lead groups, read marks, search, sweep.

Layer: services. Owns commits. Every function that names a conversation raises
`ConversationNotFoundError` for a non-member, so a stranger cannot tell a chat
exists. Message text is never logged.

Read marks are advanced with a conditional UPDATE: of two devices (or two
readers) racing, only the one that actually moved the mark sees a change, which
is what lets the second reader settle after one round of events.
"""

import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain import messages as rules
from app.domain import roles
from app.domain.errors import (
    ConversationNotFoundError,
    GroupPermissionError,
    InvalidMessageError,
    UserNotFoundError,
)
from app.models import User
from app.models_messages import Conversation, ConversationMember, Message
from app.services._like import like_pattern

logger = logging.getLogger(__name__)

KIND_DIRECT = rules.KIND_DIRECT
KIND_GROUP = rules.KIND_GROUP
_SWEEP_EVERY = timedelta(hours=24)
_last_sweep: datetime | None = None
_sweep_lock = threading.Lock()


# --- small helpers -----------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid(value) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _person(user: User) -> dict:
    return {"id": str(user.id), "name": user.full_name, "role_label": roles.label(user.role)}


def _message_out(message: Message, sender_name: str) -> dict:
    return {
        "id": message.id,
        "sender_id": str(message.sender_id),
        "sender_name": sender_name,
        "body": message.body,
        "created_at": message.created_at.isoformat(),
    }


def _require_member(db: Session, user: User, conversation_id) -> Conversation:
    """The conversation, or `ConversationNotFoundError` for a non-member
    (and for an id that is not even a UUID)."""
    cid = _uuid(conversation_id)
    conv = None
    if cid is not None:
        conv = (
            db.query(Conversation)
            .join(ConversationMember, ConversationMember.conversation_id == Conversation.id)
            .filter(Conversation.id == cid, ConversationMember.user_id == user.id)
            .first()
        )
    if conv is None:
        raise ConversationNotFoundError("Conversation not found.")
    return conv


def _member_ids(db: Session, conversation_id) -> list[uuid.UUID]:
    return [
        row[0]
        for row in db.query(ConversationMember.user_id)
        .filter(ConversationMember.conversation_id == conversation_id)
        .all()
    ]


def _advance_mark(db: Session, conversation_id, user_id, up_to: int) -> bool:
    """Raise a member's read mark to `up_to`; True only when it moved."""
    result = db.execute(
        update(ConversationMember)
        .where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == user_id,
            or_(
                ConversationMember.last_read_message_id.is_(None),
                ConversationMember.last_read_message_id < up_to,
            ),
        )
        .values(last_read_message_id=up_to)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount > 0


def _display_names(db: Session, user: User, convs: list[Conversation]) -> dict:
    """conversation id -> shown name: the group name, or the other member's."""
    direct_ids = [c.id for c in convs if c.kind == KIND_DIRECT]
    others: dict = {}
    if direct_ids:
        for cid, other in (
            db.query(ConversationMember.conversation_id, User)
            .join(User, User.id == ConversationMember.user_id)
            .filter(
                ConversationMember.conversation_id.in_(direct_ids),
                ConversationMember.user_id != user.id,
            )
            .all()
        ):
            others[cid] = other.full_name
    return {
        c.id: (others.get(c.id, "Name unavailable") if c.kind == KIND_DIRECT else (c.name or ""))
        for c in convs
    }


def _unread(db: Session, user: User) -> dict:
    """conversation id -> {sender id: count} of unread messages for `user`.
    A never-opened chat has a null mark, so it counts from 0."""
    rows = (
        db.query(Message.conversation_id, Message.sender_id, func.count())
        .join(
            ConversationMember,
            and_(
                ConversationMember.conversation_id == Message.conversation_id,
                ConversationMember.user_id == user.id,
            ),
        )
        .filter(
            Message.sender_id != user.id,
            Message.id > func.coalesce(ConversationMember.last_read_message_id, 0),
        )
        .group_by(Message.conversation_id, Message.sender_id)
        .all()
    )
    out: dict = {}
    for cid, sender_id, n in rows:
        out.setdefault(cid, {})[sender_id] = n
    return out


def _my_rows(db: Session, user: User) -> tuple[list[dict], list]:
    """(ConversationRows newest first, flat list of unread sender ids)."""
    convs = (
        db.query(Conversation)
        .join(ConversationMember, ConversationMember.conversation_id == Conversation.id)
        .filter(ConversationMember.user_id == user.id)
        .all()
    )
    if not convs:
        return [], []
    ids = [c.id for c in convs]
    names = _display_names(db, user, convs)
    unread = _unread(db, user)
    counts = dict(
        db.query(ConversationMember.conversation_id, func.count())
        .filter(ConversationMember.conversation_id.in_(ids))
        .group_by(ConversationMember.conversation_id)
        .all()
    )
    latest_ids = (
        select(func.max(Message.id))
        .where(Message.conversation_id.in_(ids))
        .group_by(Message.conversation_id)
    )
    last = {
        m.conversation_id: _message_out(m, sender.full_name)
        for m, sender in db.query(Message, User)
        .join(User, User.id == Message.sender_id)
        .filter(Message.id.in_(latest_ids))
        .all()
    }
    rows = []
    for c in sorted(convs, key=lambda c: c.last_message_at or c.created_at, reverse=True):
        if c.kind == KIND_DIRECT and c.id not in last:
            continue  # a direct chat with nothing in it stays out of the list
        senders = unread.get(c.id, {})
        rows.append(
            {
                "id": str(c.id),
                "kind": c.kind,
                "name": names[c.id],
                "starter_id": str(c.created_by) if c.created_by else None,
                "member_count": counts.get(c.id, 0),
                "last_message": last.get(c.id),
                "unread_count": sum(senders.values()),
                "unread_sender_ids": [str(s) for s in senders],
            }
        )
    flat = [s for senders in unread.values() for s in senders]
    return rows, flat


# --- reading -----------------------------------------------------------------


def list_conversations(db: Session, user: User) -> dict:
    rows, senders = _my_rows(db, user)
    return {"conversations": rows, "unread_people": rules.unread_people(senders)}


def get_conversation(db: Session, user: User, conversation_id, before: int | None = None) -> dict:
    conv = _require_member(db, user, conversation_id)
    query = (
        db.query(Message, User)
        .join(User, User.id == Message.sender_id)
        .filter(Message.conversation_id == conv.id)
    )
    if before is not None:
        query = query.filter(Message.id < before)
    page = query.order_by(Message.id.desc()).limit(rules.PAGE_SIZE + 1).all()
    has_more = len(page) > rules.PAGE_SIZE
    page = list(reversed(page[: rules.PAGE_SIZE]))

    members = (
        db.query(User, ConversationMember.last_read_message_id)
        .join(ConversationMember, ConversationMember.user_id == User.id)
        .filter(ConversationMember.conversation_id == conv.id)
        .all()
    )
    mine = next((mark for u, mark in members if u.id == user.id), None)
    seen = None
    if conv.kind == KIND_DIRECT:
        seen = next((mark for u, mark in members if u.id != user.id), None)
    starter = next((u for u, _ in members if u.id == conv.created_by), None)
    if starter is None and conv.created_by is not None:
        starter = db.query(User).filter(User.id == conv.created_by).first()
    people = sorted((_person(u) for u, _ in members), key=lambda p: p["name"].lower())
    return {
        "id": str(conv.id),
        "kind": conv.kind,
        "name": _display_names(db, user, [conv])[conv.id],
        "starter_id": str(conv.created_by) if conv.created_by else None,
        "starter_name": starter.full_name if starter else None,
        "members": people,
        "messages": [_message_out(m, sender.full_name) for m, sender in page],
        "has_more": has_more,
        "seen_message_id": seen,
        "my_read_message_id": mine,
    }


# --- writing -----------------------------------------------------------------


def send_message(db: Session, user: User, conversation_id, body: str) -> tuple[dict, list]:
    body = rules.clean_body(body)
    conv = _require_member(db, user, conversation_id)
    now = _now()
    message = Message(conversation_id=conv.id, sender_id=user.id, body=body, created_at=now)
    db.add(message)
    db.flush()
    conv.last_message_at = now
    _advance_mark(db, conv.id, user.id, message.id)
    members = _member_ids(db, conv.id)
    out = _message_out(message, user.full_name)
    db.commit()
    return out, members


def mark_read(db: Session, user: User, conversation_id, up_to: int) -> list:
    """Member ids when the mark moved, `[]` when it did not (never lowers it).
    `up_to` is capped at the newest message so a future message cannot arrive
    already read."""
    conv = _require_member(db, user, conversation_id)
    newest = (
        db.query(func.max(Message.id)).filter(Message.conversation_id == conv.id).scalar()
    )
    if newest is None:
        return []
    moved = _advance_mark(db, conv.id, user.id, min(int(up_to), newest))
    members = _member_ids(db, conv.id) if moved else []
    db.commit()
    return members


# --- starting and ending chats -----------------------------------------------


def _find_direct(db: Session, key: str) -> Conversation | None:
    return db.query(Conversation).filter(Conversation.direct_key == key).first()


def get_or_create_direct(db: Session, user: User, other_user_id) -> Conversation:
    oid = _uuid(other_user_id)
    other = None
    if oid is not None and oid != user.id:
        other = db.query(User).filter(User.id == oid, User.archived_at.is_(None)).first()
    if other is None:
        raise UserNotFoundError("User not found.")
    key = rules.direct_key(str(user.id), str(other.id))
    found = _find_direct(db, key)
    if found is not None:
        return found
    conv = Conversation(
        id=uuid.uuid4(), kind=KIND_DIRECT, created_by=user.id, direct_key=key, created_at=_now()
    )
    try:
        db.add(conv)
        db.flush()  # the unique direct_key fires here when we lost the race
        db.add_all(
            ConversationMember(conversation_id=conv.id, user_id=u) for u in (user.id, other.id)
        )
        db.commit()
    except IntegrityError:
        # Both people opened their first chat at the same moment; theirs won.
        db.rollback()
        found = _find_direct(db, key)
        if found is None:
            raise
        return found
    return conv


def create_group(db: Session, user: User, name: str, member_ids) -> tuple[Conversation, list]:
    if not rules.can_start_group(user.role):
        raise GroupPermissionError("Only a Team Lead or above can start a group.")
    name = rules.clean_group_name(name)
    others: set[uuid.UUID] = set()
    for raw in member_ids or []:
        mid = _uuid(raw)
        if mid is None:
            raise InvalidMessageError("Unknown person in the group.")
        if mid != user.id:
            others.add(mid)
    if len(others) < rules.MIN_GROUP_OTHERS:
        raise InvalidMessageError(f"Pick at least {rules.MIN_GROUP_OTHERS} other people.")
    if len(others) + 1 > rules.MAX_GROUP_MEMBERS:
        raise InvalidMessageError(f"A group holds at most {rules.MAX_GROUP_MEMBERS} people.")
    active = (
        db.query(func.count())
        .select_from(User)
        .filter(User.id.in_(others), User.archived_at.is_(None))
        .scalar()
    )
    if active != len(others):
        raise InvalidMessageError("Unknown person in the group.")
    conv = Conversation(
        id=uuid.uuid4(), kind=KIND_GROUP, name=name, created_by=user.id, created_at=_now()
    )
    db.add(conv)
    db.flush()
    everyone = [user.id, *others]
    db.add_all(ConversationMember(conversation_id=conv.id, user_id=u) for u in everyone)
    db.commit()
    return conv, everyone


def end_group(db: Session, user: User, conversation_id) -> list:
    conv = _require_member(db, user, conversation_id)
    if conv.kind != KIND_GROUP:
        raise ConversationNotFoundError("Conversation not found.")
    if conv.created_by != user.id:
        raise GroupPermissionError("Only the person who started the group can end it.")
    members = _member_ids(db, conv.id)
    db.execute(delete(Conversation).where(Conversation.id == conv.id))  # FK cascade
    db.commit()
    db.expire_all()
    return members


# --- people and search -------------------------------------------------------


def list_people(db: Session, user: User) -> list[dict]:
    # ponytail: unbounded, the roster is a shop's worth of people; cap if it ever is not.
    users = (
        db.query(User)
        .filter(User.archived_at.is_(None), User.id != user.id)
        .order_by(func.lower(User.first_name), func.lower(User.last_name), User.username)
        .all()
    )
    return [_person(u) for u in users]


def search(db: Session, user: User, q: str) -> dict:
    """People, my chats and my messages containing `q` (case-insensitive,
    literal -- `%` and `_` match themselves). Under `SEARCH_MIN_CHARS` finds nothing."""
    empty = {"people": [], "conversations": [], "messages": []}
    needle = (q or "").strip()
    if len(needle) < rules.SEARCH_MIN_CHARS:
        return empty
    pattern, esc = like_pattern(needle)
    cap = rules.SEARCH_MAX_ROWS

    people = (
        db.query(User)
        .filter(
            User.archived_at.is_(None),
            User.id != user.id,
            func.concat_ws(" ", User.first_name, User.last_name).ilike(pattern, escape=esc),
        )
        .order_by(func.lower(User.first_name), func.lower(User.last_name))
        .limit(cap)
        .all()
    )
    rows, _ = _my_rows(db, user)
    folded = needle.casefold()
    conversations = [r for r in rows if folded in r["name"].casefold()][:cap]

    hits = (
        db.query(Message, User)
        .join(User, User.id == Message.sender_id)
        .join(
            ConversationMember,
            and_(
                ConversationMember.conversation_id == Message.conversation_id,
                ConversationMember.user_id == user.id,
            ),
        )
        .filter(Message.body.ilike(pattern, escape=esc))
        .order_by(Message.id.desc())
        .limit(cap)
        .all()
    )
    names: dict = {}
    if hits:
        convs = (
            db.query(Conversation)
            .filter(Conversation.id.in_({m.conversation_id for m, _ in hits}))
            .all()
        )
        names = _display_names(db, user, convs)
    return {
        "people": [_person(u) for u in people],
        "conversations": conversations,
        "messages": [
            {
                "conversation_id": str(m.conversation_id),
                "conversation_name": names.get(m.conversation_id, ""),
                "message": _message_out(m, sender.full_name),
            }
            for m, sender in hits
        ],
    }


# --- clean-up ----------------------------------------------------------------


def sweep(db: Session, now: datetime) -> dict:
    """Delete direct messages past retention and groups quiet too long (a
    group's quiet clock starts at its last message, or its creation if empty)."""
    direct_ids = select(Conversation.id).where(Conversation.kind == KIND_DIRECT)
    messages = db.execute(
        delete(Message)
        .where(Message.conversation_id.in_(direct_ids), Message.created_at < rules.direct_cutoff(now))
        .execution_options(synchronize_session=False)
    ).rowcount
    groups = db.execute(
        delete(Conversation)
        .where(
            Conversation.kind == KIND_GROUP,
            func.coalesce(Conversation.last_message_at, Conversation.created_at)
            < rules.group_cutoff(now),
        )
        .execution_options(synchronize_session=False)
    ).rowcount
    db.commit()
    return {"messages_deleted": messages, "groups_deleted": groups}


def maybe_sweep(db: Session, now: datetime) -> dict | None:
    """`sweep` at most once per 24 h per process; None when it was skipped.
    A failing sweep is logged and never breaks the caller's request.
    # ponytail: first call after a restart sweeps; a sleepy server sweeps late."""
    global _last_sweep
    with _sweep_lock:
        if _last_sweep is not None and now - _last_sweep < _SWEEP_EVERY:
            return None
        _last_sweep = now
    try:
        return sweep(db, now)
    except Exception:
        db.rollback()
        logger.warning("message sweep failed", exc_info=True)
        return None
