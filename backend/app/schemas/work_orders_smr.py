"""Response shapes for the SMR27 audit routes (spec 2026-10-23)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.work_orders import (  # noqa: F401  (SmrTargetOut re-exported)
    SmrTargetOut,
    WorkOrderFilterChoice,
    WorkOrderSupervisorFilterChoice,
)


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


class SmrTargetImportResult(BaseModel):
    """Summary of `POST /work-orders/smr/import-targets`. `targeted` rows set
    an SMR order's target (a later duplicate overwrites an earlier one);
    `skipped` are blank WO#s (the footer); `unknown` are WO#s that are not SMR
    orders, the first 50 listed in `unknown_numbers`."""

    total: int
    targeted: int
    skipped: int
    unknown: int
    unknown_numbers: list[str] = Field(default_factory=list)


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
    # None when the order has no Breakdown row.
    target: Optional[SmrTargetOut] = None


class SmrCounts(BaseModel):
    orders: int
    edited: int
    untouched: int
    archived: int
    # `short` = has a target and is not matched; `no_target` has no row.
    matched: int = 0
    short: int = 0
    no_target: int = 0


class SmrRemaining(BaseModel):
    """Shortfall summed over every SMR order with a target."""

    hours: Decimal = Decimal(0)
    materials_total: Decimal = Decimal(0)


class SmrDelta(BaseModel):
    labor_total: Decimal
    materials_total: Decimal
    total: Decimal


class SmrFilterOptions(BaseModel):
    """Dropdown values drawn from every SMR order (not the live list): the
    Work Orders page's shape minus service type, plus the technicians."""

    priorities: list[str] = Field(default_factory=list)
    supervisors: list[WorkOrderSupervisorFilterChoice] = Field(default_factory=list)
    technicians: list[WorkOrderSupervisorFilterChoice] = Field(default_factory=list)
    communities: list[WorkOrderFilterChoice] = Field(default_factory=list)


class SmrTilesResponse(BaseModel):
    """`counts` and `delta` describe the whole SMR population; `tiles` and
    `matched` reflect the request's filters."""

    imported_at: Optional[datetime] = None
    counts: SmrCounts
    delta: SmrDelta
    remaining: SmrRemaining = Field(default_factory=SmrRemaining)
    matched: int = 0
    filter_options: SmrFilterOptions = Field(default_factory=SmrFilterOptions)
    tiles: list[SmrTile] = Field(default_factory=list)
