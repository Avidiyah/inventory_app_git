"""backfill non-positive item price user requests

Revision ID: faa2c4e6b8d0
Revises: f9b1d3e5a7c9
Create Date: 2026-08-05 16:00:00.000000

Zero-dollar (and defensive negative) prices are operationally missing prices.
Seed the same deduplicated request used for NULL-priced work-order materials.
"""

from datetime import datetime, timezone
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "faa2c4e6b8d0"
down_revision: Union[str, Sequence[str], None] = "f9b1d3e5a7c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT
                woi.item_id,
                MIN(wo.id::text)::uuid AS work_order_id,
                jsonb_agg(DISTINCT wo.number) AS work_order_numbers
            FROM work_order_items AS woi
            JOIN items AS item ON item.id = woi.item_id
            JOIN work_orders AS wo ON wo.id = woi.work_order_id
            WHERE item.price <= 0
              AND wo.archived_at IS NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM user_requests AS request
                  WHERE request.request_type = 'missing_item_price'
                    AND request.status = 'open'
                    AND request.item_id = woi.item_id
              )
            GROUP BY woi.item_id
            """
        )
    ).mappings().all()
    if not rows:
        return

    requests = sa.table(
        "user_requests",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("request_type", sa.Text()),
        sa.column("status", sa.Text()),
        sa.column("message", sa.Text()),
        sa.column("item_id", postgresql.UUID(as_uuid=True)),
        sa.column("work_order_id", postgresql.UUID(as_uuid=True)),
        sa.column("details", postgresql.JSONB()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    created_at = datetime.now(timezone.utc)
    connection.execute(
        requests.insert(),
        [
            {
                "id": uuid.uuid4(),
                "request_type": "missing_item_price",
                "status": "open",
                "message": "Please add a price and product link to this item",
                "item_id": row["item_id"],
                "work_order_id": row["work_order_id"],
                "details": {
                    "work_order_numbers": list(row["work_order_numbers"] or []),
                    "migration_source": revision,
                },
                "created_at": created_at,
            }
            for row in rows
        ],
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM user_requests
        WHERE request_type = 'missing_item_price'
          AND details ->> 'migration_source' = 'faa2c4e6b8d0'
        """
    )
