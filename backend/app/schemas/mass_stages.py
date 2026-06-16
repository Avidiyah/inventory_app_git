"""Mass-staging request/response schemas (planning).

Layer: schemas. Consumed by `app/routers/mass_stages.py`. Request validators
mirror `schemas/items.py` (strip-non-blank strings, positive `Decimal`).

The response models are plain `BaseModel`s that the router builder fills,
NOT `from_attributes` shapes: a stage item's `item_name` / `item_barcode`
come from the joined `Item`, which `from_attributes` cannot pull into renamed
fields. See `routers/mass_stages.py::_stage_detail`.
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


# --- Requests ------------------------------------------------------------

class MassStageCreate(BaseModel):
    """Payload for `POST /mass-stages`."""

    building_name: str

    @field_validator("building_name")
    @classmethod
    def _building_not_blank(cls, v):
        return _stripped_nonblank(v, "Building name")


class MassStageUpdate(BaseModel):
    """Payload for `PATCH /mass-stages/{id}` -- rename and/or change status.

    `status` is left to the service's `domain.mass_staging.validate_transition`
    to police (a bad target raises `InvalidStageTransitionError`), so it is
    accepted as a free string here. At least one field must be present.
    """

    building_name: Optional[str] = None
    status: Optional[str] = None

    @field_validator("building_name")
    @classmethod
    def _building_not_blank(cls, v):
        if v is None:
            return v
        return _stripped_nonblank(v, "Building name")

    @model_validator(mode="after")
    def _at_least_one(self):
        if self.building_name is None and self.status is None:
            raise ValueError("Provide building_name or status to update.")
        return self


class RoomCreate(BaseModel):
    """Payload for `POST /mass-stages/{id}/rooms`."""

    room_number: str
    work_order_number: str

    @field_validator("room_number")
    @classmethod
    def _room_not_blank(cls, v):
        return _stripped_nonblank(v, "Room number")

    @field_validator("work_order_number")
    @classmethod
    def _wo_not_blank(cls, v):
        return _stripped_nonblank(v, "Work order number")


class RoomUpdate(BaseModel):
    """Payload for `PATCH /mass-stages/{id}/rooms/{room_id}`."""

    room_number: Optional[str] = None
    work_order_number: Optional[str] = None

    @field_validator("room_number", "work_order_number")
    @classmethod
    def _not_blank_if_present(cls, v):
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("Field cannot be blank.")
        return v

    @model_validator(mode="after")
    def _at_least_one(self):
        if self.room_number is None and self.work_order_number is None:
            raise ValueError("Provide room_number or work_order_number to update.")
        return self


class StageItemCreate(BaseModel):
    """Payload for `POST /mass-stages/{id}/rooms/{room_id}/items`. Planning is
    estimation, so this records an intended quantity -- it is NOT a transaction."""

    item_id: UUID
    planned_quantity: Decimal

    @field_validator("planned_quantity")
    @classmethod
    def _positive(cls, v):
        if v <= 0:
            raise ValueError("Planned quantity must be greater than zero.")
        return v


class StageItemUpdate(BaseModel):
    """Payload for `PATCH /mass-stages/{id}/rooms/{room_id}/items/{stage_item_id}`."""

    planned_quantity: Decimal

    @field_validator("planned_quantity")
    @classmethod
    def _positive(cls, v):
        if v <= 0:
            raise ValueError("Planned quantity must be greater than zero.")
        return v


class LoadRequest(BaseModel):
    """Payload for `POST /mass-stages/{id}/load` -- stage `quantity` of one
    merged item onto the truck (split into per-room dispenses by the service)."""

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
    back to stock (silent stock-add, reverse-filled across the item's rooms)."""

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
    """One planned item on a room, with its actuals. `loaded_quantity` /
    `returned_quantity` stay 0 until Phase 5 wires loading/returns."""

    id: UUID
    item_id: UUID
    item_name: str
    item_barcode: str
    item_quantity: Decimal  # the item's current on-hand stock
    planned_quantity: Decimal
    loaded_quantity: Decimal
    returned_quantity: Decimal


class RoomDetail(BaseModel):
    id: UUID
    room_number: str
    work_order_number: str
    sort_order: int
    items: list[StageItemDetail] = []


class MergedItem(BaseModel):
    """One item rolled up across the whole stage -- the unit the supervisor
    loads onto the truck. `overflow` = loaded beyond planned (e.g. box-of-4
    packaging); `net_consumed` = loaded minus returned; `remaining_to_load` =
    planned still not loaded. Returned by `/load` and `/return`, and listed on
    the stage detail."""

    item_id: UUID
    item_name: str
    item_barcode: str
    on_hand: Decimal  # the item's current on-hand stock (coverage check)
    planned_total: Decimal
    loaded_total: Decimal
    returned_total: Decimal
    overflow: Decimal
    net_consumed: Decimal
    remaining_to_load: Decimal


class MassStageDetail(BaseModel):
    """Full stage view: rooms (each with their planned items) plus the
    per-item merged rollup used by the loading screen."""

    id: UUID
    building_name: str
    status: str
    created_at: datetime
    rooms: list[RoomDetail] = []
    merged_items: list[MergedItem] = []


class MassStageSummary(BaseModel):
    """One-line card data for the stage list. `item_count` is the number of
    DISTINCT items across the stage's rooms (design-record R3)."""

    id: UUID
    building_name: str
    status: str
    room_count: int
    item_count: int
    created_at: datetime
