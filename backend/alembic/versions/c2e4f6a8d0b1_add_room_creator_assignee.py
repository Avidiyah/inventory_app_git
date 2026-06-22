"""add creator + assignee to mass_stage_rooms

Revision ID: c2e4f6a8d0b1
Revises: c7e9a1b3d5f8
Create Date: 2026-06-22 12:00:00.000000

Work-order ownership + assignment. Each `mass_stage_rooms` row (a work order)
gains two nullable FKs to `users`:

- `created_by_id` — who created the work order. A supervisor sees only work
  orders they created (admin/owner see all).
- `assigned_to_id` — the technician the work order is assigned to. A technician
  sees only work orders assigned to them. Assignment is optional (NULL = none).

Both are plain (non-cascade) FKs, mirroring `mass_stages.created_by_id`. An
index on each backs the role-scoped list queries. No backfill: existing rows
get NULL for both (visible only to admin/owner until re-created/assigned).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c2e4f6a8d0b1"
down_revision: Union[str, Sequence[str], None] = "c7e9a1b3d5f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "mass_stage_rooms",
        sa.Column("created_by_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "mass_stage_rooms",
        sa.Column("assigned_to_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_mass_stage_rooms_created_by",
        "mass_stage_rooms",
        "users",
        ["created_by_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_mass_stage_rooms_assigned_to",
        "mass_stage_rooms",
        "users",
        ["assigned_to_id"],
        ["id"],
    )
    op.create_index(
        "ix_mass_stage_rooms_created_by_id", "mass_stage_rooms", ["created_by_id"]
    )
    op.create_index(
        "ix_mass_stage_rooms_assigned_to_id", "mass_stage_rooms", ["assigned_to_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_mass_stage_rooms_assigned_to_id", table_name="mass_stage_rooms")
    op.drop_index("ix_mass_stage_rooms_created_by_id", table_name="mass_stage_rooms")
    op.drop_constraint(
        "fk_mass_stage_rooms_assigned_to", "mass_stage_rooms", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_mass_stage_rooms_created_by", "mass_stage_rooms", type_="foreignkey"
    )
    op.drop_column("mass_stage_rooms", "assigned_to_id")
    op.drop_column("mass_stage_rooms", "created_by_id")
