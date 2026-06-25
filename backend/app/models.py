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
    Boolean,
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
    values in `app.domain.roles` and drives authorization.

    Soft delete: a user is archived rather than hard-deleted, so the
    transaction history -- which resolves the acting user's name via a
    live join (`services.history.list_history`) -- stays intact after a
    departure. `archived_at` is NULL for an active user; a timestamp means
    the user is hidden from the active Saved Users list and can no longer
    authenticate (`services.auth.authenticate` and `get_active_session_user`
    both reject archived users). This mirrors `Item.archived_at`."""

    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(Text, nullable=False, unique=True)
    password_hash = Column(Text, nullable=False)
    role = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    archived_at = Column(DateTime(timezone=True), nullable=True)

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
    a service pre-check (`services.items._barcode_holder`), since a single
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
    # Per-unit price snapshotted from `Item.price` when the row is written,
    # so History line values / invoice totals reflect the price at the time
    # of the transaction rather than the item's current price. Set for
    # stock / dispense (the item row is already locked when these are
    # written); left NULL for `adjust` (corrections carry no billing
    # meaning) and for every pre-snapshot row. `services.history` falls back
    # to the live `Item.price` when this is NULL.
    unit_price = Column(Numeric, nullable=True)
    # Billing override (Admin/Owner only): how many of the row's units should
    # actually be charged to the customer. NULL means "no override -- bill the
    # full `quantity`"; a value of 0 means "recorded but not charged". This is a
    # pure billing annotation: it NEVER touches `Item.quantity` (the items were
    # physically used), it only changes what the History page's price columns
    # and copy-to-clipboard export total up. Set via PATCH /transactions/{id}/billing.
    billable_quantity = Column(Numeric, nullable=True)
    work_order_number = Column(Text, nullable=True)
    # FK link to the standalone work order this transaction belongs to (the
    # `work_order_number` above is kept as a denormalized snapshot for History /
    # audit stability). Nullable: legacy rows and corrections carry no work order.
    work_order_id = Column(
        UUID(as_uuid=True), ForeignKey("work_orders.id"), nullable=True, index=True
    )
    reason = Column(Text, nullable=True)
    # Whether this row actually moved `Item.quantity`. TRUE for every ordinary
    # stock/dispense/adjust. FALSE only for a *retroactive* work-order entry (a
    # paper material-sheet backfill logged on the Work Orders page in retroactive
    # mode): it is recorded so History shows "item taken" identically to a real
    # dispense, but the stock was already consumed off-app, so the row must NOT
    # decrement on-hand on create, and `void_transaction` must NOT add it back
    # on void. See `services.work_orders` and docs/current-state.md.
    affects_stock = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    voided_at = Column(DateTime(timezone=True), nullable=True)
    voided_by_id = Column(UUID(as_uuid=True), nullable=True)

    item = relationship("Item", back_populates="transactions")
    user = relationship("User", back_populates="transactions")


class AuthSession(Base):
    """A server-side login session, keyed by an opaque random token
    that lives in an HttpOnly cookie on the client.

    State is held here (not in a signed cookie) so the server is the
    sole authority on validity: logout deletes the row. `expires_at`
    encodes the lifetime policy and is set at login
    (`app.services.auth.create_session`):

    - **NULL** -- no server-side cap. Issued when the user did *not*
      check "Remember this device": the cookie is a session cookie, so
      the session ends when the browser closes (or on manual logout).
    - **a timestamp** -- a hard absolute cap (login + `REMEMBER_LIFETIME`).
      Issued for a remembered device; the matching persistent cookie
      survives a browser restart, and the session is expired-and-deleted
      on the first request after `expires_at`.

    The FK is ON DELETE CASCADE so deleting a user also drops all of
    their sessions.
    """

    __tablename__ = "sessions"

    token = Column(Text, primary_key=True)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="sessions")


class WorkOrder(Base):
    """A work order -- the first-class unit of field work.

    Identity is the work-order `number`, unique **case-insensitively + trimmed**
    via the functional index `uq_work_orders_number_ci` (`lower(btrim(number))`);
    the surrogate `id` keeps FKs uniform with the rest of the schema. Everything
    else -- community / building / unit, description, status, entry mode,
    assignee -- is an attribute, so this single row is the source of truth that
    scan-and-go, Mass Stage, the Work Orders page, and History all reference (a
    work-order number used anywhere find-or-creates this row; see
    `services.work_orders.get_or_create_work_order`).

    `status` is two-state (`in_progress -> completed`, reopenable). `entry_mode`
    (`dispense` | `retroactive`) is the default mode for newly logged materials:
    dispense moves stock, retroactive is a stock-neutral paper backfill.
    `assigned_to_id` (must be a technician) and `created_by_id` drive visibility
    scope. Soft delete via `archived_at`, mirroring `Item` / `User`; an archived
    number stays reserved and is restored if referenced again.
    """

    __tablename__ = "work_orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    number = Column(Text, nullable=False)
    community = Column(Text, nullable=True)
    building_number = Column(Text, nullable=True)
    unit_number = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    status = Column(Text, nullable=False, default="in_progress", server_default="in_progress")
    entry_mode = Column(Text, nullable=False, default="dispense", server_default="dispense")
    assigned_to_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)

    items = relationship(
        "WorkOrderItem",
        back_populates="work_order",
        cascade="all, delete-orphan",
    )
    # Viewonly (no back-populates on User): surface usernames in responses only.
    creator = relationship("User", foreign_keys=[created_by_id], viewonly=True)
    assignee = relationship("User", foreign_keys=[assigned_to_id], viewonly=True)

    __table_args__ = (
        # Case-insensitive + trimmed uniqueness: "WO-1", " wo-1 " collide.
        Index("uq_work_orders_number_ci", text("lower(btrim(number))"), unique=True),
        Index("ix_work_orders_assigned_to_id", "assigned_to_id"),
        Index("ix_work_orders_created_by_id", "created_by_id"),
        Index("ix_work_orders_status", "status"),
    )


class MassStage(Base):
    """A truck-staging plan for one building.

    Supervisors batch-plan materials for an entire building: a stage groups the
    building's work orders (via `MassStageWorkOrder` slots), each carrying the
    items planned for it. Planning is pure estimation -- no stock moves -- until
    the stage is loaded onto the truck, when each load writes ordinary `dispense`
    transactions (one per slot allocation) carrying that slot's work order.

    A stage no longer *owns* work orders: a `WorkOrder` is a standalone entity,
    and a slot just references one. `community` / `building_name` (the building
    *number*) are the truck-plan's grouping key, and adding a work order enforces
    that its community/building match the stage.

    `status` walks `planning -> loading -> completed`. Editing slots / items is
    allowed only in `planning`; loading / returning only in `loading`;
    `completed` is read-only. One active (non-completed) stage per
    `(community, building_name)` via the partial unique index.
    """

    __tablename__ = "mass_stages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    community = Column(Text, nullable=False, server_default="")
    building_name = Column(Text, nullable=False)  # building number
    status = Column(Text, nullable=False, default="planning", server_default="planning")
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)

    work_order_slots = relationship(
        "MassStageWorkOrder",
        back_populates="stage",
        cascade="all, delete-orphan",
        order_by="MassStageWorkOrder.sort_order",
    )

    __table_args__ = (
        Index(
            "uq_mass_stages_active_community_building",
            "community",
            "building_name",
            unique=True,
            postgresql_where=text("status <> 'completed'"),
        ),
    )


class MassStageWorkOrder(Base):
    """A work order's slot in a building's truck-staging plan.

    A Mass Stage groups the work orders for one building; this thin join row
    places a `WorkOrder` in a stage with a `sort_order` that drives the truck
    load/return allocation (`app.domain.mass_staging.allocate_load`): a merged
    item's loaded quantity fills slots in `sort_order`, overflow on the last.

    The work order owns its number / location / status / assignee -- the slot
    only records membership + order, so the same work order's identity is shared
    with the Work Orders page and History. `stage_id` is `ON DELETE CASCADE`
    (the slot is owned by the plan); `work_order_id` is a plain FK (the work
    order is independent and outlives the plan). `UNIQUE(stage_id, work_order_id)`
    keeps a work order in a stage at most once.
    """

    __tablename__ = "mass_stage_work_orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stage_id = Column(
        UUID(as_uuid=True),
        ForeignKey("mass_stages.id", ondelete="CASCADE"),
        nullable=False,
    )
    work_order_id = Column(
        UUID(as_uuid=True), ForeignKey("work_orders.id"), nullable=False
    )
    sort_order = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    stage = relationship("MassStage", back_populates="work_order_slots")
    work_order = relationship("WorkOrder")
    items = relationship(
        "MassStageItem",
        back_populates="slot",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "stage_id", "work_order_id", name="uq_mass_stage_work_orders_stage_wo"
        ),
    )


class MassStageItem(Base):
    """An item planned for a work-order slot, plus what was loaded / returned.

    `planned_quantity` is the estimate the supervisor enters while planning
    (not a transaction). `loaded_quantity` accrues as the merged item is
    staged onto the truck (each load writes real `dispense` rows and bumps
    this); it may exceed planned (box-of-4 packaging), and the per-item
    overflow is derived as `Sigma loaded - Sigma planned`. `returned_quantity`
    accrues from the "unused materials" step, which adds stock back WITHOUT a
    ledger row (a deliberate, isolated exception documented in
    `docs/current-state.md`); net consumed is `Sigma loaded - Sigma returned`.

    These are the truck-plan ESTIMATES, deliberately separate from the actuals
    a worker logs on the Work Orders page (`WorkOrderItem`). `UNIQUE(
    stage_work_order_id, item_id)` keeps one row per item per slot. The
    `stage_work_order_id` FK is `ON DELETE CASCADE` (owned plan data); `item_id`
    is plain (items are soft-deleted).
    """

    __tablename__ = "mass_stage_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stage_work_order_id = Column(
        UUID(as_uuid=True),
        ForeignKey("mass_stage_work_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id"), nullable=False)
    planned_quantity = Column(Numeric, nullable=False)
    loaded_quantity = Column(Numeric, nullable=False, default=0, server_default="0")
    returned_quantity = Column(Numeric, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    slot = relationship("MassStageWorkOrder", back_populates="items")
    item = relationship("Item")

    __table_args__ = (
        UniqueConstraint(
            "stage_work_order_id", "item_id", name="uq_mass_stage_items_slot_item"
        ),
    )


class WorkOrderItem(Base):
    """A material logged against a work order (the editable "actually used" list).

    Deliberately separate from `MassStageItem` (truck-plan estimate): this is the
    field/technician surface. One row per item per work order
    (`UNIQUE(work_order_id, item_id)`); re-adding an item updates its row.

    Each row links to the `Transaction` it produced (`transaction_id`) so that
    History shows the entry. The work order's `entry_mode` at logging time is
    snapshotted in `mode`:

    - `dispense`   -- the linked transaction moved stock (`affects_stock=True`);
      editing this row's quantity auto-corrects stock by the delta, and deleting
      it reverses the stock and voids the transaction.
    - `retroactive` -- the linked transaction is stock-neutral
      (`affects_stock=False`): it appears in History identically to a dispense
      but never moved on-hand, so edits/deletes touch no stock.

    The `work_order_id` FK is `ON DELETE CASCADE` (owned data); `item_id` is plain
    (items are soft-deleted). `transaction_id` is a plain nullable FK -- the
    transaction is the audit record and outlives an edit.
    """

    __tablename__ = "work_order_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    work_order_id = Column(
        UUID(as_uuid=True),
        ForeignKey("work_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id"), nullable=False)
    quantity = Column(Numeric, nullable=False)
    mode = Column(Text, nullable=False)  # 'dispense' | 'retroactive'
    transaction_id = Column(
        UUID(as_uuid=True), ForeignKey("transactions.id"), nullable=True
    )
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    work_order = relationship("WorkOrder", back_populates="items")
    item = relationship("Item")

    __table_args__ = (
        UniqueConstraint(
            "work_order_id", "item_id", name="uq_work_order_items_wo_item"
        ),
    )
