"""backfill work_order_items from linked dispenses

Revision ID: c4e6a8b0d2f5
Revises: b3d5f7a9c1e4
Create Date: 2026-06-29 12:00:00.000000

When work orders became a first-class entity, the Scan/Stock page, scan-and-go,
and Mass Stage truck-load wrote a `dispense` transaction carrying `work_order_id`
but never created the `work_order_items` line the Work Orders page renders -- so
those materials were invisible there. The write paths now create the line; this
one-time data migration absorbs the *existing* linked dispenses into lines so
historical work orders show their materials too.

For each `(work_order_id, item_id)` with non-voided `dispense` transactions and no
line yet, insert one line whose quantity is the summed units. Stock-neutral: the
dispenses already moved on-hand when they were written. Idempotent via the
NOT EXISTS guard. `mode` is `dispense` (these moved stock); `transaction_id` is
left NULL because a line now aggregates many transactions (membership is derived
by the pair, not this column).
"""
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa


revision: str = "c4e6a8b0d2f5"
down_revision: Union[str, Sequence[str], None] = "b3d5f7a9c1e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    orphans = bind.execute(
        sa.text(
            """
            SELECT t.work_order_id AS work_order_id,
                   t.item_id       AS item_id,
                   SUM(t.quantity) AS total
            FROM transactions t
            WHERE t.work_order_id IS NOT NULL
              AND t.transaction_type = 'dispense'
              AND t.voided_at IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM work_order_items wi
                  WHERE wi.work_order_id = t.work_order_id
                    AND wi.item_id = t.item_id
              )
            GROUP BY t.work_order_id, t.item_id
            """
        )
    ).fetchall()

    if not orphans:
        return

    insert = sa.text(
        """
        INSERT INTO work_order_items
            (id, work_order_id, item_id, quantity, mode, transaction_id,
             created_by_id, created_at, updated_at)
        VALUES
            (:id, :work_order_id, :item_id, :quantity, 'dispense', NULL,
             NULL, now(), now())
        """
    )
    for row in orphans:
        bind.execute(
            insert,
            {
                "id": uuid.uuid4(),
                "work_order_id": row.work_order_id,
                "item_id": row.item_id,
                "quantity": row.total,
            },
        )


def downgrade() -> None:
    # Data-only backfill: the synthesized lines are indistinguishable from
    # hand-logged ones, so there is nothing safe to selectively undo. No-op.
    pass
