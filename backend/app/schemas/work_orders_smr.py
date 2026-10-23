"""Response shapes for the SMR27 audit routes (spec 2026-10-23)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class SmrImportResult(BaseModel):
    """Summary of `POST /work-orders/smr/import`. `created` are new numbers,
    `opened` matched a live row, `restored` matched an archived row and
    un-archived it; `skipped` are Canceled rows and blank numbers; `baselined`
    counts rows that received their frozen pre-audit snapshot on this run."""

    total: int
    created: int
    opened: int
    restored: int
    skipped: int
    baselined: int


class SmrTotals(BaseModel):
    materials_total: Decimal
    real_minutes: int
    skilled_minutes: int
    labor_total: Decimal
    total: Decimal


class SmrTile(BaseModel):
    id: UUID
    number: str
    building_number: Optional[str] = None
    unit_number: Optional[str] = None
    location: Optional[str] = None
    vendor_assignee: Optional[str] = None
    status: str
    archived_at: Optional[datetime] = None
    edited: bool
    before: SmrTotals
    after: SmrTotals
    delta: SmrTotals
    after_line_count: int


class SmrCounts(BaseModel):
    orders: int
    edited: int
    untouched: int
    archived: int


class SmrDelta(BaseModel):
    labor_total: Decimal
    materials_total: Decimal
    total: Decimal


class SmrTilesResponse(BaseModel):
    imported_at: Optional[datetime] = None
    counts: SmrCounts
    delta: SmrDelta
    tiles: list[SmrTile] = Field(default_factory=list)
