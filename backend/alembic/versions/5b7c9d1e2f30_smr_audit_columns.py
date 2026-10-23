"""smr audit columns

Revision ID: 5b7c9d1e2f30
Revises: c8e2f4a6b1d3
Create Date: 2026-10-23 12:00:00.000000

SMR27 audit workflow (spec docs/superpowers/specs/2026-10-23-smr-audit-workflow-design.md):
the SMR marker + frozen baseline on work_orders, and a nullable labor technician
so an anonymous Skilled Technician line can exist. No backfill.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "5b7c9d1e2f30"
down_revision: Union[str, Sequence[str], None] = "c8e2f4a6b1d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("work_orders", sa.Column("smr_imported_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("work_orders", sa.Column("smr_baseline", postgresql.JSONB(), nullable=True))
    op.alter_column("work_order_labor", "technician_id", existing_type=postgresql.UUID(), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM work_order_labor WHERE technician_id IS NULL")
    op.alter_column("work_order_labor", "technician_id", existing_type=postgresql.UUID(), nullable=False)
    op.drop_column("work_orders", "smr_baseline")
    op.drop_column("work_orders", "smr_imported_at")
