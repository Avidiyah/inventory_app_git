"""add multi-technician assignments and work-order labor

Revision ID: f7a9b1c3d5e6
Revises: f6e8a0b2d4f5
Create Date: 2026-08-03 12:00:00.000000

Existing singular work-order assignments are copied into the normalized join
table. ``work_orders.assigned_to_id`` remains as a compatibility mirror for
Mass Stage and older clients while Work Orders move to the plural relation.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f7a9b1c3d5e6"
down_revision: Union[str, Sequence[str], None] = "f6e8a0b2d4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "work_order_technicians",
        sa.Column("work_order_id", sa.UUID(), nullable=False),
        sa.Column("technician_id", sa.UUID(), nullable=False),
        sa.Column("assigned_by_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["work_order_id"], ["work_orders.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["technician_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["assigned_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("work_order_id", "technician_id"),
    )
    op.create_index(
        "ix_work_order_technicians_technician_id",
        "work_order_technicians",
        ["technician_id"],
    )
    op.execute(
        """
        INSERT INTO work_order_technicians (
            work_order_id, technician_id, assigned_by_id, created_at
        )
        SELECT id, assigned_to_id, created_by_id, created_at
        FROM work_orders
        WHERE assigned_to_id IS NOT NULL
        ON CONFLICT (work_order_id, technician_id) DO NOTHING
        """
    )

    op.create_table(
        "work_order_labor",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("work_order_id", sa.UUID(), nullable=False),
        sa.Column("technician_id", sa.UUID(), nullable=False),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column("recorded_by_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["work_order_id"], ["work_orders.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["technician_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["recorded_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_work_order_labor_work_order_id", "work_order_labor", ["work_order_id"]
    )
    op.create_index(
        "ix_work_order_labor_technician_id", "work_order_labor", ["technician_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_work_order_labor_technician_id", table_name="work_order_labor")
    op.drop_index("ix_work_order_labor_work_order_id", table_name="work_order_labor")
    op.drop_table("work_order_labor")
    op.drop_index(
        "ix_work_order_technicians_technician_id",
        table_name="work_order_technicians",
    )
    op.drop_table("work_order_technicians")
