"""add location to items and rename attributes to notes

Revision ID: 4c1e7f3a9b22
Revises: 9a2c5d4e8b11
Create Date: 2026-06-02 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4c1e7f3a9b22"
down_revision: Union[str, Sequence[str], None] = "9a2c5d4e8b11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add location nullable first so existing rows can be backfilled
    op.add_column("items", sa.Column("location", sa.Text(), nullable=True))
    op.execute("UPDATE items SET location = 'unspecified' WHERE location IS NULL")
    op.alter_column("items", "location", nullable=False)

    # Rename attributes -> notes
    op.alter_column("items", "attributes", new_column_name="notes")


def downgrade() -> None:
    op.alter_column("items", "notes", new_column_name="attributes")
    op.drop_column("items", "location")
