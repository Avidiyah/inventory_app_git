"""smr paper reviewed

Revision ID: a3c5e7b9d1f4
Revises: f2a4c6e8b0d1
Create Date: 2026-11-13 12:00:00.000000

A person's stamp that moves a billed, dated-less SMR order from Needs paper
review to Needs review. No backfill.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a3c5e7b9d1f4"
down_revision: Union[str, Sequence[str], None] = "f2a4c6e8b0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FK = "fk_work_orders_smr_paper_reviewed_by_id_users"


def upgrade() -> None:
    op.add_column("work_orders", sa.Column("smr_paper_reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("work_orders", sa.Column("smr_paper_reviewed_by_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(_FK, "work_orders", "users", ["smr_paper_reviewed_by_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint(_FK, "work_orders", type_="foreignkey")
    op.drop_column("work_orders", "smr_paper_reviewed_by_id")
    op.drop_column("work_orders", "smr_paper_reviewed_at")
