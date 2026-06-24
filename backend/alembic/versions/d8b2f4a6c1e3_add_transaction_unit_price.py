"""add unit_price to transactions (historical price snapshot)

Revision ID: d8b2f4a6c1e3
Revises: e7f9a1c3b5d2
Create Date: 2026-06-23 12:00:00.000000

Captures the item's per-unit price at the moment a stock/dispense
transaction is written, so the History page's line values and invoice
totals reflect the price *then* rather than the item's current price.
Previously `services.history.list_history` read `Item.price` live, so
editing an item's price retroactively changed every past line.

Adds one nullable column to `transactions`:
- `unit_price` (numeric) -- the snapshotted per-unit price for stock /
  dispense rows. NULL for `adjust` (corrections have no billing meaning)
  and for every pre-existing row.

No backfill: `list_history` falls back to the live `Item.price` whenever
`unit_price` is NULL, so historical rows behave exactly as before while
new rows carry a true snapshot.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d8b2f4a6c1e3"
down_revision: Union[str, Sequence[str], None] = "e7f9a1c3b5d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("unit_price", sa.Numeric(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("transactions", "unit_price")
