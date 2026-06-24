"""add archived_at to users (soft delete)

Revision ID: f1a3c5e7b9d4
Revises: d8b2f4a6c1e3
Create Date: 2026-06-23 13:00:00.000000

Introduces user soft delete (archival), mirroring item archival
(`f6b8c0d2e4a1`). Hard-deleting a user is refused whenever any
transaction references them (the `transactions.user_id` FK is
`ON DELETE RESTRICT`), which left no way to retire a departed user who
had ever recorded a transaction. Archiving instead sets `archived_at`:
the row is kept so the history join still resolves the user's name, but
the user is hidden from the active Saved Users list and -- critically --
can no longer authenticate.

Adds one nullable column to `users`:
- `archived_at` (timestamptz) -- NULL means "active"; a timestamp means
  the user is archived (cannot log in, excluded from active listings).

Existing rows leave it NULL (i.e. active), so no data backfill is needed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a3c5e7b9d4"
down_revision: Union[str, Sequence[str], None] = "d8b2f4a6c1e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "archived_at")
