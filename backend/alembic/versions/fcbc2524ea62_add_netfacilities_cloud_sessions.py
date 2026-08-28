"""add netfacilities_cloud_sessions

Revision ID: fcbc2524ea62
Revises: a2c4e6b8d0f1
Create Date: 2026-08-28 12:00:00.000000

Backs the per-user NetFacilities cloud-auth path (spec
docs/superpowers/specs/2026-08-28-netfacilities-cloud-auth-design.md, D8).
Nothing to backfill: no cloud session can exist before this feature ships.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "fcbc2524ea62"
down_revision: Union[str, Sequence[str], None] = "a2c4e6b8d0f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "netfacilities_cloud_sessions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "user_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("storage_state", sa.Text(), nullable=False),
        sa.Column("steel_profile_id", sa.Text(), nullable=True),
        sa.Column("signed_in_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_download_filename", sa.Text(), nullable=True),
        sa.Column("last_download_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("netfacilities_cloud_sessions")
