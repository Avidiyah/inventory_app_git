"""The performance board payload (`GET /hub/performance`).

Layer: schemas. Consumed by `app/routers/hub.py`. Components arrive raw
(what the row prints) and scaled (what the score is built from); the weights
and floor ride along so the tab prints the rule it ranks by, from one source.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.hub import HubUser


class PerformanceReason(BaseModel):
    code: str
    label: str
    days: int


class PerformanceExcludedOrder(BaseModel):
    number: str
    reason: str
    label: str


class PerformanceRow(BaseModel):
    user: HubUser
    rank: Optional[int] = None
    below_floor: bool
    score: int
    billed_dollars: Decimal
    efficiency_pct: int
    accuracy_pct: int
    counted_days: int
    active_days: int
    clocked_minutes: int
    scaled: dict[str, int]
    day_reasons: list[PerformanceReason] = Field(default_factory=list)
    excluded_orders: list[PerformanceExcludedOrder] = Field(default_factory=list)


class PerformanceResponse(BaseModel):
    window: str
    start: date
    end: date
    to_date: bool
    server_now: datetime
    weights: dict[str, int]
    floor_minutes: int
    rows: list[PerformanceRow]
