"""smr vendor invoice worker

Revision ID: c4d6e8f0a2b4
Revises: b3c5d7e9f1a2
Create Date: 2026-11-06 20:00:00.000000

The invoice's name for the person on each labor line (user 2026-11-06: fill
generic vendor crews on the correction block with names that have invoice
hours to spare). BT invoices carry classes, so their rows stay null.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4d6e8f0a2b4"
down_revision: Union[str, Sequence[str], None] = "b3c5d7e9f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("smr_vendor_invoices", sa.Column("worker", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("smr_vendor_invoices", "worker")
