"""Transaction history read service.

Layer: services. Backs `GET /transactions/history`. Performs the
JOIN across `transactions` / `items` / `users` and builds the
denormalised `TransactionHistoryPage` directly, so the router is a
pass-through and the frontend renders the table without N+1
lookups.

Schema import note: this is the one place a service imports from
`app.schemas`. The schema is used only to *construct* a value
object, not to validate inbound data, so the dependency direction
remains acceptable.
"""

import uuid
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Item, Transaction, User
from app.schemas.transactions import TransactionHistoryItem, TransactionHistoryPage


def list_history(
    db: Session,
    *,
    item_id: Optional[uuid.UUID],
    user_id: Optional[uuid.UUID],
    page: int,
    page_size: int,
) -> TransactionHistoryPage:
    """Return one page of transaction history, newest first.

    Filters `item_id` and `user_id` are optional and combine with
    AND. `User` is joined with an OUTER join because transactions
    may be recorded anonymously (NULL `user_id`) — an inner join
    would silently drop those rows from the history view.
    """
    query = (
        db.query(Transaction, Item, User)
        .join(Item, Item.id == Transaction.item_id)
        .outerjoin(User, User.id == Transaction.user_id)
    )

    if item_id is not None:
        query = query.filter(Transaction.item_id == item_id)
    if user_id is not None:
        query = query.filter(Transaction.user_id == user_id)

    total = query.count()

    rows = (
        query.order_by(Transaction.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = [
        TransactionHistoryItem(
            id=txn.id,
            item_id=txn.item_id,
            item_barcode=item.barcode,
            item_name=item.name,
            user_id=txn.user_id,
            username=user.username if user is not None else None,
            transaction_type=txn.transaction_type,
            quantity=txn.quantity,
            work_order_number=txn.work_order_number,
            created_at=txn.created_at,
        )
        for txn, item, user in rows
    ]

    return TransactionHistoryPage(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )
