"""Work order request/response schemas.

Layer: schemas. Consumed by `app/routers/work_orders.py`. The work order is the
first-class entity (identity = `number`); these shapes carry its attributes plus
the logged-material lines. Response models are plain `BaseModel`s the router
builder fills (a line's `item_name` comes from the joined `Item`).
"""

from datetime import datetime
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
    `assigned_to_ids` replaces the worker set; an empty list clears it. Active
    Technician, Team Lead, TechFM OA and Admin accounts may be assigned (not the
    Owner). Begin Charging also adds its caller to the set. `assigned_to_id`
    remains accepted for compatibility with older clients.
    A nonblank `notes` value is one new append-only note entry; the service adds
    its timestamp and authenticated author instead of replacing the log. At
    least one field required.

    `status` (created|assigned|in_progress|on_hold|ready_to_complete|completed|
    review) and `entry_mode` (dispense|retroactive) are validated in the
    service. Closed is archive state, never a PATCH status value. Driving a row
    into on_hold, ready_to_complete, or completed stops every clock on it."""

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
    # CSV-import attributes, editable after import by TechFM OA+. `supervisor_id` is
    # operational routing, remains Supervisor+, and may target active TechFM OAs,
    # Admins, or Supervisors.
    location: Optional[str] = None
    output_to: Optional[str] = None
    vendor_assignee: Optional[str] = None
    service_type: Optional[str] = None
    schedule_date: Optional[str] = None
    priority: Optional[str] = None
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
        "priority",
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
    # Set when the Add came from a stocked Material Request's one-tap line.
    # The service resolves that request in the same transaction as the line;
    # a stale id (not stocked, wrong work order, wrong item) is 409 and adds
    # nothing.
    material_request_id: Optional[UUID] = None

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
    billing rounds the combined work-order total to the next half hour.
    `technician_id` is `None` for an anonymous Skilled Technician line, which
    the service accepts only on an SMR order from Admin+ (spec 2026-10-23)."""

    technician_id: Optional[UUID] = None
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
    # TechFM OA and above only (None when redacted for lower roles).
    unit_price: Optional[Decimal] = None
    billable_quantity: Optional[Decimal] = None


class WorkOrderLaborDetail(BaseModel):
    """One actual labor entry attributed to a technician.

    The session fields describe where the duration came from. They are `None`
    for a hand-entered correction and for every row that predates tracked time,
    which the labor card must render as a bare duration rather than treat as an
    error."""

    id: UUID
    # None = Skilled Technician line (`technician_name` carries the label).
    technician_id: Optional[UUID] = None
    technician_name: str
    minutes: int
    # Pre-rendered by the server in the note log's Central timezone (e.g.
    # "2:10-3:25 PM"), for the same reason the log is: the client parses
    # nothing, so a phone in another timezone cannot show a window that
    # disagrees with the `stopped work` line beside it.
    session_window: Optional[str] = None
    # The 12-hour cap closed this session rather than a person. The figure is a
    # prompt to review, never a billing fact accepted on its own.
    auto_closed: bool = False
    # 2026-10-16 self-edit: no session behind the row (typed by a person);
    # keyed by the credited worker themselves; still inside the open Central
    # week. Together they say whether a non-Admin may revise it.
    hand_entered: bool = False
    recorded_by_self: bool = False
    week_open: bool = True


class WorkOrderLaborSessionDetail(BaseModel):
    """A tracking session that is currently running."""

    id: UUID
    technician_id: UUID
    started_at: datetime


class WorkOrderCard(BaseModel):
    """One collapsible work-order card on the Work Orders page list."""

    id: UUID
    number: str
    community: Optional[str] = None
    building_number: Optional[str] = None
    unit_number: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
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
    # SMR27 audit order (spec 2026-10-23): lives on the SMR page, may carry
    # Skilled Technician labor.
    smr: bool = False
    # True when any logged material's item has no price or a $0.00 price -- the
    # same rule that opens a missing-price request. Admin Review paints these red.
    has_unpriced_items: bool = False


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
    priorities: list[str] = Field(default_factory=list)
    supervisors: list[WorkOrderSupervisorFilterChoice] = Field(default_factory=list)
    communities: list[WorkOrderFilterChoice] = Field(default_factory=list)


class WorkOrderLookup(BaseModel):
    """Result of `GET /work-orders/lookup?number=` -- "does this number name a
    work order, and is it archived?".

    Unlike the list/detail routes, this deliberately reports an *archived* work
    order (which those routes hide), so recovery surfaces can spot a searched
    number whose work order has been archived and offer to restore it. Reports
    `found=False` for a number the caller may not see, so it leaks nothing the
    list would not."""

    found: bool
    archived: bool = False
    id: Optional[UUID] = None
    number: Optional[str] = None


class LegacyWorkOrderArchivePreview(BaseModel):
    """Number of currently live legacy work orders eligible for re-archive."""

    count: int


class LegacyWorkOrderArchiveResult(BaseModel):
    """Actual number of legacy work orders archived by the bulk action."""

    archived: int


class WorkOrderImportResult(BaseModel):
    """Summary of a `POST /work-orders/import` CSV upload. `created` are new work
    orders, `opened` matched an existing number (fill-blanks, no duplicate);
    `closed` matched an archived number and was ignored without mutation;
    `supervisors_matched`/`supervisors_unmatched` count only the newly created
    work orders whose vendor name did / did not resolve to a system supervisor
    (a re-imported number keeps its existing routing and is not recounted);
    `skipped` had a blank number. `total` counts every CSV row the import
    accounted for."""

    total: int
    created: int
    opened: int
    closed: int
    supervisors_matched: int
    supervisors_unmatched: int
    skipped: int


class WorkOrderSignatureCreate(BaseModel):
    """The witness sign-off as the pad captures it (spec 2026-09-30)."""

    # ~350 KB of base64 is the 256 KB decoded cap plus the prefix; rejects a
    # giant body before the service decodes it.
    image: str = Field(max_length=360_000)
    witness_name: str = Field(max_length=500)
    witness_phone: str = Field(max_length=40)


class WorkOrderSignatureOut(BaseModel):
    """The locked sign-off on a card (S10). The image itself is fetched from
    `image_url`; `?v=` changes with every capture so a clear-then-resign never
    shows a cached image."""

    witness_name: str
    witness_phone_display: str
    captured_by_name: str
    captured_at: datetime
    captured_at_label: str
    image_url: str


class PriorWorkOut(BaseModel):
    """Who has already worked an order, shown to a caller who has not yet."""

    by: list[str]
    last_at: datetime


class WorkOrderStartTracking(BaseModel):
    """Optional body of `POST /{id}/tracking/start`."""

    notes_acknowledged: bool = False


# The SmrTargetOut fields redacted below TechFM OA.
_SMR_TARGET_MONEY_KEYS = (
    "labor_total", "total", "materials_total", "current_materials_total",
    "gap_materials_total", "remaining_materials_total",
)


class SmrTargetOut(BaseModel):
    """The client's target for an SMR order and how far the live order is from
    it (spec 2026-10-23-smr-target-match). Hours are always visible; the money
    fields are None below TechFM OA, like `materials_total`. `gap` is current
    minus target (negative = still short); `remaining` is the shortfall, 0 when
    at or above target; `matched` is the undershoot-only band rule."""

    hours: Decimal
    current_hours: Decimal
    gap_hours: Decimal
    remaining_hours: Decimal
    matched: bool
    labor_total: Optional[Decimal] = None
    total: Optional[Decimal] = None
    materials_total: Optional[Decimal] = None
    current_materials_total: Optional[Decimal] = None
    gap_materials_total: Optional[Decimal] = None
    remaining_materials_total: Optional[Decimal] = None

    @classmethod
    def from_gap(cls, gap: dict, *, include_price: bool) -> "SmrTargetOut":
        return cls(**{
            key: (value if include_price or key not in _SMR_TARGET_MONEY_KEYS else None)
            for key, value in gap.items()
        })


class SmrPaperCheckOut(BaseModel):
    """Who keyed an SMR order from its paper work order, and when (spec
    2026-10-27-smr-paper-check). `checked_by_name` is None once that user is
    deleted."""

    checked_at: datetime
    checked_by_name: Optional[str] = None

    @classmethod
    def from_order(cls, work_order) -> Optional["SmrPaperCheckOut"]:
        if work_order.smr_paper_checked_at is None:
            return None
        who = work_order.smr_paper_checked_by
        return cls(checked_at=work_order.smr_paper_checked_at, checked_by_name=who.full_name if who else None)


class WorkOrderDetail(WorkOrderCard):
    """A work-order card plus notes, logged materials, labor, and sign-off.

    Two fields are shaped per caller rather than per work order:
    `active_labor_session` is *this* caller's running clock (the card decides
    between Start Tracking and Stop Tracking from it), while
    `tracking_technician_ids` is everyone's, so a supervisor can see that the
    crew is on the job without being on it themselves."""

    notes: Optional[str] = None
    items: list[WorkOrderItemDetail] = Field(default_factory=list)
    labor: list[WorkOrderLaborDetail] = Field(default_factory=list)
    active_labor_session: Optional[WorkOrderLaborSessionDetail] = None
    tracking_technician_ids: list[UUID] = Field(default_factory=list)
    # Others' prior work, for a caller who has not worked the order themselves;
    # the card warns on it and gates Begin Charging when there are notes.
    prior_work: Optional[PriorWorkOut] = None
    # Base materials charge = sum over lines of (effective_billable * unit_price),
    # before the +15% mark-up. TechFM OA and above only (None when redacted).
    materials_total: Optional[Decimal] = None
    labor_minutes: int = 0
    labor_billed_minutes: int = 0
    # Anonymous Skilled Technician minutes (SMR orders), rounded on their own;
    # `labor_total` below already includes their charge.
    skilled_labor_minutes: int = 0
    skilled_labor_billed_minutes: int = 0
    # Labor bills at the fixed domain rate after total-duration rounding. Both
    # cost fields are TechFM OA and above only (None when redacted).
    labor_rate: Optional[Decimal] = None
    labor_total: Optional[Decimal] = None
    # None until a witness signs; one per work order, locked after save (S1).
    signature: Optional[WorkOrderSignatureOut] = None
    # The client's target and the gap to it; SMR orders with a target only.
    smr_target: Optional[SmrTargetOut] = None
    # Paper check mark; SMR orders only, None until someone sets it.
    smr_paper_check: Optional[SmrPaperCheckOut] = None
