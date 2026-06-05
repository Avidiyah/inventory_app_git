"""add reason column to transactions

Revision ID: c3d4e5f6a7b8
Revises: b2d3e4f5a6c7
Create Date: 2026-06-05 12:30:00.000000

Introduces correction transactions. Adds `transactions.reason` (nullable
TEXT) so adjust rows can record why the count was changed (e.g. "physical
recount", "damaged stock"). Existing stock/dispense rows leave it NULL;
only `transaction_type = "adjust"` rows are required (at the schema
layer) to populate it.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2d3e4f5a6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("transactions", "reason")
