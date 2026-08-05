"""add durable user requests queue

Revision ID: f8a0c2e4b6d8
Revises: f7a9b1c3d5e6
Create Date: 2026-08-05 12:00:00.000000

The first request type is ``inventory_recount``. A Scan / Stock dispense that
exceeds recorded on-hand inventory is still recorded, and a linked open request
surfaces the discrepancy to Admin/Owner users for follow-up.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f8a0c2e4b6d8"
down_revision: Union[str, Sequence[str], None] = "f7a9b1c3d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("request_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="open", nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=True),
        sa.Column("transaction_id", sa.UUID(), nullable=True),
        sa.Column("work_order_id", sa.UUID(), nullable=True),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_id", sa.UUID(), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"]),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.ForeignKeyConstraint(["work_order_id"], ["work_orders.id"]),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transaction_id"),
    )
    op.create_index(
        "ix_user_requests_status", "user_requests", ["status"], unique=False
    )
    op.create_index(
        "ix_user_requests_request_type",
        "user_requests",
        ["request_type"],
        unique=False,
    )
    op.create_index(
        "ix_user_requests_item_id", "user_requests", ["item_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_user_requests_item_id", table_name="user_requests")
    op.drop_index("ix_user_requests_request_type", table_name="user_requests")
    op.drop_index("ix_user_requests_status", table_name="user_requests")
    op.drop_table("user_requests")
