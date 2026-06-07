"""add void columns to transactions

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-07 09:00:00.000000

Introduces transaction voids (soft delete). A mis-clicked stock /
dispense / adjust can be voided by a Supervisor or above: the row is
kept for the audit trail but excluded from the history view and its
effect on item stock is reversed.

Adds two nullable columns to `transactions`:
- `voided_at` (timestamptz) -- NULL means "live"; a timestamp means the
  row has been voided and is hidden from history.
- `voided_by_id` (UUID) -- the user who voided it, recorded as hidden
  audit metadata. Intentionally NOT a foreign key (see the model
  docstring): a second FK to `users` would force disambiguating the
  existing `transactions.user_id` relationship for no integrity gain.

Existing rows leave both NULL (i.e. live), so no data backfill is
needed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "transactions",
        sa.Column("voided_by_id", UUID(as_uuid=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("transactions", "voided_by_id")
    op.drop_column("transactions", "voided_at")
