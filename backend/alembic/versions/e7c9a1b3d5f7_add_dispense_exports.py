"""add dispense_exports

Revision ID: e7c9a1b3d5f7
Revises: d5b7f9a1c3e6
Create Date: 2026-09-28 12:00:00.000000

One row per Weekly export on the Saved Items page; the latest row's
`window_end` is where the next export starts.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "e7c9a1b3d5f7"
down_revision: Union[str, Sequence[str], None] = "d5b7f9a1c3e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dispense_exports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_dispense_exports_window_end", "dispense_exports", ["window_end"])


def downgrade() -> None:
    op.drop_index("ix_dispense_exports_window_end", table_name="dispense_exports")
    op.drop_table("dispense_exports")
