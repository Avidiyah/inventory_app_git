"""standalone work orders (first-class entity)

Revision ID: b3d5f7a9c1e4
Revises: f1a3c5e7b9d4
Create Date: 2026-06-25 12:00:00.000000

Rebuilds work orders as a standalone first-class entity whose identity is its
`number` (unique case-insensitively + trimmed). Every surface -- scan-and-go,
Mass Stage, the Work Orders page, History -- references the one `work_orders`
row. Mass Stage no longer *owns* work orders: it references them through thin
`mass_stage_work_orders` slots.

This is a clean rebuild of the prior (uncommitted) WIP model: the old
overloaded `mass_stage_rooms` (work-order-as-a-room) and the room-keyed
`work_order_items` are dropped and recreated around `work_orders`. The
mass-stage/work-order data is **wiped** (dev rebuild); inventory `items` and
historical `transactions` are preserved (old txns keep their `work_order_number`
string with `work_order_id` NULL).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b3d5f7a9c1e4"
down_revision: Union[str, Sequence[str], None] = "f1a3c5e7b9d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 0. wipe the old mass-stage/work-order data (FK-safe order) ------
    op.execute("DELETE FROM mass_stage_items")
    op.execute("DELETE FROM mass_stage_rooms")
    op.execute("DELETE FROM mass_stages")
    op.drop_table("mass_stage_items")
    op.drop_table("mass_stage_rooms")

    # --- 1. work_orders (the entity) ------------------------------------
    op.create_table(
        "work_orders",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("number", sa.Text(), nullable=False),
        sa.Column("community", sa.Text(), nullable=True),
        sa.Column("building_number", sa.Text(), nullable=True),
        sa.Column("unit_number", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.Text(), nullable=False, server_default="in_progress"
        ),
        sa.Column(
            "entry_mode", sa.Text(), nullable=False, server_default="dispense"
        ),
        sa.Column("assigned_to_id", sa.UUID(), nullable=True),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["assigned_to_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # Case-insensitive + trimmed uniqueness on the number (the identity).
    op.create_index(
        "uq_work_orders_number_ci",
        "work_orders",
        [sa.text("lower(btrim(number))")],
        unique=True,
    )
    op.create_index(
        "ix_work_orders_assigned_to_id", "work_orders", ["assigned_to_id"]
    )
    op.create_index(
        "ix_work_orders_created_by_id", "work_orders", ["created_by_id"]
    )
    op.create_index("ix_work_orders_status", "work_orders", ["status"])

    # --- 2. mass_stages: add community + move the active-unique index ----
    op.add_column(
        "mass_stages",
        sa.Column("community", sa.Text(), nullable=False, server_default=""),
    )
    op.drop_index("uq_mass_stages_active_building", table_name="mass_stages")
    op.create_index(
        "uq_mass_stages_active_community_building",
        "mass_stages",
        ["community", "building_name"],
        unique=True,
        postgresql_where=sa.text("status <> 'completed'"),
    )

    # --- 3. transactions: affects_stock + work_order_id link ------------
    op.add_column(
        "transactions",
        sa.Column(
            "affects_stock",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "transactions", sa.Column("work_order_id", sa.UUID(), nullable=True)
    )
    op.create_foreign_key(
        "fk_transactions_work_order",
        "transactions",
        "work_orders",
        ["work_order_id"],
        ["id"],
    )
    op.create_index(
        "ix_transactions_work_order_id", "transactions", ["work_order_id"]
    )

    # --- 4. mass_stage_work_orders (slot) -------------------------------
    op.create_table(
        "mass_stage_work_orders",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("stage_id", sa.UUID(), nullable=False),
        sa.Column("work_order_id", sa.UUID(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["stage_id"], ["mass_stages.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["work_order_id"], ["work_orders.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "stage_id", "work_order_id", name="uq_mass_stage_work_orders_stage_wo"
        ),
    )
    op.create_index(
        "ix_mass_stage_work_orders_stage_id", "mass_stage_work_orders", ["stage_id"]
    )
    op.create_index(
        "ix_mass_stage_work_orders_work_order_id",
        "mass_stage_work_orders",
        ["work_order_id"],
    )

    # --- 5. mass_stage_items (truck-plan estimates, re-keyed) -----------
    op.create_table(
        "mass_stage_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("stage_work_order_id", sa.UUID(), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column("planned_quantity", sa.Numeric(), nullable=False),
        sa.Column(
            "loaded_quantity", sa.Numeric(), nullable=False, server_default="0"
        ),
        sa.Column(
            "returned_quantity", sa.Numeric(), nullable=False, server_default="0"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["stage_work_order_id"],
            ["mass_stage_work_orders.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "stage_work_order_id", "item_id", name="uq_mass_stage_items_slot_item"
        ),
    )

    # --- 6. work_order_items (actuals, keyed to work_orders) ------------
    op.create_table(
        "work_order_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("work_order_id", sa.UUID(), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column("quantity", sa.Numeric(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("transaction_id", sa.UUID(), nullable=True),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["work_order_id"], ["work_orders.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"]),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "work_order_id", "item_id", name="uq_work_order_items_wo_item"
        ),
    )
    op.create_index(
        "ix_work_order_items_work_order_id", "work_order_items", ["work_order_id"]
    )


def downgrade() -> None:
    # Reverse to the f1a3c5e7b9d4 shape. Work-order data is lost.
    op.drop_index(
        "ix_work_order_items_work_order_id", table_name="work_order_items"
    )
    op.drop_table("work_order_items")
    op.drop_table("mass_stage_items")
    op.drop_index(
        "ix_mass_stage_work_orders_work_order_id",
        table_name="mass_stage_work_orders",
    )
    op.drop_index(
        "ix_mass_stage_work_orders_stage_id", table_name="mass_stage_work_orders"
    )
    op.drop_table("mass_stage_work_orders")

    op.drop_index("ix_transactions_work_order_id", table_name="transactions")
    op.drop_constraint(
        "fk_transactions_work_order", "transactions", type_="foreignkey"
    )
    op.drop_column("transactions", "work_order_id")
    op.drop_column("transactions", "affects_stock")

    op.drop_index(
        "uq_mass_stages_active_community_building", table_name="mass_stages"
    )
    op.create_index(
        "uq_mass_stages_active_building",
        "mass_stages",
        ["building_name"],
        unique=True,
        postgresql_where=sa.text("status <> 'completed'"),
    )
    op.drop_column("mass_stages", "community")

    op.drop_index("ix_work_orders_status", table_name="work_orders")
    op.drop_index("ix_work_orders_created_by_id", table_name="work_orders")
    op.drop_index("ix_work_orders_assigned_to_id", table_name="work_orders")
    op.drop_index("uq_work_orders_number_ci", table_name="work_orders")
    op.drop_table("work_orders")

    # Recreate the old mass_stage_rooms + mass_stage_items (empty).
    op.create_table(
        "mass_stage_rooms",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("stage_id", sa.UUID(), nullable=False),
        sa.Column("room_number", sa.Text(), nullable=False),
        sa.Column("work_order_number", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
        sa.Column("assigned_to_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["stage_id"], ["mass_stages.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["assigned_to_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "stage_id", "room_number", name="uq_mass_stage_rooms_stage_room"
        ),
    )
    op.create_table(
        "mass_stage_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("room_id", sa.UUID(), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column("planned_quantity", sa.Numeric(), nullable=False),
        sa.Column(
            "loaded_quantity", sa.Numeric(), nullable=False, server_default="0"
        ),
        sa.Column(
            "returned_quantity", sa.Numeric(), nullable=False, server_default="0"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["room_id"], ["mass_stage_rooms.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "room_id", "item_id", name="uq_mass_stage_items_room_item"
        ),
    )
