"""add tool_transactions reason + nullable assigned_to_id

Revision ID: e4a6c8b0d2f7
Revises: d2f4b6a8c0e3
Create Date: 2026-07-14 15:00:00.000000

Adds a "Correct Count" action for tools (mirrors items'
`POST /transactions/adjust`): an Admin+ can set a tool's on-hand quantity
to an absolute new value with a required reason, recorded as an `adjust`
row in `tool_transactions`. Two changes to support it:

- `tool_transactions.reason` (nullable Text) -- populated only for
  `transaction_type = "adjust"`, mirrors `transactions.reason`.
- `tool_transactions.assigned_to_id` becomes nullable -- an `adjust` row
  is a pure inventory correction with no custody holder, unlike
  `checkout`/`return`. `services.tools._custody_query` is updated in the
  same change to filter to `transaction_type IN ('checkout', 'return')`
  so an `adjust` row (NULL `assigned_to_id`) is never included in a
  custody sum.

Existing rows are all `checkout`/`return` with `assigned_to_id` set and
`reason` NULL, so no backfill is needed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e4a6c8b0d2f7"
down_revision: Union[str, Sequence[str], None] = "d2f4b6a8c0e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tool_transactions", sa.Column("reason", sa.Text(), nullable=True))
    op.alter_column("tool_transactions", "assigned_to_id", nullable=True)


def downgrade() -> None:
    op.alter_column("tool_transactions", "assigned_to_id", nullable=False)
    op.drop_column("tool_transactions", "reason")
