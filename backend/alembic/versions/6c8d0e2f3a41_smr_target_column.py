"""smr target column

Revision ID: 6c8d0e2f3a41
Revises: 5b7c9d1e2f30
Create Date: 2026-10-23 20:00:00.000000

SMR27 target match (spec docs/superpowers/specs/2026-10-23-smr-target-match-design.md):
the client's per-order target from the Breakdown sheet. No backfill.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "6c8d0e2f3a41"
down_revision: Union[str, Sequence[str], None] = "5b7c9d1e2f30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("work_orders", sa.Column("smr_target", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("work_orders", "smr_target")
