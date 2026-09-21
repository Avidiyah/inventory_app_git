"""add attendance_punches and attendance_punch_edits

Revision ID: b7d9f1a3c5e8
Revises: e2f4a6c8b0d3
Create Date: 2026-09-21 12:00:00.000000

The attendance record (spec 2026-09-21-attendance-timesheet-design.md 1):
on-shift time, separate from the billable `work_order_labor_sessions` record
and owned by Admin+. Nothing is backfilled -- there is no historical source
for "was this person at work," and inventing one from labor sessions would
put an estimate into a pay record.

`attendance_punch_edits` is created here although nothing writes it until
P3: 1 defines the pair as one unit, and a second migration for one design
section is churn.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b7d9f1a3c5e8"
down_revision: Union[str, Sequence[str], None] = "e2f4a6c8b0d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "attendance_punches",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("start_source", sa.Text(), nullable=False),
        sa.Column("end_source", sa.Text(), nullable=True),
        sa.Column("needs_review", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_attendance_punches_user_started",
                    "attendance_punches", ["user_id", "started_at"])
    # One open punch per person, in the database rather than in a service
    # check that races -- the mechanism
    # `uq_work_order_labor_sessions_running_technician` already uses.
    op.create_index(
        "uq_attendance_punches_open_user",
        "attendance_punches",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )
    op.create_table(
        "attendance_punch_edits",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("punch_id", sa.UUID(), nullable=False),
        sa.Column("edited_by_id", sa.UUID(), nullable=False),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("field", sa.Text(), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        # CASCADE: the audit row describes an edit to this punch and has no
        # meaning without it. A deleted punch's own deletion is itself
        # recorded by P3 against the punch that is going away, so nothing of
        # value survives the parent.
        sa.ForeignKeyConstraint(["punch_id"], ["attendance_punches.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["edited_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_attendance_punch_edits_punch_id",
                    "attendance_punch_edits", ["punch_id"])


def downgrade() -> None:
    op.drop_index("ix_attendance_punch_edits_punch_id",
                  table_name="attendance_punch_edits")
    op.drop_table("attendance_punch_edits")
    op.drop_index("uq_attendance_punches_open_user",
                  table_name="attendance_punches")
    op.drop_index("ix_attendance_punches_user_started",
                  table_name="attendance_punches")
    op.drop_table("attendance_punches")
