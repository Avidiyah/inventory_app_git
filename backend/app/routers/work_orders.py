"""HTTP routes for the `/work-orders` resource (the work order entity).

Layer: routers (FastAPI). Thin handlers: parse via a Pydantic schema, delegate
to `app.services.work_orders`, translate `DomainError` via `to_http`.

Most routes are open to any authenticated user but **server-scoped** (technician
-> assigned, supervisor -> created/routed, admin/owner -> all). Technicians may
save notes, add materials, track their time, and use the narrow assigned-worker
start/complete/hold/resume walkthrough. Supervisor+ owns operational routing,
general status, entry mode, hand-entered labor, and material corrections, and
may track time on any work order they can see without being assigned to it. Sending Completed work to Review requires a
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

import logging
import re
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, UploadFile
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
    WorkOrderLaborSessionDetail,
    WorkOrderLaborUpdate,
    WorkOrderLookup,
    WorkOrderUpdate,
)
from app.services import notifications as notifications_service
from app.services import realtime as realtime_service
from app.services import work_orders as wo_service

logger = logging.getLogger(__name__)

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


def _notify(call, *args, **kwargs) -> None:
    """Run one notification rule without letting it fail the request.

    The durable write has already committed by the time any of these run.
    A bug in recipient resolution must therefore surface as a log line and
    a missing notification, never as a 500 for a save that succeeded --
    the same contract the realtime emitters above follow, and the reason
    ``emit``'s boolean result is ignored there.
    """
    try:
        call(*args, **kwargs)
    except Exception:  # noqa: BLE001 - best-effort by contract
        logger.exception("work-order notification rule failed")


def _notify_work_order_patch(
    db: Session,
    background: BackgroundTasks,
    work_order: WorkOrder,
    *,
    actor_id: uuid.UUID,
) -> None:
    """Fire whichever notification rules a single PATCH satisfied.

    One write can be several events -- a PATCH may add assignees, route a
    supervisor, *and* move the status -- so both assignment rules are
    evaluated independently of the transition rather than as arms of the
    chain. A person who is routed as supervisor and added as a technician
    in the same write receives two notifications: both are true, they say
    different things, and suppression is deliberately per-rule.

    Both facts are read off the row the service returned. When there is no
    prior status the row did not come from a write that records one, and
    inferring an event from the post-write status alone is exactly how an
    idempotent repeat sends a second notification for one event.

    This is also the only route out of Completed: the narrow start / hold
    / resume endpoints each reject a Completed row, so the reopen rule has
    no other trigger site.

    **The On-Hold arm goes first, and that ordering is a decision.**
    ``completed -> on_hold`` is both "leaves Completed" and "entered
    On-Hold", and the reopen audience already contains the routed
    supervisor -- evaluating both would buzz them twice for one edit. It
    resolves as a hold: the row is paused, not handed back to the crew, and
    telling the assignees their finished job is "no longer Completed"
    invites work that is not yet available to them. Pinned by
    ``test_completed_to_on_hold_is_a_hold_not_a_reopen``.

    **Review is excluded from the reopen rule.** It is technically a move
    out of Completed, but it is the forward handoff rather than work
    coming back -- the assignees have nothing to do about it, and telling
    them their finished job is "no longer Completed" reads as a setback.
    Everything else that leaves Completed does mean the work is live
    again.

    **Coming back *out* of Review is its own event.** The Admin Review
    page's return button is the only way it happens -- it sends exactly
    ``{"status": "in_progress"}`` (``adminReview.js``), and the card
    editor disables the status field outright for a Review row -- so this
    branch is narrow on purpose rather than by omission.

    **So is Send Back, and it is a third rule with the same audience.**
    ``ready_to_complete -> in_progress`` is the supervisor rejecting the
    crew's handoff (``workOrders.js``'s Send Back button, which sends the
    same ``{"status": "in_progress"}``). Its pair matches no arm above it,
    so its position in the chain is free rather than load-bearing -- but
    ``test_send_back_is_its_own_event_not_a_return_from_review`` pins that,
    because the two arms differ only in their ``previous`` and a future
    edit could make them overlap without anyone noticing.
    """
    if wo_service.newly_assigned_ids(work_order):
        _notify(
            notifications_service.notify_work_order_assigned,
            db,
            background,
            work_order=work_order,
            actor_id=actor_id,
        )

    if wo_service.newly_routed_supervisor_id(work_order):
        _notify(
            notifications_service.notify_supervisor_assigned,
            db,
            background,
            work_order=work_order,
            actor_id=actor_id,
        )

    previous = wo_service.previous_status(work_order)
    if previous is None or previous == work_order.status:
        return

    if work_order.status == wo.STATUS_ON_HOLD:
        _notify(
            notifications_service.notify_work_order_held,
            db,
            background,
            work_order=work_order,
            actor_id=actor_id,
        )
    elif work_order.status == wo.STATUS_COMPLETED:
        _notify(
            notifications_service.notify_work_order_completed,
            db,
            background,
            work_order=work_order,
            actor_id=actor_id,
        )
    elif previous == wo.STATUS_COMPLETED and work_order.status != wo.STATUS_REVIEW:
        _notify(
            notifications_service.notify_work_order_reopened,
            db,
            background,
            work_order=work_order,
            actor_id=actor_id,
        )
    elif (
        previous == wo.STATUS_REVIEW
        and work_order.status == wo.STATUS_IN_PROGRESS
    ):
        _notify(
            notifications_service.notify_work_order_returned_from_review,
            db,
            background,
            work_order=work_order,
            actor_id=actor_id,
        )
    elif (
        previous == wo.STATUS_READY_TO_COMPLETE
        and work_order.status == wo.STATUS_IN_PROGRESS
    ):
        _notify(
            notifications_service.notify_work_order_sent_back,
            db,
            background,
            work_order=work_order,
            actor_id=actor_id,
        )


def _emit_status_changed(entity_id: Optional[uuid.UUID]) -> None:
    """Invalidate the Work Orders card list after a status change.

    ``None`` identifies a membership command (restore), where a recipient's
    list may have gained a row that no on-screen card can represent, so the
    client refetches the list instead of one card.

    Emitted *after* ``_emit_review_queue_changed`` on every route that sends
    both. Order is pinned rather than incidental: restore's status envelope
    carries ``id: None``, so a caller inspecting ``envelopes[0]`` must still
    find the review-queue entity invalidation.

    Delivery is best-effort for the same reason as the review-queue emitter:
    a full handoff must never fail a durable write.
    """
    realtime_service.emit(
        realtime_policy.build_envelope(
            event_type=realtime_policy.EVENT_WORK_ORDER_STATUS_CHANGED,
            entity_id=entity_id,
            request_id=current_request_id(),
        )
    )


def _emit_labor_session_changed() -> None:
    """Invalidate the Supervisor hub's crew board after a clock starts or
    stops.

    Always ``entity_id=None``: this is a membership change to *someone's*
    running-session state, not one card's field, so the recipient refetches
    the whole board rather than targeting a row -- the same reasoning
    ``restore``'s ``None`` already uses for
    ``EVENT_WORK_ORDER_STATUS_CHANGED``.

    One emit is enough on the start path even though two sessions can change
    (the new one opens, another may close via ``side_transitions``), because
    ``id: None`` already means "refetch everything." Best-effort, like every
    other emission here -- a dropped envelope never affects the durable
    write.
    """
    realtime_service.emit(
        realtime_policy.build_envelope(
            event_type=realtime_policy.EVENT_LABOR_SESSION_CHANGED,
            entity_id=None,
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
    priority: Optional[str],
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
        if priority and priority.strip():
            parts.extend(("priority", priority))
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


def _session_window(session) -> Optional[str]:
    """`2:10-3:25 PM` for a closed session, rendered in the note log's zone.

    Formatted here rather than in the browser so the window and the log line
    that records the same stop cannot disagree -- `format.js` has no timezone
    helper, and every other JS timestamp in the app renders browser-local.
    The date is omitted: the entry sits on one work order's labor card, where
    the time of day is the useful part and `MM/DD/YY` on every row is noise.
    """
    if session is None or session.started_at is None or session.ended_at is None:
        return None
    start = wo.format_note_timestamp(session.started_at)[9:]
    end = wo.format_note_timestamp(session.ended_at)[9:]
    # "02:10 PM" -> "2:10 PM"; the log pads the hour, a duration window need not.
    start, end = start.lstrip("0"), end.lstrip("0")
    start_time, start_meridiem = start.rsplit(" ", 1)
    end_time, end_meridiem = end.rsplit(" ", 1)
    if start_meridiem == end_meridiem:
        return f"{start_time}–{end_time} {end_meridiem}"
    return f"{start}–{end}"


def _labor_detail(entry: WorkOrderLabor) -> WorkOrderLaborDetail:
    session = getattr(entry, "session", None)
    return WorkOrderLaborDetail(
        id=entry.id,
        technician_id=entry.technician_id,
        technician_name=entry.technician.full_name,
        minutes=entry.minutes,
        session_window=_session_window(session),
        auto_closed=session is not None and session.auto_closed_at is not None,
    )


def _detail(
    work_order: WorkOrder,
    *,
    include_price: bool,
    viewer_id: Optional[uuid.UUID] = None,
) -> WorkOrderDetail:
    """The full card for one caller.

    Two things vary by *who is asking* rather than by the row: price redaction
    (`include_price`) and, now, which running clock is theirs. `viewer_id`
    defaults to `None` so an internal builder that has no caller simply gets no
    `active_labor_session`, which is the honest answer for it.
    """
    labor_entries = list(getattr(work_order, "labor_entries", None) or ())
    labor_minutes = sum(entry.minutes for entry in labor_entries)
    # An open session has produced no labor row, so it is absent from the sums
    # above by construction -- the property that keeps every billing read path
    # as correct for a job in progress as it was before tracking existed.
    running = [
        session
        for session in (getattr(work_order, "labor_sessions", None) or ())
        if session.ended_at is None
    ]
    mine = next(
        (s for s in running if viewer_id is not None and s.technician_id == viewer_id),
        None,
    )
    return WorkOrderDetail(
        **_card(work_order).model_dump(),
        notes=work_order.notes,
        items=[_line_detail(line, include_price=include_price) for line in work_order.items],
        labor=[_labor_detail(entry) for entry in labor_entries],
        active_labor_session=(
            WorkOrderLaborSessionDetail(
                id=mine.id,
                technician_id=mine.technician_id,
                started_at=mine.started_at,
            )
            if mine is not None
            else None
        ),
        tracking_technician_ids=[session.technician_id for session in running],
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
    assigned_to_id: Optional[uuid.UUID] = Query(None),
    community: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    scheduled_date: Optional[date] = Query(None),
    q: Optional[str] = Query(None),
    limit: Optional[int] = Query(None, ge=1, le=MAX_LIST_ROWS),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List the caller's work orders, newest scheduled date first. Optional `status`, exact
    `service_type`, routed `supervisor_id`, explicitly-assigned `assigned_to_id`,
    derived `community`, exact `priority`, exact `scheduled_date`, and number
    `q` filters combine with AND. Community is
    membership-based over structured community plus raw CSV location; Academics
    is the no-known-term fallback. Priority is an exact vendor value, or
    `__none__` for work orders NetFacilities enrichment never reached.
    `limit` caps that scheduled-date ordering (the
    page browses the first 10 by default and omits `limit` for Show all / search).
    Blank or malformed schedule values sort last. Any authenticated user;
    server-scoped -- `assigned_to_id` only narrows within that scope, it
    never widens it (e.g. a Technician cannot pass someone else's id to see
    their work orders; the caller's own `_scoped_to_user` filter still
    applies on top of it)."""
    try:
        return [
            _card(w)
            for w in wo_service.list_work_orders(
                db,
                user=user,
                status=status,
                service_type=service_type,
                supervisor_id=supervisor_id,
                assigned_to_id=assigned_to_id,
                community=community,
                priority=priority,
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
    background: BackgroundTasks,
    file: UploadFile = File(...),
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
):
    """Bulk-import work orders from the mass CSV export (TechFM OA+). Each row
    find-or-creates by number (idempotent re-upload), stores the new-schema
    columns, and matches the vendor `ASSIGNED TO` name to a supervisor to route
    visibility. Archived matches are counted as closed and left untouched.
    Returns a summary of created/opened/closed/matched/skipped counts.

    Each matched supervisor is notified once for the whole import rather
    than once per work order -- the system's only batched notification, and
    the argument for it is in
    `services/notifications.notify_supervisors_assigned_bulk`. Only newly
    *created* rows count, which is exactly what `supervisors_matched`
    reports, so the push and this response can never disagree about how
    many work orders somebody just received.

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
    # Popped rather than passed through: the routing map exists to address a
    # notification and is not part of the API contract, and
    # `WorkOrderImportResult` would have to grow a field to carry it.
    routing = summary.pop("supervisor_routing", {})
    if routing:
        _notify(
            notifications_service.notify_supervisors_assigned_bulk,
            db,
            background,
            routing=routing,
            actor_id=user.id,
        )
    return WorkOrderImportResult(**summary)


@router.get("/export", responses=_forbidden(roles.ROLE_TECHFM_OA))
def export_work_orders(
    scope: str = Query(wo.EXPORT_SCOPE_ALL),
    variant: str = Query(wo.EXPORT_VARIANT_FULL),
    service_type: Optional[str] = None,
    supervisor_id: Optional[uuid.UUID] = None,
    community: Optional[str] = None,
    priority: Optional[str] = None,
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
    `community`, exact `priority`, exact `scheduled_date`, and number `q`
    filters. They combine
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
            priority=priority,
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
        priority=priority,
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
            viewer_id=user.id,
        )
    except DomainError as exc:
        raise to_http(exc)


@router.patch("/{work_order_id}", response_model=WorkOrderDetail)
def update_work_order(
    work_order_id: uuid.UUID,
    payload: WorkOrderUpdate,
    background: BackgroundTasks,
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
        _emit_status_changed(work_order.id)
        _notify_work_order_patch(db, background, work_order, actor_id=user.id)
        return _detail(
            # The caller may just have routed the row to somebody else. The
            # write was already authorized above, so build its response through
            # the internal scope instead of turning a successful transfer into
            # a false 404.
            wo_service.get_work_order(db, work_order.id, user=None),
            include_price=_can_see_price(user),
            viewer_id=user.id,
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
        _emit_status_changed(work_order.id)
        return _detail(
            wo_service.get_work_order(db, work_order.id, user=user),
            include_price=_can_see_price(user),
            viewer_id=user.id,
        )
    except DomainError as exc:
        raise to_http(exc)


@router.post("/{work_order_id}/complete", response_model=WorkOrderDetail)
def complete_work_order(
    work_order_id: uuid.UUID,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Finish an In-Progress work order as one of its assigned workers.

    This is the final assigned-worker walkthrough step. It grants no general
    status editing and cannot send the work order to Review.

    Where it lands depends on the caller's role
    (`domain.work_orders.completion_target_status`): Supervisor+ reaches
    Completed, a Technician moves the row to Ready to Complete for review.
    Either way every clock on the work order stops.

    Deliberately keeps its path and shape rather than gaining a sibling route.
    A technician running a stale cached SPA calls this and gets the new
    behaviour instead of a 403 -- which matters more now that the button's
    label changed too.
    """
    try:
        work_order = wo_service.complete_work_order(
            db, work_order_id, user=user
        )
        _emit_status_changed(work_order.id)
        # Guarded on a real transition: this endpoint is idempotent, so a
        # slow double tap returns the same row twice and would otherwise
        # fire a second time for one event. No recorded prior status means
        # the row did not come from a write that tracks one, which is not
        # evidence that anything moved.
        previous = wo_service.previous_status(work_order)
        if previous is not None and previous != work_order.status:
            # Chosen from the row rather than from the role, so the
            # notification can never disagree with what was written.
            _notify(
                notifications_service.notify_work_order_held_for_review
                if work_order.status == wo.STATUS_READY_TO_COMPLETE
                else notifications_service.notify_work_order_completed,
                db,
                background,
                work_order=work_order,
                actor_id=user.id,
            )
        return _detail(
            wo_service.get_work_order(db, work_order.id, user=user),
            include_price=_can_see_price(user),
            viewer_id=user.id,
        )
    except DomainError as exc:
        raise to_http(exc)


@router.post("/{work_order_id}/hold", response_model=WorkOrderDetail)
def hold_work_order(
    work_order_id: uuid.UUID,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Place In-Progress work On-Hold as one of its assigned workers.

    Alerts the routed supervisor -- a paused job is otherwise invisible
    until someone opens the card.
    """
    try:
        work_order = wo_service.hold_work_order(db, work_order_id, user=user)
        _emit_status_changed(work_order.id)
        previous = wo_service.previous_status(work_order)
        if previous is not None and previous != work_order.status:
            _notify(
                notifications_service.notify_work_order_held,
                db,
                background,
                work_order=work_order,
                actor_id=user.id,
            )
        return _detail(
            wo_service.get_work_order(db, work_order.id, user=user),
            include_price=_can_see_price(user),
            viewer_id=user.id,
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
        _emit_status_changed(work_order.id)
        return _detail(
            wo_service.get_work_order(db, work_order.id, user=user),
            include_price=_can_see_price(user),
            viewer_id=user.id,
        )
    except DomainError as exc:
        raise to_http(exc)


def _notify_auto_hold(
    db: Session,
    background: BackgroundTasks,
    work_order: WorkOrder,
    *,
    actor_id: uuid.UUID,
) -> None:
    """Fire `work_order.held` when a tracking write put a row On-Hold.

    The standard `previous is not None and previous != status` guard is what
    makes this correct on the idempotent path: a repeat stop closes no session,
    performs no transition, and therefore sends nothing.

    Reuses `notify_work_order_held` unchanged -- same audience (routed
    supervisor, actor-suppressed, Admin fallback when unrouted), same body.
    This is that rule's fourth trigger site, alongside `/hold`, the PATCH arm,
    and now the stop path.
    """
    previous = wo_service.previous_status(work_order)
    if (
        previous is not None
        and previous != work_order.status
        and work_order.status == wo.STATUS_ON_HOLD
    ):
        _notify(
            notifications_service.notify_work_order_held,
            db,
            background,
            work_order=work_order,
            actor_id=actor_id,
        )


@router.post("/{work_order_id}/tracking/start", response_model=WorkOrderDetail)
def start_work_order_tracking(
    work_order_id: uuid.UUID,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start the clock on a work order -- the field's primary action.

    Assigned Technicians, and Supervisor+ on any work order they can see.
    Advances a pre-work row to In-Progress and resumes an On-Hold one, so the
    technician taps once rather than setting a status and then starting work.
    Rejected on Ready to Complete and Completed. Idempotent.

    Fires **no** notification of its own: starting a timer is not news to a
    supervisor, and the transition it performs matches no arm of any rule. It
    can still emit one `work_order.held` -- if the caller had a clock running
    on a *different* work order, that one is closed here and may auto-hold.
    """
    try:
        work_order = wo_service.start_labor_session(db, work_order_id, user=user)
        _emit_status_changed(work_order.id)
        _emit_labor_session_changed()
        for other in wo_service.side_transitions(work_order):
            _emit_status_changed(other.id)
            _notify_auto_hold(db, background, other, actor_id=user.id)
        return _detail(
            wo_service.get_work_order(db, work_order.id, user=user),
            include_price=_can_see_price(user),
            viewer_id=user.id,
        )
    except DomainError as exc:
        raise to_http(exc)


@router.post("/{work_order_id}/tracking/stop", response_model=WorkOrderDetail)
def stop_work_order_tracking(
    work_order_id: uuid.UUID,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Stop the caller's clock and record the labor it produced.

    When this closes the last running session on an In-Progress row the work
    order puts itself On-Hold and alerts the routed supervisor. A stop that
    leaves a co-worker on the clock changes no status and notifies nobody.
    Idempotent.
    """
    try:
        work_order = wo_service.stop_labor_session(db, work_order_id, user=user)
        _emit_status_changed(work_order.id)
        _emit_labor_session_changed()
        _notify_auto_hold(db, background, work_order, actor_id=user.id)
        return _detail(
            wo_service.get_work_order(db, work_order.id, user=user),
            include_price=_can_see_price(user),
            viewer_id=user.id,
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
        _emit_status_changed(work_order_id)
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
        _emit_status_changed(None)
        return _detail(
            wo_service.get_work_order(db, work_order.id, user=user),
            include_price=_can_see_price(user),
            viewer_id=user.id,
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
    """Record actual labor by hand (Supervisor+).

    The correction route now that tracked sessions are authoritative: a dead
    battery, a forgotten Start Tracking, a paper sheet. The technician credited
    must be assigned to the work order, or be the Supervisor recording
    themselves. The first entry starts pre-work, and billing rounds the
    combined work-order duration upward to the next 30 minutes.
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
