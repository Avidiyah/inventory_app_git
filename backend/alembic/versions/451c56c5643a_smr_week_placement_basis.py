"""smr week placement basis

Revision ID: 451c56c5643a
Revises: 8e0f2a4b5c63
Create Date: 2026-11-06 16:00:00.000000

Decision 13 generalised (user 2026-11-06): a second placement basis,
`week placement (weekly reports)`, may charge with a blank day. The charged
check now admits either placement basis and requires the week on it. No
data change: the tables are empty until the paper import runs.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "451c56c5643a"
down_revision: Union[str, Sequence[str], None] = "8e0f2a4b5c63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "smr_labor_lines"
_NAME = "ck_smr_labor_lines_charged_dated"
_WEEK1 = "Week 1 placement (crew sheets, Supplement)"
_WEEKLY = "week placement (weekly reports)"
_OLD = f"status <> 'charged' OR work_date IS NOT NULL OR date_basis = '{_WEEK1}'"
_NEW = (
    "status <> 'charged' OR work_date IS NOT NULL "
    f"OR (date_basis IN ('{_WEEK1}', '{_WEEKLY}') AND week IS NOT NULL)"
)


def upgrade() -> None:
    op.drop_constraint(_NAME, _TABLE, type_="check")
    op.create_check_constraint(_NAME, _TABLE, _NEW)


def downgrade() -> None:
    op.drop_constraint(_NAME, _TABLE, type_="check")
    op.create_check_constraint(_NAME, _TABLE, _OLD)
