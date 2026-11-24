"""Live messaging tables (spec
docs/superpowers/specs/2026-11-24-live-messaging-design.md).

Split out of `models.py` (past 1,200 lines); `models.py` imports this module at
its foot so Alembic's `Base.metadata` sees the tables. Every FK to
`conversations` cascades, so ending a group or sweeping it is one delete.
`last_read_message_id` has no FK: the message it names may be swept.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Conversation(Base):
    """A direct chat (two members, `direct_key` set) or a temporary group."""

    __tablename__ = "conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind = Column(Text, nullable=False)
    name = Column(Text, nullable=True)
    created_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    last_message_at = Column(DateTime(timezone=True), nullable=True)
    direct_key = Column(Text, nullable=True, unique=True)


class ConversationMember(Base):
    """One person's place in a chat and how far they have read."""

    __tablename__ = "conversation_members"

    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    last_read_message_id = Column(BigInteger, nullable=True)


class Message(Base):
    """One message. `id` only grows, so it doubles as the read mark."""

    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation_id_id", "conversation_id", "id"),)

    id = Column(BigInteger, Identity(), primary_key=True)
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    sender_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    body = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
