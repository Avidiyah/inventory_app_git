"""add work order auto-close batch columns

Revision ID: b3d5f7a9c1e2
Revises: fcbc2524ea62
Create Date: 2026-08-30 12:00:00.000000

Backs NetFacilities import reconciliation (spec
docs/superpowers/specs/2026-08-30-netfacilities-reconcile-design.md). Both
columns are provenance for the sweep that closes work orders the latest CSV did
not list: `auto_closed_batch_id` groups one import's victims and `auto_closed_at`
is what the 24-hour undo window is measured from. Nothing to backfill -- no sweep
can have run before this ships, so every existing row is correctly NULL on both.

`archived_at` remains the only thing that decides closed/live. The index is
partial because almost every row is NULL here and the only reads are "sweep rows
inside the window" and the daily report's marker.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b3d5f7a9c1e2"
down_revision: Union[str, Sequence[str], None] = "fcbc2524ea62"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_index("ix_work_orders_auto_closed_at", table_name="work_orders")
    op.drop_column("work_orders", "auto_closed_at")
    op.drop_column("work_orders", "auto_closed_batch_id")
