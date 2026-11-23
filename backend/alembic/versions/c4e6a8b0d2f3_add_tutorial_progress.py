"""add tutorial_progress

Revision ID: c4e6a8b0d2f3
Revises: b7d9f1a3c5e7
Create Date: 2026-11-23 12:00:00.000000

Tutorials 0b: one row per person per tutorial script key, first-write-wins
timestamps. Additive; no backfill.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c4e6a8b0d2f3"
down_revision: Union[str, Sequence[str], None] = "b7d9f1a3c5e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tutorial_progress",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("script_key", sa.Text(), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "script_key"),
    )


def downgrade() -> None:
    op.drop_table("tutorial_progress")
