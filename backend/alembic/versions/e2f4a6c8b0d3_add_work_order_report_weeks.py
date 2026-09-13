"""add work_order_report_weeks

Revision ID: e2f4a6c8b0d3
Revises: d1e3f5a7b9c2
Create Date: 2026-09-13 12:00:00.000000

The frozen weekly closed report (spec
docs/superpowers/specs/2026-09-13-weekly-closed-report-design.md, §4).
One row per completed week, keyed by its Monday; the payload is the JSON
response the route serves. Nothing to backfill: weeks freeze lazily on
first request (W5/W6).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e2f4a6c8b0d3"
down_revision: Union[str, Sequence[str], None] = "d1e3f5a7b9c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "work_order_report_weeks",
        sa.Column("week_start", sa.Date(), primary_key=True),
        sa.Column(
            "frozen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("work_order_report_weeks")
