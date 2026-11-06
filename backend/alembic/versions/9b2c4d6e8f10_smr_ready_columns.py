"""smr ready columns

Revision ID: 9b2c4d6e8f10
Revises: 451c56c5643a
Create Date: 2026-11-06 12:00:00.000000

SMR27 paper stage (spec docs/superpowers/specs/2026-11-06-smr-paper-stage-design.md):
who marked an SMR order ready for invoice, and when. No backfill.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "9b2c4d6e8f10"
down_revision: Union[str, Sequence[str], None] = "451c56c5643a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FK = "fk_work_orders_smr_ready_by_id_users"


def upgrade() -> None:
    op.add_column("work_orders", sa.Column("smr_ready_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("work_orders", sa.Column("smr_ready_by_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(_FK, "work_orders", "users", ["smr_ready_by_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint(_FK, "work_orders", type_="foreignkey")
    op.drop_column("work_orders", "smr_ready_by_id")
    op.drop_column("work_orders", "smr_ready_at")
