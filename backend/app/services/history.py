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
from datetime import date, datetime, time, timedelta, timezone
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


def _date_range_bounds(
    date_from: Optional[date], date_to: Optional[date]
) -> tuple[Optional[datetime], Optional[datetime]]:
    """Return `(start, end)` tz-aware UTC datetime bounds for a history
    date-range filter, with `None` for an absent side.

    The client sends calendar dates (`YYYY-MM-DD`, from a date input).
    `start` is midnight UTC on `date_from`; `end` is midnight UTC on the day
    AFTER `date_to`, so the filter is `created_at >= start` AND
    `created_at < end` and `date_to` is therefore included in full (a
    half-open interval avoids the "23:59:59 vs microseconds" edge cases of an
    inclusive upper bound). Bounds are interpreted in UTC -- how `created_at`
    is stored -- so near local midnight a row can land on the adjacent UTC
    day; this is a filter convenience, not a billing boundary.

    A reversed range (`date_from` after `date_to`) yields `start >= end`,
    which matches no rows -- an empty page, not an error.
    """
    start = (
        datetime.combine(date_from, time.min, tzinfo=timezone.utc)
        if date_from is not None
        else None
    )
    end = (
        datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone.utc)
        if date_to is not None
        else None
    )
    return start, end


def list_history(
    db: Session,
    *,
    item_id: Optional[uuid.UUID],
    user_id: Optional[uuid.UUID],
    work_order_number: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    page: int,
    page_size: int,
    include_price: bool = False,
) -> TransactionHistoryPage:
    """Return one page of transaction history, newest first.

    Filters `item_id`, `user_id`, `work_order_number`, `date_from`, and
    `date_to` are optional and combine with AND. `work_order_number` is a
    case-sensitive substring match (`LIKE %value%`); literal `%` and `_` in
    the input are escaped with `\\` and the matching ESCAPE clause so a user
    who types `%` matches a literal percent, not "anything". An empty /
    whitespace-only value is treated as "no filter".

    `date_from` / `date_to` are calendar dates bounding `created_at`. The
    range is half-open in UTC (`>= midnight(date_from)` AND
    `< midnight(date_to + 1 day)`) so `date_to` is included in full; see
    `_date_range_bounds` for the UTC-boundary caveat.

    `include_price` carries the per-unit `item_price` AND the
    `billable_quantity` billing override into each row only when the
    caller is Admin/Owner; for lower roles both stay `None` so neither
    cost data nor billing adjustments are sent to the client (the router
    decides this from the requester's role).

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
    start, end = _date_range_bounds(date_from, date_to)
    if start is not None:
        query = query.filter(Transaction.created_at >= start)
    if end is not None:
        query = query.filter(Transaction.created_at < end)

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
            work_order_id=txn.work_order_id,
            reason=txn.reason,
            # Per-row charges are emitted only for ad-hoc (non-work-order)
            # transactions. A row linked to a work order (`work_order_id`) bills
            # through its `work_order_items` LINE -- the authoritative
            # "materials used" total shown on the Work Orders page -- so
            # charging it here too would double-count, and a line edit's signed
            # stock-correction `adjust` would bill as a nonsensical negative.
            # Such rows stay a pure inventory record here (price suppressed).
            #
            # For an ad-hoc row the price is frozen to the snapshot taken when
            # it was written, so editing an item price does NOT rewrite past
            # values. The single exception: a row written while the item was
            # free (snapshot 0) was never a real price and tracks the live
            # `Item.price`; a NULL snapshot (legacy/adjust) likewise falls back
            # to live.
            item_price=(
                None
                if not include_price or txn.work_order_id is not None
                else (
                    item.price
                    if txn.unit_price is None or txn.unit_price == 0
                    else txn.unit_price
                )
            ),
            billable_quantity=(
                txn.billable_quantity
                if include_price and txn.work_order_id is None
                else None
            ),
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
