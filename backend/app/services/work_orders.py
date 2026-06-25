"""Work order service -- the standalone first-class entity.

Layer: services. Backs `/work-orders` and is the single home for
find-or-create-by-number, so every surface (scan-and-go, Mass Stage, the Work
Orders page) resolves a number to the one `work_orders` row.

Identity is the number, unique case-insensitively + trimmed
(`domain.work_orders.normalize_number`). References fill blank attributes but
never overwrite non-blank ones; explicit edits (`update_work_order`) overwrite.
A work order soft-archives (`archived_at`); an archived number stays reserved
and is restored when referenced again.

Materials logged against a work order write a `dispense` transaction carrying
`work_order_id` + the number; the work order's `entry_mode` decides
`affects_stock` (dispense moves stock; retroactive is stock-neutral but still
shows in History). Editing a dispense line auto-corrects stock by the delta and
rewrites the linked transaction in place -- the scoped exception to the
append-only ledger.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Sequence

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.domain import roles
from app.domain import work_orders as wo
from app.domain.errors import (
    InvalidAssigneeError,
    ItemNotFoundError,
    WorkOrderNotFoundError,
    WorkOrderStateError,
)
from app.domain.quantity import apply_delta
from app.models import Item, Transaction, User, WorkOrder, WorkOrderItem


# Backslash is the LIKE escape char (mirrors services.history).
_LIKE_ESCAPE = "\\"

# Editable attribute fields (used by fill-blanks references + explicit edits).
_ATTR_FIELDS = ("community", "building_number", "unit_number", "description")


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


def _visible(work_order: WorkOrder, user: Optional[User]) -> bool:
    return wo.can_view_work_order(
        user.role if user else None,
        created_by_id=work_order.created_by_id,
        assigned_to_id=work_order.assigned_to_id,
        user_id=user.id if user else None,
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


# --- find-or-create ------------------------------------------------------

def get_or_create_work_order(
    db: Session,
    *,
    number: str,
    community: Optional[str] = None,
    building_number: Optional[str] = None,
    unit_number: Optional[str] = None,
    description: Optional[str] = None,
    assigned_to_id: Optional[uuid.UUID] = None,
    created_by_id: Optional[uuid.UUID] = None,
) -> WorkOrder:
    """Resolve `number` to the one work order, creating it if new.

    Existing (incl. archived -> restored): fill-blanks merge of the supplied
    attributes; a non-blank assignee is validated + applied only if currently
    unassigned. New: created `in_progress` with the supplied attributes. Raises
    `InvalidAssigneeError` if an assignee is not a technician."""
    _validate_assignee(db, assigned_to_id)
    incoming = {
        "community": community,
        "building_number": building_number,
        "unit_number": unit_number,
        "description": description,
    }

    existing = find_by_number(db, number)
    if existing is not None:
        if existing.archived_at is not None:
            existing.archived_at = None  # restore -- numbers are permanent
        for field in _ATTR_FIELDS:
            setattr(existing, field, wo.fill_blank(getattr(existing, field), incoming[field]))
        if assigned_to_id is not None and existing.assigned_to_id is None:
            existing.assigned_to_id = assigned_to_id
        db.commit()
        db.refresh(existing)
        return existing

    work_order = WorkOrder(
        number=number.strip(),
        community=wo.fill_blank(None, community),
        building_number=wo.fill_blank(None, building_number),
        unit_number=wo.fill_blank(None, unit_number),
        description=wo.fill_blank(None, description),
        status=wo.STATUS_IN_PROGRESS,
        assigned_to_id=assigned_to_id,
        created_by_id=created_by_id,
    )
    db.add(work_order)
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


# --- list + detail -------------------------------------------------------

def list_work_orders(
    db: Session,
    *,
    user: Optional[User],
    status: Optional[str] = None,
    search: Optional[str] = None,
) -> Sequence[WorkOrder]:
    """Live work orders newest-first, scoped to `user` (technician -> assigned,
    supervisor -> created, admin/owner -> all). `status` narrows to
    in_progress|completed; `search` is a case-insensitive number substring."""
    query = (
        db.query(WorkOrder)
        .options(joinedload(WorkOrder.assignee), selectinload(WorkOrder.items))
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
            query = query.filter(WorkOrder.created_by_id == user.id)
        else:
            query = query.filter(WorkOrder.assigned_to_id == user.id)

    return query.order_by(WorkOrder.created_at.desc()).all()


def get_work_order(
    db: Session, work_order_id: uuid.UUID, *, user: Optional[User]
) -> WorkOrder:
    """Full work-order detail (with logged materials), scope-checked."""
    return _get_visible(db, work_order_id, user)


# --- create / update / archive ------------------------------------------

def create_work_order(
    db: Session,
    *,
    user: User,
    number: str,
    community: Optional[str] = None,
    building_number: Optional[str] = None,
    unit_number: Optional[str] = None,
    description: Optional[str] = None,
    assigned_to_id: Optional[uuid.UUID] = None,
) -> WorkOrder:
    """Work Orders page "New work order" (Supervisor+). Find-or-create by number
    (re-using an existing number opens it, fill-blanks), attributing creation to
    `user` for a brand-new one."""
    return get_or_create_work_order(
        db,
        number=number,
        community=community,
        building_number=building_number,
        unit_number=unit_number,
        description=description,
        assigned_to_id=assigned_to_id,
        created_by_id=user.id,
    )


def update_work_order(
    db: Session,
    work_order_id: uuid.UUID,
    *,
    user: Optional[User],
    fields: dict,
) -> WorkOrder:
    """Explicit edit (overwrite) of the fields present in `fields` -- any of
    number / community / building_number / unit_number / description / status /
    entry_mode / assigned_to_id. Validates status / mode / assignee. Completing
    stamps `completed_at`; reopening clears it. A number collision raises
    `WorkOrderStateError`."""
    work_order = _get_visible(db, work_order_id, user)

    if "status" in fields:
        wo.validate_status(fields["status"])
        work_order.status = fields["status"]
        work_order.completed_at = (
            datetime.now(timezone.utc)
            if fields["status"] == wo.STATUS_COMPLETED
            else None
        )
    if "entry_mode" in fields:
        wo.validate_mode(fields["entry_mode"])
        work_order.entry_mode = fields["entry_mode"]
    if "assigned_to_id" in fields:
        _validate_assignee(db, fields["assigned_to_id"])
        work_order.assigned_to_id = fields["assigned_to_id"]
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
    """Soft-delete a work order (hidden from lists; the number stays reserved
    and is restored if referenced again)."""
    work_order = _get_visible(db, work_order_id, user)
    work_order.archived_at = datetime.now(timezone.utc)
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


def _reconcile_quantity(
    db: Session, line: WorkOrderItem, item: Item, new_quantity: Decimal
) -> None:
    """Set an existing line to `new_quantity`, reconciling stock + the linked
    transaction. `item` must already be locked by the caller. A dispense-mode
    line keeps the mode it was logged under and corrects stock by the delta
    (on-hand changes by `old - new`); a retroactive line moves no stock."""
    if wo.affects_stock(line.mode):
        item.quantity = apply_delta(
            item.quantity, "adjust", line.quantity - new_quantity
        )
    line.quantity = new_quantity
    if line.transaction_id is not None:
        txn = (
            db.query(Transaction)
            .filter(Transaction.id == line.transaction_id)
            .first()
        )
        if txn is not None:
            txn.quantity = new_quantity


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
    Re-adding an item replaces its quantity. Writes the History transaction
    (`work_order_id` + number, `affects_stock` per mode). Raises
    `WorkOrderNotFoundError` / `ItemNotFoundError`, and `NegativeQuantityError`
    if a dispense-mode add overdraws stock."""
    work_order = _get_visible(db, work_order_id, user)
    item = _locked_live_item(db, item_id)

    existing = (
        db.query(WorkOrderItem)
        .filter(
            WorkOrderItem.work_order_id == work_order.id,
            WorkOrderItem.item_id == item_id,
        )
        .first()
    )
    if existing is not None:
        _reconcile_quantity(db, existing, item, quantity)
        db.commit()
        db.refresh(existing)
        return existing

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

    line = WorkOrderItem(
        work_order_id=work_order.id,
        item_id=item_id,
        quantity=quantity,
        mode=mode,
        transaction_id=txn.id,
        created_by_id=user.id if user else None,
    )
    db.add(line)
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
    """Edit a logged material's quantity (dispense lines auto-correct stock)."""
    work_order = _get_visible(db, work_order_id, user)
    line = _get_line(db, work_order, wo_item_id)
    item = _locked_live_item(db, line.item_id)
    _reconcile_quantity(db, line, item, quantity)
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
    """Remove a logged material. A dispense-mode line returns its units to stock;
    either way the linked History transaction is voided so it leaves History."""
    work_order = _get_visible(db, work_order_id, user)
    line = _get_line(db, work_order, wo_item_id)
    item = _locked_live_item(db, line.item_id)

    if wo.affects_stock(line.mode):
        item.quantity = apply_delta(item.quantity, "stock", line.quantity)

    if line.transaction_id is not None:
        txn = (
            db.query(Transaction)
            .filter(
                Transaction.id == line.transaction_id,
                Transaction.voided_at.is_(None),
            )
            .first()
        )
        if txn is not None:
            txn.voided_at = datetime.now(timezone.utc)
            txn.voided_by_id = user.id if user else None

    db.delete(line)
    db.commit()
