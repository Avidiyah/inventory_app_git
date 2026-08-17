"""Durable operational request queue.

The queue is intentionally generic. Scan / Stock raises an
``inventory_recount`` request when recorded stock is short. Any work-order
material path raises one deduplicated ``missing_item_price`` request when the
item has no price. Each request is staged in the same database transaction as
the operation that raised it.

``item_request`` is the third type and the only one raised by a *person* rather
than by a stock operation: a user searched for a material and the catalogue had
no row for it at all. That is deliberately narrower than it sounds -- an in-app
item sitting at zero is still findable, because ``list_items`` filters on
``archived_at`` and never on quantity, so a short count is ``inventory_recount``
territory. An item request carries a NULL ``item_id`` until a reviewer fulfils it,
and that NULL is exactly what distinguishes "not in the app" from "in the app,
count is wrong".
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session, joinedload

from app.domain.errors import ItemRequestStateError, UserRequestNotFoundError
from app.domain.list_limits import fetch_limit
from app.models import UserRequest
from app.services._list_cap import capped


REQUEST_INVENTORY_RECOUNT = "inventory_recount"
REQUEST_MISSING_ITEM_PRICE = "missing_item_price"
REQUEST_ITEM = "item_request"
STATUS_OPEN = "open"
STATUS_RESOLVED = "resolved"

# Which `details` keys each request type lets a reviewer edit. The recount
# numbers are absent by design: `recorded_quantity_before`,
# `dispensed_quantity`, and `shortage_quantity` are a frozen snapshot of what
# the system observed at dispense time, and a snapshot someone can rewrite to
# match a later recount is not an audit trail.
EDITABLE_DETAILS: dict[str, frozenset[str]] = {
    REQUEST_ITEM: frozenset({"searched_text", "quantity", "note"}),
    REQUEST_INVENTORY_RECOUNT: frozenset(),
    REQUEST_MISSING_ITEM_PRICE: frozenset(),
}


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


def create_item_request(
    db: Session,
    *,
    searched_text: str,
    quantity: Decimal,
    note: Optional[str],
    work_order_id: Optional[uuid.UUID],
    work_order_number: Optional[str],
    source: str,
    created_by_id: Optional[uuid.UUID],
) -> UserRequest:
    """Stage one open request for a material that has no catalogue row.

    Unlike the other two types this is raised by a person rather than by a
    stock operation, so it carries no transaction and no item.

    Each filing is its own row even when several name the same material: each
    carries its own work order, quantity, and requester, all of which the
    retroactive auto-add needs. Fulfilment then cascades across the confirmed
    siblings rather than merging them up front -- see
    `find_sibling_item_requests`.
    """
    request = UserRequest(
        request_type=REQUEST_ITEM,
        status=STATUS_OPEN,
        message="Please add this item to the catalogue",
        work_order_id=work_order_id,
        created_by_id=created_by_id,
        details={
            "searched_text": searched_text.strip(),
            "quantity": str(quantity),
            "note": (note or "").strip() or None,
            "source": source,
            "work_order_number": work_order_number,
        },
    )
    db.add(request)
    return request


def _token_set(text: Optional[str]) -> frozenset[str]:
    """The normalized token set of an item request's searched text.

    Reuses the item search's own tokenizer so `3/4` and `3 4` normalize
    identically -- the same rule that decided the search came up empty in the
    first place. Imported lazily because `services.items` imports this module
    to resolve missing-price requests, so a module-level import would cycle.
    """
    from app.services.items import _search_tokens

    return frozenset(_search_tokens(text or "") or ())


def find_sibling_item_requests(
    db: Session, request: UserRequest
) -> list[UserRequest]:
    """Other OPEN item requests naming the same material, newest-first.

    Token-set EQUALITY, deliberately stricter than the search's
    subset-containment matching. Search is broad on purpose because a wrong hit
    there costs the user a glance; here a wrong hit would retroactively bill
    material to another customer's work order and silently close someone
    else's request. So `copper elbow 3/4` matches `3/4 copper elbow`, while
    `copper elbow` does not sweep up `copper elbow press`.

    The reviewer still confirms the returned set before a fulfilment cascades to
    it; this is a proposal, not a decision.
    """
    target = _token_set((request.details or {}).get("searched_text"))
    if not target:
        return []

    candidates = (
        db.query(UserRequest)
        .options(
            joinedload(UserRequest.work_order),
            joinedload(UserRequest.creator),
        )
        .filter(
            UserRequest.request_type == REQUEST_ITEM,
            UserRequest.status == STATUS_OPEN,
            UserRequest.id != request.id,
        )
        .order_by(UserRequest.created_at.desc())
        .all()
    )
    return [
        candidate
        for candidate in candidates
        if _token_set((candidate.details or {}).get("searched_text")) == target
    ]


def _resolve_one_item_request(
    db: Session,
    request: UserRequest,
    *,
    item_id: uuid.UUID,
    resolved_by_id: Optional[uuid.UUID],
) -> Optional[str]:
    """Attach `item_id` to one request and log it on that request's work order.

    Returns a human-readable skip note, or None when nothing was skipped.
    `services.work_orders` imports this module, so its import is local.
    """
    from app.domain import work_orders as wo
    from app.models import WorkOrder
    from app.services.work_orders import attach_dispense_line

    details = dict(request.details or {})
    quantity = Decimal(str(details.get("quantity") or "1"))
    number = details.get("work_order_number") or "its work order"

    skipped = None
    if request.work_order_id is not None:
        work_order = (
            db.query(WorkOrder)
            .filter(WorkOrder.id == request.work_order_id)
            .first()
        )
        if work_order is None or work_order.archived_at is not None:
            skipped = f"Not added to {number} - work order was already closed."
            details["auto_add"] = "skipped_wo_closed"
        else:
            # ALWAYS retroactive, whatever the work order's own entry_mode is.
            # Fulfilment records material consumed before the app knew the item
            # existed, so it must never move stock -- which is also why this
            # calls `attach_dispense_line` directly instead of
            # `add_work_order_item`, whose mode follows the work order.
            attach_dispense_line(
                db,
                work_order_id=work_order.id,
                item_id=item_id,
                quantity=quantity,
                mode=wo.MODE_RETROACTIVE,
                user_id=resolved_by_id,
            )
            details["auto_add"] = "added"
    else:
        details["auto_add"] = "none"

    request.item_id = item_id
    request.details = details
    request.status = STATUS_RESOLVED
    request.resolved_at = datetime.now(timezone.utc)
    request.resolved_by_id = resolved_by_id
    if skipped is not None:
        request.resolution_note = skipped
    elif request.work_order_id is not None:
        request.resolution_note = (
            f"Item added to the catalogue and logged retroactively on {number}."
        )
    else:
        request.resolution_note = "Item added to the catalogue."
    return skipped


def fulfill_item_request(
    db: Session,
    request_id: uuid.UUID,
    *,
    item_id: uuid.UUID,
    sibling_ids: Optional[list[uuid.UUID]] = None,
    resolved_by_id: Optional[uuid.UUID],
) -> tuple[UserRequest, list[str]]:
    """Point an item request -- and every confirmed sibling -- at a real item.

    One transaction: either every request resolves and every live work order
    gets its material logged, or none does.

    A closed work order never blocks the catalogue fix. Its add is skipped and
    the reason is recorded on that request's `resolution_note`, because the
    item still needs to exist for everyone else.
    """
    request = (
        db.query(UserRequest)
        .filter(UserRequest.id == request_id)
        .with_for_update()
        .first()
    )
    if request is None:
        raise UserRequestNotFoundError("User request not found.")
    if request.request_type != REQUEST_ITEM:
        raise ItemRequestStateError("This is not an item request.")
    if request.status != STATUS_OPEN:
        raise ItemRequestStateError("This item request is already resolved.")

    targets = [request]
    remaining = [sid for sid in (sibling_ids or []) if sid != request_id]
    if remaining:
        targets.extend(
            db.query(UserRequest)
            .filter(
                UserRequest.id.in_(remaining),
                UserRequest.request_type == REQUEST_ITEM,
                UserRequest.status == STATUS_OPEN,
            )
            .with_for_update()
            .all()
        )

    skipped: list[str] = []
    for target in targets:
        note = _resolve_one_item_request(
            db, target, item_id=item_id, resolved_by_id=resolved_by_id
        )
        if note:
            skipped.append(note)

    db.commit()
    return get_user_request(db, request_id), skipped


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


def resolve_recount_requests(
    db: Session,
    *,
    item_id: uuid.UUID,
    resolved_by_id: Optional[uuid.UUID],
) -> int:
    """Resolve every open recount request for an item once its count is
    corrected. The correction owns the surrounding commit.

    Exact mirror of `resolve_missing_price_requests`, and deliberately global:
    a recount request asks "please re-count this", and an `adjust` answers it
    regardless of which screen the correction was made from -- the User
    Requests card or Correct Count on Find Item.
    """
    requests = (
        db.query(UserRequest)
        .filter(
            UserRequest.request_type == REQUEST_INVENTORY_RECOUNT,
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
        request.resolution_note = "Stock count corrected."
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


def update_user_request_fields(
    db: Session,
    request_id: uuid.UUID,
    *,
    message: Optional[str] = None,
    details_patch: Optional[dict] = None,
) -> UserRequest:
    """Correct a request's own wording without touching its audit stamps.

    Only `message` and the type's whitelisted `details` keys are writable, so
    status, resolution, and the recount snapshot are unreachable from here --
    see `EDITABLE_DETAILS` for why the recount numbers are not on the list.
    """
    request = (
        db.query(UserRequest)
        .filter(UserRequest.id == request_id)
        .with_for_update()
        .first()
    )
    if request is None:
        raise UserRequestNotFoundError("User request not found.")

    allowed = EDITABLE_DETAILS.get(request.request_type, frozenset())
    patch = details_patch or {}
    rejected = set(patch) - allowed
    if rejected:
        raise ItemRequestStateError(
            f"These fields cannot be edited: {', '.join(sorted(rejected))}."
        )

    if message is not None:
        cleaned = message.strip()
        if not cleaned:
            raise ItemRequestStateError("Message cannot be blank.")
        request.message = cleaned

    if patch:
        details = dict(request.details or {})
        for key, value in patch.items():
            details[key] = (
                (value.strip() or None) if isinstance(value, str) else value
            )
        request.details = details

    db.commit()
    return get_user_request(db, request_id)


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


def get_user_request(db: Session, request_id: uuid.UUID) -> UserRequest:
    """One request with its item/work-order/user context eagerly loaded."""
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


# Kept so the module's own callers read unchanged; `get_user_request` is the
# name the router uses.
_get_user_request = get_user_request
