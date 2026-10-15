"""add attendance_punches.lunch_waived

Revision ID: c8e2f4a6b1d3
Revises: a7c3e9f1b2d4
Create Date: 2026-10-15 12:00:00.000000

L2: an Admin's per-day "no lunch" waiver. No data migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c8e2f4a6b1d3"
down_revision: Union[str, Sequence[str], None] = "a7c3e9f1b2d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("attendance_punches", sa.Column(
        "lunch_waived", sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade() -> None:
    op.drop_column("attendance_punches", "lunch_waived")
