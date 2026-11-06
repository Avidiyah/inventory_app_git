"""SMR27 audit routes (spec docs/superpowers/specs/2026-10-23-smr-audit-workflow-design.md).

Mounted under `/work-orders/smr`, declared on its own router so the
`/work-orders/{work_order_id}` catch-all never swallows `smr`. Import and
export are Owner-only; the tile list and the paper check are open to every
role (all hands)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from sqlalchemy.orm import Session

from app.auth_deps import require_min_role
from app.database import get_db
from app.domain import roles
from app.domain.errors import DomainError
from app.models import User
from app.routers._errors import to_http
from app.routers._uploads import MAX_CSV_UPLOAD_BYTES, read_capped
from app.schemas.work_orders_smr import (
    SmrImportResult,
    SmrPaperCheckIn,
    SmrPaperCheckOut,
    SmrReadyIn,
    SmrTile,
    SmrTargetImportResult,
    SmrTilesResponse,
)
from app.schemas.work_orders_smr_lines import (
    SmrBlockOut,
    SmrHoursOut,
    SmrInvoiceImportResult,
    SmrLineEditIn,
    SmrLineIn,
    SmrLineOut,
    SmrPaperImportResult,
    SmrReadingEditIn,
    SmrReadingIn,
    SmrReadingOut,
    SmrWorkerIn,
    SmrWorkerMergeIn,
    SmrWorkerOut,
    SmrWeeklyHoursOut,
)
from app.services import work_orders_smr as smr_service
from app.services import work_orders_smr_import as smr_import
from app.services import work_orders_smr_lines as lines_service
from app.services import work_orders_smr_weekly as weekly_service
from app.services import work_orders_smr_xlsx as smr_xlsx

router = APIRouter(prefix="/work-orders/smr", tags=["work-orders-smr"])


def _forbidden(role: str) -> dict:
    return {403: {"description": f"Requires {roles.ROLE_LABELS[role]} or above."}}


@router.post(
    "/import",
    response_model=SmrImportResult,
    responses={**_forbidden(roles.ROLE_OWNER), 413: {"description": "CSV exceeds the upload size cap."}},
)
def import_smr(
    file: UploadFile = File(...),
    user: User = Depends(require_min_role(roles.ROLE_OWNER)),
    db: Session = Depends(get_db),
) -> SmrImportResult:
    """Import the SMR27 vendor sheet (Owner). Sync `def` for the same reason
    the mass import is: one long transaction belongs in the threadpool. The
    role gate is a dependency, so it answers before the body is read."""
    data = read_capped(file, limit=MAX_CSV_UPLOAD_BYTES, what="CSV file")
    try:
        return smr_service.import_smr(db, csv_bytes=data, user=user)
    except DomainError as exc:
        raise to_http(exc)


@router.post(
    "/import-targets",
    response_model=SmrTargetImportResult,
    responses={**_forbidden(roles.ROLE_OWNER), 413: {"description": "CSV exceeds the upload size cap."}},
)
def import_smr_targets(
    file: UploadFile = File(...),
    user: User = Depends(require_min_role(roles.ROLE_OWNER)),
    db: Session = Depends(get_db),
) -> SmrTargetImportResult:
    """Import the client's Breakdown sheet as per-order targets (Owner)."""
    data = read_capped(file, limit=MAX_CSV_UPLOAD_BYTES, what="CSV file")
    try:
        return smr_service.import_smr_targets(db, csv_bytes=data, user=user)
    except DomainError as exc:
        raise to_http(exc)


@router.get("", response_model=SmrTilesResponse, responses=_forbidden(roles.ROLE_TECHNICIAN))
def list_smr_tiles(
    supervisor_id: Optional[uuid.UUID] = Query(None),
    assigned_to_id: Optional[uuid.UUID] = Query(None),
    community: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    scheduled_date: Optional[date] = Query(None),
    q: Optional[str] = Query(None),
    location_q: Optional[str] = Query(None),
    task_q: Optional[str] = Query(None),
    sort: Literal["scheduled_desc", "scheduled_asc"] = Query("scheduled_desc"),
    has_lines: bool = Query(False),
    block_stale_or_unpasted: bool = Query(False),
    user: User = Depends(require_min_role(roles.ROLE_TECHNICIAN)),
    db: Session = Depends(get_db),
) -> SmrTilesResponse:
    """Every SMR order as a tile with before / after / delta totals (every
    role since 2026-10-23: the re-charge is all hands).
    The query params are the Work Orders list's (minus `status`, `service_type`,
    `mine` and `limit`) and run through the same server predicates. Unpaginated: the
    audit is a few hundred rows."""
    try:
        return smr_service.list_smr_tiles(
            db,
            supervisor_id=supervisor_id,
            assigned_to_id=assigned_to_id,
            community=community,
            priority=priority,
            scheduled_date=scheduled_date,
            search=q,
            location_search=location_q,
            task_search=task_q,
            descending=sort != "scheduled_asc",
            has_lines=has_lines,
            block_stale_or_unpasted=block_stale_or_unpasted,
        )
    except DomainError as exc:
        raise to_http(exc)


@router.put(
    "/{work_order_id}/paper-check",
    response_model=Optional[SmrPaperCheckOut],
    responses=_forbidden(roles.ROLE_TECHNICIAN),
)
def set_paper_check(
    work_order_id: uuid.UUID,
    body: SmrPaperCheckIn,
    user: User = Depends(require_min_role(roles.ROLE_TECHNICIAN)),
    db: Session = Depends(get_db),
) -> Optional[SmrPaperCheckOut]:
    """Mark or clear "keyed from paper" on an SMR order (every role). Returns
    the mark, or null once cleared."""
    try:
        return smr_service.set_paper_check(db, work_order_id=work_order_id, checked=body.checked, user=user)
    except DomainError as exc:
        raise to_http(exc)


@router.put("/{work_order_id}/ready", response_model=SmrTile, responses=_forbidden(roles.ROLE_ADMIN))
def set_ready(
    work_order_id: uuid.UUID,
    body: SmrReadyIn,
    user: User = Depends(require_min_role(roles.ROLE_ADMIN)),
    db: Session = Depends(get_db),
) -> SmrTile:
    """Stamp or clear Ready for invoice (Admin+). 409 "Date a line first."
    when the order has no dated line. Returns the tile."""
    try:
        return smr_service.set_ready(db, work_order_id=work_order_id, ready=body.ready, user=user)
    except DomainError as exc:
        raise to_http(exc)


@router.get("/export.xlsx", responses=_forbidden(roles.ROLE_OWNER))
def export_smr_xlsx(
    user: User = Depends(require_min_role(roles.ROLE_OWNER)),
    db: Session = Depends(get_db),
) -> Response:
    """The before / after / delta audit workbook, every SMR order (Owner)."""
    return Response(
        content=smr_xlsx.smr_workbook(db),
        media_type=smr_xlsx.XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{smr_xlsx.SMR_XLSX_FILENAME}"'},
    )


# --- paper corrections (spec 2026-11-04): Owner imports and merges, Admin+ the rest ---

@router.post(
    "/import-paper",
    response_model=SmrPaperImportResult,
    responses={**_forbidden(roles.ROLE_OWNER), 413: {"description": "A CSV exceeds the upload size cap."}},
)
def import_paper(
    readings: UploadFile = File(...),
    lines: UploadFile = File(...),
    breakdown: Optional[UploadFile] = File(None),
    user: User = Depends(require_min_role(roles.ROLE_OWNER)),
    db: Session = Depends(get_db),
) -> SmrPaperImportResult:
    """The reviewed paper record, once (Owner): `paper_readings.csv` and
    `paper_lines.csv`, plus the Breakdown sheet when reviewed numbers the
    app never had must be created from it. Every row is parsed and
    tie-checked before the first write; a rerun of the same files writes
    nothing; a changed row is refused and named (400)."""
    readings_bytes = read_capped(readings, limit=MAX_CSV_UPLOAD_BYTES, what="readings CSV")
    lines_bytes = read_capped(lines, limit=MAX_CSV_UPLOAD_BYTES, what="lines CSV")
    breakdown_bytes = (
        read_capped(breakdown, limit=MAX_CSV_UPLOAD_BYTES, what="Breakdown CSV") if breakdown is not None else None
    )
    try:
        return smr_import.import_paper(
            db, readings_bytes=readings_bytes, lines_bytes=lines_bytes, breakdown_bytes=breakdown_bytes, user=user,
        )
    except DomainError as exc:
        raise to_http(exc)


@router.post("/{work_order_id}/readings", response_model=SmrReadingOut, responses=_forbidden(roles.ROLE_ADMIN))
def add_reading(
    work_order_id: uuid.UUID,
    body: SmrReadingIn,
    user: User = Depends(require_min_role(roles.ROLE_ADMIN)),
    db: Session = Depends(get_db),
) -> SmrReadingOut:
    """Paper read after the import enters here (Admin+); a second reading of
    the same printing is refused (400)."""
    try:
        return lines_service.add_reading(db, work_order_id=work_order_id, payload=body, user=user)
    except DomainError as exc:
        raise to_http(exc)


@router.post("/{work_order_id}/lines", response_model=SmrLineOut, responses=_forbidden(roles.ROLE_ADMIN))
def add_line(
    work_order_id: uuid.UUID,
    body: SmrLineIn,
    user: User = Depends(require_min_role(roles.ROLE_ADMIN)),
    db: Session = Depends(get_db),
) -> SmrLineOut:
    """One labor line with a free-text `reason` for its `created` history row
    (Admin+). Charged needs a date or the Week 1 placement basis; excluded
    needs a ground."""
    try:
        return lines_service.add_line(db, work_order_id=work_order_id, payload=body, user=user)
    except DomainError as exc:
        raise to_http(exc)


@router.patch("/readings/{reading_id}", response_model=SmrReadingOut, responses=_forbidden(roles.ROLE_ADMIN))
def edit_reading(
    reading_id: uuid.UUID,
    body: SmrReadingEditIn,
    user: User = Depends(require_min_role(roles.ROLE_ADMIN)),
    db: Session = Depends(get_db),
) -> SmrReadingOut:
    """Any subset of a reading's fields (Admin+); a duplicate printing
    number or a no-op is refused (400), an unknown reading 404."""
    try:
        return lines_service.edit_reading(db, reading_id=reading_id, payload=body, user=user)
    except DomainError as exc:
        raise to_http(exc)


@router.patch("/lines/{line_id}", response_model=SmrLineOut, responses=_forbidden(roles.ROLE_ADMIN))
def edit_line(
    line_id: uuid.UUID,
    body: SmrLineEditIn,
    user: User = Depends(require_min_role(roles.ROLE_ADMIN)),
    db: Session = Depends(get_db),
) -> SmrLineOut:
    """Any subset of a line's fields plus the required `reason` (Admin+): one
    history row per changed field; a date on an `undated` line charges it;
    `status=excluded, exclusion_ground=removed` is the soft remove (one
    `deleted` row). Nothing is hard-deleted."""
    try:
        return lines_service.edit_line(db, line_id=line_id, payload=body, user=user)
    except DomainError as exc:
        raise to_http(exc)


@router.get("/workers", response_model=list[SmrWorkerOut], responses=_forbidden(roles.ROLE_ADMIN))
def search_workers(
    q: Optional[str] = Query(None),
    user: User = Depends(require_min_role(roles.ROLE_ADMIN)),
    db: Session = Depends(get_db),
) -> list[SmrWorkerOut]:
    """Live vendor workers by name or alias (Admin+); every one for a blank `q`."""
    return lines_service.search_workers(db, q)


@router.post("/workers", response_model=SmrWorkerOut, responses=_forbidden(roles.ROLE_ADMIN))
def add_worker(
    body: SmrWorkerIn,
    user: User = Depends(require_min_role(roles.ROLE_ADMIN)),
    db: Session = Depends(get_db),
) -> SmrWorkerOut:
    """A new `display_name + vendor`, or an alias on the one that exists (Admin+). No app user is created."""
    try:
        return lines_service.add_worker(db, payload=body)
    except DomainError as exc:
        raise to_http(exc)


@router.post("/workers/{worker_id}/merge", response_model=SmrWorkerOut, responses=_forbidden(roles.ROLE_OWNER))
def merge_workers(
    worker_id: uuid.UUID,
    body: SmrWorkerMergeIn,
    user: User = Depends(require_min_role(roles.ROLE_OWNER)),
    db: Session = Depends(get_db),
) -> SmrWorkerOut:
    """Fold `worker_id` into `into_id` (Owner): lines re-pointed with a
    history row each, aliases kept, the duplicate archived."""
    try:
        return lines_service.merge_workers(db, worker_id=worker_id, into_id=body.into_id, reason=body.reason, user=user)
    except DomainError as exc:
        raise to_http(exc)


@router.post("/{work_order_id}/block", response_model=SmrBlockOut, responses=_forbidden(roles.ROLE_ADMIN))
def generate_block(
    work_order_id: uuid.UUID,
    user: User = Depends(require_min_role(roles.ROLE_ADMIN)),
    db: Session = Depends(get_db),
) -> SmrBlockOut:
    """The next version of the order's correction block from its current
    lines (Admin+), 41 characters wide, kept with its lines digest."""
    try:
        return lines_service.generate_block(db, work_order_id=work_order_id, user=user)
    except DomainError as exc:
        raise to_http(exc)


@router.post("/blocks/{block_id}/pasted", response_model=SmrBlockOut, responses=_forbidden(roles.ROLE_ADMIN))
def mark_pasted(
    block_id: uuid.UUID,
    user: User = Depends(require_min_role(roles.ROLE_ADMIN)),
    db: Session = Depends(get_db),
) -> SmrBlockOut:
    """Stamp the block as pasted into NetFacilities (Admin+); a second stamp keeps the first."""
    try:
        return lines_service.mark_pasted(db, block_id=block_id, user=user)
    except DomainError as exc:
        raise to_http(exc)


@router.get("/hours", response_model=SmrHoursOut, responses=_forbidden(roles.ROLE_ADMIN))
def hours_table(
    user: User = Depends(require_min_role(roles.ROLE_ADMIN)),
    db: Session = Depends(get_db),
) -> SmrHoursOut:
    """Hours by worker x week and vendor x week, charged and excluded, from the lines only (Admin+)."""
    return lines_service.hours_table(db)


@router.get("/hours.csv", responses=_forbidden(roles.ROLE_ADMIN))
def hours_csv(
    user: User = Depends(require_min_role(roles.ROLE_ADMIN)),
    db: Session = Depends(get_db),
) -> Response:
    """The Hours table as CSV (Admin+)."""
    return Response(
        content=lines_service.hours_csv(db),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="smr27-hours.csv"'},
    )


@router.post(
    "/invoices",
    response_model=SmrInvoiceImportResult,
    responses={**_forbidden(roles.ROLE_OWNER), 413: {"description": "CSV exceeds the upload size cap."}},
)
def import_invoices(
    file: UploadFile = File(...),
    user: User = Depends(require_min_role(roles.ROLE_OWNER)),
    db: Session = Depends(get_db),
) -> SmrInvoiceImportResult:
    """Load vendor invoice labor lines (Owner); re-upload replaces by invoice number."""
    data = read_capped(file, limit=MAX_CSV_UPLOAD_BYTES, what="CSV file")
    try:
        return weekly_service.import_invoices(db, csv_bytes=data, user=user)
    except DomainError as exc:
        raise to_http(exc)


@router.get("/weekly-hours", response_model=SmrWeeklyHoursOut, responses=_forbidden(roles.ROLE_ADMIN))
def weekly_hours(
    user: User = Depends(require_min_role(roles.ROLE_ADMIN)),
    db: Session = Depends(get_db),
) -> SmrWeeklyHoursOut:
    """Original / added / invoiced / missing hours per week and vendor (Admin+)."""
    return weekly_service.weekly_hours(db)
