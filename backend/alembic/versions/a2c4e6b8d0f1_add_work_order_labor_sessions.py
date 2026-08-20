"""add work_order_labor_sessions (tracked start/stop labor)

Revision ID: a2c4e6b8d0f1
Revises: 1d2e3f4a5b6c
Create Date: 2026-08-19 12:00:00.000000

Tracked time replaces the hand-keyed hours box for technicians. A session
records when work started and stopped; stopping one produces an ordinary
``work_order_labor`` row and links back to it, so every existing billing read
path (``billed_labor_minutes``, the receipt, the CSV export, the detail
response) is untouched and ``work_order_labor.minutes`` stays NOT NULL.

Nothing is backfilled. Existing labor rows have no session and must keep
rendering as a bare duration -- that is the fallback the labor card relies on.

No change to ``work_orders`` despite the new ``ready_to_complete`` status:
``status`` is a plain Text column with no CHECK constraint (``f4c6e8a0b2d3``
only moved the server default), so a new status value is app-level only.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a2c4e6b8d0f1"
down_revision: Union[str, Sequence[str], None] = "1d2e3f4a5b6c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "work_order_labor_sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("work_order_id", sa.UUID(), nullable=False),
        sa.Column("technician_id", sa.UUID(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("labor_id", sa.UUID(), nullable=True),
        sa.Column("auto_closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["work_order_id"], ["work_orders.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["technician_id"], ["users.id"]),
        # SET NULL rather than CASCADE: a supervisor deleting a mistaken labor
        # row is correcting the bill, not erasing the fact that somebody was on
        # site. The session survives as the record of when.
        sa.ForeignKeyConstraint(
            ["labor_id"], ["work_order_labor.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_work_order_labor_sessions_work_order_id",
        "work_order_labor_sessions",
        ["work_order_id"],
    )
    # One running session per person, across every work order. Enforced here
    # rather than by a service check so two taps that race cannot both win.
    op.create_index(
        "uq_work_order_labor_sessions_running_technician",
        "work_order_labor_sessions",
        ["technician_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_work_order_labor_sessions_running_technician",
        table_name="work_order_labor_sessions",
    )
    op.drop_index(
        "ix_work_order_labor_sessions_work_order_id",
        table_name="work_order_labor_sessions",
    )
    op.drop_table("work_order_labor_sessions")
