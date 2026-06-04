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

from app.database import get_db
from app.domain.errors import DomainError
from app.routers._errors import to_http
from app.schemas.transactions import (
    TransactionCreate,
    TransactionResponse,
    TransactionHistoryPage,
)
from app.services import history as history_service
from app.services import transactions as transactions_service

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.post("/", response_model=TransactionResponse, status_code=201)
def create_transaction(payload: TransactionCreate, db: Session = Depends(get_db)):
    """Record a stock or dispense. 404 if the item is unknown,
    400 if a dispense would overdraw stock
    (`NegativeQuantityError` -> "Insufficient stock to dispense.")."""
    try:
        return transactions_service.apply_transaction(
            db,
            item_id=payload.item_id,
            transaction_type=payload.transaction_type,
            quantity=payload.quantity,
            user_id=payload.user_id,
            work_order_number=payload.work_order_number,
        )
    except DomainError as exc:
        raise to_http(exc)


@router.get("/", response_model=TransactionHistoryPage)
def list_transactions(
    item_id: Optional[UUID] = None,
    user_id: Optional[UUID] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Paginated history. Optional `item_id` / `user_id` filters
    combine with AND. `page_size` is capped at 100 to bound the
    join cost."""
    return history_service.list_history(
        db,
        item_id=item_id,
        user_id=user_id,
        page=page,
        page_size=page_size,
    )
