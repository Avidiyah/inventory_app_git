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
re-importing a CSV row for that number is what restores it (a plain reference
no longer resurrects it, since references can no longer create).

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
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Sequence

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.domain import roles
from app.domain import work_orders as wo
from app.domain.errors import (
    InvalidAssigneeError,
    ItemNotFoundError,
    RoleManagementError,
    WorkOrderNotFoundError,
    WorkOrderStateError,
)
from app.domain.billing import validate_billable_value
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


# Backslash is the LIKE escape char (mirrors services.history).
_LIKE_ESCAPE = "\\"

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


def _validate_assignee(db: Session, assigned_to_id: Optional[uuid.UUID]) -> None:
    """A work order may be unassigned, but if assigned the target must exist and
    be a technician."""
    if assigned_to_id is None:
        return
    user = db.query(User).filter(User.id == assigned_to_id).first()
    if user is None or user.role != roles.ROLE_TECHNICIAN:
        raise InvalidAssigneeError(
            "Work orders can only be assigned to a technician."
        )


def _validate_assignees(
    db: Session, assigned_to_ids: Sequence[uuid.UUID]
) -> list[uuid.UUID]:
    """Validate and de-duplicate a complete technician assignment set."""
    normalized = list(dict.fromkeys(assigned_to_ids))
    if not normalized:
        return []
    valid_ids = {
        row.id
        for row in db.query(User.id)
        .filter(
            User.id.in_(normalized),
            User.role == roles.ROLE_TECHNICIAN,
            User.archived_at.is_(None),
        )
        .all()
    }
    if len(valid_ids) != len(normalized):
        raise InvalidAssigneeError(
            "Work orders can only be assigned to active technicians."
        )
    return normalized


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


def find_by_number(db: Session, number: str) -> Optional[WorkOrder]:
    """The work order whose number matches `number` case-insensitively +
    trimmed, including an archived one (numbers stay reserved). `None` if
    unknown."""
    norm = wo.normalize_number(number)
    return (
        db.query(WorkOrder)
        .filter(func.lower(func.btrim(WorkOrder.number)) == norm)
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
) -> WorkOrder:
    """Fill-blanks merge of a reference's attributes into an existing work order:
    a blank column takes the incoming value, a non-blank one is left alone. A
    non-blank assignee applies only if currently unassigned, a `supervisor_id`
    only if currently unrouted. Commits and returns the refreshed row."""
    for field in _ATTR_FIELDS:
        setattr(existing, field, wo.fill_blank(getattr(existing, field), incoming[field]))
    if assigned_to_id is not None and not _assigned_technician_ids(existing):
        _sync_technician_assignments(
            db,
            existing,
            [assigned_to_id],
            assigned_by_id=None,
        )
    if supervisor_id is not None and existing.supervisor_id is None:
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
    (Re-importing a CSV row for an archived number is what restores it.)

    A resolved work order takes the same fill-blanks merge a reference has always
    applied, so a stage still fills in blank location/assignee data without
    clobbering imported values. Raises `InvalidAssigneeError` if an assignee is
    not a technician."""
    _validate_assignee(db, assigned_to_id)
    existing = find_by_number(db, number)
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
) -> WorkOrder:
    """Resolve `number` to the one work order, creating it if new.

    **Import path only** -- `import_work_orders` is the sole caller, because the
    CSV is the only thing allowed to bring a work order into existence. Every
    other surface uses `resolve_work_order`.

    Existing (incl. archived -> restored, so a re-import revives an archived
    number): fill-blanks merge of the supplied attributes; a non-blank assignee is
    validated + applied only if currently unassigned, and a `supervisor_id` is
    applied only if currently unrouted. New: starts `assigned` only when a
    technician is supplied, otherwise `created`; supervisor routing does not
    change lifecycle status. Raises `InvalidAssigneeError` if an assignee is not
    a technician."""
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

    existing = find_by_number(db, number)
    if existing is not None:
        if existing.archived_at is not None:
            existing.archived_at = None  # restore -- numbers are permanent
        return _merge_reference(
            db,
            existing,
            incoming=incoming,
            assigned_to_id=assigned_to_id,
            supervisor_id=supervisor_id,
        )

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
        # Raced another insert of the same normalized number -- reuse it.
        db.rollback()
        existing = find_by_number(db, number)
        if existing is None:
            raise WorkOrderStateError("Could not create the work order.") from exc
        return existing
    db.refresh(work_order)
    return work_order


# --- CSV import ----------------------------------------------------------

def _supervisor_lookup(db: Session) -> dict[str, Optional[uuid.UUID]]:
    """Map unambiguous active-supervisor full names to ids for CSV routing.

    Missing names are deliberately unmatchable. Duplicate normalized names are
    stored as ``None`` so import leaves the relationship unassigned instead of
    routing nondeterministically to whichever row the database returned last.
    """
    lookup: dict[str, Optional[uuid.UUID]] = {}
    supervisors = (
        db.query(User)
        .filter(User.role == roles.ROLE_SUPERVISOR, User.archived_at.is_(None))
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

    Each row funnels through `get_or_create_work_order` by number, so a re-upload
    is idempotent (fill-blanks -- an already-imported number is opened, never
    duplicated, and manual edits survive). The `ASSIGNED TO` vendor name is stored
    raw AND matched to an active system supervisor (by normalized first + last
    name) to set
    `supervisor_id`; an unmatched name imports cleanly (admin routes it later).
    Rows with a blank work-order number are skipped.

    Returns a summary dict (`total`, `created`, `opened`, `supervisors_matched`,
    `supervisors_unmatched`, `skipped`)."""
    text = csv_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    supervisors = _supervisor_lookup(db)

    created = opened = matched = unmatched = skipped = 0
    for row in reader:
        attrs = wo.parse_import_row(row)
        number = attrs.pop("number")
        if number is None:
            skipped += 1
            continue

        key = wo.normalize_assignee_name(attrs.get("vendor_assignee"))
        supervisor_id = supervisors.get(key) if key else None
        if attrs.get("vendor_assignee") is not None:
            if supervisor_id is not None:
                matched += 1
            else:
                unmatched += 1

        existed = find_by_number(db, number) is not None
        get_or_create_work_order(
            db,
            number=number,
            created_by_id=user.id,
            supervisor_id=supervisor_id,
            **attrs,
        )
        if existed:
            opened += 1
        else:
            created += 1

    return {
        "total": created + opened + skipped,
        "created": created,
        "opened": opened,
        "supervisors_matched": matched,
        "supervisors_unmatched": unmatched,
        "skipped": skipped,
    }


# --- list + detail -------------------------------------------------------

def list_work_orders(
    db: Session,
    *,
    user: Optional[User],
    status: Optional[str] = None,
    search: Optional[str] = None,
    limit: Optional[int] = None,
) -> Sequence[WorkOrder]:
    """Live work orders newest-first, scoped to `user` (technician -> assigned,
    supervisor -> created/routed, admin/owner -> all). `status` narrows to one
    live state (created, assigned, in_progress, on_hold, completed, or review); `search`
    is a case-insensitive number substring.
    `limit`, when set, caps the result to the N most-recently-created work orders:
    the Work Orders page browses the 10 newest by default and drops the cap to show
    all (or to search, which must reach the full set)."""
    query = (
        db.query(WorkOrder)
        .options(
            joinedload(WorkOrder.assignee),
            joinedload(WorkOrder.supervisor),
            selectinload(WorkOrder.technician_assignments),
            selectinload(WorkOrder.technicians),
            selectinload(WorkOrder.items),
        )
        .filter(WorkOrder.archived_at.is_(None))
    )

    if status is not None:
        wo.validate_status(status)
        query = query.filter(WorkOrder.status == status)

    pattern = _search_pattern(search)
    if pattern is not None:
        like, escape = pattern
        query = query.filter(WorkOrder.number.ilike(like, escape=escape))

    if user is not None and not roles.role_at_least(user.role, roles.ROLE_ADMIN):
        if user.role == roles.ROLE_SUPERVISOR:
            # A supervisor sees work orders they created OR are routed to them
            # (the CSV import's name-match target). Mirrors can_view_work_order.
            query = query.filter(
                or_(
                    WorkOrder.created_by_id == user.id,
                    WorkOrder.supervisor_id == user.id,
                )
            )
        else:
            query = query.filter(
                or_(
                    WorkOrder.assigned_to_id == user.id,
                    WorkOrder.technician_assignments.any(
                        WorkOrderTechnician.technician_id == user.id
                    ),
                )
            )

    query = query.order_by(WorkOrder.created_at.desc())
    if limit is not None:
        query = query.limit(limit)
    return query.all()


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

def update_work_order(
    db: Session,
    work_order_id: uuid.UUID,
    *,
    user: Optional[User],
    fields: dict,
) -> WorkOrder:
    """Explicit edit (overwrite) of the fields present in `fields` -- any of
    number / community / building_number / unit_number / description / notes /
    status / entry_mode / assigned_to_ids. Validates status / mode / assignees.
    The legacy singular `assigned_to_id` is accepted for old clients. Technician
    assignment moves Created/Assigned automatically; explicit status wins when
    both are patched. Supervisor routing is independent of lifecycle status.
    Completed/Review retain `completed_at`, while reopening to an earlier state
    clears it. A number collision raises `WorkOrderStateError`."""
    work_order = _get_visible(db, work_order_id, user)

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
        # No technician check: any user may be the routed supervisor (the FK
        # guarantees the id exists). Admins use this to route an unmatched import.
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
    if "notes" in fields:
        work_order.notes = fields["notes"]
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
    """Close a Review work order by soft-archiving it.

    The row and its material lines stay put and the number stays reserved.
    Reversible through `restore_work_order` (or a re-import of that number).
    Transactions already logged against it are untouched -- History reads them
    from the denormalized `work_order_number` on each transaction row, so a
    closed work order's past dispenses stay searchable."""
    work_order = _get_visible(db, work_order_id, user)
    if work_order.status != wo.STATUS_REVIEW:
        raise WorkOrderStateError(
            "Only a work order in Review can be closed."
        )
    work_order.archived_at = datetime.now(timezone.utc)
    db.commit()


def lookup_work_order(
    db: Session, *, number: str, user: Optional[User]
) -> Optional[WorkOrder]:
    """The work order carrying `number` **including an archived one**, or `None`
    if unknown or not visible to `user`.

    The deliberate counterpart to the scoped loaders, which hide archived work
    orders entirely: this is how a caller (History's work-order search) discovers
    that a number it can see in the transaction ledger belongs to a work order
    that has been archived, and so can offer to restore it."""
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


def _require_labor_actor(user: Optional[User], technician_id: uuid.UUID) -> None:
    """Technicians may write only their own labor; Supervisor+ may write any."""
    if user is not None and user.role == roles.ROLE_TECHNICIAN and user.id != technician_id:
        raise RoleManagementError(
            "Technicians can only add, edit, or remove their own labor."
        )


def add_work_order_labor(
    db: Session,
    work_order_id: uuid.UUID,
    *,
    user: Optional[User],
    technician_id: uuid.UUID,
    minutes: int,
) -> WorkOrderLabor:
    """Record actual labor for one assigned technician.

    The duration is stored without rounding. Billing is derived from the sum of
    every entry on the work order, rounded upward once to the next 30 minutes.
    The first labor entry advances Created/Assigned to In-Progress through the
    same domain rule used by committed material activity.
    """
    work_order = _get_visible(db, work_order_id, user)
    wo.validate_labor_minutes(minutes)
    _require_labor_actor(user, technician_id)
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
    _require_labor_actor(user, entry.technician_id)
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
    _require_labor_actor(user, entry.technician_id)
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
    `WorkOrderNotFoundError` / `ItemNotFoundError`, and `NegativeQuantityError`
    if a dispense-mode add overdraws stock."""
    work_order = _get_visible(db, work_order_id, user)
    item = _locked_live_item(db, item_id)

    mode = work_order.entry_mode
    moves_stock = wo.affects_stock(mode)
    if moves_stock:
        item.quantity = apply_delta(item.quantity, "dispense", quantity)

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
    """Edit a logged material's total to `quantity`.

    The line is the aggregate of many dispenses, so editing it does NOT rewrite
    those rows: a dispense-mode line corrects stock by the delta and appends a
    single `adjust` transaction recording the correction (the original scan rows
    stay intact in History). A retroactive line moves no stock. Raises
    `NegativeQuantityError` if reducing on-hand would drive it below zero."""
    work_order = _get_visible(db, work_order_id, user)
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
    """Remove a logged material. A dispense-mode line returns its net units to
    stock (the line's authoritative total, already net of any Mass Stage returns);
    every transaction it aggregated -- the dispenses and any edit `adjust` -- is
    voided so the line leaves History too."""
    work_order = _get_visible(db, work_order_id, user)
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

    db.delete(line)
    db.commit()
