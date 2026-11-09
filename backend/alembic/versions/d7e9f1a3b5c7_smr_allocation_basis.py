"""smr allocation basis

Revision ID: d7e9f1a3b5c7
Revises: c4d6e8f0a2b4
Create Date: 2026-11-09 16:00:00.000000

User 2026-11-09: the SMR27 post-audit allocations charge with a week and no
day under a third placement basis, `week placement (post-audit allocation)`.
The charged check admits it beside the other two. No data change.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "d7e9f1a3b5c7"
down_revision: Union[str, Sequence[str], None] = "c4d6e8f0a2b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "smr_labor_lines"
_NAME = "ck_smr_labor_lines_charged_dated"
_BASES = ["Week 1 placement (crew sheets, Supplement)", "week placement (weekly reports)"]
_ALLOCATION = "week placement (post-audit allocation)"


def _check(bases: list[str]) -> str:
    listed = ", ".join(f"'{basis}'" for basis in bases)
    return f"status <> 'charged' OR work_date IS NOT NULL OR (date_basis IN ({listed}) AND week IS NOT NULL)"


def upgrade() -> None:
    op.drop_constraint(_NAME, _TABLE, type_="check")
    op.create_check_constraint(_NAME, _TABLE, _check(_BASES + [_ALLOCATION]))


def downgrade() -> None:
    op.drop_constraint(_NAME, _TABLE, type_="check")
    op.create_check_constraint(_NAME, _TABLE, _check(_BASES))
