"""add work_order_labor_sessions.reviewed_at

Revision ID: d5b7f9a1c3e6
Revises: c4a6e8b0d2f5
Create Date: 2026-09-27 12:00:00.000000

A session the 12-hour cap closed is an estimate. The leaderboard holds its
minutes out of the ranking until an Admin accepts it; `reviewed_at` records
that acceptance. NULL on every existing row, so every historical
auto-closed session starts out pending.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d5b7f9a1c3e6"
down_revision: Union[str, Sequence[str], None] = "c4a6e8b0d2f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("work_order_labor_sessions",
                  sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("work_order_labor_sessions", "reviewed_at")
