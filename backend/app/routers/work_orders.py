"""HTTP routes for the `/work-orders` resource (the work order entity).

Layer: routers (FastAPI). Thin handlers: parse via a Pydantic schema, delegate
to `app.services.work_orders`, translate `DomainError` via `to_http`.

Most routes are open to any authenticated user but **server-scoped** (technician
-> assigned, supervisor -> created/routed, admin/owner -> all). Technicians may
save notes, add materials, and use narrow assigned-worker start/complete/hold/resume
walkthrough. Supervisor+ owns operational routing, general status, entry mode,
labor, and material corrections. Sending Completed work to Review requires a
second person: an assigned worker is excluded even when also routed Supervisor.
TechFM OA+ additionally owns imported and legacy metadata edits.
Closing (the archive operation) is TechFM OA+ from any live status. Both an expanded
Work Orders card and the Review queue may call the same endpoint.
Out-of-scope, archived, or unknown work orders surface as 404.

There is no create route: work orders are import-only, so `POST /work-orders/
import` (TechFM OA+) is the one way a work order enters the system. Everything else
here operates on an already-imported work order.

**Every static role gate in this module is declarative.** Eight routes carry
`Depends(require_min_role(...))` and declare their 403 through `_forbidden`;
none checks a rank inside the handler body. That is deliberate (item C1): an
in-body gate has no stable anchor, is invisible in the schema, runs after the
session is open and the body parsed, and is opt-in -- a new route here inherits
nothing. Per-row *visibility* and the per-field edit matrix stay in
`app.services.work_orders`, because those need the loaded row.
"""

import re
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.auth_deps import get_current_user, require_min_role
from app.database import get_db
from app.domain import realtime as realtime_policy
from app.domain import roles
from app.domain import work_orders as wo
from app.domain.errors import DomainError
from app.domain.list_limits import MAX_LIST_ROWS
from app.logging_config import current_request_id
from app.models import User, WorkOrder, WorkOrderItem, WorkOrderLabor
from app.routers._errors import to_http
from app.routers._uploads import MAX_CSV_UPLOAD_BYTES, read_capped
from app.schemas.work_orders import (
    LegacyWorkOrderArchivePreview,
    LegacyWorkOrderArchiveResult,
    WorkOrderCard,
    WorkOrderDetail,
    WorkOrderFilterOptions,
    WorkOrderImportResult,
    WorkOrderItemBilling,
    WorkOrderItemCreate,
    WorkOrderItemDetail,
    WorkOrderItemUpdate,
    WorkOrderLaborCreate,
    WorkOrderLaborDetail,
    WorkOrderLaborUpdate,
    WorkOrderLookup,
    WorkOrderUpdate,
)
from app.services import realtime as realtime_service
from app.services import work_orders as wo_service

router = APIRouter(prefix="/work-orders", tags=["work-orders"])


def _emit_review_queue_changed(entity_id: Optional[uuid.UUID]) -> None:
    """Invalidate Admin Review after one capable command succeeds.

    ``None`` identifies a collection command (CSV import or bulk legacy
    archive). Delivery is best-effort: ``emit`` is total and its boolean result
    is deliberately ignored so a full handoff can never fail a durable write.
    """
    realtime_service.emit(
        realtime_policy.build_envelope(
            event_type=realtime_policy.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED,
            entity_id=entity_id,
            request_id=current_request_id(),
        )
    )


# --- response builders ---------------------------------------------------

def _filename_slug(value) -> str:
    """Short filesystem-safe token for one active export filter value."""
    return re.sub(r"[^a-z0-9]+", "-", str(value).strip().casefold()).strip("-")[:24]


def _export_filename(
    db: Session,
    *,
    scope: str,
    variant: str,
    service_type: Optional[str],
    supervisor_id: Optional[uuid.UUID],
    community: Optional[str],
    scheduled_date: Optional[date],
    search: Optional[str],
) -> str:
    """`MM-DD-YY_HH-MM_filter1-filter2.csv` for the honored filters.

    A hyphen separates hour/minute because Windows filenames cannot contain `:`.
    """
    stamp = datetime.now(timezone.utc).strftime("%m-%d-%y_%H-%M")
    parts: list[str] = []
    if variant == wo.EXPORT_VARIANT_CLIENT:
        parts = ["client", scope]
    else:
        if scope != wo.EXPORT_SCOPE_ALL:
            parts.extend(("status", scope))
        if service_type and service_type.strip():
            parts.extend(("service", service_type))
        if supervisor_id is not None:
            supervisor = db.query(User).filter(User.id == supervisor_id).first()
            parts.extend(
                ("supervisor", supervisor.full_name if supervisor else supervisor_id)
            )
        if community and community.strip():
            parts.extend(("community", community))
        if scheduled_date is not None:
            parts.extend(("date", scheduled_date.isoformat()))
        if search and search.strip():
            parts.extend(("number", search))
    tokens = [_filename_slug(part) for part in parts]
    filters = "-".join(token for token in tokens if token) or "all"
    return f"{stamp}_{filters}.csv"

def _effective_billable(line: WorkOrderItem) -> Decimal:
    """Units actually charged on a line: the override when set, else the full
    recorded quantity. The rule itself lives in the domain so the CSV export
    bills identically."""
    return wo.effective_billable(line.quantity, line.billable_quantity)


def _line_detail(line: WorkOrderItem, *, include_price: bool) -> WorkOrderItemDetail:
    return WorkOrderItemDetail(
        id=line.id,
        item_id=line.item_id,
        item_name=line.item.name,
        item_barcode=line.item.barcode,
        item_quantity=line.item.quantity,
        quantity=line.quantity,
        mode=line.mode,
        # The line bills at the item's current price; both cost fields are
        # redacted below TechFM OA.
        unit_price=line.item.price if include_price else None,
        billable_quantity=line.billable_quantity if include_price else None,
    )


def _card(work_order: WorkOrder) -> WorkOrderCard:
    technicians = wo_service.assigned_technicians(work_order)
    legacy_id = getattr(work_order, "assigned_to_id", None)
    technician_pairs = [
        (getattr(technician, "id", legacy_id if index == 0 else None), technician)
        for index, technician in enumerate(technicians)
    ]
    technician_pairs = [(tech_id, tech) for tech_id, tech in technician_pairs if tech_id]
    technician_ids = [tech_id for tech_id, _ in technician_pairs]
    technician_names = [technician.full_name for _, technician in technician_pairs]
    primary_pair = next(
        ((tech_id, tech) for tech_id, tech in technician_pairs if tech_id == legacy_id),
        technician_pairs[0] if technician_pairs else None,
    )
    return WorkOrderCard(
        id=work_order.id,
        number=work_order.number,
        community=work_order.community,
        building_number=work_order.building_number,
        unit_number=work_order.unit_number,
        description=work_order.description,
        priority=work_order.priority,
        status=work_order.status,
        entry_mode=work_order.entry_mode,
        created_by_id=work_order.created_by_id,
        assigned_to_id=primary_pair[0] if primary_pair else None,
        assigned_to_name=primary_pair[1].full_name if primary_pair else None,
        assigned_to_ids=technician_ids,
        assigned_to_names=technician_names,
        item_count=len(work_order.items),
        location=work_order.location,
        output_to=work_order.output_to,
        vendor_assignee=work_order.vendor_assignee,
        service_type=work_order.service_type,
        schedule_date=work_order.schedule_date,
        supervisor_id=work_order.supervisor_id,
        supervisor_name=work_order.supervisor.full_name if work_order.supervisor else None,
        legacy=work_order.legacy,
    )


def _materials_total(work_order: WorkOrder) -> Decimal:
    """Base materials charge (pre-mark-up): sum of each line's effective billable
    units times the item's current price."""
    total = Decimal(0)
    for line in work_order.items:
        price = line.item.price or Decimal(0)
        total += price * _effective_billable(line)
    return total


def _labor_detail(entry: WorkOrderLabor) -> WorkOrderLaborDetail:
    return WorkOrderLaborDetail(
        id=entry.id,
        technician_id=entry.technician_id,
        technician_name=entry.technician.full_name,
        minutes=entry.minutes,
    )


def _detail(work_order: WorkOrder, *, include_price: bool) -> WorkOrderDetail:
    labor_entries = list(getattr(work_order, "labor_entries", None) or ())
    labor_minutes = sum(entry.minutes for entry in labor_entries)
    return WorkOrderDetail(
        **_card(work_order).model_dump(),
        notes=work_order.notes,
        items=[_line_detail(line, include_price=include_price) for line in work_order.items],
        labor=[_labor_detail(entry) for entry in labor_entries],
        materials_total=_materials_total(work_order) if include_price else None,
        labor_minutes=labor_minutes,
        labor_billed_minutes=wo.billed_labor_minutes(labor_minutes),
        labor_rate=wo.LABOR_RATE if include_price else None,
        labor_total=wo.labor_charge(labor_minutes) if include_price else None,
    )


def _can_see_price(user: User) -> bool:
    """Cost fields (line unit price) are TechFM OA and above only, mirroring item /
    history price redaction."""
    return roles.role_at_least(user.role, roles.ROLE_TECHFM_OA)


def _forbidden(minimum: str) -> dict:
    """The OpenAPI `responses` entry for a route's `require_min_role` gate.

    FastAPI does not infer a 403 from a dependency that is merely capable of
    raising one, so a declarative gate is exactly as invisible in the schema as
    the in-body `raise` it replaced -- unless the route says so. Declared for
    the same reason B1 declared its 413: a failure mode a caller can actually
    hit belongs in the contract.

    Named once so the eight gated routes in this module cannot drift into
    describing the same status differently."""
    return {403: {"description": f"Requires the {roles.label(minimum)} role or above."}}


# --- routes --------------------------------------------------------------

@router.get("/", response_model=list[WorkOrderCard])
def list_work_orders(
    status: Optional[str] = Query(None),
    service_type: Optional[str] = Query(None),
    supervisor_id: Optional[uuid.UUID] = Query(None),
    community: Optional[str] = Query(None),
    scheduled_date: Optional[date] = Query(None),
    q: Optional[str] = Query(None),
    limit: Optional[int] = Query(None, ge=1, le=MAX_LIST_ROWS),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List the caller's work orders, newest scheduled date first. Optional `status`, exact
    `service_type`, routed `supervisor_id`, derived `community`, exact
    `scheduled_date`, and number `q` filters combine with AND. Community is
    membership-based over structured community plus raw CSV location; Academics
    is the no-known-term fallback. `limit` caps that scheduled-date ordering (the
    page browses the first 10 by default and omits `limit` for Show all / search).
    Blank or malformed schedule values sort last. Any authenticated user;
    server-scoped.

    `limit` gained its `le` bound in X3 -- it was `ge=1` with no upper bound, so
    a caller could ask for any integer. Omitting it still means "the full
    matching set", which the service now caps at `MAX_LIST_ROWS`."""
    try:
        return [
            _card(w)
            for w in wo_service.list_work_orders(
                db,
                user=user,
                status=status,
                service_type=service_type,
                supervisor_id=supervisor_id,
                community=community,
                scheduled_date=scheduled_date,
                search=q,
                limit=limit,
            )
        ]
    except DomainError as exc:
        raise to_http(exc)


@router.get("/filter-options", response_model=WorkOrderFilterOptions)
def work_order_filter_options(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Distinct service types and supervisors from caller-visible live work
    orders, plus the stable derived-community choices. Any authenticated user;
    server-scoped exactly like the card list.

    Declared before `/{work_order_id}` so "filter-options" is not parsed as an id.
    """
    return WorkOrderFilterOptions(
        **wo_service.get_work_order_filter_options(db, user=user)
    )


@router.post(
    "/import",
    response_model=WorkOrderImportResult,
    responses={
        **_forbidden(roles.ROLE_TECHFM_OA),
        413: {"description": "CSV exceeds the upload size cap."},
    },
)
def import_work_orders(
    file: UploadFile = File(...),
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
):
    """Bulk-import work orders from the mass CSV export (TechFM OA+). Each row
    find-or-creates by number (idempotent re-upload), stores the new-schema
    columns, and matches the vendor `ASSIGNED TO` name to a supervisor to route
    visibility. Archived matches are counted as closed and left untouched.
    Returns a summary of created/opened/closed/matched/skipped counts.

    Deliberately `def`, not `async def`: the import is one long synchronous
    SQLAlchemy transaction over the whole CSV. On the event loop it would
    stall *every* concurrent request until the import finished; as a sync
    handler FastAPI runs it in the threadpool, like the rest of this app's
    routes. `read_capped` is the sync equivalent of `await file.read()`
    on the same spooled upload, refusing anything over
    `MAX_CSV_UPLOAD_BYTES` with a 413 before the parse begins.

    The size check runs *after* the role gate, so an unauthorised caller
    learns nothing about the cap. That ordering used to be statement order in
    this body; it is now FastAPI's, which solves declared dependencies before
    it reads the form body. Pinned by
    `test_the_role_gate_still_runs_before_the_size_check`."""
    data = read_capped(file, limit=MAX_CSV_UPLOAD_BYTES, what="CSV file")
    try:
        summary = wo_service.import_work_orders(db, csv_bytes=data, user=user)
        _emit_review_queue_changed(None)
    except DomainError as exc:
        raise to_http(exc)
    return WorkOrderImportResult(**summary)


@router.get("/export", responses=_forbidden(roles.ROLE_TECHFM_OA))
def export_work_orders(
    scope: str = Query(wo.EXPORT_SCOPE_ALL),
    variant: str = Query(wo.EXPORT_VARIANT_FULL),
    service_type: Optional[str] = None,
    supervisor_id: Optional[uuid.UUID] = None,
    community: Optional[str] = None,
    scheduled_date: Optional[date] = None,
    q: Optional[str] = None,
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
):
    """Download the caller's work orders as CSV, one row per work order
    (TechFM OA+).

    `scope` is `all`, `archived`, or one live status -- the same vocabulary the
    page's status filter uses, plus the closed work orders the list hides.

    `variant=full` leads with the import's own headers and also accepts the Work
    Orders page's exact `service_type`, routed `supervisor_id`, derived
    `community`, exact `scheduled_date`, and number `q` filters. They combine
    with `scope` using AND and have no result cap. `variant=client` remains the
    existing scope-only billing sheet. 400 on an unrecognised scope, community,
    or variant.

    Declared before `/{work_order_id}` so "export" is not parsed as an id."""
    try:
        body = wo_service.export_work_orders_csv(
            db,
            user=user,
            scope=scope,
            variant=variant,
            service_type=service_type,
            supervisor_id=supervisor_id,
            community=community,
            scheduled_date=scheduled_date,
            search=q,
        )
    except DomainError as exc:
        raise to_http(exc)
    filename = _export_filename(
        db,
        scope=scope,
        variant=variant,
        service_type=service_type,
        supervisor_id=supervisor_id,
        community=community,
        scheduled_date=scheduled_date,
        search=q,
    )
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/lookup",
    response_model=WorkOrderLookup,
    responses=_forbidden(roles.ROLE_SUPERVISOR),
)
def lookup_work_order(
    number: str = Query(..., min_length=1),
    user: User = Depends(require_min_role(roles.ROLE_SUPERVISOR)),
    db: Session = Depends(get_db),
):
    """Report whether `number` names a work order the caller can see, and whether
    it is archived (Supervisor+).

    Declared before `/{work_order_id}` so "lookup" is not parsed as an id. This is
    the one read that sees through the archive: the list and detail routes hide
    archived work orders, which leaves a searched number with no visible work
    order. History and TechFM OA+'s Work Orders search use this to offer a restore. A
    number the caller may not see reports `found=False`, same as the list would
    show."""
    work_order = wo_service.lookup_work_order(db, number=number, user=user)
    if work_order is None:
        return WorkOrderLookup(found=False)
    return WorkOrderLookup(
        found=True,
        archived=work_order.archived_at is not None,
        id=work_order.id,
        number=work_order.number,
    )


@router.get(
    "/legacy/archive",
    response_model=LegacyWorkOrderArchivePreview,
    responses=_forbidden(roles.ROLE_OWNER),
)
def preview_legacy_work_order_archive(
    user: User = Depends(require_min_role(roles.ROLE_OWNER)),
    db: Session = Depends(get_db),
):
    """Count live legacy work orders before the Owner confirms re-archive."""
    try:
        count = wo_service.count_live_legacy_work_orders(db, user=user)
    except DomainError as exc:
        raise to_http(exc)
    return LegacyWorkOrderArchivePreview(count=count)


@router.post(
    "/legacy/archive",
    response_model=LegacyWorkOrderArchiveResult,
    responses=_forbidden(roles.ROLE_OWNER),
)
def archive_legacy_work_orders(
    user: User = Depends(require_min_role(roles.ROLE_OWNER)),
    db: Session = Depends(get_db),
):
    """Soft-archive every currently live legacy work order (Owner only)."""
    try:
        archived = wo_service.archive_live_legacy_work_orders(db, user=user)
        _emit_review_queue_changed(None)
    except DomainError as exc:
        raise to_http(exc)
    return LegacyWorkOrderArchiveResult(archived=archived)


@router.get("/{work_order_id}", response_model=WorkOrderDetail)
def get_work_order(
    work_order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Full work-order detail with logged materials. 404 if unknown, archived,
    or not visible to the caller."""
    try:
        return _detail(
            wo_service.get_work_order(db, work_order_id, user=user),
            include_price=_can_see_price(user),
        )
    except DomainError as exc:
        raise to_http(exc)


@router.patch("/{work_order_id}", response_model=WorkOrderDetail)
def update_work_order(
    work_order_id: uuid.UUID,
    payload: WorkOrderUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Edit a scoped work order under the service's role matrix.

    Technician: append notes only. Supervisor+: routing, technicians, general
    status, and entry mode. TechFM OA+: imported/legacy metadata as well. Review is
    restricted further to a Completed row and a second, unassigned responsible
    user. The service stamps each nonblank note with server time and the
    authenticated user's display name. Server-scoped.
    """
    fields = payload.model_dump(exclude_unset=True)
    has_supervisor_precondition = "expected_supervisor_id" in fields
    expected_supervisor_id = fields.pop("expected_supervisor_id", None)
    try:
        update_kwargs = {}
        if has_supervisor_precondition:
            update_kwargs["expected_supervisor_id"] = expected_supervisor_id
        work_order = wo_service.update_work_order(
            db,
            work_order_id,
            user=user,
            fields=fields,
            **update_kwargs,
        )
        _emit_review_queue_changed(work_order.id)
        return _detail(
            # The caller may just have routed the row to somebody else. The
            # write was already authorized above, so build its response through
            # the internal scope instead of turning a successful transfer into
            # a false 404.
            wo_service.get_work_order(db, work_order.id, user=None),
            include_price=_can_see_price(user),
        )
    except DomainError as exc:
        raise to_http(exc)


@router.post("/{work_order_id}/start", response_model=WorkOrderDetail)
def start_work_order(
    work_order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start a visible Assigned work order without leaving Scan / Stock.

    Available to assigned Technicians and Supervisor+ users. This does not
    broaden the general PATCH status permission matrix.
    """
    try:
        work_order = wo_service.start_work_order(db, work_order_id, user=user)
        return _detail(
            wo_service.get_work_order(db, work_order.id, user=user),
            include_price=_can_see_price(user),
        )
    except DomainError as exc:
        raise to_http(exc)


@router.post("/{work_order_id}/complete", response_model=WorkOrderDetail)
def complete_work_order(
    work_order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Complete an In-Progress work order as one of its assigned workers.

    This is the final assigned-worker walkthrough step. It grants no general
    status editing and cannot send the work order to Review.
    """
    try:
        work_order = wo_service.complete_work_order(
            db, work_order_id, user=user
        )
        return _detail(
            wo_service.get_work_order(db, work_order.id, user=user),
            include_price=_can_see_price(user),
        )
    except DomainError as exc:
        raise to_http(exc)


@router.post("/{work_order_id}/hold", response_model=WorkOrderDetail)
def hold_work_order(
    work_order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Place In-Progress work On-Hold as one of its assigned workers."""
    try:
        work_order = wo_service.hold_work_order(db, work_order_id, user=user)
        return _detail(
            wo_service.get_work_order(db, work_order.id, user=user),
            include_price=_can_see_price(user),
        )
    except DomainError as exc:
        raise to_http(exc)


@router.post("/{work_order_id}/resume", response_model=WorkOrderDetail)
def resume_work_order(
    work_order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Resume On-Hold work as one of its assigned workers."""
    try:
        work_order = wo_service.resume_work_order(db, work_order_id, user=user)
        return _detail(
            wo_service.get_work_order(db, work_order.id, user=user),
            include_price=_can_see_price(user),
        )
    except DomainError as exc:
        raise to_http(exc)


@router.post(
    "/{work_order_id}/archive",
    status_code=204,
    responses=_forbidden(roles.ROLE_TECHFM_OA),
)
def archive_work_order(
    work_order_id: uuid.UUID,
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
):
    """Close any live work order (TechFM OA+, scoped) by soft-archiving it."""
    try:
        wo_service.archive_work_order(db, work_order_id, user=user)
        _emit_review_queue_changed(work_order_id)
    except DomainError as exc:
        raise to_http(exc)


@router.post(
    "/{work_order_id}/restore",
    response_model=WorkOrderDetail,
    responses=_forbidden(roles.ROLE_SUPERVISOR),
)
def restore_work_order(
    work_order_id: uuid.UUID,
    user: User = Depends(require_min_role(roles.ROLE_SUPERVISOR)),
    db: Session = Depends(get_db),
):
    """Un-archive a work order (Supervisor+, scoped), bringing it back onto the
    Work Orders page with its materials intact. This explicit undo is the only
    way back; CSV import counts and ignores archived matches. 404 if unknown or
    not visible to the caller."""
    try:
        work_order = wo_service.restore_work_order(db, work_order_id, user=user)
        _emit_review_queue_changed(work_order.id)
        return _detail(
            wo_service.get_work_order(db, work_order.id, user=user),
            include_price=_can_see_price(user),
        )
    except DomainError as exc:
        raise to_http(exc)


@router.post("/{work_order_id}/items", response_model=WorkOrderItemDetail, status_code=201)
def add_work_order_item(
    work_order_id: uuid.UUID,
    payload: WorkOrderItemCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Log a material using the work order's current entry mode (dispense moves
    stock; retroactive is stock-neutral). Re-adding an item adds its quantity.
    A dispense shortage is recorded and raises a recount User Request instead
    of failing. Server-scoped for Technician and above."""
    try:
        line = wo_service.add_work_order_item(
            db, work_order_id, user=user, item_id=payload.item_id, quantity=payload.quantity
        )
        return _line_detail(line, include_price=_can_see_price(user))
    except DomainError as exc:
        raise to_http(exc)


@router.patch("/{work_order_id}/items/{wo_item_id}", response_model=WorkOrderItemDetail)
def update_work_order_item(
    work_order_id: uuid.UUID,
    wo_item_id: uuid.UUID,
    payload: WorkOrderItemUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Edit a logged material's quantity (Supervisor+; stock auto-corrects)."""
    try:
        line = wo_service.update_work_order_item(
            db, work_order_id, wo_item_id, user=user, quantity=payload.quantity
        )
        return _line_detail(line, include_price=_can_see_price(user))
    except DomainError as exc:
        raise to_http(exc)


@router.patch(
    "/{work_order_id}/items/{wo_item_id}/billing",
    response_model=WorkOrderItemDetail,
    responses=_forbidden(roles.ROLE_TECHFM_OA),
)
def set_work_order_item_billing(
    work_order_id: uuid.UUID,
    wo_item_id: uuid.UUID,
    payload: WorkOrderItemBilling,
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
):
    """Set or clear a material line's billing override (TechFM OA and above). The line is
    the billing unit for work-order materials, so this charges fewer units than
    were consumed (or none) without touching stock. `null` clears the override;
    `0` records but does not charge; a value up to the line quantity bills a
    partial count. 403 below TechFM OA; 400 if the value exceeds the line quantity.

    The gate is a dependency rather than a `_can_see_price` check in this body:
    `_can_see_price` is the price-*redaction* predicate, and using it to
    authorize conflated two jobs that happen to share a rank. One consequence
    is deliberate and worth knowing -- a dependency resolves before Pydantic
    validates the body, so a request that is both malformed *and* unauthorized
    now answers 403 where it answered 422. The SPA cannot produce that
    combination; pinned by
    `test_billing_gate_answers_before_the_body_is_validated`."""
    try:
        line = wo_service.set_work_order_item_billable(
            db, work_order_id, wo_item_id, user=user, billable_quantity=payload.billable_quantity
        )
        return _line_detail(line, include_price=True)
    except DomainError as exc:
        raise to_http(exc)


@router.delete("/{work_order_id}/items/{wo_item_id}", status_code=204)
def delete_work_order_item(
    work_order_id: uuid.UUID,
    wo_item_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove a logged material (Supervisor+; stock returns and History voids)."""
    try:
        wo_service.delete_work_order_item(db, work_order_id, wo_item_id, user=user)
    except DomainError as exc:
        raise to_http(exc)


@router.post(
    "/{work_order_id}/labor",
    response_model=WorkOrderLaborDetail,
    status_code=201,
)
def add_work_order_labor(
    work_order_id: uuid.UUID,
    payload: WorkOrderLaborCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Record actual labor for an assigned technician.

    Supervisor+ may record any assigned technician. The first entry starts
    pre-work, and billing rounds the combined work-order duration upward to the
    next 30 minutes.
    """
    try:
        return _labor_detail(
            wo_service.add_work_order_labor(
                db,
                work_order_id,
                user=user,
                technician_id=payload.technician_id,
                minutes=payload.minutes,
            )
        )
    except DomainError as exc:
        raise to_http(exc)


@router.patch(
    "/{work_order_id}/labor/{labor_id}",
    response_model=WorkOrderLaborDetail,
)
def update_work_order_labor(
    work_order_id: uuid.UUID,
    labor_id: uuid.UUID,
    payload: WorkOrderLaborUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Replace a labor entry's actual duration (Supervisor+; server-scoped)."""
    try:
        return _labor_detail(
            wo_service.update_work_order_labor(
                db,
                work_order_id,
                labor_id,
                user=user,
                minutes=payload.minutes,
            )
        )
    except DomainError as exc:
        raise to_http(exc)


@router.delete("/{work_order_id}/labor/{labor_id}", status_code=204)
def delete_work_order_labor(
    work_order_id: uuid.UUID,
    labor_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove labor (Supervisor+) without rolling lifecycle status back."""
    try:
        wo_service.delete_work_order_labor(
            db, work_order_id, labor_id, user=user
        )
    except DomainError as exc:
        raise to_http(exc)
