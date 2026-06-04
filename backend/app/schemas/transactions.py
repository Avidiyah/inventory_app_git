"""Transaction and history schemas.

Layer: schemas. `TransactionCreate` is the body of `POST
/transactions`; `TransactionResponse` is its return value.
`TransactionHistoryItem` / `TransactionHistoryPage` are the
denormalised, paginated shapes served by `GET /transactions/history`
— they carry item barcode/name and username so the frontend history
view does not need a second round-trip per row.
"""

from uuid import UUID
from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, field_validator


class TransactionCreate(BaseModel):
    """Payload for `POST /transactions`.

    `transaction_type` is constrained to the two literals understood
    by `domain.quantity.apply_delta`. Quantity must be strictly
    positive — zero-quantity transactions are meaningless and would
    pollute the audit log. Stock-level overdraft (`dispense` larger
    than current quantity) is *not* checked here; that is the
    service layer's job because it requires a row lock.

    There is no `user_id` field: a transaction is always attributed to
    the logged-in user, which the router supplies from the session. A
    client cannot record a transaction "as" someone else.
    """

    item_id: UUID
    transaction_type: Literal["stock", "dispense"]
    quantity: Decimal
    work_order_number: Optional[str] = None

    @field_validator("quantity")
    @classmethod
    def quantity_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError("Quantity must be greater than zero.")
        return v


class TransactionResponse(BaseModel):
    """Outbound shape for the row created by `POST /transactions`.

    `user_id` is optional because anonymous transactions are allowed
    (the spec keeps user attribution opt-in for now).
    """

    id: UUID
    item_id: UUID
    user_id: Optional[UUID]
    transaction_type: str
    quantity: Decimal
    work_order_number: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class TransactionHistoryItem(BaseModel):
    """A single row in the paginated history view.

    Built by `services.history.list_history` from a JOIN across
    transactions / items / users so the frontend can render the
    table without further lookups. `username` is `None` when the
    transaction was recorded anonymously.
    """

    id: UUID
    item_id: UUID
    item_barcode: str
    item_name: str
    user_id: Optional[UUID]
    username: Optional[str]
    transaction_type: str
    quantity: Decimal
    work_order_number: Optional[str]
    created_at: datetime


class TransactionHistoryPage(BaseModel):
    """Envelope around a page of `TransactionHistoryItem`.

    `total` is the unfiltered count so the UI can render pagination
    controls without a second request.
    """

    items: list[TransactionHistoryItem]
    total: int
    page: int
    page_size: int
