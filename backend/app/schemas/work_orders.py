"""Work order request/response schemas.

Layer: schemas. Consumed by `app/routers/work_orders.py`. The work order is the
first-class entity (identity = `number`); these shapes carry its attributes plus
the logged-material lines. Response models are plain `BaseModel`s the router
builder fills (a line's `item_name` comes from the joined `Item`).
"""

from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


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

class WorkOrderUpdate(BaseModel):
    """Payload for `PATCH /work-orders/{id}` -- explicit edits (overwrite, unlike
    find-or-create's fill-blanks). Any subset; an explicit `null` for
    `assigned_to_ids` replaces the technician set; an empty list clears it.
    `assigned_to_id` remains accepted for compatibility with older clients.
    At least one field required.

    `status` (created|assigned|in_progress|on_hold|completed|review) and `entry_mode`
    (dispense|retroactive) are validated in the service. Closed is archive state,
    never a PATCH status value."""

    number: Optional[str] = None
    community: Optional[str] = None
    building_number: Optional[str] = None
    unit_number: Optional[str] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None
    entry_mode: Optional[str] = None
    assigned_to_id: Optional[UUID] = None
    assigned_to_ids: Optional[list[UUID]] = None
    # CSV-import attributes, editable after import by Admin+. `supervisor_id` is
    # operational routing and remains Supervisor+.
    location: Optional[str] = None
    output_to: Optional[str] = None
    vendor_assignee: Optional[str] = None
    service_type: Optional[str] = None
    schedule_date: Optional[str] = None
    supervisor_id: Optional[UUID] = None
    # Optimistic precondition for routing changes. The browser sends the value
    # it originally rendered (including an explicit null) so a stale pickup
    # cannot overwrite a supervisor selected in another request or by import.
    expected_supervisor_id: Optional[UUID] = None

    @field_validator("number")
    @classmethod
    def _number_not_blank(cls, v):
        if v is None:
            return v
        return _stripped_nonblank(v, "Work order number")

    @field_validator(
        "community",
        "building_number",
        "unit_number",
        "description",
        "notes",
        "location",
        "output_to",
        "vendor_assignee",
        "service_type",
        "schedule_date",
    )
    @classmethod
    def _trim(cls, v):
        return _stripped_or_none(v)

    @model_validator(mode="after")
    def _at_least_one(self):
        if not (self.model_fields_set - {"expected_supervisor_id"}):
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


class WorkOrderLaborCreate(BaseModel):
    """Payload for `POST /work-orders/{id}/labor`. Durations are whole minutes;
    billing rounds the combined work-order total to the next half hour."""

    technician_id: UUID
    minutes: int

    @field_validator("minutes")
    @classmethod
    def _positive_minutes(cls, v):
        if v <= 0:
            raise ValueError("Labor minutes must be greater than zero.")
        return v


class WorkOrderLaborUpdate(BaseModel):
    """Payload for `PATCH /work-orders/{id}/labor/{labor_id}`."""

    minutes: int

    @field_validator("minutes")
    @classmethod
    def _positive_minutes(cls, v):
        if v <= 0:
            raise ValueError("Labor minutes must be greater than zero.")
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


class WorkOrderLaborDetail(BaseModel):
    """One actual labor entry attributed to a technician."""

    id: UUID
    technician_id: UUID
    technician_name: str
    minutes: int


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
    assigned_to_name: Optional[str] = None
    assigned_to_ids: list[UUID] = Field(default_factory=list)
    assigned_to_names: list[str] = Field(default_factory=list)
    item_count: int
    # CSV-import schema (the new default). `vendor_assignee` is the raw export
    # name; `supervisor_id` / `supervisor_name` identify the routed system user;
    # `legacy` flags a pre-import work order (kept for search, empty new fields).
    location: Optional[str] = None
    output_to: Optional[str] = None
    vendor_assignee: Optional[str] = None
    service_type: Optional[str] = None
    schedule_date: Optional[str] = None
    supervisor_id: Optional[UUID] = None
    supervisor_name: Optional[str] = None
    legacy: bool = False


class WorkOrderFilterChoice(BaseModel):
    """A stable value/label pair for a Work Orders select control."""

    value: str
    label: str


class WorkOrderSupervisorFilterChoice(BaseModel):
    """A routed supervisor present on at least one caller-visible work order."""

    id: UUID
    name: str


class WorkOrderFilterOptions(BaseModel):
    """Scoped dynamic values used by the Work Orders advanced filters."""

    service_types: list[str] = Field(default_factory=list)
    supervisors: list[WorkOrderSupervisorFilterChoice] = Field(default_factory=list)
    communities: list[WorkOrderFilterChoice] = Field(default_factory=list)


class WorkOrderLookup(BaseModel):
    """Result of `GET /work-orders/lookup?number=` -- "does this number name a
    work order, and is it archived?".

    Unlike the list/detail routes, this deliberately reports an *archived* work
    order (which those routes hide), so History can spot a searched number whose
    work order has been archived and offer to restore it. Reports `found=False`
    for a number the caller may not see, so it leaks nothing the list would not."""

    found: bool
    archived: bool = False
    id: Optional[UUID] = None
    number: Optional[str] = None


class WorkOrderImportResult(BaseModel):
    """Summary of a `POST /work-orders/import` CSV upload. `created` are new work
    orders, `opened` matched an existing number (fill-blanks, no duplicate);
    `closed` matched an archived number and was ignored without mutation;
    `supervisors_matched`/`supervisors_unmatched` count rows whose vendor name did
    / did not resolve to a system supervisor; `skipped` had a blank number."""

    total: int
    created: int
    opened: int
    closed: int
    supervisors_matched: int
    supervisors_unmatched: int
    skipped: int


class WorkOrderDetail(WorkOrderCard):
    """A work-order card plus notes, logged materials, and labor."""

    notes: Optional[str] = None
    items: list[WorkOrderItemDetail] = Field(default_factory=list)
    labor: list[WorkOrderLaborDetail] = Field(default_factory=list)
    # Base materials charge = sum over lines of (effective_billable * unit_price),
    # before the +15% mark-up. Admin/Owner only (None when redacted).
    materials_total: Optional[Decimal] = None
    labor_minutes: int = 0
    labor_billed_minutes: int = 0
    # Labor bills at the fixed domain rate after total-duration rounding. Both
    # cost fields are Admin/Owner only (None when redacted).
    labor_rate: Optional[Decimal] = None
    labor_total: Optional[Decimal] = None
