"""SQLAlchemy ORM models -- the database schema in code.

Layer: persistence. These classes mirror the physical tables
managed by Alembic migrations under `backend/alembic/versions/`.
Any schema change must be made here AND in a new migration; the
two are not auto-synced.

Services in `app.services` are the only callers. Routers and
schemas never import from this module -- response shaping happens
through Pydantic models with `from_attributes=True`.
"""

# app/models.py

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, Text, Numeric, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.database import Base


class User(Base):
    """A person who can log in and act on the system. `username` is the
    login identifier and must be unique; `password_hash` stores a salted
    scrypt digest (see `app.services.auth`); `role` is one of the four
    values in `app.domain.roles` and drives authorization."""

    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(Text, nullable=False, unique=True)
    password_hash = Column(Text, nullable=False)
    role = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    transactions = relationship("Transaction", back_populates="user")
    sessions = relationship("AuthSession", back_populates="user", cascade="all, delete-orphan")


class Item(Base):
    """An inventoried item. `barcode` is the human/scanner-facing
    identifier and is unique; `notes` is a JSONB bag of
    `str|int|float|bool` values validated by
    `app.domain.notes_validation`."""

    __tablename__ = "items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    barcode = Column(Text, nullable=False, unique=True)
    name = Column(Text, nullable=False)
    quantity = Column(Numeric, nullable=False, default=0)
    location = Column(Text, nullable=False)
    notes = Column(JSONB, nullable=False, default=dict, server_default="{}")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    transactions = relationship("Transaction", back_populates="item")


class Transaction(Base):
    """Append-only audit row for a stock, dispense, or correction event.

    `user_id` is nullable -- anonymous transactions are allowed (older
    pre-auth rows). The FK on `user_id` and `item_id` are both
    `ON DELETE RESTRICT` (configured at the database level via
    Alembic), which is why deleting a referenced user or item raises
    `UserHasTransactionsError` / `ItemHasTransactionsError`.

    `quantity` is the signed delta applied to `Item.quantity`:
    positive for `stock` and `adjust`-up, negative for `adjust`-down.
    `dispense` rows store a positive number for historical consistency
    (the sign is implied by the type). `reason` is populated only for
    `transaction_type = "adjust"` and is required at the schema layer
    for that type.
    """

    __tablename__ = "transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    transaction_type = Column(Text, nullable=False)  # "stock" | "dispense" | "adjust"
    quantity = Column(Numeric, nullable=False)
    work_order_number = Column(Text, nullable=True)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    item = relationship("Item", back_populates="transactions")
    user = relationship("User", back_populates="transactions")


class AuthSession(Base):
    """A server-side login session, keyed by an opaque random token
    that lives in an HttpOnly cookie on the client.

    State is held here (not in a signed cookie) so the server is the
    sole authority on validity: logout deletes the row, and a session
    that has not been touched within the idle window
    (`app.services.auth.SESSION_IDLE_TIMEOUT`) is treated as expired
    and removed. `last_active_at` is bumped on every authenticated
    request, giving a sliding-window timeout. The FK is ON DELETE
    CASCADE so deleting a user also drops all of their sessions.
    """

    __tablename__ = "sessions"

    token = Column(Text, primary_key=True)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_active_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="sessions")