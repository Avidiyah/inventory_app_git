"""add item_barcodes table (additional barcodes per item)

Revision ID: a7c9e1f3b5d2
Revises: f6b8c0d2e4a1
Create Date: 2026-06-11 10:00:00.000000

A physical item often carries several barcodes on its packaging
(manufacturer code, repackaged carton code, retail label). The existing
single `items.barcode` column stays the canonical/display code; this
migration adds a child `item_barcodes` table holding the *additional*
codes, so a scan of any of them resolves to the same item
(`services.items.get_item_by_barcode`).

`code` is globally UNIQUE, guaranteeing alternates never collide with one
another across items. The remaining rule -- an alternate must not equal
any item's primary `items.barcode` -- is a service-layer pre-check
(`services.items._barcode_in_use`), since a UNIQUE constraint cannot span
two tables.

The FK is `ON DELETE CASCADE`: alternates are owned configuration (not
audit data like `transactions`), so they vanish with a deleted item.
Items are soft-deleted via `archived_at`, so the cascade only fires on a
genuine row delete.

No backfill: existing items keep their single `items.barcode`; the new
table starts empty.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7c9e1f3b5d2"
down_revision: Union[str, Sequence[str], None] = "f6b8c0d2e4a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "item_barcodes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_item_barcodes_code"),
    )
    op.create_index("ix_item_barcodes_item_id", "item_barcodes", ["item_id"])


def downgrade() -> None:
    op.drop_index("ix_item_barcodes_item_id", table_name="item_barcodes")
    op.drop_table("item_barcodes")
