"""rename item_request rows to catalogue_request

Revision ID: d1e3f5a7b9c2
Revises: c6e8a0b2d4f7
Create Date: 2026-09-08 12:00:00.000000

Data only, no DDL. `user_requests.status` and `request_type` are Text and
the domain layer owns their vocabulary; a CHECK is deliberately not added,
matching how the other statuses are enforced.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "d1e3f5a7b9c2"
down_revision: Union[str, Sequence[str], None] = "c6e8a0b2d4f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE user_requests SET request_type = 'catalogue_request' "
        "WHERE request_type = 'item_request'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE user_requests SET request_type = 'item_request' "
        "WHERE request_type = 'catalogue_request'"
    )
