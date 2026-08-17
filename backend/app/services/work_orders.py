"""Work order service -- the standalone first-class entity.

Layer: services. Backs `/work-orders` and is the single home for resolving a
number to the one `work_orders` row, so every surface (scan-and-go, Mass Stage,
the Work Orders page) agrees on what "that work order" means.

**Work orders are import-only.** The CSV import (`import_work_orders` ->
`get_or_create_work_order`) is the sole path that creates a row; every other
surface goes through `resolve_work_order`, which attaches to an already-imported
number and refuses an unknown one. There is no "new work order" form.

Identity is the number, unique case-insensitively + trimmed
(`domain.work_orders.normalize_number`). References fill blank attributes but
never overwrite non-blank ones; explicit edits (`update_work_order`) overwrite.
A work order soft-archives (`archived_at`); an archived number stays reserved --
CSV re-import counts and ignores that row. Only the explicit restore workflow
resurrects it; ordinary references cannot create or restore work orders.

Materials logged against a work order write a `dispense` transaction carrying
`work_order_id` + the number; the work order's `entry_mode` decides
`affects_stock` (dispense moves stock; retroactive is stock-neutral but still
shows in History). Editing a dispense line auto-corrects stock by the delta and
rewrites the linked transaction in place -- the scoped exception to the
append-only ledger.
"""

import csv
import io
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional, Sequence

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.domain import receipt
from app.domain import roles
from app.domain import work_orders as wo
from app.domain.errors import (
    InvalidAssigneeError,
    InvalidSupervisorError,
    ItemNotFoundError,
    RoleManagementError,
    WorkOrderAssignmentConflictError,
    WorkOrderNotFoundError,
    WorkOrderStateError,
)
from app.domain.billing import validate_billable_value
from app.domain import list_limits
from app.domain.quantity import apply_delta
from app.models import (
    Item,
    Transaction,
    User,
    WorkOrder,
    WorkOrderItem,
    WorkOrderLabor,
    WorkOrderTechnician,
)
from app.services import _list_cap
from app.services import user_requests as request_service


# Backslash is the LIKE escape char (mirrors services.history).
_LIKE_ESCAPE = "\\"
_UNSET = object()

# Editable attribute fields (used by fill-blanks references + explicit edits).
# The CSV-import columns join the original location/description set; every one is
# fill-blank on a reference so scan-and-go / Mass Stage never clobber import data
# (they simply pass None for the new fields, and fill_blank(current, None) keeps
# current).
_ATTR_FIELDS = (
    "community",
    "building_number",
    "unit_number",
    "description",
    "location",
    "output_to",
    "vendor_assignee",
    "service_type",
    "schedule_date",
)

# PATCH permission groups. Notes are the technician-level edit. Supervisor+
# owns operational routing/status/mode, while imported and legacy metadata is
# TechFM OA+ so a supervisor's editor stays focused on daily execution.
_ADMIN_UPDATE_FIELDS = frozenset(("number", *_ATTR_FIELDS))
_SUPERVISOR_UPDATE_FIELDS = frozenset(
    ("status", "entry_mode", "assigned_to_id", "assigned_to_ids", "supervisor_id")
)


def _require_role(
    user: Optional[User], minimum: str, message: str
) -> None:
    """Allow internal callers, otherwise require the stated role floor."""
    if user is not None and not roles.role_at_least(user.role, minimum):
        raise RoleManagementError(message)


def _require_update_permissions(user: Optional[User], fields: dict) -> None:
    keys = set(fields)
    if keys & _ADMIN_UPDATE_FIELDS:
        _require_role(
            user,
            roles.ROLE_TECHFM_OA,
            "Only a TechFM OA, Admin, or Owner can edit imported work order "
            "details.",
        )
    if keys & _SUPERVISOR_UPDATE_FIELDS:
        _require_role(
            user,
            roles.ROLE_SUPERVISOR,
            "Only a Supervisor, Admin, or Owner can edit work order operations.",
        )


# --- helpers -------------------------------------------------------------

def _search_pattern(value: Optional[str]):
    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    escaped = (
        trimmed.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
        .replace("%", _LIKE_ESCAPE + "%")
        .replace("_", _LIKE_ESCAPE + "_")
    )
    return f"%{escaped}%", _LIKE_ESCAPE


def _community_match(terms: Sequence[str]):
    """SQL predicate for community membership across structured and raw text."""
    location = func.lower(func.coalesce(WorkOrder.location, ""))
    community = func.lower(func.coalesce(WorkOrder.community, ""))
    return or_(
        *(
            column.like(f"%{term}%")
            for term in terms
            for column in (location, community)
        )
    )


def _apply_community_filter(query, value: Optional[str]):
    """Apply one named community membership filter or the Academics fallback."""
    community = wo.normalize_community_filter(value)
    if community is None:
        return query
    known_match = _community_match(
        tuple(
            term
            for terms in wo.COMMUNITY_SEARCH_TERMS.values()
            for term in terms
        )
    )
    if community == wo.COMMUNITY_ACADEMICS:
        return query.filter(~known_match)
    return query.filter(_community_match(wo.COMMUNITY_SEARCH_TERMS[community]))


def _validate_assignee(db: Session, assigned_to_id: Optional[uuid.UUID]) -> None:
    """A work order may be unassigned, but if assigned the target must exist and
    be an active Technician or Supervisor account."""
    if assigned_to_id is None:
        return
    user = (
        db.query(User.id)
        .filter(
            User.id == assigned_to_id,
            User.role.in_(roles.WORK_ORDER_TECHNICIAN_ROLES),
            User.archived_at.is_(None),
        )
        .first()
    )
    if user is None:
        raise InvalidAssigneeError(
            "Work orders can only be assigned to an active Technician or Supervisor."
        )


def _validate_assignees(
    db: Session, assigned_to_ids: Sequence[uuid.UUID]
) -> list[uuid.UUID]:
    """Validate and de-duplicate a complete worker assignment set."""
    normalized = list(dict.fromkeys(assigned_to_ids))
    if not normalized:
        return []
    valid_ids = {
        row.id
        for row in db.query(User.id)
        .filter(
            User.id.in_(normalized),
            User.role.in_(roles.WORK_ORDER_TECHNICIAN_ROLES),
            User.archived_at.is_(None),
        )
        .all()
    }
    if len(valid_ids) != len(normalized):
        raise InvalidAssigneeError(
            "Work orders can only be assigned to active Technicians or Supervisors."
        )
    return normalized


def _validate_supervisor(
    db: Session, supervisor_id: Optional[uuid.UUID]
) -> None:
    """A routed work order must target an active TechFM OA, Admin, or
    Supervisor account."""
    if supervisor_id is None:
        return
    supervisor = (
        db.query(User.id)
        .filter(
            User.id == supervisor_id,
            User.role.in_(roles.WORK_ORDER_SUPERVISOR_ROLES),
            User.archived_at.is_(None),
        )
        .first()
    )
    if supervisor is None:
        raise InvalidSupervisorError(
            "Work orders can only be routed to an active TechFM OA, Admin, or "
            "Supervisor."
        )


def _assigned_technician_ids(work_order: WorkOrder) -> list[uuid.UUID]:
    """Plural assignment ids with a legacy-column fallback."""
    assigned = [
        row.technician_id
        for row in (getattr(work_order, "technician_assignments", None) or ())
    ]
    legacy_id = getattr(work_order, "assigned_to_id", None)
    if legacy_id is not None and legacy_id not in assigned:
        assigned.insert(0, legacy_id)
    return assigned


def assigned_technicians(work_order: WorkOrder) -> list[User]:
    """Assigned technician users, including a legacy singular fallback."""
    technicians = list(getattr(work_order, "technicians", None) or ())
    assignee = getattr(work_order, "assignee", None)
    if assignee is not None and all(
        technician.id != assignee.id for technician in technicians
    ):
        technicians.insert(0, assignee)
    return technicians


def _require_review_handoff_permission(
    work_order: WorkOrder, user: Optional[User]
) -> None:
    """Require a second person before a Completed work order enters Review.

    Internal callers retain their existing bypass. An authenticated caller may
    not review work they are assigned to perform, even when they are also the
    routed Supervisor. Otherwise Admin+ has global authority and the unassigned
    routed Supervisor owns the operational handoff.

    The `ROLE_ADMIN` floor below is the one place in the application that still
    means Admin rather than TechFM OA, and it is deliberate: the Review handoff
    is the single capability an Admin holds that a TechFM OA does not. A TechFM
    OA may be the routed supervisor on a work order and still cannot complete
    the handoff -- Review is a second-person control, so an Admin, the Owner, or
    another routed Supervisor closes it out.
    """
    if user is None:
        return
    if user.id in _assigned_technician_ids(work_order):
        raise RoleManagementError(
            "An assigned worker cannot send their own work order to Review. "
            "Another routed Supervisor, Admin, or Owner must review it."
        )
    if roles.role_at_least(user.role, roles.ROLE_ADMIN):
        return
    if (
        user.role == roles.ROLE_SUPERVISOR
        and work_order.supervisor_id == user.id
    ):
        return
    raise RoleManagementError(
        "Only the unassigned routed Supervisor, an Admin, or the Owner can "
        "send a work order to Review."
    )


def _sync_technician_assignments(
    db: Session,
    work_order: WorkOrder,
    technician_ids: Sequence[uuid.UUID],
    *,
    assigned_by_id: Optional[uuid.UUID],
) -> None:
    """Replace a work order's normalized assignment set and legacy mirror."""
    desired = list(dict.fromkeys(technician_ids))
    existing = {
        assignment.technician_id: assignment
        for assignment in work_order.technician_assignments
    }
    for technician_id, assignment in existing.items():
        if technician_id not in desired:
            db.delete(assignment)
    for technician_id in desired:
        if technician_id not in existing:
            db.add(
                WorkOrderTechnician(
                    work_order_id=work_order.id,
                    technician_id=technician_id,
                    assigned_by_id=assigned_by_id,
                )
            )
    # Compatibility for Mass Stage and old response consumers.
    work_order.assigned_to_id = desired[0] if desired else None


def _visible(work_order: WorkOrder, user: Optional[User]) -> bool:
    return wo.can_view_work_order(
        user.role if user else None,
        created_by_id=work_order.created_by_id,
        assigned_to_id=work_order.assigned_to_id,
        user_id=user.id if user else None,
        supervisor_id=work_order.supervisor_id,
        assigned_to_ids=_assigned_technician_ids(work_order),
    )


def _find_by_number(
    db: Session, number: str, *, for_update: bool = False
) -> Optional[WorkOrder]:
    """Internal number lookup, optionally locking and refreshing the row."""
    norm = wo.normalize_number(number)
    query = db.query(WorkOrder).filter(
        func.lower(func.btrim(WorkOrder.number)) == norm
    )
    if for_update:
        query = query.populate_existing().with_for_update()
    return query.first()


def find_by_number(db: Session, number: str) -> Optional[WorkOrder]:
    """The work order whose number matches `number` case-insensitively +
    trimmed, including an archived one (numbers stay reserved). `None` if
    unknown."""
    return _find_by_number(db, number)


def _get_locked(db: Session, work_order_id: uuid.UUID) -> Optional[WorkOrder]:
    """Lock and refresh a work-order row without applying caller visibility."""
    return (
        db.query(WorkOrder)
        .populate_existing()
        .filter(WorkOrder.id == work_order_id)
        .with_for_update()
        .first()
    )


def _get_visible(
    db: Session, work_order_id: uuid.UUID, user: Optional[User]
) -> WorkOrder:
    """Load a live (non-archived) work order for the Work Orders page. Raises
    `WorkOrderNotFoundError` if unknown, archived, or not visible to `user` --
    visibility failures surface as not-found so existence is not leaked."""
    work_order = (
        db.query(WorkOrder)
        .options(
            joinedload(WorkOrder.assignee),
            joinedload(WorkOrder.supervisor),
            selectinload(WorkOrder.technician_assignments),
            selectinload(WorkOrder.technicians),
            selectinload(WorkOrder.labor_entries).joinedload(WorkOrderLabor.technician),
            selectinload(WorkOrder.items).joinedload(WorkOrderItem.item),
        )
        .filter(WorkOrder.id == work_order_id)
        .first()
    )
    if (
        work_order is None
        or work_order.archived_at is not None
        or not _visible(work_order, user)
    ):
        raise WorkOrderNotFoundError("Work order not found.")
    return work_order


# --- resolve / import-create ---------------------------------------------

def _merge_reference(
    db: Session,
    existing: WorkOrder,
    *,
    incoming: dict,
    assigned_to_id: Optional[uuid.UUID],
    supervisor_id: Optional[uuid.UUID],
    replace_generated_description: bool = False,
) -> WorkOrder:
    """Merge into an existing row already locked by the caller.

    A blank column takes the incoming value and a non-blank one is left alone.
    The import-only exception is a canonical generated task URL: when the CSV
    supplies a real task, ``replace_generated_description`` lets that task replace
    the synthetic value. An assignee applies only if currently unassigned, and
    supervisor routing applies only if the freshly locked row is still unrouted.
    Commits and returns the refreshed row."""
    for field in _ATTR_FIELDS:
        current = getattr(existing, field)
        if (
            field == "description"
            and replace_generated_description
            and wo.is_work_order_task_fallback(current, existing.number)
        ):
            # The URL is synthetic fallback data, not an operator/vendor task.
            # A later real CSV task may replace it; every other nonblank field
            # keeps the normal fill-blanks contract.
            value = incoming[field]
        else:
            value = wo.fill_blank(current, incoming[field])
        setattr(existing, field, value)
    if assigned_to_id is not None and not _assigned_technician_ids(existing):
        _sync_technician_assignments(
            db,
            existing,
            [assigned_to_id],
            assigned_by_id=None,
        )
    if supervisor_id is not None and existing.supervisor_id is None:
        _validate_supervisor(db, supervisor_id)
        existing.supervisor_id = supervisor_id
    existing.status = wo.reconcile_assignment_status(
        existing.status, _assigned_technician_ids(existing)
    )
    db.commit()
    db.refresh(existing)
    return existing


def _incoming_attrs(**kwargs) -> dict:
    """The `_ATTR_FIELDS` subset of a reference's kwargs, defaulting to None."""
    return {field: kwargs.get(field) for field in _ATTR_FIELDS}


def resolve_work_order(
    db: Session,
    *,
    number: str,
    community: Optional[str] = None,
    building_number: Optional[str] = None,
    unit_number: Optional[str] = None,
    description: Optional[str] = None,
    location: Optional[str] = None,
    output_to: Optional[str] = None,
    vendor_assignee: Optional[str] = None,
    service_type: Optional[str] = None,
    schedule_date: Optional[str] = None,
    assigned_to_id: Optional[uuid.UUID] = None,
    supervisor_id: Optional[uuid.UUID] = None,
) -> WorkOrder:
    """Attach to the work order `number` already names -- never create one.

    This is how every non-import surface (scan-and-go, Mass Stage) reaches a work
    order: work orders enter the system through the CSV import, so a number that
    is unknown -- or held only by an *archived* work order -- raises
    `WorkOrderNotFoundError` instead of quietly bringing a row into existence.
    (CSV import also ignores archived matches rather than restoring them.)

    A resolved work order takes the same fill-blanks merge a reference has always
    applied, so a stage still fills in blank location/assignee data without
    clobbering imported values. Raises `InvalidAssigneeError` if an assignee is
    not an active Technician or Supervisor."""
    _validate_assignee(db, assigned_to_id)
    existing = _find_by_number(db, number, for_update=True)
    if existing is not None and existing.archived_at is not None:
        # Distinguish the two dead ends: an archived number is recoverable
        # (restore it from the Work Orders page or History), an unknown one needs
        # an import.
        raise WorkOrderNotFoundError(
            f"Work order {number.strip()} is archived. Restore it before "
            f"logging against it."
        )
    if existing is None:
        raise WorkOrderNotFoundError(
            f"Work order {number.strip()} was not found. Work orders are added by "
            f"importing the work-order CSV."
        )
    return _merge_reference(
        db,
        existing,
        incoming=_incoming_attrs(
            community=community,
            building_number=building_number,
            unit_number=unit_number,
            description=description,
            location=location,
            output_to=output_to,
            vendor_assignee=vendor_assignee,
            service_type=service_type,
            schedule_date=schedule_date,
        ),
        assigned_to_id=assigned_to_id,
        supervisor_id=supervisor_id,
    )


def get_or_create_work_order(
    db: Session,
    *,
    number: str,
    community: Optional[str] = None,
    building_number: Optional[str] = None,
    unit_number: Optional[str] = None,
    description: Optional[str] = None,
    location: Optional[str] = None,
    output_to: Optional[str] = None,
    vendor_assignee: Optional[str] = None,
    service_type: Optional[str] = None,
    schedule_date: Optional[str] = None,
    assigned_to_id: Optional[uuid.UUID] = None,
    supervisor_id: Optional[uuid.UUID] = None,
    created_by_id: Optional[uuid.UUID] = None,
    replace_generated_description: bool = False,
) -> WorkOrder:
    """Resolve `number` to the one work order, creating it if new.

    **Import path only** -- `import_work_orders` is the sole caller, because the
    CSV is the only thing allowed to bring a work order into existence. Every
    other surface uses `resolve_work_order`.

    Existing live row: fill-blanks merge of only the supplied attributes; a
    non-blank assignee is validated + applied only if currently unassigned, and
    a `supervisor_id` is applied only if currently unrouted. An archived match is
    returned untouched so CSV import can count and ignore it. New: starts
    `assigned` only when a Technician/Supervisor worker is supplied, otherwise `created`;
    supervisor routing does not change lifecycle status. Raises
    `replace_generated_description` is import provenance carried through both the
    ordinary locked merge and insert-race recovery. Raises `InvalidAssigneeError`
    if an assignee is not an active Technician or Supervisor."""
    existing = _find_by_number(db, number, for_update=True)
    if existing is not None and existing.archived_at is not None:
        return existing

    _validate_assignee(db, assigned_to_id)
    incoming = _incoming_attrs(
        community=community,
        building_number=building_number,
        unit_number=unit_number,
        description=description,
        location=location,
        output_to=output_to,
        vendor_assignee=vendor_assignee,
        service_type=service_type,
        schedule_date=schedule_date,
    )

    if existing is not None:
        return _merge_reference(
            db,
            existing,
            incoming=incoming,
            assigned_to_id=assigned_to_id,
            supervisor_id=supervisor_id,
            replace_generated_description=replace_generated_description,
        )

    _validate_supervisor(db, supervisor_id)
    work_order = WorkOrder(
        id=uuid.uuid4(),
        number=number.strip(),
        status=wo.initial_status(assigned_to_id),
        assigned_to_id=assigned_to_id,
        supervisor_id=supervisor_id,
        created_by_id=created_by_id,
        **{field: wo.fill_blank(None, incoming[field]) for field in _ATTR_FIELDS},
    )
    db.add(work_order)
    if assigned_to_id is not None:
        _sync_technician_assignments(
            db,
            work_order,
            [assigned_to_id],
            assigned_by_id=created_by_id,
        )
    try:
        db.commit()
    except IntegrityError as exc:
        # Raced another insert of the same normalized number. Lock the winner
        # and apply this row's fill-blank merge instead of dropping its data.
        db.rollback()
        existing = _find_by_number(db, number, for_update=True)
        if existing is None:
            raise WorkOrderStateError("Could not create the work order.") from exc
        if existing.archived_at is not None:
            return existing
        return _merge_reference(
            db,
            existing,
            incoming=incoming,
            assigned_to_id=assigned_to_id,
            supervisor_id=supervisor_id,
            replace_generated_description=replace_generated_description,
        )
    db.refresh(work_order)
    return work_order


# --- CSV import ----------------------------------------------------------

def _supervisor_lookup(db: Session) -> dict[str, Optional[uuid.UUID]]:
    """Map unambiguous active routing-eligible full names to ids for CSV
    routing -- TechFM OA, Admin, or Supervisor.

    Missing names are deliberately unmatchable. Duplicate normalized names are
    stored as ``None`` so import leaves the relationship unassigned instead of
    routing nondeterministically to whichever row the database returned last.
    """
    lookup: dict[str, Optional[uuid.UUID]] = {}
    supervisors = (
        db.query(User)
        .filter(
            User.role.in_(roles.WORK_ORDER_SUPERVISOR_ROLES),
            User.archived_at.is_(None),
        )
        .all()
    )
    for supervisor in supervisors:
        if not (supervisor.first_name and supervisor.first_name.strip()):
            continue
        if not (supervisor.last_name and supervisor.last_name.strip()):
            continue
        key = wo.normalize_assignee_name(
            f"{supervisor.first_name} {supervisor.last_name}"
        )
        if key is not None:
            lookup[key] = None if key in lookup else supervisor.id
    return lookup


def import_work_orders(db: Session, *, csv_bytes: bytes, user: User) -> dict:
    """Import the mass work-order CSV export (the new default schema).

    Each live row funnels through `get_or_create_work_order` by number, so a
    re-upload is idempotent (fill-blanks -- only supplied metadata can fill an
    empty field; operational data and manual edits survive). Archived matches are
    counted as closed and ignored without restoring or mutating them. The
    `ASSIGNED TO` vendor name is stored raw AND matched to an active system
    TechFM OA, Admin, or Supervisor (by normalized first + last name) to set
    `supervisor_id`; an unmatched name imports cleanly (admin routes it later).
    A blank/missing task becomes the canonical NetFacilities URL; a later real
    task replaces that generated value without weakening other fill-blank rules.
    Rows with a blank work-order number are skipped. UTF-8 decoding, CSV parsing,
    and the required `WORK ORDER` header are preflighted before row commits.

    Returns a summary dict (`total`, `created`, `opened`, `closed`,
    `supervisors_matched`, `supervisors_unmatched`, `skipped`)."""
    try:
        text = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise WorkOrderStateError("Work-order CSV must be UTF-8 encoded.") from exc
    stream = io.StringIO(text)
    if stream.readline().strip().casefold() != "sep=,":
        stream.seek(0)
    try:
        reader = csv.DictReader(stream)
        headers = reader.fieldnames
        if headers is None or headers.count("WORK ORDER") != 1:
            raise WorkOrderStateError(
                'Work-order CSV must include exactly one "WORK ORDER" column.'
            )
        # Parse every CSV record before any row-level commit. Malformed CSV input
        # therefore fails cleanly instead of leaving a partially parsed import.
        rows = list(reader)
    except csv.Error as exc:
        raise WorkOrderStateError("Work-order CSV could not be parsed.") from exc
    supervisors = _supervisor_lookup(db)

    created = opened = closed = matched = unmatched = skipped = 0
    for row in rows:
        attrs = wo.parse_import_row(row)
        number = attrs.pop("number")
        if number is None:
            skipped += 1
            continue

        existing = find_by_number(db, number)
        if existing is not None and existing.archived_at is not None:
            closed += 1
            continue

        task_was_explicit = attrs.get("description") is not None
        if not task_was_explicit:
            attrs["description"] = wo.work_order_task_fallback(number)

        key = wo.normalize_assignee_name(attrs.get("vendor_assignee"))
        supervisor_id = supervisors.get(key) if key else None
        existed = existing is not None
        work_order = get_or_create_work_order(
            db,
            number=number,
            created_by_id=user.id,
            supervisor_id=supervisor_id,
            replace_generated_description=task_was_explicit,
            **attrs,
        )
        # A concurrent archive after the first lookup still wins: the import-only
        # resolver returns that row untouched, and this row is reported as closed.
        if work_order.archived_at is not None:
            closed += 1
            continue

        if attrs.get("vendor_assignee") is not None:
            if supervisor_id is not None:
                matched += 1
            else:
                unmatched += 1
        if existed:
            opened += 1
        else:
            created += 1

    return {
        "total": created + opened + closed + skipped,
        "created": created,
        "opened": opened,
        "closed": closed,
        "supervisors_matched": matched,
        "supervisors_unmatched": unmatched,
        "skipped": skipped,
    }


# --- list + detail -------------------------------------------------------

def _apply_work_order_filters(
    query,
    *,
    status: Optional[str] = None,
    service_type: Optional[str] = None,
    supervisor_id: Optional[uuid.UUID] = None,
    community: Optional[str] = None,
    search: Optional[str] = None,
):
    """Apply the joinable Work Orders predicates shared by list and export."""
    if status is not None:
        wo.validate_status(status)
        query = query.filter(WorkOrder.status == status)

    if service_type is not None and service_type.strip():
        normalized_service_type = service_type.strip().casefold()
        query = query.filter(
            func.lower(func.btrim(WorkOrder.service_type)) == normalized_service_type
        )

    if supervisor_id is not None:
        query = query.filter(WorkOrder.supervisor_id == supervisor_id)

    query = _apply_community_filter(query, community)

    pattern = _search_pattern(search)
    if pattern is not None:
        like, escape = pattern
        query = query.filter(WorkOrder.number.ilike(like, escape=escape))

    return query


def _filter_and_sort_by_schedule(work_orders, scheduled_date: Optional[date] = None):
    """Apply the exact calendar-date filter and sort newest scheduled first.

    The source field is intentionally raw text, so parsing happens after the SQL
    predicates. Blank or malformed legacy values sort below valid dates; ties
    keep newest-created work orders first.

    Reads only `.schedule_date` and `.created_at`, so it accepts either full
    `WorkOrder` entities or the lightweight `(id, schedule_date, created_at)`
    rows `list_work_orders` ranks with. Returns the same objects it was given,
    in order.
    """
    if scheduled_date is not None:
        work_orders = [
            work_order
            for work_order in work_orders
            if wo.parse_schedule_date(work_order.schedule_date) == scheduled_date
        ]

    def sort_key(work_order: WorkOrder):
        parsed = wo.parse_schedule_date(work_order.schedule_date)
        created_timestamp = (
            work_order.created_at.timestamp() if work_order.created_at else 0
        )
        return (parsed is not None, parsed or date.min, created_timestamp)

    return sorted(work_orders, key=sort_key, reverse=True)


# Relationship loads the Work Orders card list needs. Named once so the
# capped and uncapped paths in `list_work_orders` cannot drift apart.
_LIST_EAGER_LOADS = (
    joinedload(WorkOrder.assignee),
    joinedload(WorkOrder.supervisor),
    selectinload(WorkOrder.technician_assignments),
    selectinload(WorkOrder.technicians),
    selectinload(WorkOrder.items),
)


def list_work_orders(
    db: Session,
    *,
    user: Optional[User],
    status: Optional[str] = None,
    service_type: Optional[str] = None,
    supervisor_id: Optional[uuid.UUID] = None,
    community: Optional[str] = None,
    scheduled_date: Optional[date] = None,
    search: Optional[str] = None,
    limit: Optional[int] = None,
) -> Sequence[WorkOrder]:
    """Live work orders by scheduled date descending, scoped to `user`
    (technician -> assigned, supervisor -> created/routed, admin/owner -> all).
    Optional status, service type, routed supervisor, derived community, exact
    scheduled date, and number-substring filters combine with AND. Community
    membership searches both structured `community` and raw CSV `location`;
    Academics means no known term appears in either. Blank or malformed schedule
    values sort last, with creation time breaking ties. `limit`, when set, caps
    this ordering; filters and Show all omit it to reach the full matching set.

    **X3's ceiling applies here differently from every other capped list, and
    the difference is worth understanding before changing it.** `schedule_date`
    is raw text, so the ordering can only be decided in Python (X2 ruled out
    doing it in SQL) and there is no `LIMIT` that would preserve it. So the
    ceiling bounds the **response**, not the query: the lightweight ranking
    projection below still spans the whole matching set. Making it bound the
    query too means reopening X2.

    Consequence worth stating plainly: an omitted `limit` no longer takes a
    separate uncapped branch. It now runs the same rank-then-hydrate path a set
    `limit` takes, with `MAX_LIST_ROWS` as the effective cap. Same rows, same
    order, strictly less loading -- that path is A6's optimization, now applied
    universally instead of only when the caller asked for a subset.
    """
    def scoped(*entities):
        """Live work orders matching every filter, projected to `entities`."""
        query = db.query(*entities).filter(WorkOrder.archived_at.is_(None))
        query = _apply_work_order_filters(
            query,
            status=status,
            service_type=service_type,
            supervisor_id=supervisor_id,
            community=community,
            search=search,
        )
        return _scoped_to_user(query, user)

    ceiling = list_limits.MAX_LIST_ROWS
    effective_limit = ceiling if limit is None else min(limit, ceiling)

    # `schedule_date` is raw text, so the ordering can only be
    # decided in Python (see `_filter_and_sort_by_schedule`) and SQL cannot
    # do the LIMIT for us. Rank a lightweight projection first, then hydrate
    # only the rows that survive the cap -- otherwise the eager loads below
    # fan out across the entire matching set to return `limit` cards. Same
    # predicates, same comparison keys, same order; strictly less loaded.
    all_ranked = _filter_and_sort_by_schedule(
        scoped(WorkOrder.id, WorkOrder.schedule_date, WorkOrder.created_at).all(),
        scheduled_date,
    )
    ranked = all_ranked[:effective_limit]

    # Only report truncation when the *ceiling* bit, not when a caller's own
    # smaller `limit` did its job -- a page asking for 10 cards and getting 10
    # is not a truncated list.
    if limit is None or limit >= ceiling:
        _list_cap.report_if_truncated(len(all_ranked), what="work_orders")

    ordered_ids = [row.id for row in ranked]
    if not ordered_ids:
        return []

    by_id = {
        entity.id: entity
        for entity in (
            db.query(WorkOrder)
            .options(*_LIST_EAGER_LOADS)
            .filter(WorkOrder.id.in_(ordered_ids))
            .all()
        )
    }
    return [by_id[work_order_id] for work_order_id in ordered_ids]


def _scoped_to_user(query, user: Optional[User]):
    """Narrow a `WorkOrder` query to what `user` may see. TechFM OA and above
    (and a `None` internal caller) see everything, so the query is returned
    unchanged. Mirrors `domain.work_orders.can_view_work_order`; shared by the
    list and the CSV export so neither can drift into showing more than the
    other."""
    if user is None or roles.role_at_least(user.role, roles.ROLE_TECHFM_OA):
        return query
    if user.role == roles.ROLE_SUPERVISOR:
        # Unrouted work orders are the shared pickup queue. A Supervisor also
        # retains worker access when assigned in the technician set, even if a
        # different routing-eligible account owns the routing field.
        return query.filter(
            or_(
                WorkOrder.supervisor_id.is_(None),
                WorkOrder.supervisor_id == user.id,
                WorkOrder.assigned_to_id == user.id,
                WorkOrder.technician_assignments.any(
                    WorkOrderTechnician.technician_id == user.id
                ),
            )
        )
    return query.filter(
        or_(
            WorkOrder.assigned_to_id == user.id,
            WorkOrder.technician_assignments.any(
                WorkOrderTechnician.technician_id == user.id
            ),
        )
    )


def get_work_order_filter_options(
    db: Session, *, user: Optional[User]
) -> dict:
    """Distinct list-filter values from live work orders visible to `user`.

    This keeps technicians from needing access to the full Users endpoint and
    avoids deriving options from the page's intentionally capped card list.
    """
    live = WorkOrder.archived_at.is_(None)
    service_rows = _scoped_to_user(
        db.query(WorkOrder.service_type).filter(live), user
    ).all()
    service_types_by_key: dict[str, str] = {}
    for (raw_value,) in service_rows:
        value = raw_value.strip() if raw_value else ""
        if value:
            service_types_by_key.setdefault(value.casefold(), value)

    supervisor_rows = (
        _scoped_to_user(
            db.query(User)
            .join(WorkOrder, WorkOrder.supervisor_id == User.id)
            .filter(live),
            user,
        )
        .distinct()
        .all()
    )

    return {
        "service_types": sorted(
            service_types_by_key.values(), key=lambda value: value.casefold()
        ),
        "supervisors": sorted(
            (
                {"id": supervisor.id, "name": supervisor.full_name}
                for supervisor in supervisor_rows
            ),
            key=lambda option: (option["name"].casefold(), str(option["id"])),
        ),
        "communities": [
            {"value": value, "label": wo.COMMUNITY_LABELS[value]}
            for value in wo.ALL_COMMUNITY_FILTERS
        ],
    }


# --- CSV export ----------------------------------------------------------

def list_work_orders_for_export(
    db: Session,
    *,
    user: Optional[User],
    scope: str,
    service_type: Optional[str] = None,
    supervisor_id: Optional[uuid.UUID] = None,
    community: Optional[str] = None,
    scheduled_date: Optional[date] = None,
    search: Optional[str] = None,
) -> Sequence[WorkOrder]:
    """Work orders for the CSV export in the page's scheduled-date ordering and
    scoped to `user` exactly as the page list is.

    `scope` is `all` (every live work order), `archived` (the closed ones the
    list hides), or one live status. The remaining predicates mirror the Work
    Orders controls and combine with that scope using AND. Unlike the list there
    is no `limit`: an export is meant to be the whole matching set.

    **Deliberately exempt from X3's `MAX_LIST_ROWS` ceiling -- do not "fix"
    this.** `docs/current-state.md` documents the TechFM OA+ export as the uncapped
    filtered set, and a CSV that silently omits rows while looking complete is a
    billing and record-keeping problem rather than a performance one. Every
    other list in the app is capped; this one is the considered exception."""
    wo.validate_export_scope(scope)
    query = db.query(WorkOrder).options(
        joinedload(WorkOrder.supervisor),
        selectinload(WorkOrder.technicians),
        selectinload(WorkOrder.items).joinedload(WorkOrderItem.item),
        selectinload(WorkOrder.labor_entries),
    )

    if scope == wo.EXPORT_SCOPE_ARCHIVED:
        query = query.filter(WorkOrder.archived_at.is_not(None))
        status = None
    else:
        query = query.filter(WorkOrder.archived_at.is_(None))
        status = None if scope == wo.EXPORT_SCOPE_ALL else scope

    query = _apply_work_order_filters(
        query,
        status=status,
        service_type=service_type,
        supervisor_id=supervisor_id,
        community=community,
        search=search,
    )

    return _filter_and_sort_by_schedule(
        _scoped_to_user(query, user).all(), scheduled_date
    )


def _csv_timestamp(value: Optional[datetime]) -> str:
    """Timestamps as `YYYY-MM-DD HH:MM` UTC -- sortable in a spreadsheet and
    unambiguous, unlike a locale-formatted date."""
    if value is None:
        return ""
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%d %H:%M")


def _export_row(work_order: WorkOrder) -> list:
    """One work order as a row of `domain.work_orders.EXPORT_HEADERS` values."""
    materials_total = Decimal(0)
    for line in work_order.items:
        price = line.item.price or Decimal(0)
        materials_total += price * wo.effective_billable(
            line.quantity, line.billable_quantity
        )
    labor_minutes = sum(entry.minutes for entry in work_order.labor_entries)
    labor_total = wo.labor_charge(labor_minutes)

    return [
        work_order.number,
        work_order.location or "",
        work_order.output_to or "",
        # The raw vendor name, matching what the import reads back.
        work_order.vendor_assignee or "",
        work_order.service_type or "",
        work_order.schedule_date or "",
        work_order.description or "",
        work_order.status,
        # Multi-technician work orders collapse to one semicolon-joined cell;
        # a comma would fight the CSV itself in every spreadsheet.
        "; ".join(technician.full_name for technician in work_order.technicians),
        work_order.supervisor.full_name if work_order.supervisor else "",
        work_order.community or "",
        work_order.building_number or "",
        work_order.unit_number or "",
        work_order.entry_mode,
        len(work_order.items),
        f"{materials_total:.2f}",
        labor_minutes,
        wo.billed_labor_minutes(labor_minutes),
        f"{labor_total:.2f}",
        f"{materials_total + labor_total:.2f}",
        work_order.notes or "",
        _csv_timestamp(work_order.created_at),
        _csv_timestamp(work_order.updated_at),
        _csv_timestamp(work_order.completed_at),
        _csv_timestamp(work_order.archived_at),
    ]


def _receipt_lines(work_order: WorkOrder) -> list[receipt.ReceiptLine]:
    """A work order's materials in the receipt builder's own vocabulary."""
    return [
        receipt.ReceiptLine(
            name=line.item.name,
            quantity=line.quantity,
            billable_quantity=line.billable_quantity,
            unit_price=line.item.price,
        )
        for line in work_order.items
    ]


def _client_export_row(work_order: WorkOrder) -> list:
    """One work order as the client-facing row: number, the two billed totals,
    and the receipt exactly as Admin Review renders it.

    Both totals are what the customer is charged -- materials carry the receipt's
    mark-up, labor is the labor charge -- so the row adds up to the receipt in
    the last cell. An unpriced item contributes nothing to the material total
    and shows as `NO PRICE` in the receipt, which also relabels its Total
    `(incomplete)`; that is deliberately visible rather than silently rounded
    away."""
    lines = _receipt_lines(work_order)
    labor_minutes = sum(entry.minutes for entry in work_order.labor_entries)
    labor_total = wo.labor_charge(labor_minutes)
    document = receipt.build_receipt(
        lines=lines,
        labor_billed_minutes=wo.billed_labor_minutes(labor_minutes),
        labor_total=labor_total,
    )
    material_total = sum(
        (charge for charge in map(receipt.marked_material_charge, lines) if charge is not None),
        Decimal(0),
    )
    return [
        work_order.number,
        receipt.format_money(material_total),
        receipt.format_money(labor_total),
        document.text,
    ]


def export_work_orders_csv(
    db: Session,
    *,
    user: Optional[User],
    scope: str,
    variant: str = wo.EXPORT_VARIANT_FULL,
    service_type: Optional[str] = None,
    supervisor_id: Optional[uuid.UUID] = None,
    community: Optional[str] = None,
    scheduled_date: Optional[date] = None,
    search: Optional[str] = None,
) -> str:
    """The `scope` work orders as CSV text, one row each.

    Written with `\\r\\n` line endings (the CSV standard, and what Excel expects)
    and a header row.

    `full` is the operational export: every column, led by the import's own
    headers, so the file round-trips -- re-importing it is the idempotent
    fill-blanks path, not a duplicate. `client` is the billing export: the
    work-order number, the billed material and labor totals, and the full
    receipt text in one cell (its embedded newlines survive CSV quoting, so the
    receipt stays readable in a spreadsheet cell). Advanced predicates apply to
    the operational export only; the client variant intentionally keeps its
    existing scope-only behavior."""
    wo.validate_export_variant(variant)
    is_client = variant == wo.EXPORT_VARIANT_CLIENT
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(wo.CLIENT_EXPORT_HEADERS if is_client else wo.EXPORT_HEADERS)
    build_row = _client_export_row if is_client else _export_row
    export_filters = {} if is_client else {
        "service_type": service_type,
        "supervisor_id": supervisor_id,
        "community": community,
        "scheduled_date": scheduled_date,
        "search": search,
    }
    for work_order in list_work_orders_for_export(
        db, user=user, scope=scope, **export_filters
    ):
        writer.writerow(build_row(work_order))
    return buffer.getvalue()


def _heal_orphan_lines(db: Session, work_order: WorkOrder) -> bool:
    """Lazily absorb any work-order-linked dispenses that have no materials line
    into real `WorkOrderItem` rows, so a straggler from before this model (or any
    path that ever skipped the line) still shows on the page and stays editable.

    The companion to the one-time backfill migration: a no-op once every linked
    dispense has a line (the common case). Stock-neutral -- the dispense already
    moved on-hand when it was written -- so this only reconciles the display, and
    takes no item lock. Returns whether anything was created."""
    existing_item_ids = {line.item_id for line in work_order.items}
    totals = (
        db.query(Transaction.item_id, func.sum(Transaction.quantity))
        .filter(
            Transaction.work_order_id == work_order.id,
            Transaction.transaction_type == "dispense",
            Transaction.voided_at.is_(None),
        )
        .group_by(Transaction.item_id)
        .all()
    )
    created = False
    for item_id, total in totals:
        if item_id in existing_item_ids:
            continue
        db.add(
            WorkOrderItem(
                work_order_id=work_order.id,
                item_id=item_id,
                quantity=total,
                mode=wo.MODE_DISPENSE,
                transaction_id=None,
                created_by_id=None,
            )
        )
        created = True
    return created


def get_work_order(
    db: Session, work_order_id: uuid.UUID, *, user: Optional[User]
) -> WorkOrder:
    """Full work-order detail (with logged materials), scope-checked. Lazily
    self-heals any orphaned linked dispenses into materials lines on the way out."""
    work_order = _get_visible(db, work_order_id, user)
    if _heal_orphan_lines(db, work_order):
        db.commit()
        work_order = _get_visible(db, work_order_id, user)
    return work_order


# --- update / archive ----------------------------------------------------

def start_work_order(
    db: Session, work_order_id: uuid.UUID, *, user: Optional[User]
) -> WorkOrder:
    """Move one visible Assigned work order to In-Progress.

    This narrow action is shared by Supervisors and assigned Technicians from
    the Scan / Stock confirmation. It intentionally does not grant Technicians
    the general status-edit contract: they cannot pause, complete, review, or
    roll back a work order through this endpoint. Repeating the start after a
    slow/double tap is idempotent.
    """
    _require_role(
        user,
        roles.ROLE_TECHNICIAN,
        "Only a Technician or above can start a work order.",
    )
    work_order = _get_locked(db, work_order_id)
    if (
        work_order is None
        or work_order.archived_at is not None
        or not _visible(work_order, user)
    ):
        raise WorkOrderNotFoundError("Work order not found.")
    if work_order.status == wo.STATUS_IN_PROGRESS:
        return work_order
    if work_order.status != wo.STATUS_ASSIGNED:
        raise WorkOrderStateError(
            "Only an Assigned work order can be started from Scan / Stock."
        )

    work_order.status = wo.STATUS_IN_PROGRESS
    work_order.completed_at = None
    db.commit()
    db.refresh(work_order)
    return work_order


def complete_work_order(
    db: Session, work_order_id: uuid.UUID, *, user: User
) -> WorkOrder:
    """Move an assigned worker's In-Progress work order to Completed.

    This is the second and final assigned-worker walkthrough action. It is
    intentionally separate from the Supervisor+ PATCH contract so a Technician
    receives no arbitrary status authority. Repeating the completion after a
    slow/double tap is idempotent; every other source status is rejected.
    """
    _require_role(
        user,
        roles.ROLE_TECHNICIAN,
        "Only a Technician or above can complete assigned work.",
    )
    work_order = _get_locked(db, work_order_id)
    if (
        work_order is None
        or work_order.archived_at is not None
        or not _visible(work_order, user)
    ):
        raise WorkOrderNotFoundError("Work order not found.")
    if user.id not in _assigned_technician_ids(work_order):
        raise RoleManagementError(
            "Only a worker assigned to this work order can mark it Completed."
        )
    if work_order.status == wo.STATUS_COMPLETED:
        return work_order
    if work_order.status != wo.STATUS_IN_PROGRESS:
        raise WorkOrderStateError(
            "Only an In-Progress work order can be marked Completed by its "
            "assigned worker."
        )

    work_order.status = wo.STATUS_COMPLETED
    work_order.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(work_order)
    return work_order


def hold_work_order(
    db: Session, work_order_id: uuid.UUID, *, user: User
) -> WorkOrder:
    """Place an assigned worker's In-Progress work order On-Hold.

    This narrow pause action does not grant resume, rollback, completion, or
    Review authority. Repeating an already successful request is idempotent.
    """
    _require_role(
        user,
        roles.ROLE_TECHNICIAN,
        "Only a Technician or above can pause assigned work.",
    )
    work_order = _get_locked(db, work_order_id)
    if (
        work_order is None
        or work_order.archived_at is not None
        or not _visible(work_order, user)
    ):
        raise WorkOrderNotFoundError("Work order not found.")
    if user.id not in _assigned_technician_ids(work_order):
        raise RoleManagementError(
            "Only a worker assigned to this work order can place it On-Hold."
        )
    if work_order.status == wo.STATUS_ON_HOLD:
        return work_order
    if work_order.status != wo.STATUS_IN_PROGRESS:
        raise WorkOrderStateError(
            "Only an In-Progress work order can be placed On-Hold by its "
            "assigned worker."
        )

    work_order.status = wo.STATUS_ON_HOLD
    work_order.completed_at = None
    db.commit()
    db.refresh(work_order)
    return work_order


def resume_work_order(
    db: Session, work_order_id: uuid.UUID, *, user: User
) -> WorkOrder:
    """Return an assigned worker's On-Hold work order to In-Progress.

    This is the exact inverse of the narrow hold action and grants no other
    status authority. Repeating the request after success is idempotent.
    """
    _require_role(
        user,
        roles.ROLE_TECHNICIAN,
        "Only a Technician or above can resume assigned work.",
    )
    work_order = _get_locked(db, work_order_id)
    if (
        work_order is None
        or work_order.archived_at is not None
        or not _visible(work_order, user)
    ):
        raise WorkOrderNotFoundError("Work order not found.")
    if user.id not in _assigned_technician_ids(work_order):
        raise RoleManagementError(
            "Only a worker assigned to this work order can resume it."
        )
    if work_order.status == wo.STATUS_IN_PROGRESS:
        return work_order
    if work_order.status != wo.STATUS_ON_HOLD:
        raise WorkOrderStateError(
            "Only an On-Hold work order can be resumed by its assigned worker."
        )

    work_order.status = wo.STATUS_IN_PROGRESS
    work_order.completed_at = None
    db.commit()
    db.refresh(work_order)
    return work_order


def update_work_order(
    db: Session,
    work_order_id: uuid.UUID,
    *,
    user: Optional[User],
    fields: dict,
    expected_supervisor_id: object = _UNSET,
) -> WorkOrder:
    """Explicit edit (overwrite) of the fields present in `fields` -- any of
    number / community / building_number / unit_number / description / notes /
    status / entry_mode / assigned_to_ids. Validates status / mode / assignees.
    Nonblank notes append a server-timestamped/authored entry instead of replacing
    prior text. Notes are Technician+; operational fields require Supervisor+;
    imported and legacy metadata requires TechFM OA+. Review is the exception
    within general status editing, and the one place the floor is still Admin
    rather than TechFM OA: the row must already be Completed and the caller must
    be an unassigned routed Supervisor or Admin+. When `expected_supervisor_id` is supplied,
    routing changes use it as an optimistic precondition while the work-order
    row is locked.
    The legacy singular `assigned_to_id` is accepted for old clients. Technician
    assignment moves Created/Assigned automatically; explicit status wins when
    both are patched. Supervisor routing is independent of lifecycle status.
    Completed/Review retain `completed_at`, while reopening to an earlier state
    clears it. A number collision raises `WorkOrderStateError`."""
    _require_update_permissions(user, fields)
    work_order = _get_locked(db, work_order_id)
    if work_order is None or work_order.archived_at is not None:
        raise WorkOrderNotFoundError("Work order not found.")

    # Check the stale routing value before current visibility: a supervisor who
    # loaded this row while it was unrouted must receive the named 409 after
    # another supervisor picks it up, even though the new routing now hides it.
    if (
        "supervisor_id" in fields
        and expected_supervisor_id is not _UNSET
        and work_order.supervisor_id != expected_supervisor_id
    ):
        supervisor_name = None
        if work_order.supervisor_id is not None:
            current_supervisor = (
                db.query(User)
                .filter(User.id == work_order.supervisor_id)
                .first()
            )
            if current_supervisor is not None:
                supervisor_name = current_supervisor.full_name
        raise WorkOrderAssignmentConflictError(supervisor_name)

    if not _visible(work_order, user):
        raise WorkOrderNotFoundError("Work order not found.")

    if fields.get("status") == wo.STATUS_REVIEW:
        if work_order.status != wo.STATUS_COMPLETED:
            raise WorkOrderStateError(
                "Only a Completed work order can be sent to Review."
            )
        _require_review_handoff_permission(work_order, user)

    if "entry_mode" in fields:
        wo.validate_mode(fields["entry_mode"])
        work_order.entry_mode = fields["entry_mode"]
    if "assigned_to_ids" in fields and "assigned_to_id" in fields:
        raise WorkOrderStateError(
            "Provide assigned_to_ids or assigned_to_id, not both."
        )
    assignment_changed = False
    if "assigned_to_ids" in fields:
        technician_ids = _validate_assignees(db, fields["assigned_to_ids"] or [])
        _sync_technician_assignments(
            db,
            work_order,
            technician_ids,
            assigned_by_id=user.id if user else None,
        )
        assignment_changed = True
    elif "assigned_to_id" in fields:
        technician_ids = (
            _validate_assignees(db, [fields["assigned_to_id"]])
            if fields["assigned_to_id"] is not None
            else []
        )
        _sync_technician_assignments(
            db,
            work_order,
            technician_ids,
            assigned_by_id=user.id if user else None,
        )
        assignment_changed = True

    if assignment_changed:
        if "status" not in fields:
            work_order.status = wo.reconcile_assignment_status(
                work_order.status, technician_ids
            )
    if "supervisor_id" in fields:
        _validate_supervisor(db, fields["supervisor_id"])
        work_order.supervisor_id = fields["supervisor_id"]
    if "status" in fields:
        # Created/Assigned is an assignment-derived pair even for a manual
        # rollback. This prevents a selected technician from coexisting with
        # Created (or an unassigned row from coexisting with Assigned).
        work_order.status = wo.reconcile_assignment_status(
            fields["status"],
            technician_ids if assignment_changed else _assigned_technician_ids(work_order),
        )
        if work_order.status in (wo.STATUS_COMPLETED, wo.STATUS_REVIEW):
            work_order.completed_at = (
                work_order.completed_at or datetime.now(timezone.utc)
            )
        else:
            work_order.completed_at = None
    if "notes" in fields and fields["notes"] is not None:
        work_order.notes = wo.append_note_log(
            work_order.notes,
            fields["notes"],
            author_name=user.full_name if user is not None else "System",
            occurred_at=datetime.now(timezone.utc),
        )
    if "number" in fields and fields["number"] is not None:
        work_order.number = fields["number"].strip()
    for field in _ATTR_FIELDS:
        if field in fields:
            setattr(work_order, field, fields[field])

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise WorkOrderStateError(
            "A work order with that number already exists."
        ) from exc
    db.refresh(work_order)
    return work_order


def archive_work_order(
    db: Session, work_order_id: uuid.UUID, *, user: Optional[User]
) -> None:
    """Close any live work order by soft-archiving it (TechFM OA+).

    The row and its material lines stay put and the number stays reserved.
    Reversible only through the explicit `restore_work_order` workflow.
    Transactions already logged against it are untouched -- History reads them
    from the denormalized `work_order_number` on each transaction row, so a
    closed work order's past dispenses stay searchable."""
    _require_role(
        user,
        roles.ROLE_TECHFM_OA,
        "Only a TechFM OA, Admin, or Owner can archive a work order.",
    )
    work_order = _get_visible(db, work_order_id, user)
    work_order.archived_at = datetime.now(timezone.utc)
    db.commit()


def count_live_legacy_work_orders(
    db: Session, *, user: Optional[User]
) -> int:
    """Return the legacy work orders that are currently live (Owner only).

    The count is the preview for the owner's bulk re-archive confirmation. An
    already archived legacy row is deliberately excluded because the action
    has nothing left to do to it.
    """
    _require_role(
        user,
        roles.ROLE_OWNER,
        "Only the Owner can re-archive legacy work orders.",
    )
    return (
        db.query(WorkOrder)
        .filter(
            WorkOrder.legacy.is_(True),
            WorkOrder.archived_at.is_(None),
        )
        .count()
    )


def archive_live_legacy_work_orders(
    db: Session, *, user: Optional[User]
) -> int:
    """Soft-archive every currently live legacy work order (Owner only).

    A single bulk UPDATE keeps the operation atomic and returns the actual
    number archived, which may differ from an earlier preview if another
    session restored or archived a legacy row in between.
    """
    _require_role(
        user,
        roles.ROLE_OWNER,
        "Only the Owner can re-archive legacy work orders.",
    )
    archived = (
        db.query(WorkOrder)
        .filter(
            WorkOrder.legacy.is_(True),
            WorkOrder.archived_at.is_(None),
        )
        .update(
            {WorkOrder.archived_at: datetime.now(timezone.utc)},
            synchronize_session=False,
        )
    )
    db.commit()
    return archived


def lookup_work_order(
    db: Session, *, number: str, user: Optional[User]
) -> Optional[WorkOrder]:
    """The work order carrying `number` **including an archived one**, or `None`
    if unknown or not visible to `user`.

    The deliberate counterpart to the scoped loaders, which hide archived work
    orders entirely: this is how a recovery-aware search discovers that an exact
    number belongs to a work order that has been archived, and so can offer to
    restore it."""
    work_order = find_by_number(db, number)
    if work_order is None or not _visible(work_order, user):
        return None
    return work_order


def restore_work_order(
    db: Session, work_order_id: uuid.UUID, *, user: Optional[User]
) -> WorkOrder:
    """Un-archive a work order, putting it back on the Work Orders page with its
    materials intact. The counterpart to `archive_work_order`, and -- now that
    work orders are import-only and there is no "create it again" path -- the way
    an archived work order comes back without re-importing. Already-live work
    orders pass through unchanged. Raises `WorkOrderNotFoundError` if unknown or
    not visible to `user`."""
    work_order = db.query(WorkOrder).filter(WorkOrder.id == work_order_id).first()
    if work_order is None or not _visible(work_order, user):
        raise WorkOrderNotFoundError("Work order not found.")
    if work_order.archived_at is not None:
        work_order.archived_at = None
        db.commit()
        db.refresh(work_order)
    return work_order


# --- labor entries -------------------------------------------------------

def _get_labor_entry(
    db: Session, work_order: WorkOrder, labor_id: uuid.UUID
) -> WorkOrderLabor:
    entry = (
        db.query(WorkOrderLabor)
        .options(joinedload(WorkOrderLabor.technician))
        .filter(
            WorkOrderLabor.id == labor_id,
            WorkOrderLabor.work_order_id == work_order.id,
        )
        .first()
    )
    if entry is None:
        raise WorkOrderNotFoundError("Work order labor entry not found.")
    return entry


def _require_labor_actor(user: Optional[User]) -> None:
    """Labor management belongs to Supervisor+ for every technician row."""
    _require_role(
        user,
        roles.ROLE_SUPERVISOR,
        "Only a Supervisor, Admin, or Owner can manage work order labor.",
    )


def add_work_order_labor(
    db: Session,
    work_order_id: uuid.UUID,
    *,
    user: Optional[User],
    technician_id: uuid.UUID,
    minutes: int,
) -> WorkOrderLabor:
    """Record actual labor for one assigned technician (Supervisor+).

    The duration is stored without rounding. Billing is derived from the sum of
    every entry on the work order, rounded upward once to the next 30 minutes.
    The first labor entry advances Created/Assigned to In-Progress through the
    same domain rule used by committed material activity.
    """
    work_order = _get_visible(db, work_order_id, user)
    wo.validate_labor_minutes(minutes)
    _require_labor_actor(user)
    if technician_id not in _assigned_technician_ids(work_order):
        raise InvalidAssigneeError(
            "Labor can only be recorded for a technician assigned to this work order."
        )

    entry = WorkOrderLabor(
        id=uuid.uuid4(),
        work_order_id=work_order.id,
        technician_id=technician_id,
        minutes=minutes,
        recorded_by_id=user.id if user else None,
    )
    db.add(entry)
    work_order.status = wo.status_after_activity(work_order.status)
    db.commit()
    return _get_labor_entry(db, work_order, entry.id)


def update_work_order_labor(
    db: Session,
    work_order_id: uuid.UUID,
    labor_id: uuid.UUID,
    *,
    user: Optional[User],
    minutes: int,
) -> WorkOrderLabor:
    """Replace one labor entry's actual duration without re-rounding it."""
    work_order = _get_visible(db, work_order_id, user)
    entry = _get_labor_entry(db, work_order, labor_id)
    wo.validate_labor_minutes(minutes)
    _require_labor_actor(user)
    entry.minutes = minutes
    db.commit()
    return _get_labor_entry(db, work_order, entry.id)


def delete_work_order_labor(
    db: Session,
    work_order_id: uuid.UUID,
    labor_id: uuid.UUID,
    *,
    user: Optional[User],
) -> None:
    """Remove one labor entry. Lifecycle status is not rolled backward."""
    work_order = _get_visible(db, work_order_id, user)
    entry = _get_labor_entry(db, work_order, labor_id)
    _require_labor_actor(user)
    db.delete(entry)
    db.commit()


# --- material lines ------------------------------------------------------

def _locked_live_item(db: Session, item_id: uuid.UUID) -> Item:
    item = (
        db.query(Item)
        .filter(Item.id == item_id, Item.archived_at.is_(None))
        .with_for_update()
        .first()
    )
    if item is None:
        raise ItemNotFoundError("Item not found.")
    return item


def attach_dispense_line(
    db: Session,
    *,
    work_order_id: uuid.UUID,
    item_id: uuid.UUID,
    quantity: Decimal,
    mode: str = wo.MODE_DISPENSE,
    transaction_id: Optional[uuid.UUID] = None,
    user_id: Optional[uuid.UUID] = None,
) -> WorkOrderItem:
    """Reflect a dispense logged against a work order on its materials list,
    ADDING `quantity` to the item's line.

    The single home for "stock was taken out against a work order, show it on the
    Work Orders page". Every stock-moving surface funnels through here -- the
    Work Orders page button (`add_work_order_item`), the Scan/Stock page and
    scan-and-go (`services.transactions.apply_transaction`), and a Mass Stage
    truck-load (`services.mass_staging.load_item`) -- so a work order's materials
    stay in sync with its dispensing transactions no matter where the scan came
    from.

    Aggregates by `(work_order_id, item_id)`: re-logging an item ADDS to its line
    (the `UNIQUE(work_order_id, item_id)` row), because a scan is inherently
    additive (each scan is its own ledger row). This NEVER touches `Item.quantity`
    -- the caller already moved stock and owns the row lock. That lock serialises
    concurrent dispenses of the same item, so this find-or-add needs no race guard
    of its own.

    `mode` sets a NEW line's display/stock semantics (the Work Orders page may log
    in `retroactive`). When a stock-moving (`dispense`) entry joins an existing
    `retroactive` line, the line is surfaced as `dispense` -- the rare mixed case;
    stock correctness comes from each transaction's `affects_stock`, not this tag.
    """
    # The first real work activity starts the job. This shared line-attachment
    # path covers Work Orders, Scan/Stock, and Mass Stage materials. IMP-006's
    # future labor write should call the same domain helper when it records labor.
    work_order = db.query(WorkOrder).filter(WorkOrder.id == work_order_id).first()
    if work_order is not None:
        work_order.status = wo.status_after_activity(work_order.status)
        item = db.get(Item, item_id)
        if item is not None and (item.price is None or item.price <= 0):
            request_service.create_or_update_missing_price_request(
                db,
                item_id=item_id,
                work_order_id=work_order_id,
                work_order_number=work_order.number,
                created_by_id=user_id,
            )

    line = (
        db.query(WorkOrderItem)
        .filter(
            WorkOrderItem.work_order_id == work_order_id,
            WorkOrderItem.item_id == item_id,
        )
        .first()
    )
    if line is not None:
        line.quantity = line.quantity + quantity
        if transaction_id is not None:
            # Keep a reference to the most recent contributing transaction; the
            # line's full membership is derived by (work_order_id, item_id).
            line.transaction_id = transaction_id
        if mode == wo.MODE_DISPENSE and line.mode != wo.MODE_DISPENSE:
            line.mode = wo.MODE_DISPENSE
        return line

    line = WorkOrderItem(
        work_order_id=work_order_id,
        item_id=item_id,
        quantity=quantity,
        mode=mode,
        transaction_id=transaction_id,
        created_by_id=user_id,
    )
    db.add(line)
    return line


def reduce_dispense_line(
    db: Session,
    *,
    work_order_id: uuid.UUID,
    item_id: uuid.UUID,
    quantity: Decimal,
) -> None:
    """Walk a work order's materials line back by `quantity` (the inverse of
    `attach_dispense_line`). Used when units logged against a work order are
    returned without a ledger row -- a Mass Stage "unused materials" return -- so
    the line reflects net consumption. Stock-neutral and lock-free for the same
    reasons as the attach side; drops the line once nothing is left. A no-op if no
    line exists (nothing was logged here)."""
    line = (
        db.query(WorkOrderItem)
        .filter(
            WorkOrderItem.work_order_id == work_order_id,
            WorkOrderItem.item_id == item_id,
        )
        .first()
    )
    if line is None:
        return
    line.quantity = line.quantity - quantity
    if line.quantity <= 0:
        db.delete(line)


def _get_line(
    db: Session, work_order: WorkOrder, wo_item_id: uuid.UUID
) -> WorkOrderItem:
    line = (
        db.query(WorkOrderItem)
        .filter(
            WorkOrderItem.id == wo_item_id,
            WorkOrderItem.work_order_id == work_order.id,
        )
        .first()
    )
    if line is None:
        raise WorkOrderNotFoundError("Work order item not found.")
    return line


def add_work_order_item(
    db: Session,
    work_order_id: uuid.UUID,
    *,
    user: Optional[User],
    item_id: uuid.UUID,
    quantity: Decimal,
) -> WorkOrderItem:
    """Log a material against a work order using its current `entry_mode`.
    Re-adding an item ADDS to its line (each add is its own ledger row). Writes
    the History transaction (`work_order_id` + number, `affects_stock` per mode)
    and reflects it on the materials list via `attach_dispense_line`. Raises
    `WorkOrderNotFoundError` / `ItemNotFoundError`. A dispense-mode shortage is
    recorded with a negative expected balance plus an inventory-recount User
    Request, matching Scan / Stock; retroactive mode stays stock-neutral."""
    work_order = _get_visible(db, work_order_id, user)
    item = _locked_live_item(db, item_id)

    mode = work_order.entry_mode
    moves_stock = wo.affects_stock(mode)
    quantity_before = item.quantity
    shortage_quantity = Decimal(0)
    if moves_stock:
        available = max(quantity_before, Decimal(0))
        shortage_quantity = max(quantity - available, Decimal(0))
        item.quantity = quantity_before - quantity

    txn = Transaction(
        item_id=item.id,
        user_id=user.id if user else None,
        transaction_type="dispense",
        quantity=quantity,
        unit_price=item.price,
        work_order_number=work_order.number,
        work_order_id=work_order.id,
        affects_stock=moves_stock,
        reason=None,
    )
    db.add(txn)
    db.flush()

    line = attach_dispense_line(
        db,
        work_order_id=work_order.id,
        item_id=item_id,
        quantity=quantity,
        mode=mode,
        transaction_id=txn.id,
        user_id=user.id if user else None,
    )
    if shortage_quantity > 0:
        request_service.create_inventory_recount_request(
            db,
            item_id=item.id,
            transaction_id=txn.id,
            work_order_id=work_order.id,
            work_order_number=work_order.number,
            created_by_id=user.id if user else None,
            recorded_quantity_before=quantity_before,
            dispensed_quantity=quantity,
            shortage_quantity=shortage_quantity,
        )
    db.commit()
    db.refresh(line)
    return line


def update_work_order_item(
    db: Session,
    work_order_id: uuid.UUID,
    wo_item_id: uuid.UUID,
    *,
    user: Optional[User],
    quantity: Decimal,
) -> WorkOrderItem:
    """Edit a logged material's total to `quantity` (Supervisor+).

    The line is the aggregate of many dispenses, so editing it does NOT rewrite
    those rows: a dispense-mode line corrects stock by the delta and appends a
    single `adjust` transaction recording the correction (the original scan rows
    stay intact in History). A retroactive line moves no stock. Raises
    `NegativeQuantityError` if reducing on-hand would drive it below zero."""
    work_order = _get_visible(db, work_order_id, user)
    _require_role(
        user,
        roles.ROLE_SUPERVISOR,
        "Only a Supervisor, Admin, or Owner can edit logged materials.",
    )
    line = _get_line(db, work_order, wo_item_id)
    item = _locked_live_item(db, line.item_id)

    # Signed delta applied to stock: dispensing more (new > old) lowers on-hand,
    # so the stock delta is `old - new`. Matches the `adjust` convention where the
    # stored quantity is the signed amount added to stock.
    stock_delta = line.quantity - quantity
    if stock_delta != 0 and wo.affects_stock(line.mode):
        item.quantity = apply_delta(item.quantity, "adjust", stock_delta)
        db.add(
            Transaction(
                item_id=item.id,
                user_id=user.id if user else None,
                transaction_type="adjust",
                quantity=stock_delta,
                work_order_number=work_order.number,
                work_order_id=work_order.id,
                affects_stock=True,
                reason="Work order material quantity adjusted.",
            )
        )

    line.quantity = quantity
    # A stored billing override is a partial count; if the new total drops below
    # it the override no longer makes sense, so clear it (revert to full).
    if line.billable_quantity is not None and line.billable_quantity > quantity:
        line.billable_quantity = None
    db.commit()
    db.refresh(line)
    return line


def set_work_order_item_billable(
    db: Session,
    work_order_id: uuid.UUID,
    wo_item_id: uuid.UUID,
    *,
    user: Optional[User],
    billable_quantity: Optional[Decimal],
) -> WorkOrderItem:
    """Set (or clear) a material line's billing override -- the per-line analogue
    of `services.transactions.set_billable_quantity`.

    The line is the billing unit for work-order materials, so this records how
    many of its units to actually charge for and NEVER touches `Item.quantity`
    (the materials were physically used; only the invoice changes). `None` clears
    the override (charge the full `quantity`); `0` records but charges nothing; a
    value up to `quantity` bills a partial count. Raises `BillingQuantityError`
    if negative or above the recorded quantity."""
    work_order = _get_visible(db, work_order_id, user)
    line = _get_line(db, work_order, wo_item_id)
    line.billable_quantity = validate_billable_value(line.quantity, billable_quantity)
    db.commit()
    db.refresh(line)
    return line


def delete_work_order_item(
    db: Session,
    work_order_id: uuid.UUID,
    wo_item_id: uuid.UUID,
    *,
    user: Optional[User],
) -> None:
    """Remove a logged material (Supervisor+). A dispense-mode line returns its net units to
    stock (the line's authoritative total, already net of any Mass Stage returns);
    every transaction it aggregated -- the dispenses and any edit `adjust` -- is
    voided so the line leaves History too."""
    work_order = _get_visible(db, work_order_id, user)
    _require_role(
        user,
        roles.ROLE_SUPERVISOR,
        "Only a Supervisor, Admin, or Owner can remove logged materials.",
    )
    line = _get_line(db, work_order, wo_item_id)
    item = _locked_live_item(db, line.item_id)

    if wo.affects_stock(line.mode):
        item.quantity = apply_delta(item.quantity, "stock", line.quantity)

    # Void the line's whole contributing set, located by (work_order, item) -- the
    # stock is already squared by the net return above, so these are voided purely
    # to drop them from History, NOT reversed a second time.
    now = datetime.now(timezone.utc)
    contributors = (
        db.query(Transaction)
        .filter(
            Transaction.work_order_id == work_order.id,
            Transaction.item_id == line.item_id,
            Transaction.voided_at.is_(None),
        )
        .all()
    )
    for txn in contributors:
        txn.voided_at = now
        txn.voided_by_id = user.id if user else None
        request_service.resolve_for_transaction(
            db,
            transaction_id=txn.id,
            resolved_by_id=user.id if user else None,
        )

    db.delete(line)
    db.commit()
