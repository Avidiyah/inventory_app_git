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
from sqlalchemy import (
    Column,
    Text,
    Numeric,
    Integer,
    ForeignKey,
    DateTime,
    UniqueConstraint,
    Index,
    text,
)
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
    `app.domain.notes_validation`.

    Soft delete: items are archived rather than hard-deleted, so the
    transaction history -- which reads an item's name/barcode/price via
    a live join (`services.history.list_history`) -- stays intact after
    a "delete". `archived_at` is NULL for live items; a timestamp means
    the item is hidden from `list_items` and barcode lookups but its row
    (and therefore its history) is retained. This mirrors the
    transaction-void pattern on `Transaction.voided_at`.

    Multiple barcodes: `barcode` is the canonical/display code (shown in
    Find Item, History, and exports). A physical item can also carry
    *additional* package codes, held in the `item_barcodes` child table
    via `alt_barcodes`. A scan resolves against the primary OR any
    alternate (`services.items.get_item_by_barcode`); every code stays
    globally unique across both columns (enforced by the child table's
    UNIQUE constraint plus a cross-table service pre-check)."""

    __tablename__ = "items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    barcode = Column(Text, nullable=False, unique=True)
    name = Column(Text, nullable=False)
    quantity = Column(Numeric, nullable=False, default=0)
    location = Column(Text, nullable=False)
    notes = Column(JSONB, nullable=False, default=dict, server_default="{}")
    price = Column(Numeric, nullable=True)
    product_link = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    archived_at = Column(DateTime(timezone=True), nullable=True)

    transactions = relationship("Transaction", back_populates="item")
    alt_barcodes = relationship(
        "ItemBarcode",
        back_populates="item",
        cascade="all, delete-orphan",
    )


class ItemBarcode(Base):
    """An *additional* barcode for an item, beyond its canonical
    `Item.barcode`. One physical item often carries several codes on its
    packaging (manufacturer code, repackaged carton code, retail label);
    each gets its own row here so a scan of any of them resolves to the
    same item.

    `code` is globally UNIQUE, which guarantees alt-vs-alt codes never
    collide across items. The remaining cross-table rule -- an alternate
    must not equal any item's *primary* `Item.barcode` -- is enforced by
    a service pre-check (`services.items._barcode_in_use`), since a single
    column UNIQUE constraint cannot span two tables.

    The FK is `ON DELETE CASCADE` (deliberately NOT the `RESTRICT` used by
    `Transaction.item_id`): alternates are owned configuration, not audit
    records, so they should disappear with the item rather than block its
    removal. Items are soft-deleted via `archived_at`, so this cascade
    only fires on a genuine row delete."""

    __tablename__ = "item_barcodes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id = Column(
        UUID(as_uuid=True),
        ForeignKey("items.id", ondelete="CASCADE"),
        nullable=False,
    )
    code = Column(Text, nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    item = relationship("Item", back_populates="alt_barcodes")


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

    Voids (soft delete): a mis-clicked transaction can be voided by a
    Supervisor or above. Voiding does NOT hard-delete the row -- it sets
    `voided_at` (and records who in `voided_by_id`) and reverses the
    row's effect on `Item.quantity`. Voided rows are retained for the
    audit trail but excluded from the history view
    (`services.history.list_history` filters `voided_at IS NULL`).
    `voided_by_id` is a plain UUID, deliberately NOT a second FK to
    `users`: a second `users` FK would force disambiguating the existing
    `user` relationship, and this is hidden audit metadata rather than a
    core audit link (the `user_id` / `item_id` RESTRICT FKs still govern
    referential integrity).
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
    voided_at = Column(DateTime(timezone=True), nullable=True)
    voided_by_id = Column(UUID(as_uuid=True), nullable=True)

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


class MassStage(Base):
    """A mass-staging plan for one building.

    Supervisors batch-plan materials for an entire building rather than a
    single work order: a stage groups several rooms (each paired with one
    work order), and each room lists the items planned for it. Planning is
    pure estimation -- no stock moves -- until the stage is loaded onto the
    truck, when each load writes ordinary `dispense` transactions (one per
    room allocation) carrying that room's work order.

    `status` walks `planning -> loading -> completed` (validated in
    `app.domain.mass_staging`; stored as Text to match `User.role` /
    `Transaction.transaction_type` rather than a DB enum). Editing rooms /
    items is allowed only in `planning`; loading / returning only in
    `loading`; `completed` is read-only and terminal.

    One-active-per-building is enforced at the database level by the partial
    unique index in `__table_args__`: at most one row per `building_name`
    whose `status` is not `completed`. `created_by_id` is a plain (nullable)
    FK to `users`, mirroring `Transaction.user_id`.
    """

    __tablename__ = "mass_stages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    building_name = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="planning", server_default="planning")
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)

    rooms = relationship(
        "MassStageRoom",
        back_populates="stage",
        cascade="all, delete-orphan",
        order_by="MassStageRoom.sort_order",
    )

    __table_args__ = (
        Index(
            "uq_mass_stages_active_building",
            "building_name",
            unique=True,
            postgresql_where=text("status <> 'completed'"),
        ),
    )


class MassStageRoom(Base):
    """A room within a mass-staging plan, paired with exactly one work order.

    Room numbers repeat across buildings, so they are distinguishable only
    within a stage (`UNIQUE(stage_id, room_number)`). `sort_order` preserves
    the order rooms were entered, which drives the load allocation rule
    (`app.domain.mass_staging.allocate_load`): a merged item's loaded
    quantity fills rooms in `sort_order`, and any overflow lands on the last
    room. The FK is `ON DELETE CASCADE` -- a stage's rooms are owned plan
    data, not audit records, so they vanish with the stage.
    """

    __tablename__ = "mass_stage_rooms"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stage_id = Column(
        UUID(as_uuid=True),
        ForeignKey("mass_stages.id", ondelete="CASCADE"),
        nullable=False,
    )
    room_number = Column(Text, nullable=False)
    work_order_number = Column(Text, nullable=False)
    sort_order = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    stage = relationship("MassStage", back_populates="rooms")
    items = relationship(
        "MassStageItem",
        back_populates="room",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("stage_id", "room_number", name="uq_mass_stage_rooms_stage_room"),
    )


class MassStageItem(Base):
    """An item planned for a room, plus what was actually loaded / returned.

    `planned_quantity` is the estimate the supervisor enters while planning
    (not a transaction). `loaded_quantity` accrues as the merged item is
    staged onto the truck (each load writes real `dispense` rows and bumps
    this); it may exceed planned (box-of-4 packaging), and the per-item
    overflow is derived as `Sigma loaded - Sigma planned`. `returned_quantity`
    accrues from the "unused materials" step, which adds stock back WITHOUT a
    ledger row (a deliberate, isolated exception -- see
    `docs/mass-staging/phase-1-design-record.md` section 6); net consumed is
    `Sigma loaded - Sigma returned`.

    `UNIQUE(room_id, item_id)` keeps one row per item per room (re-planning an
    item updates its row). The `room_id` FK is `ON DELETE CASCADE` (owned plan
    data); the `item_id` FK is plain, so a referenced item cannot be hard
    deleted -- benign, since items are soft-deleted via `Item.archived_at`.
    """

    __tablename__ = "mass_stage_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    room_id = Column(
        UUID(as_uuid=True),
        ForeignKey("mass_stage_rooms.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id"), nullable=False)
    planned_quantity = Column(Numeric, nullable=False)
    loaded_quantity = Column(Numeric, nullable=False, default=0, server_default="0")
    returned_quantity = Column(Numeric, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    room = relationship("MassStageRoom", back_populates="items")
    item = relationship("Item")

    __table_args__ = (
        UniqueConstraint("room_id", "item_id", name="uq_mass_stage_items_room_item"),
    )