"""add mass staging tables

Revision ID: b1f3d5a7c9e2
Revises: a7c9e1f3b5d2
Create Date: 2026-06-16 12:00:00.000000

Mass-staging lets a supervisor batch-plan materials for an entire building.
This migration adds three tables:

- `mass_stages`: one staging plan per building, with a `status`
  (`planning` / `loading` / `completed`). The partial unique index
  `uq_mass_stages_active_building` enforces at most one *active*
  (non-completed) stage per `building_name`.
- `mass_stage_rooms`: rooms within a stage, each paired with one work order.
  `sort_order` drives the load allocation rule (fill rooms in order, overflow
  to the last). `ON DELETE CASCADE` from the stage; `UNIQUE(stage_id,
  room_number)` since room numbers only distinguish within a stage.
- `mass_stage_items`: an item planned for a room plus `loaded_quantity` /
  `returned_quantity` actuals. `ON DELETE CASCADE` from the room;
  `UNIQUE(room_id, item_id)` for one row per item per room. The `item_id` FK
  is plain (not cascade) so a referenced item cannot be hard-deleted -- benign
  because items are soft-deleted via `items.archived_at`.

No backfill: all three tables start empty. Loading writes ordinary `dispense`
rows in `transactions`; this migration does not touch existing tables.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b1f3d5a7c9e2"
down_revision: Union[str, Sequence[str], None] = "a7c9e1f3b5d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mass_stages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("building_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="planning"),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_mass_stages_active_building",
        "mass_stages",
        ["building_name"],
        unique=True,
        postgresql_where=sa.text("status <> 'completed'"),
    )

    op.create_table(
        "mass_stage_rooms",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("stage_id", sa.UUID(), nullable=False),
        sa.Column("room_number", sa.Text(), nullable=False),
        sa.Column("work_order_number", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["stage_id"], ["mass_stages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stage_id", "room_number", name="uq_mass_stage_rooms_stage_room"),
    )
    op.create_index("ix_mass_stage_rooms_stage_id", "mass_stage_rooms", ["stage_id"])

    op.create_table(
        "mass_stage_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("room_id", sa.UUID(), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column("planned_quantity", sa.Numeric(), nullable=False),
        sa.Column("loaded_quantity", sa.Numeric(), nullable=False, server_default="0"),
        sa.Column("returned_quantity", sa.Numeric(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["room_id"], ["mass_stage_rooms.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("room_id", "item_id", name="uq_mass_stage_items_room_item"),
    )
    op.create_index("ix_mass_stage_items_room_id", "mass_stage_items", ["room_id"])
    op.create_index("ix_mass_stage_items_item_id", "mass_stage_items", ["item_id"])


def downgrade() -> None:
    op.drop_index("ix_mass_stage_items_item_id", table_name="mass_stage_items")
    op.drop_index("ix_mass_stage_items_room_id", table_name="mass_stage_items")
    op.drop_table("mass_stage_items")
    op.drop_index("ix_mass_stage_rooms_stage_id", table_name="mass_stage_rooms")
    op.drop_table("mass_stage_rooms")
    op.drop_index("uq_mass_stages_active_building", table_name="mass_stages")
    op.drop_table("mass_stages")
