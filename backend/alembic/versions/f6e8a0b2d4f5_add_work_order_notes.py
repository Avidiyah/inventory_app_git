"""add free-form work-order notes

Revision ID: f6e8a0b2d4f5
Revises: f5d7f9b1c3e4
Create Date: 2026-08-03 01:00:00.000000

On-Hold remains an application-validated value in the existing text status
column. This revision adds the persistent nullable text used by the Work Order
Notes section.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6e8a0b2d4f5"
down_revision: Union[str, Sequence[str], None] = "f5d7f9b1c3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("work_orders", sa.Column("notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("work_orders", "notes")
