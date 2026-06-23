"""add billable_quantity to transactions

Revision ID: e7f9a1c3b5d2
Revises: c2e4f6a8d0b1
Create Date: 2026-06-23 10:00:00.000000

Introduces a per-transaction billing override for the History page. An
Admin/Owner reviewing a work order can decide to charge for fewer units
than were physically dispensed, or not charge for a line at all, without
disturbing the inventory record (the items were really used).

Adds one nullable column to `transactions`:
- `billable_quantity` (numeric) -- NULL means "no override, bill the full
  `quantity`"; a value of 0 means "recorded but not charged". It only
  affects the History price columns / clipboard export, never
  `Item.quantity`.

Existing rows leave it NULL (i.e. bill the full quantity), so no data
backfill is needed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7f9a1c3b5d2"
down_revision: Union[str, Sequence[str], None] = "c2e4f6a8d0b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("billable_quantity", sa.Numeric(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("transactions", "billable_quantity")
