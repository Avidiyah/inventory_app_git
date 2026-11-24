"""add work_order_photos

Revision ID: d5f7b9c1e3a5
Revises: c4e6a8b0d2f3
Create Date: 2026-11-24 12:00:00.000000

Photos held until exported to Drive and cleared. Unique
(work_order_id, taken_on, seq) keeps re-exported filenames stable; the
exported_at index serves the export and clear queries.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "d5f7b9c1e3a5"
down_revision: Union[str, Sequence[str], None] = "c4e6a8b0d2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "work_order_photos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("work_order_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("original", sa.LargeBinary(), nullable=False),
        sa.Column("original_type", sa.Text(), nullable=False),
        sa.Column("preview_jpeg", sa.LargeBinary(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("taken_on", sa.Date(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("uploaded_by_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("work_order_id", "taken_on", "seq",
                            name="uq_work_order_photos_wo_day_seq"),
    )
    op.create_index("ix_work_order_photos_exported_at", "work_order_photos", ["exported_at"])


def downgrade() -> None:
    op.drop_index("ix_work_order_photos_exported_at", table_name="work_order_photos")
    op.drop_table("work_order_photos")
