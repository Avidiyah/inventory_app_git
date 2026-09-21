"""add attendance_punches.deleted_at

Revision ID: c4a6e8b0d2f5
Revises: b7d9f1a3c5e8
Create Date: 2026-09-21 18:00:00.000000

P3's delete is soft. `b7d9f1a3c5e8` reasoned that a deleted punch's own
deletion would be recorded "against the punch that is going away" -- which
the CASCADE then removes, leaving no trace of a deleted pay record. A
`deleted_at` keeps the row and its audit and makes a wrong delete a one-line
undo rather than a restore from backup.

The open-punch index is rebuilt rather than added to: a soft-deleted open
punch must not occupy the one open slot a person has.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c4a6e8b0d2f5"
down_revision: Union[str, Sequence[str], None] = "b7d9f1a3c5e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("attendance_punches",
                  sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_index("uq_attendance_punches_open_user", table_name="attendance_punches")
    op.create_index(
        "uq_attendance_punches_open_user",
        "attendance_punches",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_attendance_punches_open_user", table_name="attendance_punches")
    op.create_index(
        "uq_attendance_punches_open_user",
        "attendance_punches",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )
    op.drop_column("attendance_punches", "deleted_at")
