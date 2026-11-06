"""smr vendor invoices

Revision ID: b3c5d7e9f1a2
Revises: 3e5a7c9b1d2f
Create Date: 2026-11-06 16:00:00.000000

SMR27 weekly hours chart (spec docs/superpowers/specs/2026-11-06-smr-weekly-hours-chart-design.md):
vendor invoiced labor lines, uploaded by the Owner. No backfill.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b3c5d7e9f1a2"
down_revision: Union[str, Sequence[str], None] = "3e5a7c9b1d2f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "smr_vendor_invoices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("invoice", sa.Text(), nullable=False),
        sa.Column("vendor", sa.Text(), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("week", sa.Integer(), nullable=False),
        sa.Column("hours", sa.Numeric(8, 2), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("uploaded_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_smr_vendor_invoices_invoice", "smr_vendor_invoices", ["invoice"])


def downgrade() -> None:
    op.drop_index("ix_smr_vendor_invoices_invoice", table_name="smr_vendor_invoices")
    op.drop_table("smr_vendor_invoices")
