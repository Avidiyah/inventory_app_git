"""add archived_at to items (soft delete)

Revision ID: f6b8c0d2e4a1
Revises: e5f67b8c9d0
Create Date: 2026-06-08 12:00:00.000000

Introduces item soft delete (archival). Deleting an item used to be
refused whenever any transaction referenced it, because the history
view reads an item's name/barcode/price via a live join and a hard
delete would orphan (or hide) those rows. Instead, a "delete" now sets
`archived_at`: the row is kept so history stays intact, but the item is
hidden from `list_items` and barcode lookups.

Adds one nullable column to `items`:
- `archived_at` (timestamptz) -- NULL means "live"; a timestamp means the
  item has been archived and is excluded from active listings/lookups.

Existing rows leave it NULL (i.e. live), so no data backfill is needed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6b8c0d2e4a1"
down_revision: Union[str, Sequence[str], None] = "e5f67b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "items",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("items", "archived_at")
