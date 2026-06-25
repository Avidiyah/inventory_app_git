"""Mass-staging request/response schemas (truck planning).

Layer: schemas. Consumed by `app/routers/mass_stages.py`. A Mass Stage groups a
building's work orders into truck-load slots; it references standalone
`WorkOrder`s rather than owning them. Response models are plain `BaseModel`s the
router builder fills (a slot's `work_order_number` / a line's `item_name` come
from joined rows).
"""

from datetime import datetime
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
    if v is None:
        return None
    v = v.strip()
    return v or None


# --- Requests ------------------------------------------------------------

class MassStageCreate(BaseModel):
    """Payload for `POST /mass-stages`. `building_name` carries the building
    *number* (column name kept); `community` is the grouping above it."""

    community: str
    building_name: str

    @field_validator("community")
    @classmethod
    def _community_not_blank(cls, v):
        return _stripped_nonblank(v, "Community")

    @field_validator("building_name")
    @classmethod
    def _building_not_blank(cls, v):
        return _stripped_nonblank(v, "Building number")


class MassStageUpdate(BaseModel):
    """Payload for `PATCH /mass-stages/{id}` -- rename and/or change status.
    Status transitions are policed by `domain.mass_staging.validate_transition`."""

    community: Optional[str] = None
    building_name: Optional[str] = None
    status: Optional[str] = None

    @field_validator("community")
    @classmethod
    def _community_not_blank(cls, v):
        if v is None:
            return v
        return _stripped_nonblank(v, "Community")

    @field_validator("building_name")
    @classmethod
    def _building_not_blank(cls, v):
        if v is None:
            return v
        return _stripped_nonblank(v, "Building number")

    @model_validator(mode="after")
    def _at_least_one(self):
        if self.community is None and self.building_name is None and self.status is None:
            raise ValueError("Provide community, building_name, or status to update.")
        return self


class StageWorkOrderCreate(BaseModel):
    """Payload for `POST /mass-stages/{id}/work-orders` -- add a work order to a
    stage's truck plan. The service find-or-creates the `WorkOrder` by number
    (community/building come from the stage; enforced to match), records the
    `unit_number`, optional technician assignee, and links it as a slot."""

    work_order_number: str
    unit_number: Optional[str] = None
    assigned_to_id: Optional[UUID] = None

    @field_validator("work_order_number")
    @classmethod
    def _wo_not_blank(cls, v):
        return _stripped_nonblank(v, "Work order number")

    @field_validator("unit_number")
    @classmethod
    def _unit_trim(cls, v):
        return _stripped_or_none(v)


class StageItemCreate(BaseModel):
    """Payload for `POST /mass-stages/{id}/work-orders/{slot_id}/items`. Planning
    is estimation, so this records an intended quantity -- NOT a transaction."""

    item_id: UUID
    planned_quantity: Decimal

    @field_validator("planned_quantity")
    @classmethod
    def _positive(cls, v):
        if v <= 0:
            raise ValueError("Planned quantity must be greater than zero.")
        return v


class StageItemUpdate(BaseModel):
    """Payload for `PATCH .../work-orders/{slot_id}/items/{stage_item_id}`."""

    planned_quantity: Decimal

    @field_validator("planned_quantity")
    @classmethod
    def _positive(cls, v):
        if v <= 0:
            raise ValueError("Planned quantity must be greater than zero.")
        return v


class LoadRequest(BaseModel):
    """Payload for `POST /mass-stages/{id}/load` -- stage `quantity` of one
    merged item onto the truck (split into per-slot dispenses by the service)."""

    item_id: UUID
    quantity: Decimal

    @field_validator("quantity")
    @classmethod
    def _positive(cls, v):
        if v <= 0:
            raise ValueError("Quantity must be greater than zero.")
        return v


class ReturnRequest(BaseModel):
    """Payload for `POST /mass-stages/{id}/return` -- add `quantity` of one item
    back to stock (silent stock-add, reverse-filled across the item's slots)."""

    item_id: UUID
    quantity: Decimal

    @field_validator("quantity")
    @classmethod
    def _positive(cls, v):
        if v <= 0:
            raise ValueError("Quantity must be greater than zero.")
        return v


# --- Responses (router builder fills nested fields) ----------------------

class StageItemDetail(BaseModel):
    """One planned item on a slot, with its loaded/returned actuals."""

    id: UUID
    item_id: UUID
    item_name: str
    item_barcode: str
    item_quantity: Decimal  # the item's current on-hand stock
    planned_quantity: Decimal
    loaded_quantity: Decimal
    returned_quantity: Decimal


class StageWorkOrderDetail(BaseModel):
    """A work order's slot in a stage: the slot id plus the referenced work
    order's number/unit/status/assignee and the slot's planned items."""

    id: UUID  # slot id (mass_stage_work_orders.id)
    work_order_id: UUID
    work_order_number: str
    unit_number: Optional[str] = None
    status: str  # the work order's status (in_progress | completed)
    sort_order: int
    assigned_to_id: Optional[UUID] = None
    assigned_to_username: Optional[str] = None
    items: list[StageItemDetail] = []


class MergedItem(BaseModel):
    """One item rolled up across the whole stage -- the unit the supervisor
    loads onto the truck. `overflow` = loaded beyond planned; `net_consumed` =
    loaded minus returned; `remaining_to_load` = planned still not loaded."""

    item_id: UUID
    item_name: str
    item_barcode: str
    on_hand: Decimal
    planned_total: Decimal
    loaded_total: Decimal
    returned_total: Decimal
    overflow: Decimal
    net_consumed: Decimal
    remaining_to_load: Decimal


class MassStageDetail(BaseModel):
    """Full stage view: work-order slots (each with planned items) plus the
    per-item merged rollup used by the loading screen."""

    id: UUID
    community: str
    building_name: str
    status: str
    created_at: datetime
    work_orders: list[StageWorkOrderDetail] = []
    merged_items: list[MergedItem] = []


class MassStageSummary(BaseModel):
    """One-line card data for the stage list. `unit_count` = work-order slots;
    `item_count` = DISTINCT items planned across them."""

    id: UUID
    community: str
    building_name: str
    status: str
    unit_count: int
    item_count: int
    created_at: datetime
