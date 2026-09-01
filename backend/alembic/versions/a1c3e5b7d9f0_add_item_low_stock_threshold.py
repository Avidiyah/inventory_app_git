"""add low_stock_threshold to items

Revision ID: a1c3e5b7d9f0
Revises: b3d5f7a9c1e2
Create Date: 2026-09-01 12:00:00.000000

Introduces per-item low-stock alerting. An item whose on-hand count falls
to or below this number raises a push to TechFM OA and above and appears
on the Low Stock page.

`server_default="6"` does double duty: it backfills every existing row in
the same statement (so the column can be NOT NULL immediately) and it is
what makes an INSERT that omits the column land on the shared default.
The CHECK pins the floor of 1 -- a zero threshold would be an invisible
mute, since stock cannot go below zero.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1c3e5b7d9f0"
down_revision: Union[str, Sequence[str], None] = "b3d5f7a9c1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "items",
        sa.Column(
            "low_stock_threshold",
            sa.Integer(),
            nullable=False,
            server_default="6",
        ),
    )
    op.create_check_constraint(
        "ck_items_low_stock_threshold_positive",
        "items",
        "low_stock_threshold >= 1",
    )


def downgrade() -> None:
    op.drop_constraint("ck_items_low_stock_threshold_positive", "items", type_="check")
    op.drop_column("items", "low_stock_threshold")
