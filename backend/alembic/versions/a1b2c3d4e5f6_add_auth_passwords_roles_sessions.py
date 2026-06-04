"""add password_hash and role to users, create sessions table

Revision ID: a1b2c3d4e5f6
Revises: 4c1e7f3a9b22
Create Date: 2026-06-04 09:00:00.000000

Introduces authentication. Adds the two new `users` columns
(`password_hash`, `role`) and a server-side `sessions` table.

The `users` table is expected to be empty at this point -- the
pre-auth users were removed before this migration, since there is no
sensible password/role backfill for accounts that never had one. The
columns are therefore added NOT NULL directly. If the table is *not*
empty the `SET NOT NULL` step will fail loudly, which is the desired
signal that those rows must be cleared (or recreated via the bootstrap
script) first.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "4c1e7f3a9b22"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add nullable first, then enforce NOT NULL. On an empty table this
    # is equivalent to adding NOT NULL outright but fails gracefully if
    # stray rows exist (see module docstring).
    op.add_column("users", sa.Column("password_hash", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("role", sa.Text(), nullable=True))
    op.alter_column("users", "password_hash", nullable=False)
    op.alter_column("users", "role", nullable=False)

    op.create_table(
        "sessions",
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("token"),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_column("users", "role")
    op.drop_column("users", "password_hash")
