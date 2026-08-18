"""add push_subscriptions

Revision ID: 1d2e3f4a5b6c
Revises: 0c1d2e3f4a5b
Create Date: 2026-08-18 10:00:00.000000

Backs Web Push opt-in.  There is nothing to backfill: no subscription can
exist before a browser has been asked for one.

`endpoint` is the primary key rather than a surrogate id so that a
re-subscribe reassigns the row instead of creating a second one -- see the
model docstring in `app/models.py::PushSubscription` for why that matters on
a shared device.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "1d2e3f4a5b6c"
down_revision: Union[str, Sequence[str], None] = "0c1d2e3f4a5b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "push_subscriptions",
        sa.Column("endpoint", sa.Text(), primary_key=True),
        sa.Column(
            "user_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("p256dh", sa.Text(), nullable=False),
        sa.Column("auth", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    # The fan-out selects by recipient; the endpoint primary key does not
    # serve that query.
    op.create_index(
        "ix_push_subscriptions_user_id", "push_subscriptions", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_push_subscriptions_user_id", table_name="push_subscriptions")
    op.drop_table("push_subscriptions")
