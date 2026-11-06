"""smr exclusion ground optional

Revision ID: 3e5a7c9b1d2f
Revises: 9b2c4d6e8f10
Create Date: 2026-11-06 15:00:00.000000

An excluded paper line no longer needs a ground (user, 2026-11-06): only what
is added to a work order needs a justification. The vocabulary stays for the
grounds that still carry meaning (`undated` charges itself when dated,
`removed` is the soft delete). No data changes.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "3e5a7c9b1d2f"
down_revision: Union[str, Sequence[str], None] = "9b2c4d6e8f10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CK = "ck_smr_labor_lines_excluded_ground"


def upgrade() -> None:
    op.drop_constraint(_CK, "smr_labor_lines", type_="check")


def downgrade() -> None:
    op.create_check_constraint(_CK, "smr_labor_lines", "status <> 'excluded' OR exclusion_ground IS NOT NULL")
