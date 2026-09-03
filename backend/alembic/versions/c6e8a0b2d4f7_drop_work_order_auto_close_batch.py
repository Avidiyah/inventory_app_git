"""drop work order auto-close batch columns

Revision ID: c6e8a0b2d4f7
Revises: a1c3e5b7d9f0
Create Date: 2026-09-03 12:00:00.000000

The NetFacilities import auto-close/reopen sweep is removed. Drops the two
provenance columns it used (`auto_closed_batch_id`, `auto_closed_at`) and
their partial index. `archived_at` remains the only thing that decides
closed/live, so nothing else changes.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c6e8a0b2d4f7"
down_revision: Union[str, Sequence[str], None] = "a1c3e5b7d9f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_work_orders_auto_closed_at", table_name="work_orders")
    op.drop_column("work_orders", "auto_closed_at")
    op.drop_column("work_orders", "auto_closed_batch_id")


def downgrade() -> None:
    op.add_column(
        "work_orders",
        sa.Column("auto_closed_batch_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "work_orders",
        sa.Column("auto_closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_work_orders_auto_closed_at",
        "work_orders",
        [sa.text("auto_closed_at DESC")],
        postgresql_where=sa.text("auto_closed_at IS NOT NULL"),
    )
