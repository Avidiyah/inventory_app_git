"""SMR27 paper-correction tables (spec
docs/superpowers/specs/2026-11-04-smr-paper-import-design.md).

Split out of `models.py`, which is past 1,200 lines; `models.py` imports this
module at its foot so `from app.models import SmrLaborLine` keeps working and
Alembic's `Base.metadata` sees every table. Plain columns, not JSONB: lines
are queried by worker, date and status and edited one at a time.

The five tables: vendor workers who are not app users; one reading per
printing of the paper; the labor lines that are the unit of charge; the
append-only edit history in the `attendance_punch_edits` shape; and the
versioned correction blocks pasted into NetFacilities.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.database import Base
from app.domain.work_orders_smr_lines import PLACEMENT_BASES

_PLACEMENT_SQL = ", ".join(f"'{basis}'" for basis in PLACEMENT_BASES)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SmrWorker(Base):
    """A person who worked, named on paper, without being an app user (D3).
    `user_id` links a Belfor employee who also has an account; nobody is
    ever created as a user from here. `aliases` are the spellings the paper
    used. Admins (`is_admin`) are tracked so their names resolve but are
    never charged."""

    __tablename__ = "smr_workers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    display_name = Column(Text, nullable=False)
    vendor = Column(Text, nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    aliases = Column(JSONB, nullable=False, default=list, server_default="[]")
    is_admin = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    archived_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", foreign_keys=[user_id], viewonly=True)

    __table_args__ = (
        UniqueConstraint("display_name", "vendor", name="uq_smr_workers_display_name_vendor"),
    )


class SmrPaperReading(Base):
    """One printing of an SMR order's paper, as read: its date, the hours the
    verdict gave it and the verdict note verbatim. The prose record is never
    lost; the lines under it are the structured record."""

    __tablename__ = "smr_paper_readings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    work_order_id = Column(UUID(as_uuid=True), ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False)
    printing_no = Column(Integer, nullable=False)
    work_date = Column(Date, nullable=True)
    hours_as_read = Column(Numeric(6, 1), nullable=True)
    raw_note = Column(Text, nullable=False, default="")
    reviewer = Column(Text, nullable=True)
    # `paper_review.csv row 212, import <sha256 prefix>`, or what the editor wrote.
    source = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    work_order = relationship("WorkOrder", back_populates="smr_readings")
    lines = relationship("SmrLaborLine", back_populates="reading", order_by="SmrLaborLine.created_at")

    __table_args__ = (
        UniqueConstraint("work_order_id", "printing_no", name="uq_smr_paper_readings_order_printing"),
        Index("ix_smr_paper_readings_work_order_id", "work_order_id"),
    )


class SmrLaborLine(Base):
    """The unit of charge: on this day, this person (or this many unnamed
    people) of this vendor worked these hours on this order, for this
    reason, on this piece of paper (D5).

    `import_key` is the CSV's `line_id`, the import's idempotence key; null
    for a line added in the app. `date_basis` says where the day came from;
    the two placement bases (D13, generalised 2026-11-06) are the only ones
    allowed to charge with a blank day, and then carry their `week`. `status` is
    `charged` or `excluded`; an excluded line always names its ground, and a
    removed line is an excluded line with ground `removed` (nothing is ever
    hard-deleted). `kind` may be a comma list (`assessment, audit`), stored
    as given. `hours_each` may be negative for an explicit credit line (D7).
    """

    __tablename__ = "smr_labor_lines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    work_order_id = Column(UUID(as_uuid=True), ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False)
    reading_id = Column(UUID(as_uuid=True), ForeignKey("smr_paper_readings.id", ondelete="SET NULL"), nullable=True)
    import_key = Column(Text, nullable=True, unique=True)
    work_date = Column(Date, nullable=True)
    date_basis = Column(Text, nullable=False, default="paper", server_default="paper")
    week = Column(Integer, nullable=True)
    vendor = Column(Text, nullable=False)
    worker_id = Column(UUID(as_uuid=True), ForeignKey("smr_workers.id"), nullable=True)
    alias_on_paper = Column(Text, nullable=True)
    headcount = Column(Integer, nullable=False, default=1)
    hours_each = Column(Numeric(6, 1), nullable=False)
    kind = Column(Text, nullable=False, default="field")
    reason_code = Column(Text, nullable=False)
    status = Column(Text, nullable=False)
    exclusion_ground = Column(Text, nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    updated_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    work_order = relationship("WorkOrder", back_populates="smr_lines")
    reading = relationship("SmrPaperReading", back_populates="lines")
    worker = relationship("SmrWorker", foreign_keys=[worker_id])
    edits = relationship(
        "SmrLineEdit", back_populates="line", cascade="all, delete-orphan",
        passive_deletes=True, order_by="SmrLineEdit.edited_at",
    )

    __table_args__ = (
        CheckConstraint("headcount >= 1", name="ck_smr_labor_lines_headcount"),
        CheckConstraint("mod(hours_each * 2, 1) = 0", name="ck_smr_labor_lines_half_hours"),
        CheckConstraint("status in ('charged', 'excluded')", name="ck_smr_labor_lines_status"),
        CheckConstraint(
            f"status <> 'charged' OR work_date IS NOT NULL OR (date_basis IN ({_PLACEMENT_SQL}) AND week IS NOT NULL)",
            name="ck_smr_labor_lines_charged_dated",
        ),
        Index("ix_smr_labor_lines_work_order_id", "work_order_id"),
        Index("ix_smr_labor_lines_worker_date", "worker_id", "work_date"),
        Index("ix_smr_labor_lines_work_date", "work_date"),
    )


class SmrLineEdit(Base):
    """Append-only history of a line, the `attendance_punch_edits` shape: one
    row per field changed, values as text, in the same transaction as the
    change. `field` is `created` / `deleted` for whole-line events, with the
    line serialized as JSON in `new_value` / `old_value`. `reason` is the
    editor's words, or the import run's identifier."""

    __tablename__ = "smr_line_edits"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    line_id = Column(UUID(as_uuid=True), ForeignKey("smr_labor_lines.id", ondelete="CASCADE"), nullable=False)
    edited_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    edited_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    field = Column(Text, nullable=False)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    reason = Column(Text, nullable=True)

    line = relationship("SmrLaborLine", back_populates="edits")
    edited_by = relationship("User", foreign_keys=[edited_by_id], viewonly=True)

    __table_args__ = (Index("ix_smr_line_edits_line_id", "line_id"),)


class SmrCorrectionBlock(Base):
    """One generated version of an order's correction block (D4): the text
    verbatim, who generated it, whether and when it was pasted into
    NetFacilities, and a digest of the lines it was built from so a block
    that no longer matches the lines reads as stale. Old versions stay."""

    __tablename__ = "smr_correction_blocks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    work_order_id = Column(UUID(as_uuid=True), ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    generated_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    generated_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    pasted_at = Column(DateTime(timezone=True), nullable=True)
    pasted_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    lines_digest = Column(Text, nullable=False)

    work_order = relationship("WorkOrder", back_populates="smr_blocks")
    generated_by = relationship("User", foreign_keys=[generated_by_id], viewonly=True)
    pasted_by = relationship("User", foreign_keys=[pasted_by_id], viewonly=True)

    __table_args__ = (
        UniqueConstraint("work_order_id", "version", name="uq_smr_correction_blocks_order_version"),
        Index("ix_smr_correction_blocks_work_order_id", "work_order_id"),
    )
