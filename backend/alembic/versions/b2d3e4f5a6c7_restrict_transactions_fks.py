"""pin transactions FKs to ON DELETE RESTRICT

Revision ID: b2d3e4f5a6c7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-05 12:00:00.000000

The original `transactions` table created its `item_id` and `user_id`
foreign keys with no explicit `ondelete`, so Postgres applied NO ACTION
by default. In practice both deletes raise an `IntegrityError` when
referenced rows exist, but:

  * `delete_user` already catches that and re-raises a clean
    `UserHasTransactionsError` (→ 400),
  * `delete_item` does NOT, so deleting an item with transactions
    surfaces as a 500.

The service layer is being changed in the same patch to pre-check both
sides before the FK ever fires, so the user always sees a friendly 400.
This migration pins the DB-level guarantee that matches the service
intent: `ON DELETE RESTRICT` is the explicit, documented form of "the
delete is refused while children exist."
"""
from typing import Sequence, Union

from alembic import op


revision: str = "b2d3e4f5a6c7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Default Postgres naming for the FKs created without `name=...` in
# `4f0a7ce7d1ac_create_users_items_transactions_tables.py`.
ITEM_FK = "transactions_item_id_fkey"
USER_FK = "transactions_user_id_fkey"


def upgrade() -> None:
    op.drop_constraint(ITEM_FK, "transactions", type_="foreignkey")
    op.create_foreign_key(
        ITEM_FK,
        "transactions",
        "items",
        ["item_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.drop_constraint(USER_FK, "transactions", type_="foreignkey")
    op.create_foreign_key(
        USER_FK,
        "transactions",
        "users",
        ["user_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(USER_FK, "transactions", type_="foreignkey")
    op.create_foreign_key(
        USER_FK,
        "transactions",
        "users",
        ["user_id"],
        ["id"],
    )

    op.drop_constraint(ITEM_FK, "transactions", type_="foreignkey")
    op.create_foreign_key(
        ITEM_FK,
        "transactions",
        "items",
        ["item_id"],
        ["id"],
    )
