"""add billable_quantity to work_order_items

Revision ID: a9d1f3b7c2e8
Revises: c4e6a8b0d2f5
Create Date: 2026-06-30 12:00:00.000000

Phase 2 of work-order billing: the work-order material line is the billing
unit (Phase 1 moved the charge off the individual ledger rows onto the line).
This adds a line-level billing override so an Admin/Owner can charge for fewer
units than were consumed, or not charge a line at all, without disturbing the
inventory record -- the per-line analogue of `transactions.billable_quantity`.

Adds one nullable column to `work_order_items`:
- `billable_quantity` (numeric) -- NULL means "no override, bill the full
  `quantity`"; 0 means "recorded but not charged"; a value <= quantity bills a
  partial count. It only affects the work order's charge total / line charge,
  never `Item.quantity`.

Existing rows leave it NULL (bill the full quantity), so no backfill is needed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a9d1f3b7c2e8"
down_revision: Union[str, Sequence[str], None] = "c4e6a8b0d2f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "work_order_items",
        sa.Column("billable_quantity", sa.Numeric(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("work_order_items", "billable_quantity")
