"""replace sessions.last_active_at with expires_at (remember-me)

Revision ID: c7e9a1b3d5f8
Revises: b1f3d5a7c9e2
Create Date: 2026-06-22 09:00:00.000000

Switches the session lifetime model from a 10-minute sliding idle
timeout to an absolute-expiry / remember-me model. `last_active_at`
(only ever read/written by the now-removed idle timer) is dropped and
replaced by a nullable `expires_at`:

- NULL  -> no server-side cap (non-remembered; ends on browser close).
- a timestamp -> hard absolute cap (remembered device, login + 12h).

Any in-flight session loses its idle data and is left with
`expires_at = NULL`, i.e. treated as non-remembered -- worst case a
logged-in user signs in once more.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7e9a1b3d5f8"
down_revision: Union[str, Sequence[str], None] = "b1f3d5a7c9e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_column("sessions", "last_active_at")


def downgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_column("sessions", "expires_at")
