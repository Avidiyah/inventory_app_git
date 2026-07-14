"""Tool request/response schemas.

Layer: schemas. Consumed by `app/routers/tools.py`. Mirrors
`app/schemas/items.py` for the CRUD shapes, minus `location`/`price`/
`product_link` (tools don't carry them) and minus the archived-barcode
override flow (tools have no confirm/override dance -- an archived tool's
barcode is simply free to reuse).
"""

from uuid import UUID
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, field_validator, model_validator


class ToolCreate(BaseModel):
    """Payload for `POST /tools`.

    `quantity` defaults to 1 (not 0, unlike `ItemCreate`) -- a tool is
    usually added because you have one in hand, whereas an item may be
    catalogued before it's stocked. A higher starting count represents an
    unserialized bulk batch.
    """

    barcode: str
    name: str
    quantity: Decimal = Decimal("1")

    @field_validator("barcode", "name")
    @classmethod
    def _not_blank(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("This field is required.")
        return v

    @field_validator("quantity")
    @classmethod
    def _quantity_not_negative(cls, v):
        if v < 0:
            raise ValueError("Quantity cannot be negative.")
        return v


class ToolUpdate(BaseModel):
    """Payload for `PATCH /tools/{id}` -- a partial edit of `barcode` and/or
    `name`. At least one field required; both are NOT NULL columns, so an
    explicit null/blank is rejected. `quantity` is intentionally not
    editable here -- it only changes via checkout/return, mirroring how
    `ItemUpdate` excludes quantity (corrections go through the transaction
    ledger, not a direct edit).
    """

    barcode: Optional[str] = None
    name: Optional[str] = None

    @field_validator("barcode", "name")
    @classmethod
    def _strip_if_present(cls, v):
        if v is None:
            return v
        return v.strip()

    @model_validator(mode="after")
    def _check(self):
        if not self.model_fields_set:
            raise ValueError("At least one field is required.")
        for field in ("barcode", "name"):
            if field in self.model_fields_set and not getattr(self, field):
                raise ValueError(f"{field} cannot be blank.")
        return self


class ToolCustodyEntry(BaseModel):
    """One user's current outstanding balance for a tool -- how many units
    they have checked out right now (Sum(checkout) - Sum(return) > 0)."""

    user_id: UUID
    username: str
    quantity: Decimal


class ToolResponse(BaseModel):
    """Outbound shape for any endpoint returning a tool.

    `custody` is NOT an ORM relationship -- it's computed by
    `services.tools.tool_custody` and set explicitly by the router
    (`_tool_response`), the same way `ItemResponse.barcodes` is filled from
    `Item.alt_barcodes` rather than via `from_attributes`.
    """

    id: UUID
    barcode: str
    name: str
    quantity: Decimal
    created_at: datetime
    custody: list[ToolCustodyEntry] = []

    model_config = {"from_attributes": True}


class ToolCheckoutCreate(BaseModel):
    """Payload for `POST /tools/{id}/checkout`. `assigned_to_id` is
    required -- a tool must be assigned to a user before a checkout is
    recorded. `work_order_id`/`work_order_number` are an optional,
    never-required linkage (unlike items, there is no find-or-create here --
    a free-text number is stored as-is, denormalized)."""

    quantity: Decimal
    assigned_to_id: UUID
    work_order_id: Optional[UUID] = None
    work_order_number: Optional[str] = None

    @field_validator("quantity")
    @classmethod
    def _quantity_positive(cls, v):
        if v <= 0:
            raise ValueError("Quantity must be greater than zero.")
        return v


class ToolReturnCreate(BaseModel):
    """Payload for `POST /tools/{id}/return`. Same shape as
    `ToolCheckoutCreate` -- `assigned_to_id` is whose custody is being
    reduced (not necessarily the logged-in user; any authenticated user may
    process a return on behalf of the holder)."""

    quantity: Decimal
    assigned_to_id: UUID
    work_order_id: Optional[UUID] = None
    work_order_number: Optional[str] = None

    @field_validator("quantity")
    @classmethod
    def _quantity_positive(cls, v):
        if v <= 0:
            raise ValueError("Quantity must be greater than zero.")
        return v


class ToolAdjustCreate(BaseModel):
    """Payload for `POST /tools/{id}/adjust` -- the "Correct Count" action,
    mirroring `CorrectionCreate` (`POST /transactions/adjust`). The client
    sends the **absolute** new on-hand quantity the tool should end up at;
    the service computes the signed delta under the row lock. Unlike
    checkout/return, this has no custody holder -- it's a pure inventory
    correction (e.g. fixing a miscount, or adding more units of a bulk
    tool)."""

    new_quantity: Decimal
    reason: str

    @field_validator("new_quantity")
    @classmethod
    def _new_quantity_not_negative(cls, v):
        if v < 0:
            raise ValueError("New quantity cannot be negative.")
        return v

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Reason is required for a correction.")
        return v
