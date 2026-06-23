"""HTTP routes for the `/transactions` resource.

Layer: routers. Two endpoints: `POST /transactions/` records a
stock or dispense (delegated to `services.transactions`, which
holds the row lock and runs the domain arithmetic), and
`GET /transactions/` returns the paginated, denormalised audit log
(delegated to `services.history`). The history endpoint has no
`try/except` block because it cannot raise any domain error --
filters that match nothing simply return an empty page.

Mounted by `app/main.py` under the root prefix.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth_deps import get_current_user, require_min_role
from app.database import get_db
from app.domain import roles
from app.domain.errors import DomainError
from app.models import User
from app.routers._errors import to_http
from app.schemas.transactions import (
    BillingUpdate,
    CorrectionCreate,
    TransactionCreate,
    TransactionResponse,
    TransactionHistoryPage,
)
from app.services import history as history_service
from app.services import transactions as transactions_service

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.post("/", response_model=TransactionResponse, status_code=201)
def create_transaction(
    payload: TransactionCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Record a stock or dispense. The transaction is attributed to the
    logged-in user.

    Authorization is per-direction (see `roles.can_transact`): any
    logged-in user may *dispense* (the floor-crew action), but *stock*
    requires Supervisor or above. A Technician attempting to stock gets
    a 403. 404 if the item is unknown, 400 if a dispense would overdraw
    stock (`NegativeQuantityError` -> "Insufficient stock to dispense.")."""
    if not roles.can_transact(user.role, payload.transaction_type):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to perform this action.",
        )
    try:
        return transactions_service.apply_transaction(
            db,
            item_id=payload.item_id,
            transaction_type=payload.transaction_type,
            quantity=payload.quantity,
            user_id=user.id,
            work_order_number=payload.work_order_number,
        )
    except DomainError as exc:
        raise to_http(exc)


@router.post("/adjust", response_model=TransactionResponse, status_code=201)
def create_correction(
    payload: CorrectionCreate,
    user: User = Depends(require_min_role(roles.ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """Record a quantity correction. Owner/Admin only. The client sends
    the absolute `new_quantity`; the service computes the signed delta
    under the item row lock and writes a `transaction_type = "adjust"`
    audit row carrying the delta and the required `reason`.

    404 if the item is unknown; 400 if the new quantity is negative,
    matches the current quantity (`NoChangeError`), or — in the
    impossible-from-the-Pydantic-side case — would otherwise drive
    stock below zero (`NegativeQuantityError`)."""
    try:
        return transactions_service.apply_correction(
            db,
            item_id=payload.item_id,
            new_quantity=payload.new_quantity,
            reason=payload.reason,
            user_id=user.id,
        )
    except DomainError as exc:
        raise to_http(exc)


@router.patch("/{transaction_id}/billing", response_model=TransactionResponse)
def update_billing(
    transaction_id: UUID,
    payload: BillingUpdate,
    user: User = Depends(require_min_role(roles.ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """Set or clear a transaction's billing override. Owner/Admin only.

    Lets an Admin reviewing a work order charge for fewer units than were
    dispensed (or not charge at all) without touching the inventory
    record. `billable_quantity = null` clears the override (bill the full
    recorded quantity); `0` records-but-does-not-charge; any value up to
    the recorded quantity bills a partial count.

    404 if the transaction is unknown or voided; 400 if the override is
    negative, exceeds the recorded quantity, or targets an `adjust`
    (correction) row (`BillingQuantityError`)."""
    try:
        return transactions_service.set_billable_quantity(
            db,
            transaction_id=transaction_id,
            billable_quantity=payload.billable_quantity,
        )
    except DomainError as exc:
        raise to_http(exc)


@router.delete("/{transaction_id}", status_code=204)
def void_transaction(
    transaction_id: UUID,
    user: User = Depends(require_min_role(roles.ROLE_SUPERVISOR)),
    db: Session = Depends(get_db),
):
    """Void a mis-clicked transaction. Supervisor or above. This is a
    soft delete: the row is retained (stamped with who/when) but hidden
    from history, and its effect on the item's stock is reversed.

    404 if the transaction is unknown or already voided; 400 if undoing
    it would drive the item's stock below zero
    (`TransactionVoidError` — make a correction instead)."""
    try:
        transactions_service.void_transaction(
            db,
            transaction_id=transaction_id,
            user_id=user.id,
        )
    except DomainError as exc:
        raise to_http(exc)


@router.get(
    "/",
    response_model=TransactionHistoryPage,
)
def list_transactions(
    item_id: Optional[UUID] = None,
    user_id: Optional[UUID] = None,
    work_order_number: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    user: User = Depends(require_min_role(roles.ROLE_SUPERVISOR)),
    db: Session = Depends(get_db),
):
    """Paginated history. Supervisor or above. Optional `item_id`,
    `user_id`, and `work_order_number` filters combine with AND.
    `work_order_number` is a case-sensitive substring match against
    `Transaction.work_order_number`; an empty / whitespace-only value
    is treated as "no filter". `page_size` is capped at 100 to bound
    the join cost.

    The per-unit `item_price` is included in each row only for
    Admin/Owner; Supervisors get `None` so cost data stays gated."""
    return history_service.list_history(
        db,
        item_id=item_id,
        user_id=user_id,
        work_order_number=work_order_number,
        page=page,
        page_size=page_size,
        include_price=roles.role_at_least(user.role, roles.ROLE_ADMIN),
    )
