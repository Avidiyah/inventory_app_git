"""Takeoff request/response schemas (predicted material per work order).

Layer: schemas. Consumed by `app/services/takeoff.py` and the takeoff router.
"""

from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class TakeoffLineCreate(BaseModel):
    item_id: UUID
    quantity: Decimal = Field(gt=0)


class TakeoffLineUpdate(BaseModel):
    quantity: Decimal = Field(gt=0)


class TakeoffLineOut(BaseModel):
    id: UUID
    item_id: UUID
    item_name: str
    quantity: Decimal


class TakeoffPurchaseSet(BaseModel):
    item_id: UUID
    service_type_key: str
    service_type_label: str
    quantity: Decimal = Field(ge=0)


class TakeoffWorkOrderRef(BaseModel):
    id: UUID
    number: str
    quantity: Decimal


class TakeoffRow(BaseModel):
    item_id: UUID
    item_name: str
    product_link: Optional[str] = None
    price: Optional[Decimal] = None
    need: Decimal
    total: Optional[Decimal] = None
    stock: Decimal
    on_the_way: Decimal
    shortfall: Decimal
    shared: bool
    work_orders: list[TakeoffWorkOrderRef]


class TakeoffGroup(BaseModel):
    service_type_key: str
    service_type_label: str
    total: Decimal
    rows: list[TakeoffRow]


class TakeoffOverview(BaseModel):
    groups: list[TakeoffGroup]
