"""Shapes for the SMR27 paper-correction routes (spec
docs/superpowers/specs/2026-11-04-smr-paper-import-design.md).

Imports from neither schemas sibling: `schemas/work_orders.py` needs
`SmrLineOut`, `SmrReadingOut` and `SmrBlockOut` for `WorkOrderDetail`, and
`schemas/work_orders_smr.py` already imports from `schemas/work_orders.py`,
so this module sits under both. Response models are built by classmethods
from ORM rows; the `*In` models are the request bodies the router parses.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


def _name(user) -> Optional[str]:
    return getattr(user, "full_name", None) if user is not None else None


# --- workers -------------------------------------------------------------

class SmrWorkerOut(BaseModel):
    id: UUID
    display_name: str
    vendor: str
    aliases: list[str] = Field(default_factory=list)
    is_admin: bool = False
    user_id: Optional[UUID] = None
    archived_at: Optional[datetime] = None

    @classmethod
    def from_row(cls, worker) -> "SmrWorkerOut":
        return cls(
            id=worker.id, display_name=worker.display_name, vendor=worker.vendor,
            aliases=list(worker.aliases or []), is_admin=worker.is_admin,
            user_id=worker.user_id, archived_at=worker.archived_at,
        )


class SmrWorkerIn(BaseModel):
    """Create a worker, or add `alias` to the one that already carries this
    `display_name` + `vendor`. Nobody becomes an app user here."""

    display_name: str
    vendor: str
    alias: Optional[str] = None
    is_admin: bool = False
    user_id: Optional[UUID] = None


class SmrWorkerMergeIn(BaseModel):
    """`POST /workers/{id}/merge`: fold worker `{id}` into `into_id`."""

    into_id: UUID
    reason: str


# --- readings ------------------------------------------------------------

class SmrReadingIn(BaseModel):
    printing_no: int
    work_date: Optional[date] = None
    hours_as_read: Optional[Decimal] = None
    raw_note: str = ""
    reviewer: Optional[str] = None


class SmrReadingEditIn(BaseModel):
    """Any subset of a reading's fields; an explicit null clears a date or hours."""
    printing_no: Optional[int] = None
    work_date: Optional[date] = None
    hours_as_read: Optional[Decimal] = None
    raw_note: Optional[str] = None
    reviewer: Optional[str] = None


class SmrReadingOut(BaseModel):
    id: UUID
    work_order_id: UUID
    printing_no: int
    work_date: Optional[date] = None
    hours_as_read: Optional[Decimal] = None
    raw_note: str
    reviewer: Optional[str] = None
    source: Optional[str] = None
    created_at: datetime

    @classmethod
    def from_row(cls, reading) -> "SmrReadingOut":
        return cls(
            id=reading.id, work_order_id=reading.work_order_id, printing_no=reading.printing_no,
            work_date=reading.work_date, hours_as_read=reading.hours_as_read, raw_note=reading.raw_note or "",
            reviewer=reading.reviewer, source=reading.source, created_at=reading.created_at,
        )


# --- lines ---------------------------------------------------------------

class SmrLineIn(BaseModel):
    """`POST /{id}/lines`. `reason` is the free text the history row keeps."""

    reading_id: Optional[UUID] = None
    work_date: Optional[date] = None
    date_basis: str = "paper"
    vendor: str
    worker_id: Optional[UUID] = None
    alias_on_paper: Optional[str] = None
    headcount: int = 1
    hours_each: Decimal
    kind: str = "field"
    reason_code: str
    status: str = "charged"
    exclusion_ground: Optional[str] = None
    note: Optional[str] = None
    reason: str


class SmrLineEditIn(BaseModel):
    """`PATCH /lines/{line_id}`: any subset of the line's fields plus the
    required `reason`. Only fields present in the body change, so an explicit
    `null` clears a nullable field. `status=excluded, exclusion_ground=removed`
    is the soft remove."""

    reading_id: Optional[UUID] = None
    work_date: Optional[date] = None
    date_basis: Optional[str] = None
    vendor: Optional[str] = None
    worker_id: Optional[UUID] = None
    alias_on_paper: Optional[str] = None
    headcount: Optional[int] = None
    hours_each: Optional[Decimal] = None
    kind: Optional[str] = None
    reason_code: Optional[str] = None
    status: Optional[str] = None
    exclusion_ground: Optional[str] = None
    week: Optional[int] = None  # the week a week placement names; ignored by every other basis
    note: Optional[str] = None
    reason: str


class SmrLineEditOut(BaseModel):
    id: UUID
    field: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    reason: Optional[str] = None
    edited_at: datetime
    edited_by_name: Optional[str] = None

    @classmethod
    def from_row(cls, edit) -> "SmrLineEditOut":
        return cls(
            id=edit.id, field=edit.field, old_value=edit.old_value, new_value=edit.new_value,
            reason=edit.reason, edited_at=edit.edited_at, edited_by_name=_name(getattr(edit, "edited_by", None)),
        )


class SmrLineOut(BaseModel):
    id: UUID
    work_order_id: UUID
    reading_id: Optional[UUID] = None
    import_key: Optional[str] = None
    work_date: Optional[date] = None
    date_basis: str
    week: Optional[int] = None
    vendor: str
    worker_id: Optional[UUID] = None
    worker_name: Optional[str] = None
    alias_on_paper: Optional[str] = None
    headcount: int
    hours_each: Decimal
    # headcount x hours_each, what the line is worth.
    hours: Decimal
    kind: str
    reason_code: str
    status: str
    exclusion_ground: Optional[str] = None
    note: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    history: list[SmrLineEditOut] = Field(default_factory=list)

    @classmethod
    def from_row(cls, line) -> "SmrLineOut":
        worker = getattr(line, "worker", None)
        return cls(
            id=line.id, work_order_id=line.work_order_id, reading_id=line.reading_id,
            import_key=line.import_key, work_date=line.work_date, date_basis=line.date_basis,
            week=line.week, vendor=line.vendor, worker_id=line.worker_id,
            worker_name=worker.display_name if worker is not None else None,
            alias_on_paper=line.alias_on_paper, headcount=line.headcount, hours_each=line.hours_each,
            hours=Decimal(line.headcount) * Decimal(line.hours_each), kind=line.kind,
            reason_code=line.reason_code, status=line.status, exclusion_ground=line.exclusion_ground,
            note=line.note, created_at=line.created_at, updated_at=line.updated_at,
            history=[SmrLineEditOut.from_row(edit) for edit in (getattr(line, "edits", None) or ())],
        )


# --- blocks --------------------------------------------------------------

class SmrBlockOut(BaseModel):
    """The latest (or just generated) correction block. `stale` means the
    order's lines no longer match the digest the block was built from.
    `text` is None below TechFM OA: the block prints dollars."""

    id: UUID
    work_order_id: UUID
    version: int
    text: Optional[str] = None
    generated_at: datetime
    generated_by_name: Optional[str] = None
    pasted_at: Optional[datetime] = None
    pasted_by_name: Optional[str] = None
    lines_digest: str
    stale: bool = False

    @classmethod
    def from_row(cls, block, *, stale: bool, include_price: bool = True) -> "SmrBlockOut":
        return cls(
            id=block.id, work_order_id=block.work_order_id, version=block.version,
            text=block.text if include_price else None, generated_at=block.generated_at,
            generated_by_name=_name(getattr(block, "generated_by", None)), pasted_at=block.pasted_at,
            pasted_by_name=_name(getattr(block, "pasted_by", None)), lines_digest=block.lines_digest, stale=stale,
        )


# --- import --------------------------------------------------------------

class SmrPaperImportResult(BaseModel):
    """Summary of `POST /work-orders/smr/import-paper`. A rerun of the same
    files counts its rows under `skipped_*` and writes nothing. The import
    aborts (400) on an unknown number, so `unknown_numbers` is empty on
    success and the refusal message names them."""

    orders: int
    readings: int
    lines: int
    workers_created: int
    charged_hours: Decimal
    excluded_hours: Decimal
    unknown_numbers: list[str] = Field(default_factory=list)
    created_orders: list[str] = Field(default_factory=list)
    skipped_readings: int = 0
    skipped_lines: int = 0
    run_id: str = ""


# --- hours ---------------------------------------------------------------

class SmrHoursRow(BaseModel):
    """One cell of the Hours tab: `group` is `worker` or `vendor`, `week` is
    the Mon-Sun week number from 05/25/2026 (None for a line with neither a
    date nor a Week 1 placement)."""

    group: str
    name: str
    vendor: str
    week: Optional[int] = None
    week_label: str = ""
    charged_hours: Decimal = Decimal(0)
    excluded_hours: Decimal = Decimal(0)
    lines: int = 0


class SmrHoursOut(BaseModel):
    weeks: list[Optional[int]] = Field(default_factory=list)
    rows: list[SmrHoursRow] = Field(default_factory=list)
    charged_hours: Decimal = Decimal(0)
    excluded_hours: Decimal = Decimal(0)


# --- invoices + weekly chart (spec 2026-11-06-smr-weekly-hours-chart) ------

class SmrInvoiceImportResult(BaseModel):
    """`POST /work-orders/smr/invoices`: rows loaded, the invoice numbers the
    file named (each one's earlier rows replaced), and their hours."""

    total: int
    invoices: list[str] = Field(default_factory=list)
    hours: Decimal = Decimal(0)


class SmrWeeklyCell(BaseModel):
    """One (week, vendor) bar: `invoiced` is the vendor's invoiced hours that
    week, split into `original` (Breakdown billed hours of the orders whose
    paper lines fall there, pro rata), `found` (charged paper hours) and
    `missing` = max(invoiced - original - found, 0). `undated` is the paper
    hours with no date, only in the trailing Undated column (week None)."""

    week: Optional[int] = None
    week_label: str = ""
    vendor: str
    original: Decimal = Decimal(0)
    found: Decimal = Decimal(0)
    undated: Decimal = Decimal(0)
    invoiced: Decimal = Decimal(0)
    carried: Decimal = Decimal(0)  # paper rolled in from the vendor's earlier week
    missing: Decimal = Decimal(0)


class SmrWeeklyHoursOut(BaseModel):
    weeks: list[Optional[int]] = Field(default_factory=list)
    vendors: list[str] = Field(default_factory=list)
    cells: list[SmrWeeklyCell] = Field(default_factory=list)
