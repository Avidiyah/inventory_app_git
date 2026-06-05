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

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth_deps import require_min_role
from app.database import get_db
from app.domain import roles
from app.domain.errors import DomainError
from app.models import User
from app.routers._errors import to_http
from app.schemas.transactions import (
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
    user: User = Depends(require_min_role(roles.ROLE_SUPERVISOR)),
    db: Session = Depends(get_db),
):
    """Record a stock or dispense. Supervisor or above. The transaction
    is attributed to the logged-in user. 404 if the item is unknown,
    400 if a dispense would overdraw stock
    (`NegativeQuantityError` -> "Insufficient stock to dispense.")."""
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


@router.get(
    "/",
    response_model=TransactionHistoryPage,
    dependencies=[Depends(require_min_role(roles.ROLE_SUPERVISOR))],
)
def list_transactions(
    item_id: Optional[UUID] = None,
    user_id: Optional[UUID] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Paginated history. Supervisor or above. Optional `item_id` /
    `user_id` filters combine with AND. `page_size` is capped at 100 to
    bound the join cost."""
    return history_service.list_history(
        db,
        item_id=item_id,
        user_id=user_id,
        page=page,
        page_size=page_size,
    )
