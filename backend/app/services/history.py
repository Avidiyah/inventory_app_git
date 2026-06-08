"""Transaction history read service.

Layer: services. Backs `GET /transactions/`. Performs the
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


# Backslash is the LIKE escape character we pass to SQLAlchemy below.
# Escape the escape char first, then the two LIKE wildcards.
_LIKE_ESCAPE = "\\"


def _build_wo_like_pattern(value):
    """Return a `(pattern, escape_char)` tuple suitable for
    `Column.like(pattern, escape=escape_char)`, or `None` if the value
    should not produce a filter at all (None / empty / whitespace-only).

    The pattern is `%<escaped value>%` so the match is a case-sensitive
    substring; literal `%` and `_` in the input are escaped so a user
    who types `_` matches a literal underscore, not "any single char".
    """
    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    escaped = (
        trimmed.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
        .replace("%", _LIKE_ESCAPE + "%")
        .replace("_", _LIKE_ESCAPE + "_")
    )
    return f"%{escaped}%", _LIKE_ESCAPE


def list_history(
    db: Session,
    *,
    item_id: Optional[uuid.UUID],
    user_id: Optional[uuid.UUID],
    work_order_number: Optional[str] = None,
    page: int,
    page_size: int,
    include_price: bool = False,
) -> TransactionHistoryPage:
    """Return one page of transaction history, newest first.

    Filters `item_id`, `user_id`, and `work_order_number` are optional
    and combine with AND. `work_order_number` is a case-sensitive
    substring match (`LIKE %value%`); literal `%` and `_` in the input
    are escaped with `\\` and the matching ESCAPE clause so a user who
    types `%` matches a literal percent, not "anything". An empty /
    whitespace-only value is treated as "no filter".

    `include_price` carries the per-unit `item_price` into each row only
    when the caller is Admin/Owner; for lower roles it stays `None` so
    cost data is never sent to the client (the router decides this from
    the requester's role).

    `User` is joined with an OUTER join because transactions may be
    recorded anonymously (NULL `user_id`) — an inner join would
    silently drop those rows from the history view.

    Voided (soft-deleted) transactions are excluded entirely: a void
    sets `voided_at`, and history only ever shows live rows
    (`voided_at IS NULL`). This applies to the filtered `total` too, so
    pagination counts match what is shown.
    """
    query = (
        db.query(Transaction, Item, User)
        .join(Item, Item.id == Transaction.item_id)
        .outerjoin(User, User.id == Transaction.user_id)
        .filter(Transaction.voided_at.is_(None))
    )

    if item_id is not None:
        query = query.filter(Transaction.item_id == item_id)
    if user_id is not None:
        query = query.filter(Transaction.user_id == user_id)
    wo_filter = _build_wo_like_pattern(work_order_number)
    if wo_filter is not None:
        pattern, escape_char = wo_filter
        query = query.filter(
            Transaction.work_order_number.like(pattern, escape=escape_char)
        )

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
            reason=txn.reason,
            item_price=item.price if include_price else None,
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
