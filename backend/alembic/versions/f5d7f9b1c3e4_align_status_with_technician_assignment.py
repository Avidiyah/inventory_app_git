"""align pre-work status with technician assignment

Revision ID: f5d7f9b1c3e4
Revises: f4c6e8a0b2d3
Create Date: 2026-08-03 00:30:00.000000

Created/Assigned describes technician assignment, not CSV supervisor routing.
Only pre-work rows are reconciled; In-Progress and later lifecycle history is
preserved. The first material activity is advanced by application services.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f5d7f9b1c3e4"
down_revision: Union[str, Sequence[str], None] = "f4c6e8a0b2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE work_orders
            SET status = CASE
                WHEN assigned_to_id IS NULL THEN 'created'
                ELSE 'assigned'
            END
            WHERE status IN ('created', 'assigned')
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE work_orders
            SET status = CASE
                WHEN supervisor_id IS NULL THEN 'created'
                ELSE 'assigned'
            END
            WHERE status IN ('created', 'assigned')
            """
        )
    )
