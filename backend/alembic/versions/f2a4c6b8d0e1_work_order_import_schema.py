"""work order CSV-import schema + legacy backfill

Revision ID: f2a4c6b8d0e1
Revises: e4a6c8b0d2f7
Create Date: 2026-08-02 12:00:00.000000

The mass work-order CSV export becomes the new default schema. `work_orders`
gains the export's columns -- `location` (raw), `output_to`, `vendor_assignee`
(the raw "ASSIGNED TO" contact name), `service_type`, `schedule_date` (raw) --
plus `supervisor_id` (the supervisor a work order is routed to; set by
name-match at import or manually) and a `legacy` flag.

Legacy backfill: every work order that already exists is pre-import, so it is
marked `legacy = true` and its OLD descriptive attributes (community /
building_number / unit_number / description) are dropped to NULL. Its `number`,
`status`, `entry_mode`, assignment, and all `work_order_items` are kept intact --
so an already-priced-out work order stays fully searchable, just with empty
new-schema fields.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2a4c6b8d0e1"
down_revision: Union[str, Sequence[str], None] = "e4a6c8b0d2f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("work_orders", sa.Column("location", sa.Text(), nullable=True))
    op.add_column("work_orders", sa.Column("output_to", sa.Text(), nullable=True))
    op.add_column("work_orders", sa.Column("vendor_assignee", sa.Text(), nullable=True))
    op.add_column("work_orders", sa.Column("service_type", sa.Text(), nullable=True))
    op.add_column("work_orders", sa.Column("schedule_date", sa.Text(), nullable=True))
    op.add_column("work_orders", sa.Column("supervisor_id", sa.UUID(), nullable=True))
    op.add_column(
        "work_orders",
        sa.Column(
            "legacy", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.create_foreign_key(
        "fk_work_orders_supervisor",
        "work_orders",
        "users",
        ["supervisor_id"],
        ["id"],
    )
    op.create_index(
        "ix_work_orders_supervisor_id", "work_orders", ["supervisor_id"]
    )

    # Legacy backfill: mark every pre-existing work order and drop its old
    # descriptive attributes (number / status / entry_mode / assignment / items
    # are untouched so priced-out work orders stay searchable).
    op.execute(
        sa.text(
            """
            UPDATE work_orders
            SET legacy = true,
                community = NULL,
                building_number = NULL,
                unit_number = NULL,
                description = NULL
            """
        )
    )


def downgrade() -> None:
    # The legacy null-out is a lossy data migration with nothing safe to restore,
    # so downgrade only reverses the schema additions (mirrors c4e6a8b0d2f5).
    op.drop_index("ix_work_orders_supervisor_id", table_name="work_orders")
    op.drop_constraint(
        "fk_work_orders_supervisor", "work_orders", type_="foreignkey"
    )
    op.drop_column("work_orders", "legacy")
    op.drop_column("work_orders", "supervisor_id")
    op.drop_column("work_orders", "schedule_date")
    op.drop_column("work_orders", "service_type")
    op.drop_column("work_orders", "vendor_assignee")
    op.drop_column("work_orders", "output_to")
    op.drop_column("work_orders", "location")
