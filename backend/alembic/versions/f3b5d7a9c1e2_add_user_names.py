"""add first and last names to users

Revision ID: f3b5d7a9c1e2
Revises: f2a4c6b8d0e1
Create Date: 2026-08-02 23:00:00.000000

Human names become the display identity and the CSV work-order routing key;
`username` remains the login/account-management identifier. Columns are
nullable for legacy accounts because a username is not a reliable source of a
person's name. New users require both fields, and the Users page provides an
explicit name-update path for existing accounts.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f3b5d7a9c1e2"
down_revision: Union[str, Sequence[str], None] = "f2a4c6b8d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("first_name", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("last_name", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "last_name")
    op.drop_column("users", "first_name")
