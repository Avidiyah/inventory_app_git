"""SMR27 audit services (spec docs/superpowers/specs/2026-10-23-smr-audit-workflow-design.md).

The Owner-only sheet import that turns every Closed row into a
closed-but-unarchived SMR order with a baseline frozen once, and the tile
projection the SMR page reads (before / after / delta per order). Lives beside `services.work_orders` rather
than inside it because that module is already past three thousand lines."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session, selectinload

from app.domain import work_orders as wo
from app.domain import work_orders_smr as smr
from app.domain.errors import WorkOrderStateError
from app.models import User, WorkOrder, WorkOrderItem, WorkOrderLabor, WorkOrderLaborSession, WorkOrderTechnician
from app.schemas.work_orders_smr import (
    SmrCounts,
    SmrDelta,
    SmrFilterOptions,
    SmrImportResult,
    SmrTile,
    SmrTilesResponse,
    SmrTotals,
)
from app.services import work_orders as wos


# --- import --------------------------------------------------------------

def _read_sheet(csv_bytes: bytes) -> list[dict]:
    """Decode, strip an Excel `sep=,` line, parse every record before any
    write, and insist on the headers the import reads by name."""
    try:
        text = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise WorkOrderStateError("SMR sheet must be UTF-8 encoded.") from exc
    stream = io.StringIO(text)
    if stream.readline().strip().casefold() != "sep=,":
        stream.seek(0)
    try:
        reader = csv.DictReader(stream)
        headers = reader.fieldnames or []
        missing = [h for h in smr.SMR_REQUIRED_HEADERS if headers.count(h) != 1]
        if missing:
            raise WorkOrderStateError(
                "SMR sheet must include exactly one of each column: " + ", ".join(missing)
            )
        return list(reader)
    except csv.Error as exc:
        raise WorkOrderStateError("SMR sheet could not be parsed.") from exc


def import_smr(db: Session, *, csv_bytes: bytes, user: User) -> SmrImportResult:
    """Import the SMR27 sheet (Owner).

    Per Closed row: an archived match is restored, a live match is
    fill-blanks merged, a new number is created -- all through the same
    `get_or_create_work_order` the mass import uses. Each touched row gets
    `smr_imported_at` once and `smr_baseline` once (the snapshot taken after
    restore and merge, so a re-run can never move the pre-audit record).
    Canceled rows and blank numbers are skipped untouched. The task text is
    the NetFacilities fallback link so the normal enrichment fills it."""
    rows = _read_sheet(csv_bytes)
    supervisors = wos._supervisor_lookup(db)
    now = datetime.now(timezone.utc)
    created = opened = restored = skipped = baselined = 0

    for row in rows:
        parsed = smr.parse_smr_row(row)
        number = parsed["number"]
        if number is None or not parsed["closed"]:
            skipped += 1
            continue

        existing = wos.find_by_number(db, number)
        was_archived = existing is not None and existing.archived_at is not None
        if was_archived:
            existing.archived_at = None
            db.flush()

        attrs = parsed["attrs"]
        key = wo.normalize_assignee_name(attrs.get("vendor_assignee"))
        work_order = wos.get_or_create_work_order(
            db,
            number=number,
            created_by_id=user.id,
            supervisor_id=supervisors.get(key) if key else None,
            description=wo.work_order_task_fallback(number),
            **attrs,
        )
        if was_archived:
            restored += 1
        elif existing is not None:
            opened += 1
        else:
            created += 1

        if work_order.smr_imported_at is None:
            work_order.smr_imported_at = now
        if work_order.smr_baseline is None:
            db.flush()
            db.refresh(work_order)
            work_order.smr_baseline = smr.snapshot(
                work_order, taken_at=now, source_row=parsed["source_row"]
            )
            baselined += 1
        db.commit()

    return SmrImportResult(
        total=created + opened + restored + skipped,
        created=created,
        opened=opened,
        restored=restored,
        skipped=skipped,
        baselined=baselined,
    )


# --- tiles ---------------------------------------------------------------

def _smr_query(db: Session):
    return db.query(WorkOrder).filter(WorkOrder.smr_imported_at.is_not(None))


def _with_lines(query):
    return query.options(
        selectinload(WorkOrder.items).selectinload(WorkOrderItem.item),
        selectinload(WorkOrder.labor_entries).selectinload(WorkOrderLabor.technician),
        selectinload(WorkOrder.labor_entries).selectinload(WorkOrderLabor.recorded_by),
        selectinload(WorkOrder.labor_sessions).selectinload(WorkOrderLaborSession.technician),
        selectinload(WorkOrder.labor_sessions).selectinload(WorkOrderLaborSession.labor),
    )


def smr_orders(db: Session) -> list[WorkOrder]:
    """Every SMR order, archived or not, with lines and labor loaded."""
    return _with_lines(_smr_query(db)).order_by(WorkOrder.number).all()


def filtered_smr_orders(
    db: Session,
    *,
    status: Optional[str] = None,
    supervisor_id: Optional[uuid.UUID] = None,
    assigned_to_id: Optional[uuid.UUID] = None,
    community: Optional[str] = None,
    priority: Optional[str] = None,
    scheduled_date: Optional[date] = None,
    search: Optional[str] = None,
    location_search: Optional[str] = None,
    task_search: Optional[str] = None,
    descending: bool = True,
) -> list[WorkOrder]:
    """SMR orders through the Work Orders list's own predicates and sort, so
    the SMR page's search and filters cannot drift from the live list's."""
    query = wos._apply_work_order_filters(
        _with_lines(_smr_query(db)),
        status=status,
        supervisor_id=supervisor_id,
        assigned_to_id=assigned_to_id,
        community=community,
        priority=priority,
        search=search,
        location_search=location_search,
        task_search=task_search,
    )
    return wos._filter_and_sort_by_schedule(query.all(), scheduled_date, descending=descending)


def smr_filter_options(db: Session) -> SmrFilterOptions:
    """Dropdown values over every SMR order: the live list's shaping helpers,
    applied to the SMR population instead of the live one."""
    priorities = wos._distinct_filter_values(
        db.query(WorkOrder.priority).filter(WorkOrder.smr_imported_at.is_not(None)).all()
    )
    supervisors = (
        db.query(User).join(WorkOrder, WorkOrder.supervisor_id == User.id)
        .filter(WorkOrder.smr_imported_at.is_not(None)).distinct().all()
    )
    technicians = (
        db.query(User)
        .join(WorkOrderTechnician, WorkOrderTechnician.technician_id == User.id)
        .join(WorkOrder, WorkOrder.id == WorkOrderTechnician.work_order_id)
        .filter(WorkOrder.smr_imported_at.is_not(None)).distinct().all()
    )

    def people(rows):
        return sorted(
            ({"id": row.id, "name": row.full_name} for row in rows),
            key=lambda option: (option["name"].casefold(), str(option["id"])),
        )

    return SmrFilterOptions(
        priorities=priorities,
        supervisors=people(supervisors),
        technicians=people(technicians),
        communities=[
            {"value": value, "label": wo.COMMUNITY_LABELS[value]}
            for value in wo.ALL_COMMUNITY_FILTERS
        ],
    )


def _totals(snap: dict) -> SmrTotals:
    t = snap["totals"]
    return SmrTotals(
        materials_total=Decimal(t["materials_total"]),
        real_minutes=t["real_minutes"],
        skilled_minutes=t["skilled_minutes"],
        labor_total=Decimal(t["labor_total"]),
        total=Decimal(t["total"]),
    )


def current_snapshot(work_order: WorkOrder, *, now: Optional[datetime] = None) -> dict:
    """The AFTER phase: the live order through the baseline's own serializer."""
    return smr.snapshot(work_order, taken_at=now or datetime.now(timezone.utc), source_row=None)


def tile_for(work_order: WorkOrder, *, now: Optional[datetime] = None) -> SmrTile:
    baseline = work_order.smr_baseline or current_snapshot(work_order, now=now)
    current = current_snapshot(work_order, now=now)
    d = smr.deltas(baseline, current)
    return SmrTile(
        id=work_order.id,
        number=work_order.number,
        building_number=work_order.building_number,
        unit_number=work_order.unit_number,
        location=work_order.location,
        vendor_assignee=work_order.vendor_assignee,
        status=work_order.status,
        archived_at=work_order.archived_at,
        edited=smr.is_edited(work_order),
        before=_totals(baseline),
        after=_totals(current),
        delta=SmrTotals(
            materials_total=d["materials_total"],
            real_minutes=d["real_minutes"],
            skilled_minutes=d["skilled_minutes"],
            labor_total=d["labor_total"],
            total=d["total"],
        ),
        after_line_count=len(current["material_lines"]),
    )


def list_smr_tiles(db: Session, **filters) -> SmrTilesResponse:
    """The SMR page payload. `counts`, `delta` and `filter_options` always
    describe every SMR order; `tiles` (schedule-date order, see
    `filtered_smr_orders`) and `matched` honour `filters`."""
    population = smr_orders(db)
    all_tiles = [tile_for(order) for order in population]
    edited = sum(1 for t in all_tiles if t.edited)
    shown = [tile_for(o) for o in filtered_smr_orders(db, **filters)]
    return SmrTilesResponse(
        imported_at=max((o.smr_imported_at for o in population), default=None),
        counts=SmrCounts(
            orders=len(all_tiles),
            edited=edited,
            untouched=len(all_tiles) - edited,
            archived=sum(1 for t in all_tiles if t.archived_at is not None),
        ),
        delta=SmrDelta(
            labor_total=sum((t.delta.labor_total for t in all_tiles), Decimal(0)),
            materials_total=sum((t.delta.materials_total for t in all_tiles), Decimal(0)),
            total=sum((t.delta.total for t in all_tiles), Decimal(0)),
        ),
        matched=len(shown),
        filter_options=smr_filter_options(db),
        tiles=shown,
    )
