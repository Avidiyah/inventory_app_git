"""add feature switches

Revision ID: f7b9d1e3a5c7
Revises: e6a8c0d2f4b6
Create Date: 2026-11-24 20:00:00.000000

App-wide on/off switches the Owner flips on Dev Tools. No rows: every
switch starts off, so the SMR27 pages disappear on deploy.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f7b9d1e3a5c7"
down_revision: Union[str, Sequence[str], None] = "e6a8c0d2f4b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "feature_switches",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_table("feature_switches")
