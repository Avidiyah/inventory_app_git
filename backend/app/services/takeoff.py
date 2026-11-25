"""Takeoff: predicted material per work order, and the office overview.

Layer: services. Predictions live in their own tables and never touch stock,
`work_order_items`, billing or invoices. `add_line` / `update_line` /
`delete_line` / `set_purchase` commit; `consume_line` and
`count_down_purchases` do not, because their callers (dispense, stock
arrival) own the transaction.
"""

import uuid
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.domain.errors import TakeoffLineConflictError, WorkOrderStateError
from app.domain.work_orders import STATUS_COMPLETED, normalize_service_type
from app.models import (
    Item,
    TakeoffPurchase,
    User,
    WorkOrder,
    WorkOrderTakeoffLine,
)
from app.schemas.takeoff import (
    TakeoffGroup,
    TakeoffOverview,
    TakeoffRow,
    TakeoffWorkOrderRef,
)
from app.services.work_orders import _get_visible, _locked_live_item

_CHANGED = "This takeoff line changed. Refresh and try again."


def _editable_order(db: Session, work_order_id: uuid.UUID, user: Optional[User]) -> WorkOrder:
    order = _get_visible(db, work_order_id, user)
    if order.status == STATUS_COMPLETED:
        raise WorkOrderStateError("Completed work orders can't be changed.")
    return order


def _line_on_order(
    db: Session, work_order_id: uuid.UUID, line_id: uuid.UUID
) -> WorkOrderTakeoffLine:
    line = (
        db.query(WorkOrderTakeoffLine)
        .filter(
            WorkOrderTakeoffLine.id == line_id,
            WorkOrderTakeoffLine.work_order_id == work_order_id,
        )
        .with_for_update()
        .first()
    )
    if line is None:
        raise TakeoffLineConflictError(_CHANGED)
    return line


def add_line(
    db: Session, work_order_id: uuid.UUID, *, user: Optional[User],
    item_id: uuid.UUID, quantity: Decimal,
) -> WorkOrderTakeoffLine:
    _editable_order(db, work_order_id, user)
    _locked_live_item(db, item_id)
    line = (
        db.query(WorkOrderTakeoffLine)
        .filter_by(work_order_id=work_order_id, item_id=item_id)
        .with_for_update()
        .first()
    )
    if line is None:
        line = WorkOrderTakeoffLine(
            work_order_id=work_order_id, item_id=item_id, quantity=quantity,
            created_by_id=user.id if user else None,
        )
        db.add(line)
    else:
        line.quantity = line.quantity + quantity
    db.commit()
    return line


def update_line(
    db: Session, work_order_id: uuid.UUID, line_id: uuid.UUID, *,
    user: Optional[User], quantity: Decimal,
) -> WorkOrderTakeoffLine:
    _editable_order(db, work_order_id, user)
    line = _line_on_order(db, work_order_id, line_id)
    line.quantity = quantity
    db.commit()
    return line


def delete_line(
    db: Session, work_order_id: uuid.UUID, line_id: uuid.UUID, *, user: Optional[User]
) -> None:
    _editable_order(db, work_order_id, user)
    db.delete(_line_on_order(db, work_order_id, line_id))
    db.commit()


def consume_line(
    db: Session, *, line_id: uuid.UUID, work_order_id: uuid.UUID,
    item_id: uuid.UUID, quantity: Decimal,
) -> None:
    """Subtract a dispensed quantity from the line; delete it at zero or below.
    Does not commit."""
    line = (
        db.query(WorkOrderTakeoffLine)
        .filter(WorkOrderTakeoffLine.id == line_id)
        .with_for_update()
        .first()
    )
    if line is None or line.work_order_id != work_order_id or line.item_id != item_id:
        raise TakeoffLineConflictError(_CHANGED)
    remaining = line.quantity - quantity
    if remaining <= 0:
        db.delete(line)
    else:
        line.quantity = remaining
    db.flush()


def count_down_purchases(db: Session, *, item_id: uuid.UUID, quantity: Decimal) -> None:
    """A delivery arrived: reduce the item's on-the-way rows, oldest first,
    across service types. Surplus is ignored. Does not commit."""
    rows = (
        db.query(TakeoffPurchase)
        .filter(TakeoffPurchase.item_id == item_id)
        .order_by(TakeoffPurchase.created_at, TakeoffPurchase.id)
        .with_for_update()
        .all()
    )
    left = quantity
    for row in rows:
        if left <= 0:
            break
        taken = min(left, row.quantity_on_the_way)
        left -= taken
        if taken == row.quantity_on_the_way:
            db.delete(row)
        else:
            row.quantity_on_the_way -= taken
    db.flush()


def set_purchase(
    db: Session, *, user: Optional[User], item_id: uuid.UUID,
    service_type_key: str, service_type_label: str, quantity: Decimal,
) -> None:
    """Set one page row's on-the-way figure; 0 clears it. `created_at` is set
    on insert only (it orders the arrival count-down)."""
    _locked_live_item(db, item_id, allow_archived=True)
    row = (
        db.query(TakeoffPurchase)
        .filter_by(item_id=item_id, service_type_key=service_type_key)
        .with_for_update()
        .first()
    )
    if quantity <= 0:
        if row is not None:
            db.delete(row)
    elif row is None:
        db.add(TakeoffPurchase(
            item_id=item_id, service_type_key=service_type_key,
            service_type_label=service_type_label, quantity_on_the_way=quantity,
            created_by_id=user.id if user else None,
        ))
    else:
        row.quantity_on_the_way = quantity
    db.commit()


def overview(db: Session) -> TakeoffOverview:
    """Need per (service type, item) from live orders, with shortfall pooled
    per item across service types."""
    lines = (
        db.query(WorkOrderTakeoffLine, WorkOrder, Item)
        .join(WorkOrder, WorkOrder.id == WorkOrderTakeoffLine.work_order_id)
        .join(Item, Item.id == WorkOrderTakeoffLine.item_id)
        .filter(WorkOrder.status != STATUS_COMPLETED, WorkOrder.archived_at.is_(None))
        .order_by(WorkOrder.number)
        .all()
    )
    purchases = db.query(TakeoffPurchase).all()
    way_by_pair: dict[tuple[uuid.UUID, str], Decimal] = {}
    way_by_item: dict[uuid.UUID, Decimal] = {}
    for p in purchases:
        way_by_pair[(p.item_id, p.service_type_key)] = p.quantity_on_the_way
        way_by_item[p.item_id] = way_by_item.get(p.item_id, Decimal(0)) + p.quantity_on_the_way

    # key -> item_id -> (Item, need, [refs]). Case variants ("WMR"/"wmr") share
    # a key, so they are one group; the label is the smallest spelling.
    groups: dict[str, dict[uuid.UUID, list]] = {}
    labels: dict[str, str] = {}
    need_by_item: dict[uuid.UUID, Decimal] = {}
    for line, order, item in lines:
        key, label = normalize_service_type(order.service_type)
        if key not in labels or label < labels[key]:
            labels[key] = label
        slot = groups.setdefault(key, {})
        entry = slot.setdefault(item.id, [item, Decimal(0), []])
        entry[1] += line.quantity
        entry[2].append(TakeoffWorkOrderRef(id=order.id, number=order.number, quantity=line.quantity))
        need_by_item[item.id] = need_by_item.get(item.id, Decimal(0)) + line.quantity

    # A purchase whose pair has no need (service type edited, orders completed)
    # still gets a row, so it can be seen and cleared.
    for p in purchases:
        labels.setdefault(p.service_type_key, p.service_type_label)
        groups.setdefault(p.service_type_key, {}).setdefault(p.item_id, [p.item, Decimal(0), []])

    groups_per_item: dict[uuid.UUID, int] = {}
    for slot in groups.values():
        for item_id in slot:
            groups_per_item[item_id] = groups_per_item.get(item_id, 0) + 1

    out = []
    for key, slot in sorted(groups.items(), key=lambda kv: labels[kv[0]].casefold()):
        label = labels[key]
        rows = []
        for item_id, (item, need, refs) in sorted(slot.items(), key=lambda kv: kv[1][0].name.casefold()):
            shortfall = max(
                Decimal(0),
                need_by_item.get(item_id, Decimal(0)) - item.quantity - way_by_item.get(item_id, Decimal(0)),
            )
            rows.append(TakeoffRow(
                item_id=item_id, item_name=item.name, product_link=item.product_link,
                price=item.price, need=need,
                total=None if item.price is None else need * item.price,
                stock=item.quantity, on_the_way=way_by_pair.get((item_id, key), Decimal(0)),
                shortfall=shortfall, shared=groups_per_item[item_id] > 1, work_orders=refs,
            ))
        out.append(TakeoffGroup(
            service_type_key=key, service_type_label=label,
            total=sum((r.total for r in rows if r.total is not None), Decimal(0)),
            rows=rows,
        ))
    return TakeoffOverview(groups=out)
