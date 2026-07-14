"""add tools tables

Revision ID: d2f4b6a8c0e3
Revises: a9d1f3b7c2e8
Create Date: 2026-07-14 12:00:00.000000

Tool-specific tracking, additive alongside `items`/`transactions`. This
migration adds two tables:

- `tools`: a tracked tool, parallel to `items` but deliberately smaller --
  no `location`, `price`, or `product_link`. `quantity` is the on-hand/
  available count (same semantics as `items.quantity`). A row may be one
  serialized unit (`quantity` 1, its own barcode) or an unserialized bulk
  batch (`quantity` > 1, one shared barcode) -- both valid, no schema
  distinction between them. Soft delete via `archived_at`, mirroring
  `items.archived_at`. `barcode` uniqueness is a **partial** unique index
  scoped to live rows (`archived_at IS NULL`), not a plain column UNIQUE --
  unlike `items.barcode`, an archived tool's barcode is simply free to
  reuse with no retire/confirm dance.
- `tool_transactions`: append-only checkout/return ledger, the custody-
  tracking analogue of `transactions` kept as a separate table (different
  vocabulary, and a mandatory custody field `transactions` has no
  equivalent of). `assigned_to_id` is who has/had custody (required);
  `performed_by_id` is who was logged in and processed the action. "Who
  currently has a tool" is derived at query time (Sum(checkout) -
  Sum(return) per (tool, user)), not stored. `work_order_id` /
  `work_order_number` are an optional, never-required linkage.

No backfill: both tables start empty. Does not touch any existing table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d2f4b6a8c0e3"
down_revision: Union[str, Sequence[str], None] = "a9d1f3b7c2e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tools",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("barcode", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_tools_barcode_live",
        "tools",
        ["barcode"],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
    )

    op.create_table(
        "tool_transactions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tool_id", sa.UUID(), nullable=False),
        sa.Column("transaction_type", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(), nullable=False),
        sa.Column("assigned_to_id", sa.UUID(), nullable=False),
        sa.Column("performed_by_id", sa.UUID(), nullable=True),
        sa.Column("work_order_id", sa.UUID(), nullable=True),
        sa.Column("work_order_number", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tool_id"], ["tools.id"]),
        sa.ForeignKeyConstraint(["assigned_to_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["performed_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["work_order_id"], ["work_orders.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tool_transactions_tool_id", "tool_transactions", ["tool_id"])
    op.create_index(
        "ix_tool_transactions_assigned_to_id", "tool_transactions", ["assigned_to_id"]
    )
    op.create_index(
        "ix_tool_transactions_work_order_id", "tool_transactions", ["work_order_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_tool_transactions_work_order_id", table_name="tool_transactions")
    op.drop_index("ix_tool_transactions_assigned_to_id", table_name="tool_transactions")
    op.drop_index("ix_tool_transactions_tool_id", table_name="tool_transactions")
    op.drop_table("tool_transactions")
    op.drop_index("uq_tools_barcode_live", table_name="tools")
    op.drop_table("tools")
