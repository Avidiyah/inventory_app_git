"""Transaction and history schemas.

Layer: schemas. `TransactionCreate` is the body of `POST
/transactions`; `TransactionResponse` is its return value.
`CorrectionCreate` is the body of `POST /transactions/adjust`, a
sibling route that records a quantity correction (signed delta
computed by the service from `new_quantity - current`).
`TransactionHistoryItem` / `TransactionHistoryPage` are the
denormalised, paginated shapes served by `GET /transactions/`
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
    by `domain.quantity.apply_delta` for stock/dispense. Quantity must
    be strictly positive — zero-quantity transactions are meaningless
    and would pollute the audit log. Stock-level overdraft (`dispense`
    larger than current quantity) is *not* checked here; that is the
    service layer's job because it requires a row lock.

    Corrections (`transaction_type = "adjust"`) live on a separate
    route (`POST /transactions/adjust`) with its own `CorrectionCreate`
    schema and Admin+ gate, so this body intentionally does NOT accept
    "adjust".

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


class CorrectionCreate(BaseModel):
    """Payload for `POST /transactions/adjust`.

    The client sends the **absolute** new quantity the item should end
    up at, plus a non-blank `reason`. The service computes the signed
    delta under the item row lock (`new_quantity - current`) and stores
    it as the `transactions.quantity` value, keeping every history row
    uniformly representing "what was applied to stock". A zero delta
    raises `NoChangeError` rather than creating an empty audit row.
    """

    item_id: UUID
    new_quantity: Decimal
    reason: str

    @field_validator("new_quantity")
    @classmethod
    def new_quantity_must_not_be_negative(cls, v):
        if v < 0:
            raise ValueError("New quantity cannot be negative.")
        return v

    @field_validator("reason")
    @classmethod
    def reason_not_blank(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Reason is required for a correction.")
        return v


class BillingUpdate(BaseModel):
    """Payload for `PATCH /transactions/{id}/billing` (Admin/Owner only).

    `billable_quantity` is how many of the row's units to charge the
    customer for: `0` to record-but-not-charge, a smaller number to bill
    a partial count, or `null` to clear any override and bill the full
    recorded quantity again. The upper bound (cannot exceed the recorded
    quantity) and the stock/dispense-only rule are enforced in
    `domain.billing.validate_billable_quantity`, which needs the row's
    actual quantity and type, so they are not duplicated here.
    """

    billable_quantity: Optional[Decimal] = None


class TransactionResponse(BaseModel):
    """Outbound shape for the row created by `POST /transactions` or
    `POST /transactions/adjust`, and returned by the billing PATCH.

    `user_id` is optional because older pre-auth rows may have it as
    NULL; new rows always carry the logged-in user's id. `reason` is
    populated only for `transaction_type = "adjust"`. `billable_quantity`
    is the billing override (NULL = bill the full `quantity`)."""

    id: UUID
    item_id: UUID
    user_id: Optional[UUID]
    transaction_type: str
    quantity: Decimal
    billable_quantity: Optional[Decimal] = None
    work_order_number: Optional[str]
    reason: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class TransactionHistoryItem(BaseModel):
    """A single row in the paginated history view.

    Built by `services.history.list_history` from a JOIN across
    transactions / items / users so the frontend can render the
    table without further lookups. `username` is `None` when the
    transaction was recorded anonymously. `reason` is populated only
    for `transaction_type = "adjust"`.

    `item_price` is the item's current *per-unit* price, included ONLY
    when the requester is Admin/Owner (the service nulls it otherwise);
    the frontend multiplies it by `quantity` to show the line value and
    hides the column for lower roles. It is the live item price, not a
    historical snapshot — prices are not versioned per transaction.

    `billable_quantity` is the Admin's billing override (how many units
    to actually charge for; NULL = charge the full `quantity`). Like
    `item_price` it is included ONLY for Admin/Owner — billing is an
    Admin-only concern — so lower roles always see `None` and the live,
    unedited quantity in the Quantity column.
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
    reason: Optional[str] = None
    item_price: Optional[Decimal] = None
    billable_quantity: Optional[Decimal] = None
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
