"""Material Requests: a catalogue item the shelf does not have.

Layer: services, and -- like `services/low_stock.py` -- deliberately the
thinnest kind. **This module imports only `app.models` and `app.domain`.**
Three stock-writing services (`transactions`, `mass_staging`,
`work_orders`) call `record_stock_change` from inside their transactions,
and `services.notifications` imports `work_orders`; one `from app.services
import ...` here would close that ring.

**The transition is atomic with the stock write.** `record_stock_change`
runs after the caller has mutated `item.quantity` under the item's
`FOR UPDATE` lock and before the caller's `db.commit()`. The request rows
move in the same transaction, so a rollback takes the transition with it
and the queue can never disagree with the count.

**Notifying is not this module's job.** It freezes everything a push will
need -- ids and strings, never ORM objects -- into a `StockedFact` on a
per-request ContextVar buffer, and `routers/_stock_events.py` drains it
after commit. Same invariant as the low-stock buffer: `record` before the
commit while the rows are loaded, `drain` only on the router's success path.
"""

import logging
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload, selectinload

from app.domain import material_requests as policy
from app.domain import roles
from app.domain.errors import (
    ItemNotFoundError,
    ItemRequestStateError,
    MaterialRequestOwnershipError,
    UserRequestNotFoundError,
)
from app.models import Item, User, UserRequest, WorkOrder, WorkOrderTechnician

logger = logging.getLogger(__name__)

MESSAGE = "Please stock this item"
NOTE_CANCELLED = "Cancelled by requester"
NOTE_WORK_ORDER_CLOSED = "Work order was closed before the item was stocked."

ORIGIN_REQUEST_CARD = "request_card"
ORIGIN_CATALOGUE_FULFILMENT = "catalogue_fulfilment"

# Same ceiling and same reasoning as `low_stock.MAX_BUFFERED_CROSSINGS`.
MAX_BUFFERED_FACTS = 500

_LIVE_STATUSES = (policy.STATUS_OPEN, policy.STATUS_STOCKED)
_LISTED_TYPES = (policy.REQUEST_MATERIAL, "catalogue_request")


@dataclass(frozen=True)
class StockedFact:
    """One request that just became `stocked`, as plain values.

    The recipient *parts* are frozen separately (assignees, supervisor,
    requester) so the pure rule in `domain/notifications.py` does the
    dedup and the actor decision, and stays testable on its own.
    """

    request_id: uuid.UUID
    item_name: str
    work_order_id: Optional[uuid.UUID]
    work_order_number: str
    assignee_ids: tuple
    supervisor_id: Optional[uuid.UUID]
    requester_id: Optional[uuid.UUID]


_buffer: ContextVar[Optional[list]] = ContextVar("stocked_facts_buffer", default=None)


def _buffer_fact(fact: StockedFact) -> None:
    entries = _buffer.get()
    if entries is None:
        entries = []
        _buffer.set(entries)
    if len(entries) >= MAX_BUFFERED_FACTS:
        logger.warning(
            "material-request buffer full at %s entries; dropping further facts",
            MAX_BUFFERED_FACTS,
        )
        return
    entries.append(fact)


def drain() -> list:
    """Take every buffered fact and empty the buffer. Total by contract."""
    entries = _buffer.get()
    if not entries:
        return []
    taken = list(entries)
    entries.clear()
    return taken


# --- helpers ---------------------------------------------------------------


def lock_live_item(db: Session, item_id: uuid.UUID) -> Item:
    """The item row under `FOR UPDATE`, or `ItemNotFoundError`. Mirrors
    `services.work_orders._locked_live_item`, re-declared here rather than
    imported for the import-ring reason in the module docstring."""
    item = (
        db.query(Item)
        .filter(Item.id == item_id, Item.archived_at.is_(None))
        .with_for_update()
        .first()
    )
    if item is None:
        raise ItemNotFoundError("Item not found.")
    return item


def _assignee_ids(work_order: WorkOrder) -> tuple:
    """Plural assignments with the legacy singular folded in -- the same
    rule as `services.work_orders._assigned_technician_ids`, restated here
    for the import-ring reason."""
    assigned = [row.technician_id for row in (work_order.technician_assignments or ())]
    legacy = work_order.assigned_to_id
    if legacy is not None and legacy not in assigned:
        assigned.insert(0, legacy)
    return tuple(assigned)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _set_stocked(request: UserRequest, *, stocked_by: str) -> None:
    details = dict(request.details or {})
    details["stocked_at"] = _now_iso()
    details["stocked_by"] = stocked_by
    details["stock_cycles"] = int(details.get("stock_cycles") or 0) + 1
    request.details = details
    request.status = policy.STATUS_STOCKED


def clear_stocked_stamps(request: UserRequest) -> None:
    """Drop `stocked_at` / `stocked_by`; keep `stock_cycles` (history)."""
    details = dict(request.details or {})
    details.pop("stocked_at", None)
    details.pop("stocked_by", None)
    request.details = details


def _resolve(request: UserRequest, *, note: str, resolved_by_id: Optional[uuid.UUID]) -> None:
    request.status = policy.STATUS_RESOLVED
    request.resolved_at = datetime.now(timezone.utc)
    request.resolved_by_id = resolved_by_id
    request.resolution_note = note


def _locked(db: Session, request_id: uuid.UUID) -> UserRequest:
    request = (
        db.query(UserRequest)
        .filter(UserRequest.id == request_id)
        .with_for_update()
        .first()
    )
    if request is None:
        raise UserRequestNotFoundError("User request not found.")
    if request.request_type != policy.REQUEST_MATERIAL:
        raise ItemRequestStateError("This is not a material request.")
    return request


# --- filing ----------------------------------------------------------------


def create_or_update(
    db: Session,
    *,
    item_id: uuid.UUID,
    work_order: WorkOrder,
    quantity: Decimal,
    product_link: Optional[str],
    note: Optional[str],
    created_by_id: Optional[uuid.UUID],
    origin: str,
) -> tuple[UserRequest, bool]:
    """One live request per (work order, item). Returns `(request, created)`.

    A second filing overwrites quantity, link, and note rather than adding a
    row: the staff already know, and two rows would mean two Hub lines for
    one shelf. Pending objects are checked first because `SessionLocal`
    disables autoflush and a catalogue fulfilment can create several
    requests before its single commit (see `create_or_update_missing_price_request`).
    """
    def _matches(candidate) -> bool:
        return (
            isinstance(candidate, UserRequest)
            and candidate.request_type == policy.REQUEST_MATERIAL
            and candidate.status in _LIVE_STATUSES
            and candidate.item_id == item_id
            and candidate.work_order_id == work_order.id
        )

    request = next((c for c in db.new if _matches(c)), None)
    if request is None:
        request = (
            db.query(UserRequest)
            .filter(
                UserRequest.request_type == policy.REQUEST_MATERIAL,
                UserRequest.status.in_(_LIVE_STATUSES),
                UserRequest.item_id == item_id,
                UserRequest.work_order_id == work_order.id,
            )
            .first()
        )

    cleaned_note = (note or "").strip() or None
    cleaned_link = (product_link or "").strip() or None

    if request is None:
        request = UserRequest(
            request_type=policy.REQUEST_MATERIAL,
            status=policy.STATUS_OPEN,
            message=MESSAGE,
            item_id=item_id,
            work_order_id=work_order.id,
            created_by_id=created_by_id,
            details={
                "quantity": str(quantity),
                "product_link": cleaned_link,
                "note": cleaned_note,
                "work_order_number": work_order.number,
                "stock_cycles": 0,
                "origin": origin,
            },
        )
        db.add(request)
        return request, True

    details = dict(request.details or {})
    details["quantity"] = str(quantity)
    details["product_link"] = cleaned_link
    details["note"] = cleaned_note
    request.details = details
    return request, False


# --- the automatic edges ---------------------------------------------------


def _live_requests_for_item(db: Session, item_id: uuid.UUID, status: str) -> list[UserRequest]:
    """This item's material requests currently in `status`.

    `SessionLocal` has autoflush off, so a row transitioned earlier in the
    same transaction (a `mark_stocked` that has not flushed yet) still
    matches in SQL while the identity map hands back the already-moved
    object. The in-session status is the truth, so it is re-checked here
    rather than trusting the WHERE clause alone.
    """
    rows = (
        db.query(UserRequest)
        .options(
            joinedload(UserRequest.work_order).selectinload(WorkOrder.technician_assignments)
        )
        .filter(
            UserRequest.request_type == policy.REQUEST_MATERIAL,
            UserRequest.status == status,
            UserRequest.item_id == item_id,
        )
        .all()
    )
    return [row for row in rows if row.status == status]


def _stock_request(db: Session, request: UserRequest, item: Item, *, stocked_by: str) -> None:
    """`open -> stocked` for one request, buffering the fact -- or a quiet
    resolve when its work order is already closed."""
    work_order = request.work_order
    if work_order is None or work_order.archived_at is not None:
        _resolve(request, note=NOTE_WORK_ORDER_CLOSED, resolved_by_id=None)
        return
    _set_stocked(request, stocked_by=stocked_by)
    _buffer_fact(
        StockedFact(
            request_id=request.id,
            item_name=item.name,
            work_order_id=work_order.id,
            work_order_number=work_order.number,
            assignee_ids=_assignee_ids(work_order),
            supervisor_id=work_order.supervisor_id,
            requester_id=request.created_by_id,
        )
    )


def record_stock_change(db: Session, item: Item, *, quantity_before: Decimal) -> None:
    """Move this item's requests across whichever zero edge this write took.

    Call immediately after `low_stock.record(...)` at each stock-writing
    site, before the commit. No row lock of its own: every caller already
    holds the item row `FOR UPDATE`, which serialises stock writes per item,
    and `mark_stocked` locks the request row it touches.

    Neither edge: return after one comparison each -- the common case.
    """
    after = Decimal(item.quantity)
    if policy.restocked(quantity_before, after):
        for request in _live_requests_for_item(db, item.id, policy.STATUS_OPEN):
            _stock_request(db, request, item, stocked_by="auto")
    elif policy.went_out(quantity_before, after):
        for request in _live_requests_for_item(db, item.id, policy.STATUS_STOCKED):
            clear_stocked_stamps(request)
            request.status = policy.STATUS_OPEN


# --- staff and requester actions --------------------------------------------


def mark_stocked(db: Session, request_id: uuid.UUID, *, actor_id: uuid.UUID) -> UserRequest:
    """TechFM OA+ pressed "Mark stocked & notify". Allowed while `open` at any
    on-hand; 409 otherwise. Buffers the same fact the automatic edge would,
    so the router's `flush_stock_events` sends the same push."""
    request = _locked(db, request_id)
    if request.status == policy.STATUS_STOCKED:
        raise ItemRequestStateError("This material request is already stocked.")
    if request.status != policy.STATUS_OPEN:
        raise ItemRequestStateError("This material request is already resolved.")
    item = db.get(Item, request.item_id)
    if item is None:
        raise ItemNotFoundError("Item not found.")
    # Load the work order with assignments the same way the edge does.
    request = (
        db.query(UserRequest)
        .options(
            joinedload(UserRequest.work_order).selectinload(WorkOrder.technician_assignments)
        )
        .filter(UserRequest.id == request_id)
        .populate_existing()
        .one()
    )
    _stock_request(db, request, item, stocked_by=str(actor_id))
    return request


def cancel(db: Session, request_id: uuid.UUID, *, actor_id: uuid.UUID) -> UserRequest:
    """The filer withdraws their own open request. A stocked one has already
    cost staff work, so cancelling it is the page's job (409)."""
    request = _locked(db, request_id)
    if request.created_by_id != actor_id:
        raise MaterialRequestOwnershipError("Only the person who filed this request can cancel it.")
    if request.status != policy.STATUS_OPEN:
        raise ItemRequestStateError("Only an open material request can be cancelled.")
    _resolve(request, note=NOTE_CANCELLED, resolved_by_id=actor_id)
    return request


def resolve_from_line(
    db: Session,
    *,
    request_id: uuid.UUID,
    work_order_id: uuid.UUID,
    work_order_number: str,
    item_id: uuid.UUID,
    quantity: Decimal,
    resolved_by_id: Optional[uuid.UUID],
) -> UserRequest:
    """The crew tapped "Add requested material". Must be `stocked`, on this
    work order, for this item -- anything else is a stale button (409)."""
    request = _locked(db, request_id)
    if request.status != policy.STATUS_STOCKED:
        raise ItemRequestStateError("This material request is not waiting to be added.")
    if request.work_order_id != work_order_id or request.item_id != item_id:
        raise ItemRequestStateError("This material request belongs to a different work order or item.")
    details = dict(request.details or {})
    details["added_quantity"] = str(quantity)
    request.details = details
    _resolve(request, note=f"Added to {work_order_number}.", resolved_by_id=resolved_by_id)
    return request


# --- reads -------------------------------------------------------------------


def _with_context(query):
    return query.options(
        joinedload(UserRequest.item),
        joinedload(UserRequest.work_order),
        joinedload(UserRequest.creator),
        joinedload(UserRequest.resolver),
    )


def list_for_work_order(db: Session, work_order_id: uuid.UUID) -> list[UserRequest]:
    """Every material and catalogue request on one work order, newest first.
    Visibility is the caller's job (the route resolves the work order through
    the scoped reader first)."""
    return (
        _with_context(db.query(UserRequest))
        .filter(
            UserRequest.work_order_id == work_order_id,
            UserRequest.request_type.in_(_LISTED_TYPES),
        )
        .order_by(UserRequest.created_at.desc())
        .all()
    )


def open_counts(db: Session) -> dict[str, dict[str, int]]:
    """`{request_type: {"open": n, "stocked": n}}` for the tab labels."""
    rows = (
        db.query(UserRequest.request_type, UserRequest.status, func.count(UserRequest.id))
        .filter(UserRequest.status.in_(_LIVE_STATUSES))
        .group_by(UserRequest.request_type, UserRequest.status)
        .all()
    )
    counts: dict[str, dict[str, int]] = {}
    for request_type, status, n in rows:
        counts.setdefault(request_type, {})[status] = n
    return counts


def stocked_requests_for_user(db: Session, user: User) -> list[UserRequest]:
    """The Hub's "Requested material in stock" rows.

    Everyone: `stocked` requests whose work order they are assigned to,
    routed on, or which they filed. TechFM OA+: every `stocked` request.
    """
    query = _with_context(db.query(UserRequest)).filter(
        UserRequest.request_type == policy.REQUEST_MATERIAL,
        UserRequest.status == policy.STATUS_STOCKED,
    )
    if not roles.role_at_least(user.role, roles.ROLE_TECHFM_OA):
        assigned = (
            db.query(WorkOrderTechnician.work_order_id)
            .filter(WorkOrderTechnician.technician_id == user.id)
        )
        query = query.join(WorkOrder, WorkOrder.id == UserRequest.work_order_id).filter(
            or_(
                UserRequest.created_by_id == user.id,
                WorkOrder.supervisor_id == user.id,
                WorkOrder.assigned_to_id == user.id,
                WorkOrder.id.in_(assigned),
            )
        )
    return query.order_by(UserRequest.created_at.desc()).all()
