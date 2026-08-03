"""expand work-order lifecycle statuses

Revision ID: f4c6e8a0b2d3
Revises: f3b5d7a9c1e2
Create Date: 2026-08-02 23:30:00.000000

New imports begin Created when supervisor-name routing misses and Assigned when
it succeeds. Existing In-Progress and Completed rows keep their status so the
migration does not rewrite operational history. In-Progress, Completed, and
Review remain application-validated text values; Closed continues to use the
existing `archived_at` soft-archive column.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4c6e8a0b2d3"
down_revision: Union[str, Sequence[str], None] = "f3b5d7a9c1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "work_orders",
        "status",
        existing_type=sa.Text(),
        server_default="created",
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "work_orders",
        "status",
        existing_type=sa.Text(),
        server_default="in_progress",
        existing_nullable=False,
    )
