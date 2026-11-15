"""work order field stamps

Revision ID: b7d9f1a3c5e7
Revises: a3c5e7b9d1f4
Create Date: 2026-11-15 12:00:00.000000

W3 save-time conflict check: who last changed each protected work-order
field (one row per field per order), and who last changed each material
line and labor entry. Additive; no backfill.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b7d9f1a3c5e7"
down_revision: Union[str, Sequence[str], None] = "a3c5e7b9d1f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ITEM_FK = "fk_work_order_items_updated_by_id_users"
_LABOR_FK = "fk_work_order_labor_updated_by_id_users"


def upgrade() -> None:
    op.create_table(
        "work_order_field_stamps",
        sa.Column("work_order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("field", sa.Text(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("changed_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["work_order_id"], ["work_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["changed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("work_order_id", "field"),
    )
    op.add_column("work_order_items", sa.Column("updated_by_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(_ITEM_FK, "work_order_items", "users", ["updated_by_id"], ["id"], ondelete="SET NULL")
    op.add_column("work_order_labor", sa.Column("updated_by_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(_LABOR_FK, "work_order_labor", "users", ["updated_by_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint(_LABOR_FK, "work_order_labor", type_="foreignkey")
    op.drop_column("work_order_labor", "updated_by_id")
    op.drop_constraint(_ITEM_FK, "work_order_items", type_="foreignkey")
    op.drop_column("work_order_items", "updated_by_id")
    op.drop_table("work_order_field_stamps")
