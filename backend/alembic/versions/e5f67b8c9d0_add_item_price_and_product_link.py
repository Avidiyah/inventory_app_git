from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e5f67b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column("items", sa.Column("price", sa.Numeric(), nullable=True))
    op.add_column("items", sa.Column("product_link", sa.Text(), nullable=True))

def downgrade() -> None:
    op.drop_column("items", "product_link")
    op.drop_column("items", "price")

"""This module defines the SQLAlchemy models
for the application. These are the Python classes
that represent the database tables. Each class
corresponds to a table, and the attributes of the
class correspond to the columns in the table.
The models also define relationships between
tables, which allow for easy querying of related
data. Any changes to the database schema must be
reflected in these models, as well as in the
Alembic migrations that manage the database
schema changes over time."""