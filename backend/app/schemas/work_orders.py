"""Work order request/response schemas.

Layer: schemas. Consumed by `app/routers/work_orders.py`. The work order is the
first-class entity (identity = `number`); these shapes carry its attributes plus
the logged-material lines. Response models are plain `BaseModel`s the router
builder fills (a line's `item_name` comes from the joined `Item`).
"""

from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, field_validator, model_validator


def _stripped_nonblank(v: str, label: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError(f"{label} is required.")
    return v


def _stripped_or_none(v):
    """Trim an optional attribute; turn blank into None."""
    if v is None:
        return None
    v = v.strip()
    return v or None


# --- Requests ------------------------------------------------------------

class WorkOrderCreate(BaseModel):
    """Payload for `POST /work-orders` (Supervisor+). `number` is the identity;
    everything else is an optional attribute. Re-using an existing number opens
    that work order (fill-blanks), it is not an error."""

    number: str
    community: Optional[str] = None
    building_number: Optional[str] = None
    unit_number: Optional[str] = None
    description: Optional[str] = None
    assigned_to_id: Optional[UUID] = None

    @field_validator("number")
    @classmethod
    def _number_not_blank(cls, v):
        return _stripped_nonblank(v, "Work order number")

    @field_validator("community", "building_number", "unit_number", "description")
    @classmethod
    def _trim(cls, v):
        return _stripped_or_none(v)


class WorkOrderUpdate(BaseModel):
    """Payload for `PATCH /work-orders/{id}` -- explicit edits (overwrite, unlike
    find-or-create's fill-blanks). Any subset; an explicit `null` for
    `assigned_to_id` clears the assignment. At least one field required.

    `status` (in_progress|completed) and `entry_mode` (dispense|retroactive) are
    validated in the service."""

    number: Optional[str] = None
    community: Optional[str] = None
    building_number: Optional[str] = None
    unit_number: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    entry_mode: Optional[str] = None
    assigned_to_id: Optional[UUID] = None

    @field_validator("number")
    @classmethod
    def _number_not_blank(cls, v):
        if v is None:
            return v
        return _stripped_nonblank(v, "Work order number")

    @field_validator("community", "building_number", "unit_number", "description")
    @classmethod
    def _trim(cls, v):
        return _stripped_or_none(v)

    @model_validator(mode="after")
    def _at_least_one(self):
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to update.")
        return self


class WorkOrderItemCreate(BaseModel):
    """Payload for `POST /work-orders/{id}/items` -- log a material using the
    work order's current `entry_mode`. Re-adding an item replaces its quantity."""

    item_id: UUID
    quantity: Decimal

    @field_validator("quantity")
    @classmethod
    def _positive(cls, v):
        if v <= 0:
            raise ValueError("Quantity must be greater than zero.")
        return v


class WorkOrderItemUpdate(BaseModel):
    """Payload for `PATCH /work-orders/{id}/items/{wo_item_id}`."""

    quantity: Decimal

    @field_validator("quantity")
    @classmethod
    def _positive(cls, v):
        if v <= 0:
            raise ValueError("Quantity must be greater than zero.")
        return v


class WorkOrderItemBilling(BaseModel):
    """Payload for `PATCH /work-orders/{id}/items/{wo_item_id}/billing` -- set or
    clear a line's billing override. `null` clears (bill the full quantity); `0`
    records but does not charge; a value up to the line quantity bills a partial
    count. Bounds against the line quantity are enforced server-side."""

    billable_quantity: Optional[Decimal] = None

    @field_validator("billable_quantity")
    @classmethod
    def _non_negative(cls, v):
        if v is not None and v < 0:
            raise ValueError("Billed quantity cannot be negative.")
        return v


# --- Responses (router builder fills nested fields) ----------------------

class WorkOrderItemDetail(BaseModel):
    """One logged material on a work order."""

    id: UUID
    item_id: UUID
    item_name: str
    item_barcode: str
    item_quantity: Decimal  # the item's current on-hand stock
    quantity: Decimal
    mode: str  # 'dispense' | 'retroactive' (mode when logged)
    # The line is the billing unit for work-order materials: the customer
    # charge is `effective_billable * unit_price`, where `effective_billable`
    # is `billable_quantity` when set else `quantity`. Both cost fields are
    # Admin/Owner only (None when redacted for lower roles).
    unit_price: Optional[Decimal] = None
    billable_quantity: Optional[Decimal] = None


class WorkOrderCard(BaseModel):
    """One collapsible work-order card on the Work Orders page list."""

    id: UUID
    number: str
    community: Optional[str] = None
    building_number: Optional[str] = None
    unit_number: Optional[str] = None
    description: Optional[str] = None
    status: str
    entry_mode: str
    created_by_id: Optional[UUID] = None
    assigned_to_id: Optional[UUID] = None
    assigned_to_username: Optional[str] = None
    item_count: int


class WorkOrderDetail(WorkOrderCard):
    """A work-order card plus its logged materials."""

    items: list[WorkOrderItemDetail] = []
    # Base materials charge = sum over lines of (effective_billable * unit_price),
    # before the +15% mark-up. Admin/Owner only (None when redacted).
    materials_total: Optional[Decimal] = None
