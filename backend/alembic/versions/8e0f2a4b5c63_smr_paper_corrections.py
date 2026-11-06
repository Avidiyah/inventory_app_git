"""smr paper corrections

Revision ID: 8e0f2a4b5c63
Revises: 7d9e1f3a4b52
Create Date: 2026-11-06 09:00:00.000000

SMR27 paper-correction import (spec docs/superpowers/specs/2026-11-04-smr-paper-import-design.md):
vendor workers, paper readings, labor lines, their append-only edit history and the
versioned correction blocks. Five new tables, no backfill, existing `smr_*` columns untouched.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "8e0f2a4b5c63"
down_revision: Union[str, Sequence[str], None] = "7d9e1f3a4b52"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_WEEK1_PLACEMENT = "Week 1 placement (crew sheets, Supplement)"


def _uuid():
    return postgresql.UUID(as_uuid=True)


def _stamp(name: str, nullable: bool = False):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "smr_workers",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("vendor", sa.Text(), nullable=False),
        sa.Column("user_id", _uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("aliases", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default="false"),
        _stamp("created_at"),
        _stamp("archived_at", nullable=True),
        sa.UniqueConstraint("display_name", "vendor", name="uq_smr_workers_display_name_vendor"),
    )

    op.create_table(
        "smr_paper_readings",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("work_order_id", _uuid(), sa.ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("printing_no", sa.Integer(), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=True),
        sa.Column("hours_as_read", sa.Numeric(6, 1), nullable=True),
        sa.Column("raw_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("reviewer", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        _stamp("created_at"),
        sa.Column("created_by_id", _uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("work_order_id", "printing_no", name="uq_smr_paper_readings_order_printing"),
    )
    op.create_index("ix_smr_paper_readings_work_order_id", "smr_paper_readings", ["work_order_id"])

    op.create_table(
        "smr_labor_lines",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("work_order_id", _uuid(), sa.ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reading_id", _uuid(), sa.ForeignKey("smr_paper_readings.id", ondelete="SET NULL"), nullable=True),
        sa.Column("import_key", sa.Text(), nullable=True, unique=True),
        sa.Column("work_date", sa.Date(), nullable=True),
        sa.Column("date_basis", sa.Text(), nullable=False, server_default="paper"),
        sa.Column("week", sa.Integer(), nullable=True),
        sa.Column("vendor", sa.Text(), nullable=False),
        sa.Column("worker_id", _uuid(), sa.ForeignKey("smr_workers.id"), nullable=True),
        sa.Column("alias_on_paper", sa.Text(), nullable=True),
        sa.Column("headcount", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("hours_each", sa.Numeric(6, 1), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False, server_default="field"),
        sa.Column("reason_code", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("exclusion_ground", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        _stamp("created_at"),
        sa.Column("created_by_id", _uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        _stamp("updated_at"),
        sa.Column("updated_by_id", _uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.CheckConstraint("headcount >= 1", name="ck_smr_labor_lines_headcount"),
        sa.CheckConstraint("mod(hours_each * 2, 1) = 0", name="ck_smr_labor_lines_half_hours"),
        sa.CheckConstraint("status in ('charged', 'excluded')", name="ck_smr_labor_lines_status"),
        sa.CheckConstraint(
            f"status <> 'charged' OR work_date IS NOT NULL OR date_basis = '{_WEEK1_PLACEMENT}'",
            name="ck_smr_labor_lines_charged_dated",
        ),
        sa.CheckConstraint(
            "status <> 'excluded' OR exclusion_ground IS NOT NULL",
            name="ck_smr_labor_lines_excluded_ground",
        ),
    )
    op.create_index("ix_smr_labor_lines_work_order_id", "smr_labor_lines", ["work_order_id"])
    op.create_index("ix_smr_labor_lines_worker_date", "smr_labor_lines", ["worker_id", "work_date"])
    op.create_index("ix_smr_labor_lines_work_date", "smr_labor_lines", ["work_date"])

    op.create_table(
        "smr_line_edits",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("line_id", _uuid(), sa.ForeignKey("smr_labor_lines.id", ondelete="CASCADE"), nullable=False),
        sa.Column("edited_by_id", _uuid(), sa.ForeignKey("users.id"), nullable=False),
        _stamp("edited_at"),
        sa.Column("field", sa.Text(), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
    )
    op.create_index("ix_smr_line_edits_line_id", "smr_line_edits", ["line_id"])

    op.create_table(
        "smr_correction_blocks",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("work_order_id", _uuid(), sa.ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        _stamp("generated_at"),
        sa.Column("generated_by_id", _uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        _stamp("pasted_at", nullable=True),
        sa.Column("pasted_by_id", _uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("lines_digest", sa.Text(), nullable=False),
        sa.UniqueConstraint("work_order_id", "version", name="uq_smr_correction_blocks_order_version"),
    )
    op.create_index("ix_smr_correction_blocks_work_order_id", "smr_correction_blocks", ["work_order_id"])


def downgrade() -> None:
    op.drop_table("smr_correction_blocks")
    op.drop_table("smr_line_edits")
    op.drop_table("smr_labor_lines")
    op.drop_table("smr_paper_readings")
    op.drop_table("smr_workers")
