"""add attendance_punches.shop

Revision ID: f2a4c6e8b0d1
Revises: e1f3a5b7c9d2
Create Date: 2026-11-11 12:00:00.000000

Shop hours: a punch spent in the shop. Paid and on the Admin timesheet, left
out of the leaderboard score. No data migration -- every existing punch is
field time.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f2a4c6e8b0d1"
down_revision: Union[str, Sequence[str], None] = "e1f3a5b7c9d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("attendance_punches", sa.Column(
        "shop", sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade() -> None:
    op.drop_column("attendance_punches", "shop")
