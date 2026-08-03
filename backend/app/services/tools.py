"""Tool CRUD + checkout/return/adjust service.

Layer: services. Called by `app/routers/tools.py`. CRUD mirrors
`app.services.items` (barcode uniqueness, partial update via `_UNSET`,
soft-delete archive). Checkout/return/adjust mirror the row-locking pattern
in `app.services.transactions`: lock the `Tool` row, apply the on-hand
quantity delta via the same `app.domain.quantity.apply_delta` items use
(checkout -> "dispense", return -> "stock", adjust -> "adjust"), then
append a `ToolTransaction` audit row.

Custody ("who currently has this tool") is never stored -- it's derived by
summing `tool_transactions` per `(tool_id, assigned_to_id)`, scoped to
`checkout`/`return` rows only (an `adjust`/Correct Count row has no
custody holder). `tool_custody` is the shared aggregate query both the
router (for display) and `return_tool` (for the outstanding-balance cap)
use.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Sequence

from sqlalchemy import case, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.errors import (
    DuplicateToolBarcodeError,
    NoChangeError,
    ToolHasOutstandingCustodyError,
    ToolNotFoundError,
    UserNotFoundError,
)
from app.domain.quantity import apply_delta
from app.domain.tools import validate_return
from app.models import Tool, ToolTransaction, User


def _ensure_barcode_free(
    db: Session, code: str, *, exclude_tool_id: uuid.UUID | None = None
) -> None:
    """Enforce barcode uniqueness against **live** tools only. Unlike
    `services.items._ensure_barcode_free`, there is no archived-conflict/
    override flow for tools -- an archived tool's barcode is simply free to
    reuse without confirmation (a deliberate v1 scope cut)."""
    q = db.query(Tool).filter(Tool.barcode == code, Tool.archived_at.is_(None))
    if exclude_tool_id is not None:
        q = q.filter(Tool.id != exclude_tool_id)
    if q.first() is not None:
        raise DuplicateToolBarcodeError("A tool with this barcode already exists.")


def create_tool(db: Session, *, barcode: str, name: str, quantity: Decimal) -> Tool:
    """Insert a new tool. Raises `DuplicateToolBarcodeError` if the barcode
    is held by a live tool."""
    _ensure_barcode_free(db, barcode)
    new_tool = Tool(barcode=barcode, name=name, quantity=quantity)
    db.add(new_tool)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateToolBarcodeError(
            "A tool with this barcode already exists."
        ) from exc
    db.refresh(new_tool)
    return new_tool


def list_tools(db: Session) -> Sequence[Tool]:
    """Return every live tool, newest first. Archived tools are excluded."""
    return (
        db.query(Tool)
        .filter(Tool.archived_at.is_(None))
        .order_by(Tool.created_at.desc())
        .all()
    )


def get_tool_by_barcode(db: Session, barcode: str) -> Tool:
    """Lookup by barcode for the Tools-page scanner. Archived tools are
    treated as not found. Raises `ToolNotFoundError` if none match."""
    tool = (
        db.query(Tool)
        .filter(Tool.barcode == barcode, Tool.archived_at.is_(None))
        .first()
    )
    if not tool:
        raise ToolNotFoundError("Tool not found.")
    return tool


def get_tool(db: Session, tool_id: uuid.UUID) -> Tool:
    """Lookup by id (used by checkout/return/update/delete). Raises
    `ToolNotFoundError` if unknown or archived."""
    tool = (
        db.query(Tool)
        .filter(Tool.id == tool_id, Tool.archived_at.is_(None))
        .first()
    )
    if not tool:
        raise ToolNotFoundError("Tool not found.")
    return tool


_UNSET = object()


def update_tool(
    db: Session,
    tool_id: uuid.UUID,
    *,
    barcode=_UNSET,
    name=_UNSET,
) -> Tool:
    """Partially edit `barcode` and/or `name`. Only fields the caller
    passes are written. Raises `ToolNotFoundError` if the id is unknown,
    `DuplicateToolBarcodeError` if a new barcode collides with a live
    tool."""
    tool = get_tool(db, tool_id)
    if barcode is not _UNSET:
        if barcode != tool.barcode:
            _ensure_barcode_free(db, barcode, exclude_tool_id=tool_id)
        tool.barcode = barcode
    if name is not _UNSET:
        tool.name = name
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateToolBarcodeError(
            "A tool with this barcode already exists."
        ) from exc
    db.refresh(tool)
    return tool


def delete_tool(db: Session, tool_id: uuid.UUID) -> None:
    """Archive a tool only when no user still has custody.

    The row lock serialises this check with checkout/return, which lock the
    same `Tool` row before changing the ledger and on-hand quantity.
    """
    tool = (
        db.query(Tool)
        .filter(Tool.id == tool_id, Tool.archived_at.is_(None))
        .with_for_update()
        .first()
    )
    if not tool:
        raise ToolNotFoundError("Tool not found.")
    if tool_custody(db, tool_id):
        raise ToolHasOutstandingCustodyError(
            "Check in all outstanding units before archiving this tool."
        )
    tool.archived_at = datetime.now(timezone.utc)
    db.commit()


def _custody_query(db: Session, tool_id: uuid.UUID):
    """Shared aggregate: per `assigned_to_id`, net = Sum(checkout) -
    Sum(return) for this tool, filtered to positive balances only.

    Explicitly scoped to `transaction_type IN ('checkout', 'return')` --
    an `adjust` row (Correct Count) carries no custody holder
    (`assigned_to_id` NULL) and must never enter this sum."""
    net = func.sum(
        case(
            (ToolTransaction.transaction_type == "checkout", ToolTransaction.quantity),
            else_=-ToolTransaction.quantity,
        )
    ).label("net")
    return (
        db.query(
            ToolTransaction.assigned_to_id,
            User.first_name,
            User.last_name,
            net,
        )
        .join(User, User.id == ToolTransaction.assigned_to_id)
        .filter(
            ToolTransaction.tool_id == tool_id,
            ToolTransaction.transaction_type.in_(("checkout", "return")),
        )
        .group_by(
            ToolTransaction.assigned_to_id,
            User.first_name,
            User.last_name,
        )
        .having(net > 0)
    )


def tool_custody(
    db: Session, tool_id: uuid.UUID
) -> list[tuple[uuid.UUID, str, Decimal]]:
    """Current custody as `(user_id, display_name, quantity)` rows."""
    return [
        (
            uid,
            " ".join(part.strip() for part in (first_name, last_name) if part and part.strip())
            or "Name unavailable",
            net,
        )
        for uid, first_name, last_name, net in _custody_query(db, tool_id).all()
    ]


def user_custody(
    db: Session, assigned_to_id: uuid.UUID
) -> list[tuple[uuid.UUID, str, str, Decimal]]:
    """Current custody for one user across tools.

    Returns `(tool_id, tool_name, barcode, quantity)` tuples for every
    positive checkout-minus-return balance. `adjust` rows are excluded for
    the same reason they are excluded from `tool_custody`. This service-level
    read is used by user archival; the frontend continues to invert the
    existing `ToolResponse.custody` data and does not need another endpoint.
    """
    net = func.sum(
        case(
            (ToolTransaction.transaction_type == "checkout", ToolTransaction.quantity),
            else_=-ToolTransaction.quantity,
        )
    ).label("net")
    rows = (
        db.query(Tool.id, Tool.name, Tool.barcode, net)
        .join(ToolTransaction, ToolTransaction.tool_id == Tool.id)
        .filter(
            ToolTransaction.assigned_to_id == assigned_to_id,
            ToolTransaction.transaction_type.in_(("checkout", "return")),
        )
        .group_by(Tool.id, Tool.name, Tool.barcode)
        .having(net > 0)
        .all()
    )
    return [
        (tool_id, name, barcode, quantity)
        for tool_id, name, barcode, quantity in rows
    ]


def return_all_for_user(
    db: Session,
    assigned_to_id: uuid.UUID,
    *,
    performed_by_id: Optional[uuid.UUID],
) -> list[tuple[str, Decimal]]:
    """Force check-in: return every tool `assigned_to_id` still holds, as
    `(tool_name, quantity)` rows describing what was returned.

    Writes the same `return` transactions `return_tool` writes -- one per
    tool, for that user's whole outstanding balance -- so the custody audit
    trail reads the same whether the return was done at the counter or
    forced. Deliberately does NOT commit: the caller (user archival) owns
    the transaction, so the returns and the archive land together or not at
    all, and the caller's row lock stays held throughout.
    """
    returned: list[tuple[str, Decimal]] = []
    for tool_id, name, _barcode, quantity in user_custody(db, assigned_to_id):
        tool = db.query(Tool).filter(Tool.id == tool_id).with_for_update().first()
        if not tool:  # pragma: no cover - custody rows come from a Tool join
            continue
        tool.quantity = apply_delta(tool.quantity, "stock", quantity)
        db.add(
            ToolTransaction(
                tool_id=tool_id,
                transaction_type="return",
                quantity=quantity,
                assigned_to_id=assigned_to_id,
                performed_by_id=performed_by_id,
            )
        )
        returned.append((name, quantity))
    db.flush()
    return returned


def _outstanding_for_user(
    db: Session, tool_id: uuid.UUID, assigned_to_id: uuid.UUID
) -> Decimal:
    """Current outstanding balance for one `(tool, user)` pair, or 0 if
    none. Used by `return_tool`'s cap check."""
    row = (
        _custody_query(db, tool_id)
        .filter(ToolTransaction.assigned_to_id == assigned_to_id)
        .first()
    )
    return row[-1] if row else Decimal(0)


def checkout_tool(
    db: Session,
    tool_id: uuid.UUID,
    *,
    quantity: Decimal,
    assigned_to_id: uuid.UUID,
    performed_by_id: Optional[uuid.UUID],
    work_order_id: Optional[uuid.UUID] = None,
    work_order_number: Optional[str] = None,
) -> ToolTransaction:
    """Check a tool out to `assigned_to_id`, decrementing on-hand quantity.
    Raises `UserNotFoundError` if the custody target is unknown/archived,
    `ToolNotFoundError` if the tool is unknown/archived, or
    `NegativeQuantityError` (reused from `domain.quantity`) if `quantity`
    exceeds on-hand.

    Lock the target user before the tool so a concurrent archive cannot make
    a new checkout invisible from the user-first custody workflow.
    """
    assigned_to = (
        db.query(User)
        .filter(User.id == assigned_to_id, User.archived_at.is_(None))
        .with_for_update()
        .first()
    )
    if not assigned_to:
        raise UserNotFoundError("Active user not found.")

    tool = (
        db.query(Tool)
        .filter(Tool.id == tool_id, Tool.archived_at.is_(None))
        .with_for_update()
        .first()
    )
    if not tool:
        raise ToolNotFoundError("Tool not found.")

    tool.quantity = apply_delta(tool.quantity, "dispense", quantity)

    new_txn = ToolTransaction(
        tool_id=tool_id,
        transaction_type="checkout",
        quantity=quantity,
        assigned_to_id=assigned_to_id,
        performed_by_id=performed_by_id,
        work_order_id=work_order_id,
        work_order_number=work_order_number,
    )
    db.add(new_txn)
    db.commit()
    db.refresh(new_txn)
    return new_txn


def adjust_tool_quantity(
    db: Session,
    tool_id: uuid.UUID,
    *,
    new_quantity: Decimal,
    reason: str,
    performed_by_id: Optional[uuid.UUID],
) -> ToolTransaction:
    """"Correct Count": set the tool's on-hand quantity to the absolute
    `new_quantity`, mirroring `services.transactions.apply_correction`. No
    custody holder is involved (`assigned_to_id` is NULL on the inserted
    row) -- this is a pure inventory correction, e.g. fixing a miscount or
    adding more units of a bulk tool. Raises `ToolNotFoundError` if unknown/
    archived, `NoChangeError` if `new_quantity` equals the current
    quantity (no audit row for a no-op)."""
    tool = (
        db.query(Tool)
        .filter(Tool.id == tool_id, Tool.archived_at.is_(None))
        .with_for_update()
        .first()
    )
    if not tool:
        raise ToolNotFoundError("Tool not found.")

    delta = new_quantity - tool.quantity
    if delta == 0:
        raise NoChangeError("No change to apply.")

    tool.quantity = apply_delta(tool.quantity, "adjust", delta)

    new_txn = ToolTransaction(
        tool_id=tool_id,
        transaction_type="adjust",
        quantity=delta,
        assigned_to_id=None,
        performed_by_id=performed_by_id,
        reason=reason,
    )
    db.add(new_txn)
    db.commit()
    db.refresh(new_txn)
    return new_txn


def return_tool(
    db: Session,
    tool_id: uuid.UUID,
    *,
    quantity: Decimal,
    assigned_to_id: uuid.UUID,
    performed_by_id: Optional[uuid.UUID],
    work_order_id: Optional[uuid.UUID] = None,
    work_order_number: Optional[str] = None,
) -> ToolTransaction:
    """Return `quantity` of a tool from `assigned_to_id`'s custody,
    incrementing on-hand quantity. Raises `ToolNotFoundError` if unknown/
    archived, `ToolReturnExceedsCheckedOutError` if `quantity` exceeds that
    user's current outstanding balance for this tool."""
    tool = (
        db.query(Tool)
        .filter(Tool.id == tool_id, Tool.archived_at.is_(None))
        .with_for_update()
        .first()
    )
    if not tool:
        raise ToolNotFoundError("Tool not found.")

    outstanding = _outstanding_for_user(db, tool_id, assigned_to_id)
    validate_return(outstanding, quantity)

    tool.quantity = apply_delta(tool.quantity, "stock", quantity)

    new_txn = ToolTransaction(
        tool_id=tool_id,
        transaction_type="return",
        quantity=quantity,
        assigned_to_id=assigned_to_id,
        performed_by_id=performed_by_id,
        work_order_id=work_order_id,
        work_order_number=work_order_number,
    )
    db.add(new_txn)
    db.commit()
    db.refresh(new_txn)
    return new_txn
