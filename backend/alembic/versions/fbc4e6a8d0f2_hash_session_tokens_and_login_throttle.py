"""hash session tokens, cap every session, add login throttle counters

Revision ID: fbc4e6a8d0f2
Revises: faa2c4e6b8d0
Create Date: 2026-08-09 09:00:00.000000

Two changes, both security hardening (API hardening checklist X1 + C3).

**1. `sessions` now stores a token hash, and every session expires.**

The old table used the raw bearer token as its primary key, stored in
plaintext, with `expires_at` nullable -- and NULL was the *default* case
(any login without "remember this device"). That combination meant the
table was a growing pile of permanently valid credentials sitting in the
clear: one read of it -- a backup, a replica, a dashboard query -- was a
full account takeover for every logged-in user, and nothing ever swept
it.

Now the column is `token_hash` (SHA-256 of the cookie value) and
`expires_at` is NOT NULL.

**This upgrade signs every user out.** That is deliberate, not a side
effect. Rewriting the existing rows in place was possible -- hash each
token, leave the cookies working -- but it would have preserved exactly
the backlog of never-expiring credentials the change exists to
eliminate. Dropping the table is the only step that actually clears
them. No other data is touched: users, work orders, transactions, and
inventory are untouched, and the FK is recreated identically.

The table is dropped and recreated rather than altered because the
primary key itself is changing and no row is worth preserving.

**2. `login_attempts`** backs the new login throttle. Transient
counters, swept after 24h; not an audit trail.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "fbc4e6a8d0f2"
down_revision: Union[str, Sequence[str], None] = "faa2c4e6b8d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Signs everyone out -- see the module docstring for why that is the
    # intended outcome rather than a cost.
    op.drop_table("sessions")

    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])

    op.create_table(
        "login_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope", "key", name="uq_login_attempts_scope_key"),
    )
    op.create_index(
        "ix_login_attempts_last_failed_at", "login_attempts", ["last_failed_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_login_attempts_last_failed_at", table_name="login_attempts")
    op.drop_table("login_attempts")

    # Restores the pre-hardening shape (plaintext token PK, nullable
    # expiry), also empty -- the hashes cannot be turned back into
    # usable tokens, so there is nothing to carry across.
    op.drop_index("ix_sessions_expires_at", table_name="sessions")
    op.drop_table("sessions")
    op.create_table(
        "sessions",
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("token"),
    )
