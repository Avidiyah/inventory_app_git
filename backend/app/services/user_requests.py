"""Durable operational request queue.

The queue is intentionally generic. Scan / Stock raises an
``inventory_recount`` request when recorded stock is short. Any work-order
material path raises one deduplicated ``missing_item_price`` request when the
item has no price. Each request is staged in the same database transaction as
the operation that raised it.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session, joinedload

from app.domain.errors import UserRequestNotFoundError
from app.domain.list_limits import fetch_limit
from app.models import UserRequest
from app.services._list_cap import capped


REQUEST_INVENTORY_RECOUNT = "inventory_recount"
REQUEST_MISSING_ITEM_PRICE = "missing_item_price"
STATUS_OPEN = "open"
STATUS_RESOLVED = "resolved"


def create_inventory_recount_request(
    db: Session,
    *,
    item_id: uuid.UUID,
    transaction_id: uuid.UUID,
    work_order_id: Optional[uuid.UUID],
    work_order_number: Optional[str],
    created_by_id: Optional[uuid.UUID],
    recorded_quantity_before: Decimal,
    dispensed_quantity: Decimal,
    shortage_quantity: Decimal,
) -> UserRequest:
    """Stage one open recount request; the caller owns the surrounding commit."""
    request = UserRequest(
        request_type=REQUEST_INVENTORY_RECOUNT,
        status=STATUS_OPEN,
        message="Please re-count stock",
        item_id=item_id,
        transaction_id=transaction_id,
        work_order_id=work_order_id,
        created_by_id=created_by_id,
        details={
            "recorded_quantity_before": str(recorded_quantity_before),
            "dispensed_quantity": str(dispensed_quantity),
            "shortage_quantity": str(shortage_quantity),
            "work_order_number": work_order_number,
        },
    )
    db.add(request)
    return request


def create_or_update_missing_price_request(
    db: Session,
    *,
    item_id: uuid.UUID,
    work_order_id: uuid.UUID,
    work_order_number: Optional[str],
    created_by_id: Optional[uuid.UUID],
) -> UserRequest:
    """Stage one open missing-price request per item.

    Every caller already owns the item-row lock, so concurrent work-order
    dispenses for the same item serialize before reaching this lookup. Repeated
    use does not flood the queue; it adds the work-order number to the request's
    generic JSON details instead.
    """
    # SessionLocal deliberately disables autoflush. Mass Stage may attach one
    # item to several work orders before its single commit, so inspect pending
    # objects before querying persisted rows or the same request would be staged
    # more than once in that transaction.
    request = next(
        (
            candidate
            for candidate in db.new
            if isinstance(candidate, UserRequest)
            and candidate.request_type == REQUEST_MISSING_ITEM_PRICE
            and candidate.status == STATUS_OPEN
            and candidate.item_id == item_id
        ),
        None,
    )
    if request is None:
        request = (
            db.query(UserRequest)
            .filter(
                UserRequest.request_type == REQUEST_MISSING_ITEM_PRICE,
                UserRequest.status == STATUS_OPEN,
                UserRequest.item_id == item_id,
            )
            .first()
        )
    if request is None:
        numbers = [work_order_number] if work_order_number else []
        request = UserRequest(
            request_type=REQUEST_MISSING_ITEM_PRICE,
            status=STATUS_OPEN,
            message="Please add a price and product link to this item",
            item_id=item_id,
            work_order_id=work_order_id,
            created_by_id=created_by_id,
            details={"work_order_numbers": numbers},
        )
        db.add(request)
        return request

    details = dict(request.details or {})
    numbers = list(details.get("work_order_numbers") or [])
    if work_order_number and work_order_number not in numbers:
        numbers.append(work_order_number)
        details["work_order_numbers"] = numbers
        request.details = details
    return request


def resolve_missing_price_requests(
    db: Session,
    *,
    item_id: uuid.UUID,
    resolved_by_id: Optional[uuid.UUID],
) -> int:
    """Resolve every open missing-price request for an item atomically.

    The item update owns the surrounding commit. Requests remain in resolved
    history rather than being deleted from the audit trail.
    """
    requests = (
        db.query(UserRequest)
        .filter(
            UserRequest.request_type == REQUEST_MISSING_ITEM_PRICE,
            UserRequest.status == STATUS_OPEN,
            UserRequest.item_id == item_id,
        )
        .with_for_update()
        .all()
    )
    now = datetime.now(timezone.utc)
    for request in requests:
        request.status = STATUS_RESOLVED
        request.resolved_at = now
        request.resolved_by_id = resolved_by_id
        request.resolution_note = "Item price and product link added."
    return len(requests)


def list_user_requests(
    db: Session, *, status: Optional[str] = STATUS_OPEN
) -> list[UserRequest]:
    """Requests newest-first, optionally filtered by status.

    Capped at `list_limits.MAX_LIST_ROWS` (X3). This is the list most likely
    to grow without anyone watching -- requests accumulate from short counts
    and missing prices and are only cleared by someone resolving them -- so
    the `event=list.truncated` trigger matters more here than elsewhere.
    """
    query = db.query(UserRequest).options(
        joinedload(UserRequest.item),
        joinedload(UserRequest.work_order),
        joinedload(UserRequest.creator),
        joinedload(UserRequest.resolver),
    )
    if status is not None:
        query = query.filter(UserRequest.status == status)
    return capped(
        query.order_by(UserRequest.created_at.desc()).limit(fetch_limit()).all(),
        what="user_requests",
    )


def update_user_request(
    db: Session,
    request_id: uuid.UUID,
    *,
    status: str,
    resolution_note: Optional[str],
    resolved_by_id: uuid.UUID,
) -> UserRequest:
    request = (
        db.query(UserRequest)
        .filter(UserRequest.id == request_id)
        .with_for_update()
        .first()
    )
    if request is None:
        raise UserRequestNotFoundError("User request not found.")

    request.status = status
    if status == STATUS_RESOLVED:
        request.resolved_at = datetime.now(timezone.utc)
        request.resolved_by_id = resolved_by_id
        request.resolution_note = resolution_note
    else:
        request.resolved_at = None
        request.resolved_by_id = None
        request.resolution_note = None
    db.commit()
    return _get_user_request(db, request.id)


def resolve_for_transaction(
    db: Session,
    *,
    transaction_id: uuid.UUID,
    resolved_by_id: Optional[uuid.UUID],
) -> None:
    """Resolve an open request when its source scan is removed.

    The caller owns the commit so this update stays atomic with the transaction
    void and stock/work-order reversal.
    """
    request = (
        db.query(UserRequest)
        .filter(
            UserRequest.transaction_id == transaction_id,
            UserRequest.status == STATUS_OPEN,
        )
        .first()
    )
    if request is None:
        return
    request.status = STATUS_RESOLVED
    request.resolved_at = datetime.now(timezone.utc)
    request.resolved_by_id = resolved_by_id
    request.resolution_note = "Source transaction removed."


def _get_user_request(db: Session, request_id: uuid.UUID) -> UserRequest:
    request = (
        db.query(UserRequest)
        .options(
            joinedload(UserRequest.item),
            joinedload(UserRequest.work_order),
            joinedload(UserRequest.creator),
            joinedload(UserRequest.resolver),
        )
        .filter(UserRequest.id == request_id)
        .first()
    )
    if request is None:
        raise UserRequestNotFoundError("User request not found.")
    return request
