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
