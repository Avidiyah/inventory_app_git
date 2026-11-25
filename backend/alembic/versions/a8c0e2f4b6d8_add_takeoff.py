"""add takeoff

Revision ID: a8c0e2f4b6d8
Revises: f7b9d1e3a5c7
Create Date: 2026-11-25 09:00:00.000000

Takeoff: predicted material per work order, and the on-the-way figures the
Takeoff page records. Neither table touches stock, billing or work_order_items.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a8c0e2f4b6d8"
down_revision: Union[str, Sequence[str], None] = "f7b9d1e3a5c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "work_order_takeoff_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "work_order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("work_orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Numeric(), nullable=False),
        sa.Column(
            "created_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "work_order_id", "item_id", name="uq_takeoff_line_order_item"
        ),
        sa.CheckConstraint("quantity > 0", name="ck_takeoff_line_quantity_positive"),
    )
    op.create_table(
        "takeoff_purchases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("service_type_key", sa.Text(), nullable=False),
        sa.Column("service_type_label", sa.Text(), nullable=False),
        sa.Column("quantity_on_the_way", sa.Numeric(), nullable=False),
        sa.Column(
            "created_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "item_id", "service_type_key", name="uq_takeoff_purchase_item_type"
        ),
        sa.CheckConstraint(
            "quantity_on_the_way > 0", name="ck_takeoff_purchase_quantity_positive"
        ),
    )


def downgrade() -> None:
    op.drop_table("takeoff_purchases")
    op.drop_table("work_order_takeoff_lines")
