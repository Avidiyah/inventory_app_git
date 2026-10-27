"""smr paper check columns

Revision ID: 7d9e1f3a4b52
Revises: 6c8d0e2f3a41
Create Date: 2026-10-27 12:00:00.000000

SMR27 paper check (spec docs/superpowers/specs/2026-10-27-smr-paper-check-design.md):
who keyed an SMR order from its paper work order, and when. No backfill.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "7d9e1f3a4b52"
down_revision: Union[str, Sequence[str], None] = "6c8d0e2f3a41"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FK = "fk_work_orders_smr_paper_checked_by_id_users"


def upgrade() -> None:
    op.add_column("work_orders", sa.Column("smr_paper_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("work_orders", sa.Column("smr_paper_checked_by_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(_FK, "work_orders", "users", ["smr_paper_checked_by_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint(_FK, "work_orders", type_="foreignkey")
    op.drop_column("work_orders", "smr_paper_checked_by_id")
    op.drop_column("work_orders", "smr_paper_checked_at")
