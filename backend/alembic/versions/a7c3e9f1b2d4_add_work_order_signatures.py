"""add work_order_signatures

Revision ID: a7c3e9f1b2d4
Revises: e7c9a1b3d5f7
Create Date: 2026-09-30 12:00:00.000000

One witness sign-off per work order (unique `work_order_id`); "unsigned" is
simply no row. The PNG lives here rather than on `work_orders` so list
queries and reports never carry the image.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a7c3e9f1b2d4"
down_revision: Union[str, Sequence[str], None] = "e7c9a1b3d5f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "work_order_signatures",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("work_order_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("work_orders.id", ondelete="CASCADE"),
                  nullable=False, unique=True),
        sa.Column("image_png", sa.LargeBinary(), nullable=False),
        sa.Column("witness_name", sa.Text(), nullable=False),
        sa.Column("witness_phone", sa.String(10), nullable=False),
        sa.Column("captured_by_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("work_order_signatures")
