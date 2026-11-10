"""smr work description

Revision ID: e1f3a5b7c9d2
Revises: d7e9f1a3b5c7
Create Date: 2026-11-10 12:00:00.000000

SMR27 invoicing (user 2026-11-10): the human-written work description that
prints in the correction block under WORK DESCRIPTION. No backfill.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e1f3a5b7c9d2"
down_revision: Union[str, Sequence[str], None] = "d7e9f1a3b5c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("work_orders", sa.Column("smr_description", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("work_orders", "smr_description")
