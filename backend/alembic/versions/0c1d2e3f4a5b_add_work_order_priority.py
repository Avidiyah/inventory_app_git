"""add nullable work-order priority

Revision ID: 0c1d2e3f4a5b
Revises: fbc4e6a8d0f2
Create Date: 2026-08-14 14:00:00.000000

Priority is intentionally nullable, has no default or backfill, and is not
editable through the generic work-order update contract.  The NetFacilities
enrichment service will be its only writer in the first release.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0c1d2e3f4a5b"
down_revision: Union[str, Sequence[str], None] = "fbc4e6a8d0f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("work_orders", sa.Column("priority", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("work_orders", "priority")
