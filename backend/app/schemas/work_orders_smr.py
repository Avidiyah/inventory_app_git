"""Response shapes for the SMR27 audit routes (spec 2026-10-23)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.work_orders import (  # noqa: F401  (SmrTargetOut, SmrPaperCheckOut, SmrReadyOut re-exported)
    SmrPaperCheckOut,
    SmrReadyOut,
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


class SmrPaperCheckIn(BaseModel):
    checked: bool


class SmrReadyIn(BaseModel):
    ready: bool


class SmrTotals(BaseModel):
    materials_total: Decimal
    real_minutes: int
    skilled_minutes: int
    labor_total: Decimal
    total: Decimal


class SmrTileLines(BaseModel):
    """Paper-correction lines on a tile (spec 2026-11-04): what the order now
    charges, how far that is from the Breakdown, and the latest block's state.
    `block_stale` means the lines changed after that block was generated."""

    count: int
    charged_hours: Decimal
    excluded_hours: Decimal
    # charged hours minus the Breakdown target; None without a target.
    change_hours: Optional[Decimal] = None
    block_version: Optional[int] = None
    block_pasted_at: Optional[datetime] = None
    block_stale: bool = False


class SmrTile(BaseModel):
    id: UUID
    number: str
    building_number: Optional[str] = None
    unit_number: Optional[str] = None
    location: Optional[str] = None
    vendor_assignee: Optional[str] = None
    status: str
    archived_at: Optional[datetime] = None
    # Anything billable changed since the import, or a paper-correction line
    # exists (user 2026-11-06: paper review counts as edited).
    edited: bool
    # Invoice weeks the order's paper lines fall in ("Before W1", "Week 3",
    # "After W7"), in order, "Undated" last; `["Undated"]` with no lines.
    weeks: list[str] = Field(default_factory=list)
    # Paper stage: not_reviewed | undated | dated | ready (rules.stage_for).
    stage: str
    # Week label of the NetFacilities close date, for undated stages only.
    closed_week: Optional[str] = None
    # Every non-removed line is Belfor's (and there is at least one).
    belfor_only: bool = False
    # The Ready stamp, kept even while the stage has fallen back to undated.
    ready: Optional[SmrReadyOut] = None
    before: SmrTotals
    after: SmrTotals
    delta: SmrTotals
    after_line_count: int
    # None when the order has no Breakdown row.
    target: Optional[SmrTargetOut] = None
    # None until someone marks the order keyed from paper.
    paper_check: Optional[SmrPaperCheckOut] = None
    # None until the order carries a paper-correction line.
    lines: Optional[SmrTileLines] = None


class SmrCounts(BaseModel):
    orders: int
    archived: int
    # Paper stage counts over every SMR order (spec 2026-11-06).
    not_reviewed: int = 0
    undated: int = 0
    dated: int = 0
    ready: int = 0
    belfor_only: int = 0
    # Paper corrections: line hours, and orders with lines whose latest block
    # is missing, not yet pasted or stale.
    charged_hours: Decimal = Decimal(0)
    excluded_hours: Decimal = Decimal(0)
    blocks_not_pasted: int = 0


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
    # The newest Regenerate all run that can still be undone; the page shows Undo while set.
    regenerated_at: Optional[datetime] = None
    counts: SmrCounts
    delta: SmrDelta
    remaining: SmrRemaining = Field(default_factory=SmrRemaining)
    matched: int = 0
    filter_options: SmrFilterOptions = Field(default_factory=SmrFilterOptions)
    tiles: list[SmrTile] = Field(default_factory=list)
