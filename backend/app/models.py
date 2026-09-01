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
from app.domain.low_stock import DEFAULT_LOW_STOCK_THRESHOLD


class User(Base):
    """A person who can log in and act on the system. `username` is the
    login identifier and must be unique; `first_name` / `last_name` are the
    human-facing identity used everywhere outside login and account management;
    `password_hash` stores a salted scrypt digest (see `app.services.auth`);
    `role` is one of the four values in `app.domain.roles` and drives
    authorization.

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
    # Legacy accounts may be NULL until a user/manager fills their name on the
    # Users page; POST /users requires both names through UserCreate.
    first_name = Column(Text, nullable=True)
    last_name = Column(Text, nullable=True)
    password_hash = Column(Text, nullable=False)
    role = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    archived_at = Column(DateTime(timezone=True), nullable=True)

    transactions = relationship("Transaction", back_populates="user")
    sessions = relationship("AuthSession", back_populates="user", cascade="all, delete-orphan")
    push_subscriptions = relationship(
        "PushSubscription", back_populates="user", cascade="all, delete-orphan"
    )
    netfacilities_cloud_session = relationship(
        "NetFacilitiesCloudSession",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )

    @property
    def full_name(self) -> str:
        """Trimmed display identity without exposing the login username."""
        full_name = " ".join(
            part.strip() for part in (self.first_name, self.last_name) if part and part.strip()
        )
        return full_name or "Name unavailable"


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
    # The count at or below which this item raises a low-stock push and
    # appears on the Low Stock page. Whole numbers >= 1 (see
    # `domain.low_stock`); every item has one, so there is no "unmonitored"
    # state to handle at the eight stock-mutation sites.
    low_stock_threshold = Column(
        Integer, nullable=False, default=DEFAULT_LOW_STOCK_THRESHOLD, server_default="6"
    )
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
    # Billing override (TechFM OA and above only): how many of the row's units should
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
    """A server-side login session. The client holds an opaque random
    token in an HttpOnly cookie; this table stores only its **SHA-256
    hash**, never the token itself.

    Hashing at rest is the point of the table's shape: the raw token is
    a bearer credential, so storing it verbatim would make any read of
    this table -- a backup, a read replica, a dashboard query, a
    read-only injection -- a full account takeover for every logged-in
    user. Storing the digest makes such a read useless, because the hash
    cannot be replayed as a cookie. See `app.services.auth._hash_token`,
    which is the only place the conversion happens.

    SHA-256 rather than scrypt is deliberate. Slow KDFs exist because
    passwords are low-entropy and guessable; this token is 256 bits from
    a CSPRNG, so there is nothing to brute-force, and a slow hash would
    add cost to *every* authenticated request.

    State is held here (not in a signed cookie) so the server is the
    sole authority on validity: logout deletes the row, and
    `services.users` deletes a user's rows on archive, role change, and
    password reset.

    `expires_at` is a hard absolute cap and is **never NULL** -- every
    session expires (`app.services.auth.create_session`). "Remember this
    device" no longer changes the server-side lifetime; it only decides
    whether the *cookie* is persistent or dies with the browser. A row
    past its cap is deleted on the first request that presents it, and
    `sweep_expired_sessions` clears the rest.

    The FK is ON DELETE CASCADE so deleting a user also drops all of
    their sessions.
    """

    __tablename__ = "sessions"

    # Lowercase hex SHA-256 of the cookie token (64 chars). The raw
    # token exists only in the client's cookie and in the local variable
    # that `create_session` returns.
    token_hash = Column(Text, primary_key=True)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    # Absolute expiry; NOT NULL so no session can outlive its cap.
    expires_at = Column(DateTime(timezone=True), nullable=False)

    user = relationship("User", back_populates="sessions")

    # Supports the expired-row sweep, which is the only query that
    # filters on this column alone.
    __table_args__ = (Index("ix_sessions_expires_at", "expires_at"),)


class LoginAttempt(Base):
    """Failed-login counter backing the login throttle
    (`app.services.login_throttle`).

    One generic keyed counter serves both throttle layers rather than a
    table each:

    - `scope="user_ip"`, `key="<normalized username>|<ip>"` -- the layer
      that actually stops credential brute-forcing.
    - `scope="ip"`, `key="<ip>"` -- an optional wider net for username
      enumeration, off unless `LOGIN_THROTTLE_PER_IP` is enabled.

    The key deliberately uses the **submitted** username string, not a
    resolved user id: `services.auth.authenticate` makes "no such user"
    and "wrong password" indistinguishable on purpose, and keying on a
    resolved id would leak account existence back out through throttle
    behavior.

    Rows are transient -- deleted on a successful login and swept after
    `domain.login_throttle.ATTEMPT_TTL` -- so this is not an audit trail.
    """

    __tablename__ = "login_attempts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope = Column(Text, nullable=False)
    key = Column(Text, nullable=False)
    failure_count = Column(Integer, nullable=False, default=0)
    first_failed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_failed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    # NULL means "counting failures but not currently locked".
    locked_until = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("scope", "key", name="uq_login_attempts_scope_key"),
        Index("ix_login_attempts_last_failed_at", "last_failed_at"),
    )


class WorkOrder(Base):
    """A work order -- the first-class unit of field work.

    Identity is the work-order `number`, unique **case-insensitively + trimmed**
    via the functional index `uq_work_orders_number_ci` (`lower(btrim(number))`);
    the surrogate `id` keeps FKs uniform with the rest of the schema. Everything
    else -- community / building / unit, description, status, entry mode,
    assignee -- is an attribute, so this single row is the source of truth that
    scan-and-go, Mass Stage, the Work Orders page, and History all reference.

    Rows are **import-only**: the work-order CSV import
    (`services.work_orders.get_or_create_work_order`) is the only thing that
    creates one. Everywhere else a number is used, it must already name a row
    (`services.work_orders.resolve_work_order`).

    Live `status` follows `created -> assigned -> in_progress ->
    ready_to_complete -> completed -> review`, with `on_hold` as the pause
    state: technician assignment derives Assigned and first material/labor
    activity derives In-Progress. Ready to Complete is the crew's handoff to a
    supervisor; On-Hold means nobody is on the clock, and the tracking service
    sets it when the last session stops. Closed is represented by
    `archived_at`.
    `entry_mode` (`dispense` |
    `retroactive`) is the default mode for newly logged materials: dispense moves
    stock, retroactive is a stock-neutral paper backfill.
    Worker scope comes from `work_order_technicians`; active Technician and
    Supervisor accounts may participate. `assigned_to_id` is retained as a
    primary/legacy mirror for older clients and Mass Stage, while Work Orders
    may carry any number of technician assignments. Soft delete via
    `archived_at`, mirroring `Item` / `User`; an archived
    number stays reserved, its material lines are kept, and CSV re-import ignores
    it. An explicit `restore_work_order` can bring it back. Transactions carry their own
    `work_order_number`, so archiving never hides a work order's history.
    """

    __tablename__ = "work_orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    number = Column(Text, nullable=False)
    community = Column(Text, nullable=True)
    building_number = Column(Text, nullable=True)
    unit_number = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    # Source-owned enrichment value. It is deliberately nullable and excluded
    # from the generic work-order edit/import contracts.
    priority = Column(Text, nullable=True)
    # Append-only plain-text operational log. New entries are server-formatted
    # as MM/DD/YY hh:MM AM/PM User text; pre-log free-form content and lines in
    # the earlier [TIME] [MMDDYY] [User] shape are preserved, never rewritten.
    notes = Column(Text, nullable=True)
    status = Column(Text, nullable=False, default="created", server_default="created")
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

    # --- CSV-import schema (the new default source of truth) -------------
    # These mirror the mass work-order export columns. `location` holds the raw
    # LOCATION string (deliberately unparsed -- the export format is
    # inconsistent / multi-line). `vendor_assignee` is the raw "ASSIGNED TO"
    # name (a vendor contact, NOT a system user); the import separately maps it
    # to `supervisor_id` by name. `schedule_date` is raw text (some rows carry a
    # time). All nullable: a hand-created or legacy work order simply leaves them
    # empty.
    location = Column(Text, nullable=True)
    output_to = Column(Text, nullable=True)
    vendor_assignee = Column(Text, nullable=True)
    service_type = Column(Text, nullable=True)
    schedule_date = Column(Text, nullable=True)
    # The account a work order is routed to. Set by name-match at import
    # or manually by Supervisor+; drives Supervisor visibility alongside worker
    # assignment membership.
    supervisor_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    # A pre-import (old-schema) work order: kept for search so already-priced-out
    # work orders stay findable, but its old descriptive attributes were dropped.
    legacy = Column(Boolean, nullable=False, default=False, server_default="false")
    # Provenance for the import sweep that closes work orders the latest
    # NetFacilities CSV did not list (absence upstream means closed upstream).
    # `auto_closed_batch_id` groups one import's victims; `auto_closed_at` equals
    # this row's `archived_at` at the moment of the sweep and is what the undo
    # window is measured from. Set together by the sweep, cleared together by
    # every path that un-archives the row -- so a live row never carries either,
    # and a restored one stops looking auto-closed. Nothing reads them to decide
    # visibility: `archived_at` is still the only source of truth for closed/live.
    auto_closed_batch_id = Column(UUID(as_uuid=True), nullable=True)
    auto_closed_at = Column(DateTime(timezone=True), nullable=True)

    items = relationship(
        "WorkOrderItem",
        back_populates="work_order",
        cascade="all, delete-orphan",
    )
    technician_assignments = relationship(
        "WorkOrderTechnician",
        back_populates="work_order",
        cascade="all, delete-orphan",
        order_by="WorkOrderTechnician.created_at",
    )
    technicians = relationship(
        "User",
        secondary="work_order_technicians",
        primaryjoin="WorkOrder.id == WorkOrderTechnician.work_order_id",
        secondaryjoin="User.id == WorkOrderTechnician.technician_id",
        viewonly=True,
        order_by="User.first_name, User.last_name, User.id",
    )
    labor_entries = relationship(
        "WorkOrderLabor",
        back_populates="work_order",
        cascade="all, delete-orphan",
        order_by="WorkOrderLabor.created_at",
    )
    labor_sessions = relationship(
        "WorkOrderLaborSession",
        back_populates="work_order",
        cascade="all, delete-orphan",
        order_by="WorkOrderLaborSession.started_at",
    )
    # Viewonly (no back-populates on User): surface account + display identity.
    creator = relationship("User", foreign_keys=[created_by_id], viewonly=True)
    assignee = relationship("User", foreign_keys=[assigned_to_id], viewonly=True)
    supervisor = relationship("User", foreign_keys=[supervisor_id], viewonly=True)

    __table_args__ = (
        # Case-insensitive + trimmed uniqueness: "WO-1", " wo-1 " collide.
        Index("uq_work_orders_number_ci", text("lower(btrim(number))"), unique=True),
        Index("ix_work_orders_assigned_to_id", "assigned_to_id"),
        Index("ix_work_orders_created_by_id", "created_by_id"),
        Index("ix_work_orders_supervisor_id", "supervisor_id"),
        Index("ix_work_orders_status", "status"),
    )


class WorkOrderTechnician(Base):
    """One technician-role assignment on a work order.

    The join table is the source of truth for Work Orders visibility and permits
    multiple workers on a job. Eligible accounts are active Technicians and
    Supervisors. `WorkOrder.assigned_to_id` remains a compatibility mirror of
    the first selected worker while older callers migrate to the plural API.
    """

    __tablename__ = "work_order_technicians"

    work_order_id = Column(
        UUID(as_uuid=True),
        ForeignKey("work_orders.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    technician_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True, nullable=False
    )
    assigned_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    work_order = relationship("WorkOrder", back_populates="technician_assignments")
    technician = relationship("User", foreign_keys=[technician_id], viewonly=True)

    __table_args__ = (
        Index("ix_work_order_technicians_technician_id", "technician_id"),
    )


class WorkOrderLabor(Base):
    """An actual labor-duration entry attributed to an assigned technician.

    Durations are stored as whole minutes so billing can deterministically round
    the work order's combined labor upward to a 30-minute increment. The rate is
    a domain constant rather than copied onto each row; IMP-006 fixes it at
    $62.50/hour. Labor survives later technician unassignment as historical work.
    """

    __tablename__ = "work_order_labor"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    work_order_id = Column(
        UUID(as_uuid=True),
        ForeignKey("work_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    technician_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    minutes = Column(Integer, nullable=False)
    recorded_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    work_order = relationship("WorkOrder", back_populates="labor_entries")
    technician = relationship("User", foreign_keys=[technician_id], viewonly=True)
    recorded_by = relationship("User", foreign_keys=[recorded_by_id], viewonly=True)
    # The session that produced this row, or None for a hand-entered
    # correction and for every row predating tracked time. Read by the detail
    # response to show the entry's start/stop window; the FK lives on the
    # session side, so this is the reverse of `WorkOrderLaborSession.labor`.
    session = relationship(
        "WorkOrderLaborSession",
        back_populates="labor",
        uselist=False,
        viewonly=True,
    )

    __table_args__ = (
        Index("ix_work_order_labor_work_order_id", "work_order_id"),
        Index("ix_work_order_labor_technician_id", "technician_id"),
    )


class WorkOrderLaborSession(Base):
    """One tracked start/stop of work by one person on one work order.

    The authoritative record of *when* labor happened, as opposed to
    `WorkOrderLabor`, which records how long it lasted and is what billing
    reads. Stopping a session produces a labor row and links it through
    `labor_id`; a **running** session (`ended_at IS NULL`) has produced nothing
    and therefore contributes nothing to any total. That is deliberate and is
    what keeps tracked time additive: `labor_minutes`, the receipt, and the CSV
    export are exactly as correct for a job in progress as they were before.

    Sessions were given their own table rather than nullable timestamps on
    `work_order_labor` because a running session has no duration, which would
    force `minutes` to become nullable and make every consumer of that column
    learn to skip NULLs.

    The partial unique index enforces one running session per person -- across
    every work order, not per row -- in the database rather than in a service
    check that races. Starting a session while another is running closes the
    other one first (`services.work_orders.start_labor_session`).
    """

    __tablename__ = "work_order_labor_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    work_order_id = Column(
        UUID(as_uuid=True),
        ForeignKey("work_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Who was working, which is not necessarily who recorded it: a supervisor
    # stopping a forgotten clock does not take the hours.
    technician_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    # NULL means the clock is still running.
    ended_at = Column(DateTime(timezone=True), nullable=True)
    labor_id = Column(
        UUID(as_uuid=True),
        ForeignKey("work_order_labor.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Set when the 12-hour cap closed this session rather than a person. Flags
    # the produced labor row as an estimate for a supervisor to correct; the
    # row is never blocked from billing on account of it.
    auto_closed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    work_order = relationship("WorkOrder", back_populates="labor_sessions")
    technician = relationship("User", foreign_keys=[technician_id], viewonly=True)
    labor = relationship(
        "WorkOrderLabor",
        foreign_keys=[labor_id],
        back_populates="session",
    )

    __table_args__ = (
        Index("ix_work_order_labor_sessions_work_order_id", "work_order_id"),
        Index(
            "uq_work_order_labor_sessions_running_technician",
            "technician_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
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
    # Line-level billing override (the line is the billing unit for work-order
    # materials). NULL = bill the full `quantity`; 0 = recorded but not charged;
    # a value <= quantity bills a partial count. Never touches stock.
    billable_quantity = Column(Numeric, nullable=True)
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


class UserRequest(Base):
    """An operational exception raised by a user for later review.

    Initial request types are ``inventory_recount`` (a dispense exceeds the
    recorded on-hand quantity) and ``missing_item_price`` (an unpriced item is
    attached to a work order and needs both price and product link). The general
    request/status/message/details shape lets later real-world vs. in-app
    disparities use the same review queue without another table.

    Requests are durable audit records. Resolving one stamps who/when rather
    than deleting it; voiding the source transaction resolves its request with
    a system note because the reported discrepancy was removed.
    """

    __tablename__ = "user_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_type = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="open", server_default="open")
    message = Column(Text, nullable=False)
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id"), nullable=True)
    transaction_id = Column(
        UUID(as_uuid=True), ForeignKey("transactions.id"), nullable=True, unique=True
    )
    work_order_id = Column(
        UUID(as_uuid=True), ForeignKey("work_orders.id"), nullable=True
    )
    created_by_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    details = Column(JSONB, nullable=False, default=dict, server_default="{}")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolution_note = Column(Text, nullable=True)

    item = relationship("Item", foreign_keys=[item_id], viewonly=True)
    transaction = relationship("Transaction", foreign_keys=[transaction_id], viewonly=True)
    work_order = relationship("WorkOrder", foreign_keys=[work_order_id], viewonly=True)
    creator = relationship("User", foreign_keys=[created_by_id], viewonly=True)
    resolver = relationship("User", foreign_keys=[resolved_by_id], viewonly=True)

    __table_args__ = (
        Index("ix_user_requests_status", "status"),
        Index("ix_user_requests_request_type", "request_type"),
        Index("ix_user_requests_item_id", "item_id"),
    )


class Tool(Base):
    """A tracked tool -- parallel to `Item` but deliberately smaller: no
    `location`, `price`, or `product_link` (tools are not billed or shelved
    like consumable materials). `quantity` is the on-hand/available count,
    identical semantics to `Item.quantity`: a checkout decrements it, a
    return increments it, via the same `domain.quantity.apply_delta`.

    A tool row may represent one specific serialized unit (`quantity`
    effectively 1, its own barcode) or an unserialized bulk batch
    (`quantity` > 1, one shared barcode, fungible units) -- both are valid;
    serializing a batch later is just data entry (shrink the bulk row,
    create individual rows), not a schema concept.

    Soft delete mirrors `Item.archived_at`: `archived_at` NULL means live;
    a timestamp hides the tool from `list_tools` / barcode lookup but keeps
    the row so `tool_transactions` history still resolves it. Unlike
    `Item.barcode` (a plain global UNIQUE, with a retire/free dance for
    archived-holder reuse), `barcode` uniqueness here is a **partial**
    unique index scoped to live rows (`archived_at IS NULL`) -- an archived
    tool's barcode is simply free to reuse with no confirmation, matching
    `services.tools._ensure_barcode_free`'s live-only check."""

    __tablename__ = "tools"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    barcode = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    quantity = Column(Numeric, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    archived_at = Column(DateTime(timezone=True), nullable=True)

    checkouts = relationship("ToolTransaction", back_populates="tool")

    __table_args__ = (
        Index(
            "uq_tools_barcode_live",
            "barcode",
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
    )


class ToolTransaction(Base):
    """Append-only audit row for a tool checkout or return -- the
    custody-tracking analogue of `Transaction`, kept as a separate table
    because the vocabulary (`checkout`/`return`) and the mandatory custody
    field have no equivalent on the billing/work-order-coupled `transactions`
    table.

    Carries two distinct user references: `assigned_to_id` is who has/had
    custody of the tool (required for `checkout`/`return` -- a tool must be
    assigned to a user before a checkout is recorded; NULL for `adjust`,
    which has no custody holder), and `performed_by_id` is who was logged
    in and processed the action (mirrors `Transaction.user_id`).
    `assigned_to_id` and `performed_by_id` may differ -- a TechFM OA or Admin can check
    a tool out to a technician.

    "Who currently has this tool" is derived, not stored: for a given
    `(tool_id, assigned_to_id)` pair, outstanding = Sum(checkout.quantity) -
    Sum(return.quantity) (see `services.tools.tool_custody`), filtered to
    `transaction_type IN ('checkout', 'return')` so an `adjust` row never
    contributes to a custody balance.

    `transaction_type = "adjust"` is the "Correct Count" action (mirrors
    `Transaction`'s `adjust`): `quantity` is the *signed delta* applied to
    `Tool.quantity` (not a positive count like `checkout`/`return`), and
    `reason` is required for it -- both mirror `Transaction.quantity` /
    `Transaction.reason`.

    `work_order_id` / `work_order_number` are an optional linkage, never
    required -- mirrors `Transaction.work_order_id` /
    `Transaction.work_order_number` but nullable with no find-or-create
    behavior attached."""

    __tablename__ = "tool_transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tool_id = Column(UUID(as_uuid=True), ForeignKey("tools.id"), nullable=False)
    transaction_type = Column(Text, nullable=False)  # "checkout" | "return" | "adjust"
    quantity = Column(Numeric, nullable=False)
    assigned_to_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    performed_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    work_order_id = Column(
        UUID(as_uuid=True), ForeignKey("work_orders.id"), nullable=True, index=True
    )
    work_order_number = Column(Text, nullable=True)
    reason = Column(Text, nullable=True)  # required (schema-level) for "adjust" only
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    tool = relationship("Tool", back_populates="checkouts")
    # Viewonly (no back-populates on User): surface account + display identity.
    assigned_to = relationship("User", foreign_keys=[assigned_to_id], viewonly=True)
    performed_by = relationship("User", foreign_keys=[performed_by_id], viewonly=True)


class PushSubscription(Base):
    """One Web Push subscription: a single browser profile on a single
    device that has opted in to notifications.

    `endpoint` is the primary key rather than a surrogate id, and that is
    the load-bearing decision here. A subscription belongs to a *browser
    profile*, not to an account -- the browser mints one endpoint and
    hands that same endpoint back to whoever is logged in. Keying on it
    means re-subscribing after a different user logs in on a shared
    device **reassigns** the row instead of adding a second one, so the
    device stops receiving the previous user's notifications. Keying on
    `user_id` would leave both rows alive and deliver to the wrong
    person, which on a shared crew phone is a privacy failure rather
    than a tidiness one.

    `p256dh` and `auth` are browser-generated payload-encryption material
    (RFC 8291). The push service relays ciphertext it cannot read; only
    this device can decrypt. They are per-device secrets and must not be
    logged.

    The FK is ON DELETE CASCADE, matching `sessions`: a deleted account
    stops receiving as well as stops authenticating.
    """

    __tablename__ = "push_subscriptions"

    # The URL the push service handed the browser. Always HTTPS, always
    # on one of the hosts in `domain.push.ALLOWED_PUSH_HOSTS`, which
    # `services.push` re-checks before every send -- the column itself
    # carries no constraint, so the check cannot be skipped by writing
    # the row some other way.
    endpoint = Column(Text, primary_key=True)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    p256dh = Column(Text, nullable=False)
    auth = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="push_subscriptions")

    # The fan-out selects by recipient; the endpoint primary key does not
    # serve that query.
    __table_args__ = (Index("ix_push_subscriptions_user_id", "user_id"),)


class NetFacilitiesCloudSession(Base):
    """One user's captured NetFacilities cloud-auth session (spec D8, D9).

    Per-user, not shared (spec D2): `user_id` is unique, so each authorized
    user has at most one captured session. `storage_state` is Fernet
    ciphertext (`app.services.netfacilities_cloud_crypto`), never the
    plaintext Playwright snapshot -- decrypt it only at the moment a
    reconnect needs it, and never return it or `steel_profile_id` in any
    API response. `steel_profile_id` is populated only if the D6
    Profiles-API fallback is in use; both columns exist from day one so
    that fallback needs no migration, only a code path change.

    `expires_at` is set only once an enrichment attempt actually reports
    `authentication_required` against this session, mirroring how the
    existing saved-state expiry is detected today
    (`routers/netfacilities.py::_saved_state_refreshed_after`) rather than
    guessed from a TTL.
    """

    __tablename__ = "netfacilities_cloud_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    storage_state = Column(Text, nullable=False)
    steel_profile_id = Column(Text, nullable=True)
    signed_in_at = Column(DateTime(timezone=True), nullable=False)
    last_download_filename = Column(Text, nullable=True)
    last_download_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="netfacilities_cloud_session")
    __table_args__ = (Index("ix_push_subscriptions_user_id", "user_id"),)
