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
    """Operator who recorded a transaction. Username is the only
    identifier (no auth yet) and must be unique."""

    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(Text, nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    transactions = relationship("Transaction", back_populates="user")


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
    """Append-only audit row for a stock or dispense event.

    `user_id` is nullable -- anonymous transactions are allowed.
    The FK on `user_id` is RESTRICT (configured at the database
    level via Alembic), which is why deleting a referenced user
    raises `UserHasTransactionsError`.
    """

    __tablename__ = "transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    transaction_type = Column(Text, nullable=False)  # "stock" or "dispense"
    quantity = Column(Numeric, nullable=False)
    work_order_number = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    item = relationship("Item", back_populates="transactions")
    user = relationship("User", back_populates="transactions")